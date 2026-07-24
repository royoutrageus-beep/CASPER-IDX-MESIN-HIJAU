# -*- coding: utf-8 -*-
"""
CASPER ENGINE v3.1 — scanner + jurnal + Telegram + lapisan risiko kuantitatif
+ AUTO-MODE (regime pasar) — patch dari Mesin Presisi
===========================================================================
SKOR (transparan, bisa diaudit):
  score (0-10)  = 2*(trend naik) + 2*min(rvol/2,1) + 2*(RSI di zona mode)
                + 1*(close > VWAP20) + 2*min(retN/target,1) + 1*(ATR di zona)
  signal        : GACOR >= 6 | POTENSIAL >= 4.5 | WATCH < 4.5
  mesin_score   = score/10*60 + min(rvol/3,1)*25 + 15*(close>VWAP20)   (0-100)
  mesin_grade   : BANDAR (>=90 & rvol>=3) | PRESISI (>=90) | KUAT (>=70)
                  | WATCH (>=45) | WAIT (<45)
  iq_score      = 0.5*mesin_score + 5*score
  iq_verdict    : BUY (iq>=65 & trend naik & >VWAP & rvol>=1.5)
                  | WAIT (iq<40) | HOLD
  TP / SL       : TP = harga + 1.9*ATR, SL = harga - 1*ATR (R:R 1.9)

LAPISAN RISIKO (5 hukum kuantitatif):
  * Momentum & mean reversion -> inti skor semua mode (trend, retN, RSI).
  * Volatility clustering     -> kolom vol_regime: vol EWMA (lambda 0.94,
    ala RiskMetrics/GARCH-lite) vs rata2 60 hari. SPIKE = vol tinggi
    cenderung lanjut tinggi; kecilkan size / lebarkan SL.
  * Fat tails / power law     -> kolom var5_pct: VaR 5% EMPIRIS dari
    distribusi return asli (bukan asumsi normal). Ini kerugian harian
    yang 1-dari-20 hari bisa kejadian.
  * Square-root law of impact -> kolom max_order_jt: order maksimal (juta
    Rp) supaya impact ~ sigma*sqrt(Q/ADV) <= 0.5%, dicap 5% turnover.
    Alasan matematis kenapa akumulasi harus pelan-pelan.
  * Kelly criterion           -> kolom kelly_%: f* = p - (1-p)/b dihitung
    dari rekam jejak jurnal LO SENDIRI per label sinyal (>=10 sampel),
    dipakai half-Kelly, cap 10% modal. Sizing, bukan prediksi.

AUTO-MODE (BARU): get_market_regime() baca IHSG (^JKSE) harian, bandingin
posisi vs EMA20/EMA55 + return 20 hari, terus balikin mode Casper yang
paling cocok (Scalping/Momentum/Intraday/Swing/Bagger). Dipakai casper_app.py
buat auto-pilih mode scan tiap kali browser dibuka / tiap siklus auto-scan
— boleh tetap di-override manual dari sidebar.

Jurnal: tiap scan tercatat ke jurnal_sinyal.csv; scan berikutnya otomatis
mengevaluasi sinyal lama -> jurnal_evaluasi.csv (win rate per label) ->
dari situlah Kelly dihitung. Sistem belajar dari jejaknya sendiri.

CLI:
  python casper_engine.py --all --mode Swing --tele
  python casper_engine.py --demo --mode Momentum
  python casper_engine.py --all --min-turnover 1000

Telegram: isi config_tele.json -> {"token": "...", "chat_id": "..."}
"""

import argparse
import json
import os
import time
import numpy as np
import pandas as pd
import pytz

TZ_WIB = pytz.timezone("Asia/Jakarta")


def now_wib():
    """Selalu jam WIB, di mana pun servernya (Streamlit Cloud = UTC/AS)."""
    return pd.Timestamp.now(tz=TZ_WIB)


DEFAULT_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK",
    "UNVR.JK", "ICBP.JK", "ANTM.JK", "ADRO.JK", "PGAS.JK", "GOTO.JK",
]
URL_DAFTAR_IDX = ("https://raw.githubusercontent.com/wildangunawan/"
                  "Dataset-Saham-IDX/master/List%20Emiten/all.csv")
# Daftar ~700 ticker IDX TIDAK di-hardcode: saat pertama kali pakai
# --all / "Semua IDX", daftar diunduh otomatis dari dataset publik lalu
# disimpan ke tickers_idx.txt (satu ticker per baris, boleh tanpa .JK).
# EDIT FILE ITU untuk menambah/menghapus saham. Hapus filenya kalau mau
# unduh ulang daftar terbaru.
CACHE_TICKER = "tickers_idx.txt"
PERIODE = "1y"
BATCH = 50
JEDA = 1.0
RR = 1.9
MODES = {
    "Scalping":  dict(emoji="⚡",  rsi=(50, 70), atr=(1.0, 4.0),
                      ret_n=5,  ret_t=0.05, ma=(20, 50)),
    "Momentum":  dict(emoji="🚀", rsi=(55, 75), atr=(1.5, 6.0),
                      ret_n=10, ret_t=0.10, ma=(20, 50)),
    "Intraday":  dict(emoji="🌤️", rsi=(45, 65), atr=(0.8, 3.0),
                      ret_n=3,  ret_t=0.03, ma=(10, 20)),
    "Swing":     dict(emoji="🌙", rsi=(45, 65), atr=(2.0, 6.0),
                      ret_n=20, ret_t=0.10, ma=(50, 200)),
    "Bagger":    dict(emoji="💎", rsi=(50, 80), atr=(2.0, 8.0),
                      ret_n=60, ret_t=0.30, ma=(50, 200)),
}


# ══════════════════ AUTO-MODE: REGIME PASAR (dari Mesin Presisi) ═══════
def get_market_regime():
    """Auto-deteksi kondisi market dari IHSG (^JKSE) -> rekomendasi mode Casper.

      RALLY (di atas EMA20 & EMA55 + ret20 kuat >= 8%) -> Bagger 💎
      UPTREND mapan  (di atas EMA20 & EMA55)           -> Swing 🌙
      Recovery/breakout awal (di atas EMA20 doang)     -> Momentum 🚀
      BEARISH (di bawah EMA20 & EMA55, turun)          -> Scalping ⚡
      SIDEWAYS / netral (selain di atas)               -> Intraday 🌤️

    Return: (mode, harga_ihsg, ema20, ema55, penjelasan)
    Kalau data IHSG gagal diambil -> fallback ("Scalping", 0, 0, 0, alasan).
    """
    import yfinance as yf
    try:
        df = yf.Ticker("^JKSE").history(period="60d", interval="1d",
                                        auto_adjust=True)
        close = df["Close"].dropna()
        if len(close) < 20:
            return ("Scalping", 0.0, 0.0, 0.0,
                    "Data IHSG kurang -> default Scalping")
        price = float(close.iloc[-1])
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema55 = float(close.ewm(span=min(55, len(close) - 1),
                                adjust=False).mean().iloc[-1])
        chg = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
        ret20 = (float((close.iloc[-1] / close.iloc[-21] - 1) * 100)
                 if len(close) > 21 else 0.0)
        above20, above55 = price > ema20, price > ema55

        if above20 and above55 and ret20 >= 8:
            return ("Bagger", price, ema20, ema55,
                    f"RALLY 🚀 — IHSG {price:,.0f} +{ret20:.1f}%/20 hari, "
                    f"di atas EMA20 & EMA55")
        if above20 and above55:
            return ("Swing", price, ema20, ema55,
                    f"UPTREND mapan — IHSG {price:,.0f} di atas EMA20 & "
                    f"EMA55 ({ret20:+.1f}%/20 hari)")
        if above20 and not above55 and chg > 0:
            return ("Momentum", price, ema20, ema55,
                    f"Recovery/breakout awal — IHSG {price:,.0f} di atas "
                    f"EMA20, belum tembus EMA55")
        if not above20 and not above55 and chg < -0.3:
            return ("Scalping", price, ema20, ema55,
                    f"BEARISH — IHSG {price:,.0f} di bawah EMA20 & EMA55 "
                    f"({chg:+.2f}%)")
        return ("Intraday", price, ema20, ema55,
                f"SIDEWAYS — IHSG {price:,.0f} netral, belum ada arah jelas")
    except Exception as e:
        return "Scalping", 0.0, 0.0, 0.0, f"IHSG error ({e}) -> default Scalping"


MIN_TURNOVER_JT = 500     # likuiditas: rata2 nilai transaksi/hari (juta Rp)
MIN_RVOL_BUY = 1.5        # BUY wajib volume >= 1.5x rata-rata
JURNAL = "jurnal_sinyal.csv"
EVALUASI = "jurnal_evaluasi.csv"
CONF_TELE = "config_tele.json"
SHEET_NAME = "casper_jurnal"        # nama Google Spreadsheet untuk jurnal
_SHEET = None

LAST_CLOSE = None


def normalisasi(tickers):
    """'bbca' / 'BBCA' / 'BBCA.JK' -> 'BBCA.JK' (nggak usah ribet .JK)."""
    return [t.upper() if t.upper().endswith(".JK") else t.upper() + ".JK"
            for t in tickers if t.strip()]


# ----------------------------- DATA ------------------------------------
def muat_ticker_semua():
    if os.path.exists(CACHE_TICKER):
        with open(CACHE_TICKER) as fh:
            return normalisasi([b.strip() for b in fh if b.strip()])
    import urllib.request
    data = urllib.request.urlopen(URL_DAFTAR_IDX, timeout=30).read().decode()
    kode = [ln.split(",")[0].strip() for ln in data.splitlines()[1:] if ln.strip()]
    tickers = sorted({k + ".JK" for k in kode if len(k) == 4 and k.isalpha()})
    with open(CACHE_TICKER, "w") as fh:
        fh.write("\n".join(tickers))
    return tickers


def unduh_ohlcv(tickers, periode=PERIODE):
    import yfinance as yf
    bag = {k: [] for k in ("Close", "High", "Low", "Volume")}
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i:i + BATCH]
        df = yf.download(chunk, period=periode, auto_adjust=True, progress=False)
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_product([df.columns, [chunk[0]]])
        for k in bag:
            bag[k].append(df[k])
        print(f"    data {min(i + BATCH, len(tickers))}/{len(tickers)}")
        if i + BATCH < len(tickers):
            time.sleep(JEDA)
    out = {k: pd.concat(v, axis=1) for k, v in bag.items()}
    out = {k: v.loc[:, ~v.columns.duplicated()] for k, v in out.items()}
    ok = out["Close"].dropna(axis=1, thresh=60).columns
    return {k: v[ok] for k, v in out.items()}


def data_demo(tickers, n=252, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    m = len(tickers)
    mu = rng.uniform(-0.1, 0.4, m) / 252
    sg = rng.uniform(0.2, 0.5, m) / np.sqrt(252)
    logr = mu + sg * rng.normal(0, 1, (n, m))
    close = pd.DataFrame(rng.uniform(100, 8000, m) * np.exp(np.cumsum(logr, 0)),
                         index=idx, columns=tickers)
    span = np.abs(rng.normal(0.012, 0.006, (n, m)))
    volv = rng.lognormal(15, 0.6, (n, m))
    spike = rng.random((n, m)) < 0.05
    volv[spike] *= rng.uniform(2, 6, int(spike.sum()))
    return {"Close": close,
            "High": pd.DataFrame(close.values * (1 + span), index=idx, columns=tickers),
            "Low": pd.DataFrame(close.values * (1 - span), index=idx, columns=tickers),
            "Volume": pd.DataFrame(volv, index=idx, columns=tickers)}


# --------------------------- INDIKATOR ----------------------------------
def rsi_wilder(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def skor_ticker(c, h, l, v, mode="Scalping",
                min_turnover_jt=MIN_TURNOVER_JT):
    prof = MODES.get(mode, MODES["Scalping"])
    ma_a, ma_b = prof["ma"]
    c, h, l, v = (s.dropna() for s in (c, h, l, v))
    n = min(len(c), len(h), len(l), len(v))
    if n < max(60, ma_b + 5):
        return None
    c, h, l, v = c.iloc[-n:], h.iloc[-n:], l.iloc[-n:], v.iloc[-n:]
    harga = float(c.iloc[-1])
    turnover = float((c * v).iloc[-20:].mean())
    if turnover < min_turnover_jt * 1e6:
        return None                          # kurang likuid, buang
    rsi = rsi_wilder(c)
    rsi_ema = float(rsi.ewm(span=9, adjust=False).mean().iloc[-1])
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    atr_pct = atr / harga * 100
    rvol = float(v.iloc[-1] / max(v.iloc[-21:-1].mean(), 1))
    ret_d = c.pct_change().dropna()
    ew_var = (ret_d ** 2).ewm(alpha=0.06, adjust=False).mean()
    sigma_d = float(np.sqrt(ew_var.iloc[-1]))            # vol EWMA hari ini
    sigma_avg = float(np.sqrt(ew_var.iloc[-60:].mean()))
    vol_regime = ("SPIKE 🔥" if sigma_d > 1.5 * sigma_avg else
                  "CALM 🌊" if sigma_d < 0.75 * sigma_avg else "NORMAL")
    var5 = float(np.percentile(ret_d.iloc[-250:], 5) * 100)  # VaR5 empiris
    max_order_jt = int(min(
        (turnover / 1e6) * (0.005 / max(sigma_d, 1e-4)) ** 2,
        0.05 * turnover / 1e6))                          # sqrt-law impact
    tp_ = (h + l + c) / 3
    vwap20 = float((tp_ * v).rolling(20).sum().iloc[-1]
                   / max(v.rolling(20).sum().iloc[-1], 1))
    above = harga > vwap20
    maa = float(c.rolling(ma_a).mean().iloc[-1])
    mab = float(c.rolling(ma_b).mean().iloc[-1])
    trend_up = harga > maa > mab
    rn = prof["ret_n"]
    retn = float(c.iloc[-1] / c.iloc[-rn - 1] - 1) if n > rn else 0.0
    r_lo, r_hi = prof["rsi"]
    a_lo, a_hi = prof["atr"]

    score = (2 * trend_up + 2 * min(rvol / 2, 1)
             + 2 * (r_lo <= rsi_ema <= r_hi) + 1 * above
             + 2 * min(max(retn, 0) / prof["ret_t"], 1)
             + 1 * (a_lo <= atr_pct <= a_hi))
    score = round(float(score), 1)
    signal = ("GACOR ⚡" if score >= 6 else
              "POTENSIAL 🔥" if score >= 4.5 else "WATCH 👀")
    sinyal_v2 = ("HAKA 🔨" if score >= 6 and rvol >= 2 and above else
                 "ON TRACK ✅" if trend_up else "WAIT ❌")
    mesin = round(score / 10 * 60 + min(rvol / 3, 1) * 25 + 15 * above, 1)
    grade = ("BANDAR 🔵" if mesin >= 90 and rvol >= 3 else
             "PRESISI 🎯" if mesin >= 90 else
             "KUAT ⚡" if mesin >= 70 else
             "WATCH 👀" if mesin >= 45 else "WAIT ❌")
    iq = round(0.5 * mesin + 5 * score, 1)
    verdict = ("BUY" if iq >= 65 and trend_up and above
               and rvol >= MIN_RVOL_BUY else
               "WAIT" if iq < 40 else "HOLD")
    now = now_wib()
    return {"ts": now.strftime("%H:%M:%S"), "date": now.strftime("%Y-%m-%d"),
            "ticker": c.name.replace(".JK", ""),
            "mode": f"{mode} {prof['emoji']}",
            "score": score, "signal": signal, "sinyal_v2": sinyal_v2,
            "mesin_grade": grade, "mesin_score": mesin,
            "iq_verdict": verdict, "iq_score": iq,
            "price": round(harga, 0),
            "tp": round(harga + RR * atr, 0), "sl": round(harga - atr, 0),
            "rr": RR, "atr_pct": round(atr_pct, 2),
            "rvol": round(rvol, 2), "rsi_ema": round(rsi_ema, 1),
            "turnover_jt": round(turnover / 1e6),
            "vol_regime": vol_regime, "var5_pct": round(var5, 2),
            "max_order_jt": max_order_jt,
            "above_vwap": bool(above)}


def ukuran_kelly(df, cap=0.10, min_sampel=10):
    """Kelly criterion dari rekam jejak jurnal SENDIRI (bukan asumsi).
    f* = p - (1-p)/b, b = avg win / avg loss. Dipakai half-Kelly, cap 10%.
    Butuh >= 10 sampel evaluasi per label; sebelum itu tampil '-'. """
    df["kelly_%"] = "-"
    if df.empty:
        return df
    ev = baca_evaluasi()
    if ev is None or ev.empty:
        return df
    peta = {}
    for sig, g in ev.groupby("signal"):
        if len(g) < min_sampel:
            continue
        p = float((g["return_%"] > 0).mean())
        win = g.loc[g["return_%"] > 0, "return_%"].mean()
        loss = -g.loc[g["return_%"] <= 0, "return_%"].mean()
        if not np.isfinite(win) or not np.isfinite(loss) or loss <= 0:
            continue
        f = max(p - (1 - p) / (win / loss), 0)
        peta[sig] = round(min(f / 2, cap) * 100, 1)
    df["kelly_%"] = df["signal"].map(peta).fillna("-")
    return df


# ------------------------------ SCAN ------------------------------------
def scan(tickers=None, demo=False, semua=False, mode="Scalping",
         min_turnover_jt=MIN_TURNOVER_JT):
    global LAST_CLOSE
    if tickers is None:
        tickers = muat_ticker_semua() if semua else DEFAULT_TICKERS
    else:
        tickers = normalisasi(tickers)
    data = data_demo(tickers) if demo else unduh_ohlcv(tickers)
    LAST_CLOSE = data["Close"]
    rows = []
    for t in data["Close"].columns:
        r = skor_ticker(data["Close"][t], data["High"][t],
                        data["Low"][t], data["Volume"][t],
                        mode=mode, min_turnover_jt=min_turnover_jt)
        if r:
            rows.append(r)
    df = pd.DataFrame(rows).sort_values(
        "score", ascending=False).reset_index(drop=True)
    return ukuran_kelly(df)


# ----------------- JURNAL: Google Sheets ☁️ / CSV lokal ------------------
def _kredensial_gsheet():
    """Service account dari gsheet_creds.json (lokal) atau st.secrets
    [gcp_service_account] (Streamlit Cloud)."""
    if os.path.exists("gsheet_creds.json"):
        return json.load(open("gsheet_creds.json"))
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    return None


def jurnal_backend():
    """Spreadsheet gspread kalau kredensial tersedia, selain itu 'csv'."""
    global _SHEET
    if _SHEET is not None:
        return _SHEET
    info = _kredensial_gsheet()
    if info:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            sc = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
            gc = gspread.authorize(
                Credentials.from_service_account_info(info, scopes=sc))
            _SHEET = gc.open(SHEET_NAME)
            print(f"[i] Jurnal tersambung ke Google Sheets '{SHEET_NAME}'.")
            return _SHEET
        except Exception as e:
            print(f"[!] Google Sheets gagal ({e}) — pakai CSV lokal.")
    _SHEET = "csv"
    return _SHEET


def backend_label():
    return ("Google Sheets ☁️" if jurnal_backend() != "csv"
            else "CSV lokal 📁")


def _worksheet(sh, nama, header):
    import gspread
    try:
        ws = sh.worksheet(nama)
        if header and ws.row_values(1) != [str(h) for h in header]:
            ws.update_title(                       # skema berubah: arsipkan
                f"{nama}_lama_{now_wib():%m%d%H%M}")
            raise gspread.WorksheetNotFound(nama)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(nama, rows=2000, cols=max(len(header), 5))
        if header:
            ws.append_row([str(h) for h in header])
    return ws


def catat_jurnal(df, path=JURNAL):
    sh = jurnal_backend()
    if sh != "csv":
        try:
            ws = _worksheet(sh, "sinyal", df.columns.tolist())
            ws.append_rows(df.astype(str).values.tolist())
            return
        except Exception as e:
            print(f"[!] Gagal tulis Sheets ({e}) — fallback CSV.")
    if os.path.exists(path):
        lama = pd.read_csv(path, nrows=0).columns.tolist()
        if lama != df.columns.tolist():          # skema berubah -> arsipkan
            os.replace(path, path.replace(".csv", "_lama.csv"))
    df.to_csv(path, mode="a", index=False, header=not os.path.exists(path))


def baca_jurnal(path=JURNAL):
    sh = jurnal_backend()
    if sh != "csv":
        try:
            rows = sh.worksheet("sinyal").get_all_records()
            if rows:
                return pd.DataFrame(rows)
        except Exception:
            pass
        return None
    return pd.read_csv(path) if os.path.exists(path) else None


def baca_evaluasi(out=EVALUASI):
    sh = jurnal_backend()
    if sh != "csv":
        try:
            rows = sh.worksheet("evaluasi").get_all_records()
            if rows:
                ev = pd.DataFrame(rows)
                ev["return_%"] = pd.to_numeric(ev["return_%"],
                                               errors="coerce")
                return ev
        except Exception:
            pass
        return None
    return pd.read_csv(out) if os.path.exists(out) else None


def evaluasi_jurnal(close_df, path=JURNAL, out=EVALUASI):
    """Bukti matematis: harga saat sinyal vs harga terkini."""
    j = baca_jurnal(path)
    if j is None or close_df is None or len(j) == 0:
        return None
    j["price"] = pd.to_numeric(j["price"], errors="coerce")
    today = now_wib().strftime("%Y-%m-%d")
    j = j[j["date"].astype(str) < today]
    if j.empty:
        return None
    j = j.drop_duplicates(subset=["date", "ticker"], keep="last")
    kolmap = {c.replace(".JK", ""): c for c in close_df.columns}
    rows = []
    for _, r in j.iterrows():
        col = kolmap.get(str(r["ticker"]))
        if col is None or not np.isfinite(r["price"]) or r["price"] <= 0:
            continue
        now = float(close_df[col].dropna().iloc[-1])
        ret = (now / r["price"] - 1) * 100
        rows.append({**r[["date", "ticker", "signal", "iq_verdict",
                          "score", "price"]].to_dict(),
                     "harga_kini": round(now, 0),
                     "return_%": round(ret, 2),
                     "hasil": "NAIK ✅" if ret > 0 else "TURUN ❌"})
    if not rows:
        return None
    ev = pd.DataFrame(rows)
    sh = jurnal_backend()
    if sh != "csv":
        try:
            ws = _worksheet(sh, "evaluasi", [])
            ws.clear()
            ws.append_row(ev.columns.tolist())
            ws.append_rows(ev.astype(str).values.tolist())
        except Exception as e:
            print(f"[!] Gagal tulis evaluasi ke Sheets: {e}")
            ev.to_csv(out, index=False)
    else:
        ev.to_csv(out, index=False)
    return ev


def ringkas_evaluasi(ev):
    if ev is None or ev.empty:
        return None
    g = ev.groupby("signal").agg(
        jumlah=("return_%", "size"),
        naik=("return_%", lambda x: int((x > 0).sum())),
        avg_return=("return_%", "mean")).reset_index()
    g["win_rate"] = (g["naik"] / g["jumlah"] * 100).round(1)
    g["avg_return"] = g["avg_return"].round(2)
    return g


# ---------------------------- TELEGRAM ----------------------------------
def ambil_config_tele(conf=CONF_TELE):
    """Cari kredensial Telegram dari 3 sumber (urut prioritas):
    1. config_tele.json           -> pemakaian lokal
    2. env var TELE_TOKEN/CHAT_ID -> server / task scheduler
    3. st.secrets                 -> deploy di Streamlit Cloud
       (isi lewat dashboard: Settings > Secrets, format TOML)"""
    if os.path.exists(conf):
        return json.load(open(conf))
    tok = os.environ.get("TELE_TOKEN")
    cid = os.environ.get("TELE_CHAT_ID")
    if tok and cid:
        return {"token": tok, "chat_id": cid}
    try:
        import streamlit as st
        if "token" in st.secrets and "chat_id" in st.secrets:
            return {"token": st.secrets["token"],
                    "chat_id": st.secrets["chat_id"]}
    except Exception:
        pass
    return None


def kirim_tele(df, top=8, conf=CONF_TELE):
    cfg = ambil_config_tele(conf)
    if cfg is None:
        print("[!] Kredensial Telegram tidak ditemukan "
              "(config_tele.json / env var / st.secrets).")
        return False
    now = now_wib()
    pilih = df[df["iq_verdict"] == "BUY"].head(top)
    sub = "sinyal BUY 🟢" if len(pilih) else "tidak ada BUY — top skor:"
    if pilih.empty:
        pilih = df.head(min(top, 5))
    baris = ["🔴 MARKET SCAN",
             "⚡ CASPER MESIN HIJAU 👻",
             f"⏰ {now:%H:%M:%S} WIB · {now:%d %b %Y}",
             f"📌 {sub}",
             "━━━━━━━━━━━━━━━━━━━━", ""]
    for _, r in pilih.iterrows():
        vw = "Above VWAP" if r["above_vwap"] else "Below VWAP"
        baris += [
            f"🎯 {r['ticker']} [{r['mesin_grade']}] MS:{r['mesin_score']:.0f}",
            f"💰 {r['price']:,.0f} · TT:{r['signal']} · {r['mode']}",
            f"🧠 IQ Daily: {r['iq_verdict']} ({r['iq_score']:.0f}/100)",
            f"📊 RSI: {r['rsi_ema']:.0f} · RVOL: {r['rvol']}x",
            f"🎯 TP: {r['tp']:,.0f} 🔴 SL: {r['sl']:,.0f} · R:R {r['rr']}",
            f"📐 ½-Kelly: {r['kelly_%']}% · Max order ≤ "
            f"Rp{r['max_order_jt']}jt · Vol {r['vol_regime']}",
            f"💡 {vw} · {r['sinyal_v2']} · ATR {r['atr_pct']}%",
            ""]
    baris.append("👻 sistem & disiplin — bukan rekomendasi")
    import urllib.request
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = json.dumps({"chat_id": cfg["chat_id"],
                          "text": "\n".join(baris)}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        print("[i] Terkirim ke Telegram.")
        return True
    except Exception as e:
        print(f"[!] Gagal kirim Telegram: {e}")
        return False


# ------------------------------- MAIN ------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tickers", nargs="+", default=None)
    ap.add_argument("--tele", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--mode", default="Scalping",
                    choices=list(MODES))
    ap.add_argument("--auto-mode", action="store_true",
                    help="abaikan --mode, pilih otomatis dari regime IHSG")
    ap.add_argument("--min-turnover", type=int, default=MIN_TURNOVER_JT,
                    help="minimal turnover harian (juta Rp)")
    args = ap.parse_args()

    print("=== CASPER ENGINE v3.1 ===")
    mode = args.mode
    if args.auto_mode:
        mode, price, e20, e55, label = get_market_regime()
        print(f"[i] Auto-mode: {mode} — {label}")
    df = scan(tickers=args.tickers, demo=args.demo, semua=args.all,
              mode=mode, min_turnover_jt=args.min_turnover)
    print(df.head(20).to_string(index=False))
    catat_jurnal(df)
    ev = evaluasi_jurnal(LAST_CLOSE)
    if ev is not None:
        print("\n--- EVALUASI SINYAL LAMA (bukti statistik) ---")
        print(ringkas_evaluasi(ev).to_string(index=False))
    if args.tele:
        kirim_tele(df, top=args.top)


if __name__ == "__main__":
    main()
