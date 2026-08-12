# -*- coding: utf-8 -*-
"""
CASPER ENGINE v4.0 — perbaikan matematika + sinyal berbasis EVENT
=================================================================
Ditulis ulang dari v3.1. Tiga masalah yang diperbaiki:

  1. ITUNGAN NGACO
     - RSI Wilder balikin NaN kalau 14 hari nggak ada down-day (harusnya 100).
     - score / mesin_score / iq_score sebenernya SATU angka yang sama
       dipakai 3x (korelasi 0.98). rvol dihitung 2x, trend dihitung 2x.
     - rvol pakai volume bar hari ini yang MASIH JALAN (partial bar) dibagi
       rata-rata 20 hari penuh -> jam 10 pagi rvol selalu kelihatan kecil.
     - turnover pakai MEAN 20 hari -> satu hari pump bikin saham tipis
       kelihatan likuid. Sekarang MEDIAN.
     - sigma_avg = sqrt(mean(EWMA var)) dibandingin sama EWMA var hari ini:
       dua-duanya dari deret yang sama -> vol_regime hampir nggak pernah
       bunyi SPIKE. Sekarang EWMA(sigma) vs realized sigma 60 hari.
     - scan() CRASH (KeyError 'score') kalau nol saham lolos filter, dan
       itu persis yang kejadian tiap kali Yahoo lagi ngambek.
     - TP/SL nggak di-snap ke fraksi harga IDX -> angkanya nggak bisa
       dipasang di order book.
     - jurnal: dedup di-bypass diem-diem kalau backend Google Sheets
       kebaca gagal -> jurnal lo isinya 4x duplikat persis (1264 baris =
       316 saham x 4 scan). Udah gue cek di jurnal_sinyal.csv.

  2. TELEGRAM ITU-ITU AJA
     Akar masalahnya: v3.1 nge-scan KEADAAN ("harga di atas MA, RSI di
     zona") bukan KEJADIAN ("MA baru aja cross", "baru break Donchian").
     Keadaan bertahan berminggu-minggu -> saham yang sama dikirim tiap 15
     menit sampai bosen. v4 cuma ngirim EVENT yang masih FRESH (<= N bar)
     + cooldown per ticker, jadi satu saham nggak dikirim dua kali untuk
     kejadian yang sama.

  3. FORMULA DARI BUKU
     "151 Trading Strategies" (Kakushadze & Serur, 2018) — bagian 3 Stocks:
       3.1  Price-momentum      -> R^risk.adj = R^mean / sigma  (eq. 268-269)
                                   pakai formation T + skip S
       3.4  Low-volatility      -> ranking sigma 126 hari, rendah = bagus
       3.6  Multifactor         -> gabung faktor
       3.7  Residual momentum   -> momentum SISA setelah beta IHSG dibuang
                                   (eq. 278-281; di sini 1 faktor pasar,
                                   bukan FF3 — IDX nggak punya SMB/HML siap
                                   pakai)
       3.9  Mean-reversion      -> return di-demean lintas cluster
                                   (eq. 292-294)
       3.11 Single MA           -> eq. 321
       3.12 Two MA + stop 2%    -> eq. 322-323
       3.13 Three MA            -> eq. 324
       3.14 Support/Resistance  -> pivot C=(H+L+C)/3, R=2C-L, S=2C-H
                                   (eq. 325-328)  -> dipakai buat TP/SL
       3.15 Channel (Donchian)  -> eq. 329-331 + konfirmasi volume
       3.20 Alpha combos / 3.6  -> DEMEANED RANK, eq. 276-277:
                                   s_Ai = rank(f_Ai) - mean(rank)
                                   s_i  = (1/F) * sum_A s_Ai
                                   ^ ini yang gantiin bobot ngarang
                                     2+2+2+1+2+1 di v3.1

     Plus dari poster candlestick + support/resistance:
       - deteksi pola candle (engulfing, hammer, marubozu, morning star,
         three white soldiers, doji, shooting star, dark cloud, piercing)
       - fase Wyckoff (Akumulasi / Mark-Up / Distribusi / Mark-Down)
       - breakout wajib dikonfirmasi volume

CLI:
  python casper_engine.py --all --mode Swing --tele
  python casper_engine.py --demo --mode Momentum
  python casper_engine.py --all --auto-mode --min-turnover 1000 --tele
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time

import numpy as np
import pandas as pd
import pytz

VERSI = "4.0"
TZ_WIB = pytz.timezone("Asia/Jakarta")


def now_wib() -> pd.Timestamp:
    """Selalu jam WIB, di mana pun servernya (Streamlit Cloud = UTC)."""
    return pd.Timestamp.now(tz=TZ_WIB)


# ════════════════════════════════════════════════════════════════════════
#  KONSTANTA
# ════════════════════════════════════════════════════════════════════════
DEFAULT_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK",
    "UNVR.JK", "ICBP.JK", "ANTM.JK", "ADRO.JK", "PGAS.JK", "GOTO.JK",
]
URL_DAFTAR_IDX = ("https://raw.githubusercontent.com/wildangunawan/"
                  "Dataset-Saham-IDX/master/List%20Emiten/all.csv")
CACHE_TICKER = "tickers_idx.txt"
IHSG = "^JKSE"

PERIODE = "2y"          # v3.1 pakai 1y -> MA200 cuma punya 50 bar sejarah
BATCH = 50
JEDA = 1.0

JURNAL = "jurnal_sinyal.csv"
EVALUASI = "jurnal_evaluasi.csv"
TERKIRIM = "casper_terkirim.json"      # memori anti-spam Telegram
CONF_TELE = "config_tele.json"
SHEET_NAME = "casper_jurnal"
_SHEET = None

LAST_CLOSE = None
LAST_META = {}

# ---- filter kualitas universe -----------------------------------------
MIN_TURNOVER_JT = 500      # median (bukan mean) nilai transaksi harian
MIN_HARGA = 50             # buang saham gocap/nyangkut di batas bawah
MAX_ATR_PCT = 15.0         # di atas ini bukan saham, itu koin
MIN_RVOL_BUY = 1.5
FRESH_MAX_BAR = 3          # event dianggap "fresh" kalau <= 3 bar lalu
COOLDOWN_JAM = 20          # jangan kirim ulang ticker+event dalam 20 jam

# ---- profil mode -------------------------------------------------------
# form = formation window (T), skip = skip period (S) -> buku 3.1
# ma   = (cepat, lambat) buat cross; ma3 = tiga MA (3.13)
MODES = {
    "Scalping": dict(emoji="⚡",  rsi=(45, 75), atr=(1.0, 6.0),
                     form=10,  skip=0,  ma=(5, 20),   ma3=(3, 10, 21),
                     donchian=10, ret_t=0.05),
    "Intraday": dict(emoji="🌤️", rsi=(40, 70), atr=(0.8, 5.0),
                     form=5,   skip=0,  ma=(5, 10),   ma3=(3, 8, 21),
                     donchian=5,  ret_t=0.03),
    "Momentum": dict(emoji="🚀", rsi=(50, 80), atr=(1.5, 8.0),
                     form=21,  skip=2,  ma=(10, 30),  ma3=(5, 10, 30),
                     donchian=20, ret_t=0.10),
    "Swing":    dict(emoji="🌙", rsi=(45, 72), atr=(1.5, 8.0),
                     form=63,  skip=5,  ma=(20, 60),  ma3=(10, 20, 60),
                     donchian=40, ret_t=0.10),
    "Bagger":   dict(emoji="💎", rsi=(45, 80), atr=(1.5, 10.0),
                     form=126, skip=21, ma=(50, 150), ma3=(20, 50, 150),
                     donchian=60, ret_t=0.30),
}

# faktor yang digabung pakai demeaned rank (buku eq. 276-277).
# bobot dipisah dari definisi faktor supaya gampang diaudit / diubah.
FAKTOR = {
    # f_mom & f_resmom biasanya berkorelasi tinggi (0.6-0.95) — itu wajar,
    # residual momentum emang versi bersih dari momentum. Bobot f_mom
    # sengaja lebih kecil biar versi bersihnya yang nyetir.
    "f_mom":     0.7,   # 3.1  risk-adjusted momentum
    "f_resmom":  1.0,   # 3.7  residual momentum (beta IHSG dibuang)
    "f_lowvol":  0.7,   # 3.4  low-volatility anomaly
    "f_meanrev": 0.5,   # 3.9  mean-reversion lintas cluster
    "f_trend":   0.8,   # 3.11-3.13 struktur MA
    "f_vol":     0.6,   # konfirmasi volume (poster: breakout butuh volume)
}


# ════════════════════════════════════════════════════════════════════════
#  FRAKSI HARGA IDX  (biar TP/SL bisa beneran dipasang di order book)
# ════════════════════════════════════════════════════════════════════════
def tick_size(harga: float) -> int:
    """Fraksi harga BEI (Peraturan II-A). v3.1 nggak punya ini sama sekali,
    jadi TP kayak 3.612 muncul padahal tick di harga segitu Rp10."""
    if harga < 200:
        return 1
    if harga < 500:
        return 2
    if harga < 2000:
        return 5
    if harga < 5000:
        return 10
    return 25


def snap(harga: float, arah: str = "nearest") -> float:
    """Bulatkan ke fraksi harga. arah: 'up' (TP), 'down' (SL), 'nearest'."""
    if not np.isfinite(harga) or harga <= 0:
        return float("nan")
    t = tick_size(harga)
    if arah == "up":
        return float(math.ceil(harga / t) * t)
    if arah == "down":
        return float(math.floor(harga / t) * t)
    return float(round(harga / t) * t)


# ════════════════════════════════════════════════════════════════════════
#  SESI BURSA  (buat tahu bar hari ini masih jalan atau udah selesai)
# ════════════════════════════════════════════════════════════════════════
def porsi_sesi(ts: pd.Timestamp | None = None) -> float:
    """Berapa bagian sesi perdagangan yang UDAH lewat (0..1).

    Dipakai buat proyeksi rvol: v3.1 bagi volume-sampai-sekarang sama
    rata-rata volume SEHARI PENUH, jadi jam 10 pagi rvol-nya otomatis
    kecil dan nggak ada yang lolos MIN_RVOL_BUY. Sekarang penyebutnya
    diskalakan ke porsi sesi yang udah jalan.

    IDX: Sen-Kam 09:00-12:00 & 13:30-15:50 ; Jum 09:00-11:30 & 14:00-15:50
    """
    ts = ts or now_wib()
    if ts.weekday() >= 5:
        return 1.0
    jumat = ts.weekday() == 4
    if jumat:
        blok = [(9 * 60, 11 * 60 + 30), (14 * 60, 15 * 60 + 50)]
    else:
        blok = [(9 * 60, 12 * 60), (13 * 60 + 30, 15 * 60 + 50)]
    menit = ts.hour * 60 + ts.minute
    total = sum(b - a for a, b in blok)
    lewat = sum(max(0, min(menit, b) - a) for a, b in blok)
    if lewat <= 0:
        return 0.0
    return min(lewat / total, 1.0)


def normalisasi(tickers):
    """'bbca' / 'BBCA' / 'BBCA.JK' -> 'BBCA.JK'."""
    return [t.upper() if t.upper().endswith(".JK") else t.upper() + ".JK"
            for t in tickers if str(t).strip()]


# ════════════════════════════════════════════════════════════════════════
#  DATA
# ════════════════════════════════════════════════════════════════════════
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


class DataKosong(RuntimeError):
    """Dilempar kalau Yahoo nggak ngasih data sama sekali.

    v3.1 diam-diam lanjut dengan DataFrame kosong terus mati di
    sort_values('score') dengan KeyError yang nggak ada hubungannya.
    """


def unduh_ohlcv(tickers, periode=PERIODE):
    import yfinance as yf
    bag = {k: [] for k in ("Open", "Close", "High", "Low", "Volume")}
    gagal = []
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i:i + BATCH]
        try:
            df = yf.download(chunk, period=periode, auto_adjust=True,
                             progress=False, threads=True)
        except Exception as e:                       # noqa: BLE001
            gagal += chunk
            print(f"    [!] batch gagal ({e})")
            continue
        if df is None or df.empty:
            gagal += chunk
            continue
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_product([df.columns, [chunk[0]]])
        for k in bag:
            if k in df.columns.get_level_values(0):
                bag[k].append(df[k])
        print(f"    data {min(i + BATCH, len(tickers))}/{len(tickers)}")
        if i + BATCH < len(tickers):
            time.sleep(JEDA)

    if not bag["Close"]:
        raise DataKosong(
            f"Yahoo Finance nggak balikin data buat {len(tickers)} ticker "
            f"({len(gagal)} batch gagal). Cek koneksi / rate limit, "
            "jangan dianggap 'nggak ada sinyal'.")

    out = {k: pd.concat(v, axis=1) for k, v in bag.items() if v}
    out = {k: v.loc[:, ~v.columns.duplicated()] for k, v in out.items()}
    # butuh minimal 200 bar biar MA/momentum panjang punya arti
    ok = out["Close"].dropna(axis=1, thresh=200).columns
    ok = [c for c in ok if all(c in out[k].columns for k in out)]
    if len(ok) == 0:
        raise DataKosong("Semua ticker kebuang: sejarah harga < 200 bar.")
    return {k: v[ok] for k, v in out.items()}


def unduh_ihsg(periode=PERIODE):
    """Return harian IHSG buat residual momentum (buku 3.7)."""
    import yfinance as yf
    try:
        df = yf.download(IHSG, period=periode, auto_adjust=True,
                         progress=False)
        s = df["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        return s.dropna()
    except Exception as e:                           # noqa: BLE001
        print(f"    [!] IHSG gagal diambil ({e}) — residual momentum "
              "dilewati (faktor f_resmom = 0 buat semua saham).")
        return None


def data_demo(tickers, n=520, seed=42):
    """Data simulasi + satu faktor pasar bersama, biar residual momentum
    dan mean-reversion lintas saham beneran ada yang dikerjain."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    m = len(tickers)
    pasar = rng.normal(0.0003, 0.009, (n, 1))            # faktor bersama
    beta = rng.uniform(0.4, 1.6, m)
    mu = rng.uniform(-0.15, 0.45, m) / 252
    sg = rng.uniform(0.20, 0.65, m) / np.sqrt(252)
    logr = mu + pasar * beta + sg * rng.normal(0, 1, (n, m))
    close = pd.DataFrame(rng.uniform(80, 9000, m) * np.exp(np.cumsum(logr, 0)),
                         index=idx, columns=tickers)
    span = np.abs(rng.normal(0.012, 0.006, (n, m)))
    op = close.values * (1 + rng.normal(0, 0.004, (n, m)))
    volv = rng.lognormal(15, 0.6, (n, m))
    spike = rng.random((n, m)) < 0.05
    volv[spike] *= rng.uniform(2, 6, int(spike.sum()))
    return {
        "Open": pd.DataFrame(op, index=idx, columns=tickers),
        "Close": close,
        "High": pd.DataFrame(np.maximum(close.values, op) * (1 + span),
                             index=idx, columns=tickers),
        "Low": pd.DataFrame(np.minimum(close.values, op) * (1 - span),
                            index=idx, columns=tickers),
        "Volume": pd.DataFrame(volv, index=idx, columns=tickers),
    }


# ════════════════════════════════════════════════════════════════════════
#  INDIKATOR
# ════════════════════════════════════════════════════════════════════════
def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI Wilder — FIX: v3.1 pakai dn.replace(0, np.nan) jadi saham yang
    14 hari nggak pernah turun malah dapet RSI = NaN (harusnya 100), terus
    kebuang dari zona RSI. Justru saham paling kuat yang di-blank."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    both0 = (up <= 0) & (dn <= 0)
    rs = up / dn.where(dn > 0)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(dn > 0, 100.0)          # nggak ada down-day -> 100
    rsi = rsi.where(~((up <= 0) & (dn > 0)), 0.0)   # nggak ada up-day -> 0
    rsi = rsi.where(~both0, 50.0)                   # harga flat -> netral
    rsi.iloc[:n] = np.nan
    return rsi


def bar_sejak_nyala(kondisi: pd.Series, min_off: int = 1) -> tuple[int, bool]:
    """Berapa bar sejak `kondisi` TERAKHIR berubah False -> True.

    Ini pembeda EVENT vs KEADAAN. Hati-hati: di pandas, Series.shift() pada
    dtype bool balikin dtype OBJECT (NaN masuk), dan `~` pada object itu
    bitwise-not per elemen (~True == -2, yang truthy) — jadi
    `b & ~b.shift(1).fillna(False)` diam-diam sama dengan `b` dan semua
    "event" balik jadi "keadaan". Makanya di sini di-astype(bool) dulu.

    `min_off` = kondisi harus MATI minimal sekian bar berturut-turut sebelum
    nyala, biar level yang harganya nempel terus (contoh: pivot point, yang
    posisinya cuma typical-price kemarin) nggak dianggap "kejadian baru"
    tiap hari.
    """
    b = kondisi.fillna(False).astype(bool)
    prev = b.shift(1, fill_value=False).astype(bool)
    nyala = b & (~prev)
    if min_off > 1:
        # jumlah bar mati beruntun tepat sebelum tiap titik nyala
        mati_beruntun = (~b).astype(int)
        beruntun = mati_beruntun.groupby((b != b.shift()).cumsum()).cumsum()
        nyala = nyala & (beruntun.shift(1, fill_value=0) >= min_off)
    idx = np.flatnonzero(nyala.to_numpy())
    if len(idx) == 0:
        return 999, False
    return int(len(b) - 1 - idx[-1]), bool(nyala.iloc[-1])


def atr_wilder(h, l, c, n=14) -> pd.Series:
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def pivot_levels(h, l, c):
    """Buku 3.14 eq. 325-327 — pivot dari bar SEBELUMNYA.
        C = (P_H + P_L + P_C)/3 ; R = 2C - P_L ; S = 2C - P_H
    """
    ph, pl, pc = float(h), float(l), float(c)
    piv = (ph + pl + pc) / 3
    return piv, 2 * piv - pl, 2 * piv - ph


def donchian(h, l, T):
    """Buku 3.15 eq. 329-330 — ceiling/floor channel dari T bar SEBELUMNYA
    (shift(1), biar bar hari ini nggak dibandingin sama dirinya sendiri —
    kesalahan klasik yang bikin breakout kelihatan selalu terjadi)."""
    return (h.rolling(T).max().shift(1), l.rolling(T).min().shift(1))


# ════════════════════════════════════════════════════════════════════════
#  POLA CANDLE  (dari poster: single / double / triple candle pattern)
# ════════════════════════════════════════════════════════════════════════
def deteksi_candle(o, h, l, c) -> str:
    """Balikin nama pola candle di bar terakhir (string kosong kalau nggak
    ada). Cuma pola yang punya definisi numerik jelas — sisanya subjektif."""
    if min(len(o), len(h), len(l), len(c)) < 8:
        return ""
    o1, h1, l1, c1 = (float(x.iloc[-1]) for x in (o, h, l, c))
    o2, h2, l2, c2 = (float(x.iloc[-2]) for x in (o, h, l, c))
    o3, c3 = float(o.iloc[-3]), float(c.iloc[-3])
    rng1 = max(h1 - l1, 1e-9)
    body1 = abs(c1 - o1)
    atas = h1 - max(c1, o1)
    bawah = min(c1, o1) - l1
    naik1, naik2 = c1 > o1, c2 > o2

    body2 = abs(c2 - o2)
    body3 = abs(c3 - o3)
    rng2 = max(h2 - l2, 1e-9)

    # --- triple ---------------------------------------------------------
    # Morning/Evening Star DIPERKETAT: candle-1 harus badan gede & searah
    # trend lama, candle-2 harus beneran kecil DAN nge-gap, candle-3 harus
    # nutup lewat titik tengah candle-1. Tanpa syarat ini polanya nongol di
    # ~1 dari 30 bar acak dan jadi sampah.
    if (c3 < o3 and body3 / max(h.iloc[-3] - l.iloc[-3], 1e-9) > 0.5
            and body2 / rng2 < 0.3 and max(o2, c2) < c3 * 1.002
            and naik1 and body1 / rng1 > 0.4 and c1 > (o3 + c3) / 2):
        return "Morning Star 🌅"
    if (c3 > o3 and body3 / max(h.iloc[-3] - l.iloc[-3], 1e-9) > 0.5
            and body2 / rng2 < 0.3 and min(o2, c2) > c3 * 0.998
            and not naik1 and body1 / rng1 > 0.4 and c1 < (o3 + c3) / 2):
        return "Evening Star 🌇"
    if (naik1 and naik2 and c3 > o3 and c1 > c2 > c3
            and body1 / rng1 > 0.6 and body2 / rng2 > 0.6):
        return "Three White Soldiers 🕊️"

    # --- double ---------------------------------------------------------
    if naik1 and not naik2 and c1 >= o2 and o1 <= c2:
        return "Bullish Engulfing 🟢"
    if not naik1 and naik2 and c1 <= o2 and o1 >= c2:
        return "Bearish Engulfing 🔴"
    if naik1 and not naik2 and o1 < l2 and c1 > (o2 + c2) / 2 and c1 < o2:
        return "Piercing Line 🗡️"
    if not naik1 and naik2 and o1 > h2 and c1 < (o2 + c2) / 2 and c1 > o2:
        return "Dark Cloud Cover ☁️"
    if naik1 and not naik2 and body1 < abs(c2 - o2) * 0.6 \
            and max(c1, o1) <= max(c2, o2) and min(c1, o1) >= min(c2, o2):
        return "Bullish Harami 🫄"

    # --- single ---------------------------------------------------------
    if body1 / rng1 > 0.9:
        return "Marubozu Bullish 🟩" if naik1 else "Marubozu Bearish 🟥"
    if body1 / rng1 < 0.08:
        return "Doji ✚"
    # Hammer/Shooting Star cuma valid SETELAH pergerakan berlawanan
    # (poster: "reversal bullish setelah downtrend"). Tanpa syarat konteks
    # ini, dua-duanya cuma "candle berekor" dan nggak berarti apa-apa.
    turun_dulu = float(c.iloc[-1]) < float(c.iloc[-6:-1].mean())
    naik_dulu = float(c.iloc[-1]) > float(c.iloc[-6:-1].mean())
    if bawah > 2 * body1 and atas < body1 and turun_dulu:
        return "Hammer 🔨"
    if atas > 2 * body1 and bawah < body1 and naik_dulu:
        return "Shooting Star 🌠"
    return ""


BULLISH_CANDLE = ("Morning Star", "Three White Soldiers", "Bullish Engulfing",
                  "Piercing Line", "Bullish Harami", "Marubozu Bullish",
                  "Hammer")
BEARISH_CANDLE = ("Evening Star", "Bearish Engulfing", "Dark Cloud",
                  "Marubozu Bearish", "Shooting Star")


def fase_wyckoff(c, v, n=60) -> str:
    """Poster 'Siklus Pergerakan Saham': Akumulasi → Mark-Up → Distribusi
    → Mark-Down. Diterjemahkan ke aturan numerik:
        lebar range n hari (sempit/lebar) x arah trend x arah volume.
    """
    if len(c) < n + 5:
        return "-"
    cw = c.iloc[-n:]
    vw = v.iloc[-n:]
    lebar = float((cw.max() - cw.min()) / max(cw.mean(), 1e-9))
    slope = float(cw.iloc[-1] / cw.iloc[0] - 1)
    vol_naik = float(vw.iloc[-n // 3:].mean() / max(vw.iloc[:n // 3].mean(), 1))
    datar = lebar < 0.22 and abs(slope) < 0.10
    if datar:
        posisi = float((cw.iloc[-1] - cw.min()) / max(cw.max() - cw.min(), 1e-9))
        return ("Distribusi 📤" if posisi > 0.6 and vol_naik > 1.1
                else "Akumulasi 📥")
    if slope > 0.10:
        return "Mark-Up 📈" if vol_naik > 0.9 else "Mark-Up lemah 📈"
    if slope < -0.10:
        return "Mark-Down 📉"
    return "Transisi ↔️"


# ════════════════════════════════════════════════════════════════════════
#  FITUR PER SAHAM  (mentah — belum ada skor; skor dihitung lintas saham)
# ════════════════════════════════════════════════════════════════════════
def fitur_ticker(o, h, l, c, v, mode="Swing",
                 min_turnover_jt=MIN_TURNOVER_JT,
                 min_harga=MIN_HARGA, max_atr_pct=MAX_ATR_PCT,
                 bar_partial=False, porsi=1.0):
    prof = MODES.get(mode, MODES["Swing"])
    ma_f, ma_s = prof["ma"]
    t1, t2, t3 = prof["ma3"]

    nama = str(getattr(c, "name", "?"))
    df = pd.concat([o, h, l, c, v], axis=1,
                   keys=["o", "h", "l", "c", "v"]).dropna()
    if len(df) < max(210, ma_s + 10, prof["form"] + prof["skip"] + 10):
        return None
    o, h, l, c, v = (df[k] for k in ("o", "h", "l", "c", "v"))
    harga = float(c.iloc[-1])

    # ---- filter kualitas ------------------------------------------------
    if harga < min_harga:
        return None
    # lompatan ekstrem sehari = glitch feed (kasus MLPT di jurnal lama)
    median_5 = float(c.iloc[-6:-1].median())
    if median_5 > 0 and not (0.55 < harga / median_5 < 1.8):
        return None
    # MEDIAN, bukan mean: satu hari pump nggak boleh bikin saham tipis
    # kelihatan likuid (bug v3.1)
    turnover = float((c * v).iloc[-20:].median())
    if turnover < min_turnover_jt * 1e6:
        return None

    # ---- volatilitas & risiko ------------------------------------------
    atr = float(atr_wilder(h, l, c).iloc[-1])
    atr_pct = atr / harga * 100
    if not np.isfinite(atr_pct) or atr_pct > max_atr_pct:
        return None

    ret_d = np.log(c / c.shift()).dropna()
    sigma_126 = float(ret_d.iloc[-126:].std())
    # FIX vol_regime: EWMA lambda 0.94 (RiskMetrics) DIBANDING realized std
    # 60 hari — v3.1 bandingin EWMA sama akar rata-rata EWMA yang sama,
    # jadi dua-duanya gerak bareng dan SPIKE nyaris nggak pernah nyala.
    ew_var = (ret_d ** 2).ewm(alpha=0.06, adjust=False).mean()
    sigma_ewma = float(np.sqrt(ew_var.iloc[-1]))
    sigma_real60 = float(ret_d.iloc[-60:].std())
    rasio_vol = sigma_ewma / max(sigma_real60, 1e-9)
    vol_regime = ("SPIKE 🔥" if rasio_vol > 1.4 else
                  "CALM 🌊" if rasio_vol < 0.75 else "NORMAL")
    var5 = (float(np.percentile(ret_d.iloc[-250:], 5) * 100)
            if len(ret_d) >= 120 else np.nan)

    # ---- volume ---------------------------------------------------------
    vol_ref = float(v.iloc[-21:-1].median())
    vol_kini = float(v.iloc[-1])
    # FIX rvol: kalau bar hari ini masih jalan, penyebutnya diskalakan ke
    # porsi sesi yang udah lewat — bukan dibandingin sama sehari penuh.
    penyebut = max(vol_ref * (porsi if bar_partial else 1.0), 1.0)
    rvol = vol_kini / penyebut
    rvol_full = vol_kini / max(vol_ref, 1.0)

    # ---- RSI ------------------------------------------------------------
    rsi = rsi_wilder(c)
    rsi_ema = float(rsi.ewm(span=9, adjust=False).mean().iloc[-1])

    # ---- VWAP / MA ------------------------------------------------------
    tp = (h + l + c) / 3
    vwap20 = float((tp * v).rolling(20).sum().iloc[-1]
                   / max(float(v.rolling(20).sum().iloc[-1]), 1.0))
    above_vwap = harga > vwap20

    ema_f = c.ewm(span=ma_f, adjust=False).mean()
    ema_s = c.ewm(span=ma_s, adjust=False).mean()
    m1 = c.rolling(t1).mean()
    m2 = c.rolling(t2).mean()
    m3 = c.rolling(t3).mean()

    # ---- MOMENTUM: buku 3.1 eq. 268-269 ---------------------------------
    #   R^mean = rata-rata return harian pada formation window
    #   R^risk.adj = R^mean / sigma        <- ini yang di-rank
    #   skip S bar terakhir (efek reversal jangka pendek)
    T, S = prof["form"], prof["skip"]
    win = ret_d.iloc[-(T + S):len(ret_d) - S] if S > 0 else ret_d.iloc[-T:]
    r_mean = float(win.mean())
    r_sig = float(win.std())
    f_mom = r_mean / r_sig if r_sig > 0 else 0.0
    ret_form = float(np.exp(win.sum()) - 1)

    # ---- STRUKTUR TREND: buku 3.11-3.13 ---------------------------------
    ef, es = float(ema_f.iloc[-1]), float(ema_s.iloc[-1])
    ef_p, es_p = float(ema_f.iloc[-2]), float(ema_s.iloc[-2])
    v1, v2, v3 = float(m1.iloc[-1]), float(m2.iloc[-1]), float(m3.iloc[-1])
    trend_up = harga > ef > es                       # eq. 321 + 322
    tiga_ma = v1 > v2 > v3                           # eq. 324
    # jarak relatif MA -> dipakai sebagai faktor kontinu (bukan 0/1)
    f_trend = (ef / es - 1) if es > 0 else 0.0

    # cross EVENT (bukan keadaan): kapan terakhir kali cross ke atas
    bar_since_cross, cross_up_now = bar_sejak_nyala(ema_f > ema_s)
    _ = (ef_p, es_p)

    # ---- CHANNEL / DONCHIAN: buku 3.15 eq. 329-331 ----------------------
    dc_hi_s, dc_lo_s = donchian(h, l, prof["donchian"])
    dc_hi = float(dc_hi_s.iloc[-1]) if np.isfinite(dc_hi_s.iloc[-1]) else np.nan
    dc_lo = float(dc_lo_s.iloc[-1]) if np.isfinite(dc_lo_s.iloc[-1]) else np.nan
    break_up = bool(np.isfinite(dc_hi) and harga > dc_hi)
    bar_since_break, _break_now = bar_sejak_nyala(c > dc_hi_s)
    # poster: "breakout dengan volume besar lebih valid"
    break_valid = break_up and rvol >= 1.5

    # ---- SUPPORT/RESISTANCE: buku 3.14 eq. 325-328 ----------------------
    piv, res, sup = pivot_levels(h.iloc[-2], l.iloc[-2], c.iloc[-2])
    di_atas_pivot = harga >= piv                     # eq. 328 long
    kena_resist = harga >= res                       # eq. 328 liquidate
    piv_s = ((h + l + c) / 3).shift(1)
    # min_off=3: pivot itu cuma typical price kemarin, jadi harga nyeberang
    # bolak-balik hampir tiap hari. Baru dihitung "reclaim" kalau sebelumnya
    # minimal 3 bar berturut-turut ADA DI BAWAH pivot.
    bar_since_pivot, _ = bar_sejak_nyala(c >= piv_s, min_off=3)
    # buku 3.12 eq. 323: likuidasi long kalau harga jatuh > Δ (2%) di bawah
    # close kemarin — stop taktis yang nggak nunggu MA cross balik
    exit_2pct = snap(float(c.iloc[-2]) * 0.98, "down")

    # ---- LOW-VOL & MEAN-REVERSION (bahan rank lintas saham) -------------
    f_lowvol = -sigma_126                            # buku 3.4 (rendah=bagus)
    r_pendek = float(np.log(c.iloc[-1] / c.iloc[-6]))  # 5 hari, buat 3.9
    f_vol = math.log(max(rvol_full, 0.05))           # konfirmasi volume

    # ---- pola candle & fase ---------------------------------------------
    pola = deteksi_candle(o, h, l, c)
    fase = fase_wyckoff(c, v)

    return {
        "ticker": nama.replace(".JK", ""),
        "price": harga,
        "atr": atr, "atr_pct": atr_pct,
        "rsi_ema": rsi_ema,
        "rvol": rvol, "rvol_full": rvol_full,
        "turnover_jt": turnover / 1e6,
        "sigma_126": sigma_126, "sigma_ewma": sigma_ewma,
        "vol_regime": vol_regime, "var5_pct": var5,
        "above_vwap": bool(above_vwap), "vwap20": vwap20,
        "trend_up": bool(trend_up), "tiga_ma": bool(tiga_ma),
        "cross_up_now": cross_up_now, "bar_since_cross": int(bar_since_cross),
        "break_up": bool(break_up), "break_valid": bool(break_valid),
        "bar_since_break": int(bar_since_break),
        "dc_hi": dc_hi, "dc_lo": dc_lo,
        "pivot_c": piv, "pivot_r": res, "pivot_s": sup,
        "di_atas_pivot": bool(di_atas_pivot), "kena_resist": bool(kena_resist),
        "bar_since_pivot": int(bar_since_pivot), "exit_2pct": exit_2pct,
        "ret_form": ret_form,
        "pola": pola, "fase": fase,
        # bahan faktor mentah:
        "f_mom": f_mom, "f_lowvol": f_lowvol, "f_trend": f_trend,
        "f_vol": f_vol, "_r_pendek": r_pendek,
    }


# ════════════════════════════════════════════════════════════════════════
#  RESIDUAL MOMENTUM — buku 3.7 (eq. 278-281), 1 faktor pasar (IHSG)
# ════════════════════════════════════════════════════════════════════════
def residual_momentum(close: pd.DataFrame, ihsg: pd.Series | None,
                      T: int, S: int) -> pd.Series:
    """R_i = beta_i * MKT + eps_i  ->  ranking pakai mean(eps)/std(eps).

    Kenapa penting buat IDX: kalau IHSG lagi rally, HAMPIR SEMUA saham
    momentum-nya positif. v3.1 nggak bisa bedain "saham ini kuat" dari
    "pasarnya lagi naik" — makanya sinyalnya numpuk dan seragam.
    """
    if ihsg is None or close.empty:
        return pd.Series(0.0, index=close.columns)
    r = np.log(close / close.shift()).dropna(how="all")
    rm = np.log(ihsg / ihsg.shift()).reindex(r.index).dropna()
    r = r.reindex(rm.index)
    if len(rm) < T + S + 30:
        return pd.Series(0.0, index=close.columns)
    # beta dari 252 bar terakhir (atau semaunya kalau lebih pendek)
    est = r.iloc[-252:]
    mkt = rm.iloc[-252:]
    mkt_c = mkt - mkt.mean()
    var_m = float((mkt_c ** 2).sum())
    if var_m <= 0:
        return pd.Series(0.0, index=close.columns)
    cov = est.sub(est.mean()).mul(mkt_c, axis=0).sum()
    beta = (cov / var_m).fillna(0.0)
    eps = r.sub(pd.DataFrame(np.outer(rm.values, beta.values),
                             index=r.index, columns=r.columns))
    win = eps.iloc[-(T + S):len(eps) - S] if S > 0 else eps.iloc[-T:]
    mu = win.mean()
    sd = win.std().replace(0, np.nan)
    return (mu / sd).fillna(0.0)


# ════════════════════════════════════════════════════════════════════════
#  GABUNG FAKTOR — buku 3.6/3.20 eq. 276-277 (DEMEANED RANK)
# ════════════════════════════════════════════════════════════════════════
def demeaned_rank(s: pd.Series) -> pd.Series:
    """s_Ai = rank(f_Ai) - (1/N) * sum_j rank(f_Aj)   (eq. 276)

    Dinormalisasi ke [-1, 1] biar faktor dengan N berbeda tetap sebanding.
    Rank kebal outlier — inilah kenapa dia dipakai buku, dan kenapa dia
    lebih waras dari bobot 2+2+2+1+2+1 punya v3.1 yang bisa dipenuhin
    100% sama saham gorengan yang ATR-nya 14%.
    """
    r = s.rank(method="average")
    n = len(r)
    if n <= 1:
        return pd.Series(0.0, index=s.index)
    return (r - r.mean()) / ((n - 1) / 2)


def gabung_alpha(df: pd.DataFrame, bobot=None) -> pd.DataFrame:
    """s_i = sum_A w_A * s_Ai  (eq. 277, versi berbobot)."""
    bobot = bobot or FAKTOR
    total = sum(bobot.values())
    s = pd.Series(0.0, index=df.index)
    for kol, w in bobot.items():
        if kol not in df.columns:
            continue
        f = pd.to_numeric(df[kol], errors="coerce").fillna(0.0)
        df[f"s_{kol}"] = demeaned_rank(f)
        s = s + w * df[f"s_{kol}"]
    df["alpha"] = s / max(total, 1e-9)
    # persentil 0-100 -> angka yang gampang dibaca manusia
    df["alpha_pct"] = (df["alpha"].rank(pct=True) * 100).round(1)
    return df


# ════════════════════════════════════════════════════════════════════════
#  TP / SL — struktur dulu (buku 3.14), ATR cuma cadangan
# ════════════════════════════════════════════════════════════════════════
def level_tp_sl(r) -> dict:
    """v3.1: TP = harga + 1.9*ATR, SL = harga - ATR, R:R DIKLAIM 1.9 tanpa
    dihitung. Di sini TP/SL diambil dari struktur harga (resistance pivot /
    Donchian ceiling / floor), di-snap ke fraksi harga IDX, dan R:R DIHITUNG
    dari angka yang benar-benar dipakai."""
    harga, atr = float(r["price"]), float(r["atr"])
    dc_hi, dc_lo = r.get("dc_hi"), r.get("dc_lo")
    res, sup = r.get("pivot_r"), r.get("pivot_s")

    # ── 1. STOP dulu, baru target. Urutannya penting: risiko itu yang
    #      ditentukan pasar (struktur), target itu konsekuensinya.
    kandidat_sl = [x for x in (sup, dc_lo)
                   if x is not None and np.isfinite(x) and x < harga * 0.995]
    sl = max(kandidat_sl) if kandidat_sl else harga - 1.5 * atr
    sl = min(sl, harga - 0.8 * atr) - 0.3 * atr     # kasih bantal, jangan ketat
    tipe_sl = "Struktur" if kandidat_sl else "ATR"
    # PAGAR: support terdekat bisa jauh banget (Donchian low 40 bar). Stop
    # 35% di bawah harga itu bukan stop, itu doa. Dibatasi 3 ATR.
    if sl < harga - 3 * atr:
        sl, tipe_sl = harga - 3 * atr, "ATR (struktur ketinggian)"
    sl = snap(sl, "down")
    risiko = harga - sl
    if risiko <= 0:
        return {"tp": np.nan, "sl": sl, "rr": np.nan, "tp_dari": "-",
                "sl_dari": tipe_sl, "risiko_pct": np.nan}

    # ── 2. TARGET: resistance struktural pertama yang jaraknya minimal 1R.
    #      Kalau breakout (harga udah di atas ceiling), pakai measured move
    #      = ceiling + lebar channel. Kalau nggak ada yang layak, pakai 2R
    #      murni — dan LABELNYA jujur "2R", bukan pura-pura level teknikal.
    lebar = (dc_hi - dc_lo) if (dc_hi and dc_lo and np.isfinite(dc_hi)
                                and np.isfinite(dc_lo)) else np.nan
    kandidat = []
    if res is not None and np.isfinite(res):
        kandidat.append(("Pivot R", res))
    if dc_hi is not None and np.isfinite(dc_hi):
        kandidat.append(("Donchian", dc_hi))
        if np.isfinite(lebar) and harga > dc_hi:
            kandidat.append(("Measured move", dc_hi + lebar))
    layak = sorted([(v, n) for n, v in kandidat if v >= harga + risiko])
    if layak:
        tp, tipe_tp = layak[0][0], layak[0][1]
    else:
        tp, tipe_tp = harga + 2 * risiko, "2R"

    tp = snap(tp, "down")        # jual: pasang di bawah level biar kena
    rr = round((tp - harga) / risiko, 2)
    return {"tp": tp, "sl": sl, "rr": rr, "tp_dari": tipe_tp,
            "sl_dari": tipe_sl,
            "risiko_pct": round(risiko / harga * 100, 2)}


# ════════════════════════════════════════════════════════════════════════
#  KLASIFIKASI SINYAL — berbasis EVENT, ini inti fix "itu-itu aja"
# ════════════════════════════════════════════════════════════════════════
def klasifikasi(df: pd.DataFrame, mode: str, fresh_max=FRESH_MAX_BAR,
                min_iq=70.0, max_risiko=8.0, min_rr=1.5) -> pd.DataFrame:
    prof = MODES.get(mode, MODES["Swing"])
    r_lo, r_hi = prof["rsi"]

    def event_row(r):
        """Kejadian apa yang baru terjadi.

        Dipisah KUAT vs LEMAH. Yang lemah tetap dicatat ke jurnal (biar
        nanti kebukti secara statistik apakah konfirmasi volume beneran
        penting), tapi NGGAK bikin sinyal jadi BUY dan nggak dikirim ke
        Telegram. Buku 3.21 sendiri bilang sinyal single-stock kayak MA
        cross & candle itu lemah kalau berdiri sendiri.
        """
        kandidat = []   # (nama, umur_bar, kuat?)
        if r["bar_since_break"] <= fresh_max:
            if r["break_valid"]:
                kandidat.append(("BREAKOUT 🚀", r["bar_since_break"], True))
            else:
                kandidat.append(("Breakout tanpa volume ⚠️",
                                 r["bar_since_break"], False))
        if r["bar_since_cross"] <= fresh_max:
            kandidat.append(("GOLDEN CROSS ✨", r["bar_since_cross"],
                             bool(r["tiga_ma"])))
        if r["bar_since_pivot"] <= fresh_max and r["trend_up"]:
            kandidat.append(("RECLAIM PIVOT 🎯", r["bar_since_pivot"],
                             bool(r["rvol"] >= 1.2)))
        if r["pola"] and any(k in r["pola"] for k in BULLISH_CANDLE):
            # candle cuma "kuat" kalau ada konteks: trend naik + volume
            kuat = bool(r["trend_up"] and r["rvol"] >= 1.2
                        and r["di_atas_pivot"])
            kandidat.append((r["pola"], 0, kuat))
        if not kandidat:
            return pd.Series({"event": "-", "bar_since": 999,
                              "event_kuat": False, "fresh": False})
        # prioritas: yang kuat dulu, lalu yang paling baru
        kandidat.sort(key=lambda x: (not x[2], x[1]))
        nama, umur, kuat = kandidat[0]
        return pd.Series({"event": nama, "bar_since": int(umur),
                          "event_kuat": bool(kuat), "fresh": bool(kuat)})

    df = pd.concat([df, df.apply(event_row, axis=1)], axis=1)

    rsi_ok = df["rsi_ema"].between(r_lo, r_hi)
    a_lo, a_hi = prof["atr"]
    atr_ok = df["atr_pct"].between(a_lo, a_hi)
    likuid = df["turnover_jt"] >= MIN_TURNOVER_JT
    konfirmasi = df["rvol"] >= MIN_RVOL_BUY

    # --- iq_score: SATU angka, murni dari alpha lintas saham -------------
    df["iq_score"] = df["alpha_pct"].round(1)
    df["score"] = (df["iq_score"] / 10).round(1)      # 0-10, buat UI lama

    # --- mesin_score: KUALITAS EKSEKUSI, bukan salinan alpha -------------
    # (v3.1: mesin_score korelasi 0.89 sama score, iq_score 0.98 — tiga
    #  kolom yang isinya informasi yang sama. Sekarang mesin_score ngukur
    #  hal yang beda: seberapa layak sinyal ini DIEKSEKUSI.)
    likuid_r = demeaned_rank(np.log(df["turnover_jt"].clip(lower=1)))
    sempit_r = demeaned_rank(-df["risiko_pct"].fillna(df["risiko_pct"].max()))
    rr_r = demeaned_rank(df["rr"].fillna(0))
    df["mesin_score"] = (((likuid_r + sempit_r + rr_r) / 3 + 1) * 50).round(1)

    df["mesin_grade"] = pd.cut(
        df["mesin_score"], [-0.1, 35, 55, 75, 90, 100.1],
        labels=["WAIT ❌", "WATCH 👀", "LAYAK ⚡", "PRESISI 🎯", "BANDAR 🔵"]
    ).astype(str)

    # --- verdict ---------------------------------------------------------
    # ── FUNNEL: tiap syarat dicatat terpisah. Kalau nol BUY, lo bisa lihat
    #    GERBANG MANA yang nutup — bukan cuma "nggak ada sinyal" yang bikin
    #    orang nebak-nebak. Ini yang paling sering hilang di scanner.
    syarat = {
        "event fresh & kuat": df["fresh"],
        f"alpha >= {min_iq:.0f}": df["iq_score"] >= min_iq,
        "trend naik": df["trend_up"],
        "di atas VWAP20": df["above_vwap"],
        f"RSI {r_lo}-{r_hi}": rsi_ok,
        f"ATR {prof['atr'][0]}-{prof['atr'][1]}%": atr_ok,
        "likuid": likuid,
        f"RVOL >= {MIN_RVOL_BUY}": konfirmasi,
        f"R:R >= {min_rr}": df["rr"] >= min_rr,
        f"risiko <= {max_risiko:.0f}%": df["risiko_pct"] <= max_risiko,
        # CATATAN: aturan buku 3.14 eq. 328 ("likuidasi long kalau P >= R")
        # BENTROK sama strategi channel 3.15 — breakout Donchian artinya
        # harga MEMANG di atas resistance, itu justru sinyalnya. Digabung
        # mentah-mentah, syarat ini ngebunuh 100% breakout (kelihatan jelas
        # di funnel: 7 breakout -> 0 lolos). Jadi aturan pivot cuma dipakai
        # buat sinyal NON-breakout.
        "belum kena resistance": (~df["kena_resist"]
                                  | df["event"].str.contains("BREAKOUT",
                                                             na=False)),
        # poster: "ikuti smart money, hindari melawan arus". Beli di fase
        # Mark-Down = ngelawan distribusi yang lagi jalan; cuma dibolehin
        # kalau breakout-nya beneran dibarengi ledakan volume (rvol >= 2).
        "bukan fase Mark-Down": (~df["fase"].str.contains("Mark-Down",
                                                          na=False)
                                 | (df["event"].str.contains("BREAKOUT",
                                                             na=False)
                                    & (df["rvol"] >= 2.0))),
    }
    layak = pd.Series(True, index=df.index)
    funnel = {}
    for nama, m in syarat.items():
        m = m.fillna(False).astype(bool)
        funnel[nama] = {"lolos_sendiri": int(m.sum()),
                        "lolos_kumulatif": int((layak & m).sum())}
        layak = layak & m
    df.attrs["funnel"] = funnel
    # berapa saham yang cuma gagal DI SATU syarat -> daftar "nyaris"
    gagal = sum((~m.fillna(False).astype(bool)).astype(int)
                for m in syarat.values())
    df["gagal_syarat"] = gagal
    df["nyaris"] = (gagal == 1) & (~layak)
    # syarat mana yang kurang (buat baris yang nyaris lolos)
    kurang = pd.Series("", index=df.index, dtype=object)
    for nama, m in syarat.items():
        m = m.fillna(False).astype(bool)
        kurang = kurang.mask(df["nyaris"] & (~m), nama)
    df["kurang"] = kurang

    hold = (df["trend_up"] & (df["iq_score"] >= 60))
    df["iq_verdict"] = np.where(layak, "BUY",
                                np.where(df["nyaris"], "NYARIS",
                                         np.where(hold, "HOLD", "WAIT")))

    df["signal"] = np.where(
        df["iq_score"] >= 90, "GACOR ⚡",
        np.where(df["iq_score"] >= 70, "POTENSIAL 🔥", "WATCH 👀"))
    df["sinyal_v2"] = np.where(
        layak & (df["rvol"] >= 2), "HAKA 🔨",
        np.where(df["trend_up"], "ON TRACK ✅", "WAIT ❌"))

    # alasan yang bisa dibaca manusia (buat Telegram & audit)
    def alasan(r):
        a = []
        if r["iq_verdict"] == "NYARIS" and r["kurang"]:
            a.append(f"NYARIS — kurang: {r['kurang']}")
        if r["fresh"]:
            a.append(f"{r['event']} ({r['bar_since']}d lalu)")
        if r["tiga_ma"]:
            a.append("3MA searah")
        if r["fase"] not in ("-", "Transisi ↔️"):
            a.append(r["fase"])
        if r["vol_regime"] != "NORMAL":
            a.append(r["vol_regime"])
        return " · ".join(a) if a else "-"
    df["alasan"] = df.apply(alasan, axis=1)
    return df


# ════════════════════════════════════════════════════════════════════════
#  KELLY — dari rekam jejak jurnal sendiri
# ════════════════════════════════════════════════════════════════════════
def ukuran_kelly(df, cap=0.10, min_sampel=30):
    """f* = p - (1-p)/b, dipakai half-Kelly, cap 10%.

    v3.1 pakai min_sampel=10. Di n=10, standard error win-rate itu ~16
    poin persen — Kelly-nya cuma noise yang dipoles. Dinaikin ke 30.
    """
    df = df.copy()
    df["kelly_%"] = "-"
    if df.empty:
        return df
    ev = baca_evaluasi()
    if ev is None or ev.empty or "t3_ret" not in ev.columns:
        return df
    d = ev.dropna(subset=["t3_ret"])
    peta = {}
    for sig, g in d.groupby("signal"):
        if len(g) < min_sampel:
            continue
        p = float((g["t3_ret"] > 0).mean())
        win = g.loc[g["t3_ret"] > 0, "t3_ret"].mean()
        loss = -g.loc[g["t3_ret"] <= 0, "t3_ret"].mean()
        if not np.isfinite(win) or not np.isfinite(loss) or loss <= 0:
            continue
        f = max(p - (1 - p) / (win / loss), 0)
        peta[sig] = round(min(f / 2, cap) * 100, 1)
    if peta:
        df["kelly_%"] = df["signal"].map(peta).fillna("-")
    return df


def max_order(turnover_jt, sigma_d, target_impact=0.005, cap_adv=0.05):
    """Square-root law: impact ≈ sigma * sqrt(Q/ADV) <= target.
       -> Q <= ADV * (target/sigma)^2, dicap cap_adv * ADV."""
    if not np.isfinite(sigma_d) or sigma_d <= 0:
        return 0
    q = turnover_jt * (target_impact / sigma_d) ** 2
    return int(max(round(min(q, cap_adv * turnover_jt)), 0))


# ════════════════════════════════════════════════════════════════════════
#  REGIME PASAR — IHSG + BREADTH
# ════════════════════════════════════════════════════════════════════════
def get_market_regime(close: pd.DataFrame | None = None):
    """Auto-deteksi kondisi market -> rekomendasi mode Casper.

    v3.1 cuma lihat IHSG vs EMA. Ditambah BREADTH (% saham di atas MA50):
    IHSG bisa naik gara-gara 4 bank besar sementara 90% pasar turun —
    persis kondisi di mana scanner momentum ngasih sinyal palsu.

    Return: (mode, harga, ema_cepat, ema_lambat, penjelasan)
    """
    import yfinance as yf
    breadth = np.nan
    if close is not None and not close.empty:
        try:
            ma50 = close.rolling(50).mean().iloc[-1]
            breadth = float((close.iloc[-1] > ma50).mean() * 100)
        except Exception:                              # noqa: BLE001
            breadth = np.nan
    try:
        df = yf.Ticker(IHSG).history(period="6mo", interval="1d",
                                     auto_adjust=True)
        c = df["Close"].dropna()
        if len(c) < 40:
            return ("Intraday", 0.0, 0.0, 0.0,
                    "Data IHSG kurang -> default Intraday")
        price = float(c.iloc[-1])
        ema_f = float(c.ewm(span=10, adjust=False).mean().iloc[-1])
        ema_s = float(c.ewm(span=30, adjust=False).mean().iloc[-1])
        chg3 = float((c.iloc[-1] / c.iloc[-4] - 1) * 100)
        ret20 = float((c.iloc[-1] / c.iloc[-21] - 1) * 100)

        band = 0.012
        atas_f = price > ema_f * (1 - band)
        atas_f_jelas = price > ema_f * (1 + band)
        atas_s = price > ema_s
        b_txt = f" · breadth {breadth:.0f}%" if np.isfinite(breadth) else ""
        # breadth rendah = rally cuma di segelintir saham -> jangan agresif
        rapuh = np.isfinite(breadth) and breadth < 40

        if atas_f_jelas and atas_s and ret20 >= 6 and not rapuh:
            return ("Bagger", price, ema_f, ema_s,
                    f"RALLY 🚀 — IHSG {price:,.0f} +{ret20:.1f}%/20h, "
                    f"di atas EMA10 & EMA30{b_txt}")
        if atas_f and atas_s:
            m = "Momentum" if rapuh else "Swing"
            note = " (breadth tipis — rally cuma di segelintir saham)" if rapuh else ""
            return (m, price, ema_f, ema_s,
                    f"UPTREND — IHSG {price:,.0f} di atas EMA10 & EMA30 "
                    f"({ret20:+.1f}%/20h){b_txt}{note}")
        if atas_f and not atas_s:
            return ("Momentum", price, ema_f, ema_s,
                    f"Recovery — IHSG {price:,.0f} di atas EMA10, EMA30 "
                    f"nyusul (3D {chg3:+.1f}%){b_txt}")
        if not atas_f and chg3 > 0.5:
            return ("Intraday", price, ema_f, ema_s,
                    f"Mulai pulih tapi belum clear — IHSG {price:,.0f} "
                    f"3D {chg3:+.1f}%{b_txt}")
        if not atas_f and not atas_s:
            return ("Scalping", price, ema_f, ema_s,
                    f"BEARISH — IHSG {price:,.0f} di bawah EMA10 & EMA30 "
                    f"({ret20:+.1f}%/20h){b_txt}")
        return ("Intraday", price, ema_f, ema_s,
                f"SIDEWAYS — IHSG {price:,.0f} belum ada arah{b_txt}")
    except Exception as e:                             # noqa: BLE001
        return ("Intraday", 0.0, 0.0, 0.0,
                f"IHSG error ({e}) -> default Intraday")


# ════════════════════════════════════════════════════════════════════════
#  SCAN
# ════════════════════════════════════════════════════════════════════════
KOLOM_HASIL = [
    "ts", "date", "data_date", "bar", "ticker", "mode",
    "score", "signal", "sinyal_v2", "mesin_grade", "mesin_score",
    "iq_verdict", "iq_score", "alpha", "event", "bar_since", "event_kuat",
    "alasan",
    "price", "tp", "sl", "rr", "tp_dari", "sl_dari", "risiko_pct",
    "exit_2pct", "pivot_c", "pivot_r", "pivot_s", "dc_hi", "dc_lo",
    "atr_pct", "rvol", "rsi_ema", "turnover_jt", "vol_regime", "var5_pct",
    "max_order_jt", "above_vwap", "pola", "fase",
    "f_mom", "f_resmom", "f_lowvol", "f_meanrev",
    "gagal_syarat", "kurang", "kelly_%",
]


def scan(tickers=None, demo=False, semua=False, mode="Swing",
         min_turnover_jt=MIN_TURNOVER_JT, min_harga=MIN_HARGA,
         fresh_max=FRESH_MAX_BAR, min_iq=70.0, max_risiko=8.0, min_rr=1.5):
    global LAST_CLOSE, LAST_META
    if tickers is None:
        tickers = muat_ticker_semua() if semua else DEFAULT_TICKERS
    else:
        tickers = normalisasi(tickers)

    if demo:
        data = data_demo(tickers)
        ihsg = data["Close"].mean(axis=1)          # proksi indeks
    else:
        data = unduh_ohlcv(tickers)
        ihsg = unduh_ihsg()

    close = data["Close"]
    LAST_CLOSE = close

    # ---- STATUS BAR TERAKHIR (fix penting) ------------------------------
    # v3.1 nggak pernah cek tanggal bar terakhir. Kalau Yahoo balikin data
    # basi (libur, feed telat), sinyalnya tetap dicap tanggal HARI INI dan
    # masuk jurnal — evaluasi T+1/T+3 jadi ngukur hari yang salah.
    tgl_bar = pd.Timestamp(close.index[-1]).date()
    hari_ini = now_wib().date()
    porsi = porsi_sesi()
    if tgl_bar == hari_ini and 0 < porsi < 1:
        bar_status, bar_partial = f"BERJALAN ({porsi*100:.0f}% sesi)", True
    elif tgl_bar == hari_ini:
        bar_status, bar_partial = "TUTUP", False
    else:
        selisih = (hari_ini - tgl_bar).days
        bar_status = f"BASI ({selisih} hari lalu)"
        bar_partial = False
    LAST_META = {"data_date": str(tgl_bar), "bar": bar_status,
                 "porsi_sesi": porsi, "mode": mode}

    rows = []
    for t in close.columns:
        try:
            r = fitur_ticker(data["Open"][t], data["High"][t], data["Low"][t],
                             close[t], data["Volume"][t], mode=mode,
                             min_turnover_jt=min_turnover_jt,
                             min_harga=min_harga,
                             bar_partial=bar_partial, porsi=porsi)
        except Exception as e:                          # noqa: BLE001
            print(f"    [!] {t} dilewati ({type(e).__name__}: {e})")
            continue
        if r:
            rows.append(r)

    if not rows:
        # FIX: v3.1 crash KeyError 'score' di sini.
        print("[i] Nol saham lolos filter kualitas.")
        return pd.DataFrame(columns=KOLOM_HASIL)

    df = pd.DataFrame(rows).set_index("ticker", drop=False)

    # ---- faktor lintas saham -------------------------------------------
    prof = MODES.get(mode, MODES["Swing"])
    rm = residual_momentum(close[[c for c in close.columns
                                  if str(c).replace(".JK", "") in df.index]],
                           ihsg, prof["form"], prof["skip"])
    rm.index = [str(i).replace(".JK", "") for i in rm.index]
    df["f_resmom"] = rm.reindex(df.index).fillna(0.0)

    # buku 3.9 eq. 292-294: return di-demean lintas cluster (di sini
    # cluster = seluruh universe). Yang return-nya di BAWAH rata-rata
    # pasar = "murah" -> faktor dibalik tandanya.
    df["f_meanrev"] = -(df["_r_pendek"] - df["_r_pendek"].mean())

    df = gabung_alpha(df)

    # ---- TP/SL & risiko -------------------------------------------------
    lvl = df.apply(level_tp_sl, axis=1, result_type="expand")
    df = pd.concat([df, lvl], axis=1)
    df["max_order_jt"] = [max_order(t, s) for t, s
                          in zip(df["turnover_jt"], df["sigma_ewma"])]

    df = klasifikasi(df, mode, fresh_max=fresh_max, min_iq=min_iq,
                     max_risiko=max_risiko, min_rr=min_rr)
    LAST_META["funnel"] = df.attrs.get("funnel", {})
    LAST_META["n_discan"] = len(df)

    now = now_wib()
    df["ts"] = now.strftime("%H:%M:%S")
    df["date"] = now.strftime("%Y-%m-%d")
    df["data_date"] = str(tgl_bar)
    df["bar"] = bar_status
    df["mode"] = f"{mode} {prof['emoji']}"
    for k in ("price", "tp", "sl"):
        df[k] = df[k].round(0)
    for k in ("alpha", "f_mom", "f_resmom", "f_lowvol", "f_meanrev"):
        df[k] = pd.to_numeric(df[k], errors="coerce").round(3)
    for k in ("atr_pct", "rvol", "rsi_ema", "var5_pct"):
        df[k] = pd.to_numeric(df[k], errors="coerce").round(2)
    df["turnover_jt"] = df["turnover_jt"].round(0)
    df["rsi_ema"] = df["rsi_ema"].round(1)

    df = ukuran_kelly(df)
    df = df.sort_values(["fresh", "iq_score", "mesin_score"],
                        ascending=[False, False, False]).reset_index(drop=True)
    return df.reindex(columns=KOLOM_HASIL)


# ════════════════════════════════════════════════════════════════════════
#  JURNAL
# ════════════════════════════════════════════════════════════════════════
def _kredensial_gsheet():
    if os.path.exists("gsheet_creds.json"):
        return json.load(open("gsheet_creds.json"))
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:                                   # noqa: BLE001
        pass
    return None


def jurnal_backend():
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
        except Exception as e:                          # noqa: BLE001
            print(f"[!] Google Sheets gagal ({e}) — pakai CSV lokal.")
    _SHEET = "csv"
    return _SHEET


def backend_label():
    return "Google Sheets ☁️" if jurnal_backend() != "csv" else "CSV lokal 📁"


def _worksheet(sh, nama, header):
    import gspread
    try:
        ws = sh.worksheet(nama)
        if header and ws.row_values(1) != [str(h) for h in header]:
            ws.update_title(f"{nama}_lama_{now_wib():%m%d%H%M}")
            raise gspread.WorksheetNotFound(nama)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(nama, rows=5000, cols=max(len(header), 5))
        if header:
            ws.append_row([str(h) for h in header])
    return ws


def _kunci_lama(path=JURNAL):
    """Baca kunci (date, ticker, mode) yang UDAH ada.

    Return None kalau gagal baca — BUKAN set kosong. Ini bug v3.1 yang
    bikin jurnal lo isinya 4x duplikat: waktu backend Sheets kepilih tapi
    read-nya gagal, `existing` jadi set kosong, semua baris dianggap baru,
    append_rows juga gagal, terus fallback nulis SEMUANYA ke CSV. Tiap
    scan. Sekarang gagal-baca = batal nulis, bukan tulis ulang semua.
    """
    sh = jurnal_backend()
    kunci = set()
    if sh != "csv":
        try:
            rows = sh.worksheet("sinyal").get_all_records()
            for r in rows:
                kunci.add((str(r.get("date")), str(r.get("ticker")),
                           str(r.get("mode"))))
            return kunci
        except Exception as e:                          # noqa: BLE001
            print(f"[!] Gagal baca jurnal Sheets ({e}).")
            return None
    if not os.path.exists(path):
        return kunci
    try:
        lama = pd.read_csv(path, usecols=["date", "ticker", "mode"])
        return set(zip(lama["date"].astype(str), lama["ticker"].astype(str),
                       lama["mode"].astype(str)))
    except Exception as e:                              # noqa: BLE001
        print(f"[!] Gagal baca {path} ({e}).")
        return None


def catat_jurnal(df, path=JURNAL):
    """Tulis sinyal baru dengan dedup per (date, ticker, mode)."""
    if df is None or df.empty:
        return 0
    kunci = _kunci_lama(path)
    if kunci is None:
        print("[!] Jurnal nggak bisa dibaca — penulisan DIBATALKAN "
              "biar nggak numpuk duplikat. Perbaiki backend dulu.")
        return 0

    baru = df[~df.apply(lambda r: (str(r["date"]), str(r["ticker"]),
                                   str(r["mode"])) in kunci, axis=1)]
    if baru.empty:
        return 0

    sh = jurnal_backend()
    if sh != "csv":
        try:
            ws = _worksheet(sh, "sinyal", baru.columns.tolist())
            ws.append_rows(baru.fillna("").astype(str).values.tolist())
            return len(baru)
        except Exception as e:                          # noqa: BLE001
            print(f"[!] Gagal tulis Sheets ({e}) — fallback CSV.")

    if os.path.exists(path):
        try:
            lama_cols = pd.read_csv(path, nrows=0).columns.tolist()
            if lama_cols != baru.columns.tolist():
                os.replace(path, path.replace(".csv", "_lama.csv"))
        except Exception:                               # noqa: BLE001
            pass
    baru.to_csv(path, mode="a", index=False, header=not os.path.exists(path))
    return len(baru)


def baca_jurnal(path=JURNAL):
    sh = jurnal_backend()
    if sh != "csv":
        try:
            rows = sh.worksheet("sinyal").get_all_records()
            if rows:
                return pd.DataFrame(rows)
        except Exception:                               # noqa: BLE001
            pass
        return None
    return pd.read_csv(path) if os.path.exists(path) else None


def baca_evaluasi(out=EVALUASI):
    sh = jurnal_backend()
    ev = None
    if sh != "csv":
        try:
            rows = sh.worksheet("evaluasi").get_all_records()
            if rows:
                ev = pd.DataFrame(rows)
        except Exception:                               # noqa: BLE001
            ev = None
    elif os.path.exists(out):
        ev = pd.read_csv(out)
    if ev is None:
        return None
    for col in ("t1_ret", "t3_ret", "t5_ret"):
        if col in ev.columns:
            ev[col] = pd.to_numeric(ev[col], errors="coerce")
    return ev


def _muat_close_evaluasi(tickers, periode="6mo"):
    import yfinance as yf
    hasil = {}
    tickers_jk = normalisasi(tickers)
    for i in range(0, len(tickers_jk), BATCH):
        chunk = tickers_jk[i:i + BATCH]
        try:
            data = yf.download(chunk, period=periode, auto_adjust=True,
                               progress=False)["Close"]
            if isinstance(data, pd.Series):
                data = data.to_frame(chunk[0])
            for col in data.columns:
                s = data[col].dropna()
                if len(s):
                    hasil[str(col).replace(".JK", "")] = s
        except Exception:                               # noqa: BLE001
            pass
    return hasil


def evaluasi_jurnal(close_df=None, path=JURNAL, out=EVALUASI, max_tickers=250):
    """Fixed horizon T+1 / T+3 / T+5 hari bursa dari TANGGAL BAR DATA
    (bukan tanggal scan) — kalau scan jalan pas pasar tutup atau feed basi,
    dua tanggal itu beda dan v3.1 salah geser satu hari."""
    j = baca_jurnal(path)
    if j is None or len(j) == 0:
        return baca_evaluasi(out)

    lama_ev = baca_evaluasi(out)
    sudah = set()
    if lama_ev is not None and len(lama_ev):
        sudah = set(zip(lama_ev["date"].astype(str),
                        lama_ev["ticker"].astype(str)))

    j = j.copy()
    j["price"] = pd.to_numeric(j["price"], errors="coerce")
    # pakai data_date kalau ada (v4), fallback ke date (jurnal v3 lama)
    j["_basis"] = (j["data_date"].astype(str) if "data_date" in j.columns
                   else j["date"].astype(str))
    today = now_wib().strftime("%Y-%m-%d")
    j = j[j["_basis"] < today]
    if j.empty:
        return lama_ev
    j = j.drop_duplicates(subset=["date", "ticker"], keep="first")
    j = j[~j.apply(lambda r: (str(r["date"]), str(r["ticker"])) in sudah,
                   axis=1)]
    if j.empty:
        return lama_ev

    tickers = j["ticker"].astype(str).unique().tolist()[:max_tickers]
    closes = _muat_close_evaluasi(tickers)

    rows = []
    for _, r in j.iterrows():
        tkr = str(r["ticker"])
        s = closes.get(tkr)
        entry = r["price"]
        if s is None or len(s) < 2 or not np.isfinite(entry) or entry <= 0:
            continue
        try:
            sdate = pd.Timestamp(r["_basis"]).date()
        except Exception:                               # noqa: BLE001
            continue
        idx_dates = [pd.Timestamp(x).date() for x in s.index]
        pos = next((i for i, d0 in enumerate(idx_dates) if d0 > sdate), None)
        if pos is None:
            continue

        def _ret(off, _s=s, _pos=pos, _e=entry):
            k = _pos + off
            if k >= len(_s):
                return np.nan
            return round((float(_s.iloc[k]) - float(_e)) / float(_e) * 100, 2)

        rows.append({
            "date": r["date"], "data_date": r["_basis"], "ticker": tkr,
            "mode": r.get("mode", ""), "signal": r.get("signal", ""),
            "event": r.get("event", ""), "sinyal_v2": r.get("sinyal_v2", ""),
            "mesin_grade": r.get("mesin_grade", ""),
            "iq_verdict": r.get("iq_verdict", ""),
            "score": r.get("score", ""), "price": float(entry),
            "t1_ret": _ret(0), "t3_ret": _ret(2), "t5_ret": _ret(4),
        })
    if not rows:
        return lama_ev

    ev_baru = pd.DataFrame(rows)
    ev = (pd.concat([lama_ev, ev_baru], ignore_index=True)
          if lama_ev is not None and len(lama_ev) else ev_baru)

    sh = jurnal_backend()
    if sh != "csv":
        try:
            ws = _worksheet(sh, "evaluasi", [])
            ws.clear()
            ws.append_row(ev.columns.tolist())
            ws.append_rows(ev.fillna("").astype(str).values.tolist())
        except Exception as e:                          # noqa: BLE001
            print(f"[!] Gagal tulis evaluasi ke Sheets: {e}")
            ev.to_csv(out, index=False)
    else:
        ev.to_csv(out, index=False)
    return ev


def ringkas_evaluasi(ev, per="signal"):
    """Win rate per label per horizon. `per` bisa 'signal' atau 'event' —
    yang kedua jauh lebih berguna: dia jawab 'breakout beneran lebih baik
    dari golden cross nggak?' """
    if ev is None or ev.empty:
        return None
    if per not in ev.columns:
        per = "signal"
    potongan = []
    for col in ("t1_ret", "t3_ret", "t5_ret"):
        if col not in ev.columns:
            continue
        d = ev.dropna(subset=[col])
        if d.empty:
            continue
        g = d.groupby(per).agg(
            jumlah=(col, "size"),
            naik=(col, lambda x: int((x > 0).sum())),
            avg_return=(col, "mean"),
            med_return=(col, "median")).reset_index()
        g["win_rate"] = (g["naik"] / g["jumlah"] * 100).round(1)
        g["avg_return"] = g["avg_return"].round(2)
        g["med_return"] = g["med_return"].round(2)
        g["horizon"] = col.replace("_ret", "").upper()
        g = g.rename(columns={per: "label"})
        potongan.append(g)
    if not potongan:
        return None
    return pd.concat(potongan, ignore_index=True)[
        ["horizon", "label", "jumlah", "naik", "win_rate",
         "avg_return", "med_return"]]


# ════════════════════════════════════════════════════════════════════════
#  TELEGRAM — dengan memori anti-spam
# ════════════════════════════════════════════════════════════════════════
def ambil_config_tele(conf=CONF_TELE):
    if os.path.exists(conf):
        return json.load(open(conf))
    tok, cid = os.environ.get("TELE_TOKEN"), os.environ.get("TELE_CHAT_ID")
    if tok and cid:
        return {"token": tok, "chat_id": cid}
    try:
        import streamlit as st
        if "token" in st.secrets and "chat_id" in st.secrets:
            return {"token": st.secrets["token"],
                    "chat_id": st.secrets["chat_id"]}
    except Exception:                                   # noqa: BLE001
        pass
    return None


def _baca_terkirim(path=TERKIRIM):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:                               # noqa: BLE001
            return {}
    return {}


def _tulis_terkirim(memori, path=TERKIRIM):
    try:
        json.dump(memori, open(path, "w"), indent=1)
    except Exception as e:                              # noqa: BLE001
        print(f"[!] Gagal simpan memori kirim: {e}")


def pilih_untuk_kirim(df, top=8, cooldown_jam=COOLDOWN_JAM, path=TERKIRIM):
    """INTI FIX 'itu-itu aja'.

    Aturan:
      1. cuma sinyal BUY yang EVENT-nya masih fresh;
      2. satu ticker + event yang sama nggak dikirim lagi dalam
         `cooldown_jam` jam;
      3. kalau nggak ada yang baru -> balikin kosong, dan Telegram DIAM.
         Nggak ada lagi "tidak ada BUY — top skor:" yang tiap 15 menit
         ngirim 5 saham yang sama.
    """
    if df is None or df.empty:
        return df.iloc[0:0] if df is not None else None, {}
    memori = _baca_terkirim(path)
    sekarang = now_wib()

    kandidat = df[(df["iq_verdict"] == "BUY") & (df["bar_since"] <= FRESH_MAX_BAR)]
    pilih, baru_memori = [], dict(memori)
    for _, r in kandidat.iterrows():
        kunci = f"{r['ticker']}|{r['event']}"
        prev = memori.get(kunci)
        if prev:
            try:
                lalu = pd.Timestamp(prev["ts"])
                if (sekarang - lalu).total_seconds() < cooldown_jam * 3600:
                    continue
            except Exception:                           # noqa: BLE001
                pass
        pilih.append(r)
        baru_memori[kunci] = {"ts": sekarang.isoformat(),
                              "iq": float(r["iq_score"])}
        if len(pilih) >= top:
            break
    # buang memori yang lebih tua dari 7 hari biar file nggak numpuk
    batas = sekarang - pd.Timedelta(days=7)
    baru_memori = {k: v for k, v in baru_memori.items()
                   if pd.Timestamp(v["ts"]) > batas}
    return (pd.DataFrame(pilih) if pilih else df.iloc[0:0]), baru_memori


LAST_TELE = {"status": "-", "n": 0}


def kirim_tele(df, top=8, conf=CONF_TELE, paksa=False, diam_kalau_kosong=True):
    """Return True kalau beneran ngirim. Kalau sengaja diam (nggak ada
    sinyal baru), status-nya dicatat di LAST_TELE supaya UI bisa bedain
    'diam karena aman' vs 'gagal karena kredensial'."""
    global LAST_TELE
    cfg = ambil_config_tele(conf)
    if cfg is None:
        LAST_TELE = {"status": "kredensial", "n": 0}
        print("[!] Kredensial Telegram nggak ketemu.")
        return False

    if paksa:
        pilih, memori = df.head(top), None
    else:
        pilih, memori = pilih_untuk_kirim(df, top=top)

    if (pilih is None or pilih.empty) and diam_kalau_kosong:
        LAST_TELE = {"status": "diam", "n": 0}
        print("[i] Nggak ada sinyal BARU — Telegram sengaja diam "
              "(anti-spam). Pakai paksa=True kalau tetap mau kirim.")
        return False

    now = now_wib()
    meta = LAST_META or {}
    baris = [
        "👻 CASPER IDX — SINYAL BARU",
        f"⏰ {now:%H:%M:%S} WIB · {now:%d %b %Y}",
        f"📅 bar data: {meta.get('data_date', '?')} ({meta.get('bar', '?')})",
        f"🎯 mode: {meta.get('mode', '?')} · {len(pilih)} sinyal fresh",
        "━━━━━━━━━━━━━━━━━━━━", ""]
    for _, r in pilih.iterrows():
        vw = "di atas VWAP" if r["above_vwap"] else "di bawah VWAP"
        rr = r["rr"] if np.isfinite(r["rr"]) else "-"
        baris += [
            f"🎯 {r['ticker']} — {r['event']}",
            f"💰 {r['price']:,.0f} · IQ {r['iq_score']:.0f}/100 · "
            f"{r['mesin_grade']}",
            f"🎯 TP {r['tp']:,.0f} ({r['tp_dari']}) · "
            f"🔴 SL {r['sl']:,.0f} ({r['sl_dari']}) · R:R {rr}",
            f"📊 RSI {r['rsi_ema']:.0f} · RVOL {r['rvol']:.2f}x · "
            f"ATR {r['atr_pct']}% · {vw}",
            f"🕯️ {r['pola'] or '-'} · {r['fase']}",
            f"📐 ½-Kelly {r['kelly_%']}% · maks order ≤ "
            f"Rp{r['max_order_jt']}jt · risiko {r['risiko_pct']}%",
            f"💡 {r['alasan']}",
            ""]
    baris.append("👻 sistem & disiplin — bukan rekomendasi beli/jual")

    import urllib.request
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = json.dumps({"chat_id": cfg["chat_id"],
                          "text": "\n".join(baris)}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        print(f"[i] Terkirim ke Telegram ({len(pilih)} sinyal).")
        if memori is not None:
            _tulis_terkirim(memori)
        LAST_TELE = {"status": "terkirim", "n": len(pilih)}
        return True
    except Exception as e:                              # noqa: BLE001
        LAST_TELE = {"status": f"error: {e}", "n": 0}
        print(f"[!] Gagal kirim Telegram: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tickers", nargs="+", default=None)
    ap.add_argument("--tele", action="store_true")
    ap.add_argument("--paksa-tele", action="store_true",
                    help="kirim top-N walau bukan sinyal baru")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--mode", default="Swing", choices=list(MODES))
    ap.add_argument("--auto-mode", action="store_true")
    ap.add_argument("--min-turnover", type=int, default=MIN_TURNOVER_JT)
    ap.add_argument("--min-harga", type=int, default=MIN_HARGA)
    ap.add_argument("--fresh", type=int, default=FRESH_MAX_BAR)
    args = ap.parse_args()

    print(f"=== CASPER ENGINE v{VERSI} ===")
    mode = args.mode
    if args.auto_mode:
        mode, *_rest, label = get_market_regime()
        print(f"[i] Auto-mode: {mode} — {label}")

    try:
        df = scan(tickers=args.tickers, demo=args.demo, semua=args.all,
                  mode=mode, min_turnover_jt=args.min_turnover,
                  min_harga=args.min_harga, fresh_max=args.fresh)
    except DataKosong as e:
        print(f"[X] {e}")
        return

    if df.empty:
        print("Nol saham lolos filter.")
        return
    print(f"[i] bar data {LAST_META['data_date']} ({LAST_META['bar']})")
    kol = ["ticker", "iq_score", "signal", "event", "bar_since", "price",
           "tp", "sl", "rr", "rvol", "rsi_ema", "pola", "fase", "iq_verdict"]
    print(df[kol].head(20).to_string(index=False))
    n = catat_jurnal(df)
    print(f"[i] {n} baris baru masuk jurnal.")

    ev = evaluasi_jurnal()
    if ev is not None and len(ev):
        print("\n--- EVALUASI (per event) ---")
        r = ringkas_evaluasi(ev, per="event")
        if r is not None:
            print(r.to_string(index=False))
    if args.tele:
        kirim_tele(df, top=args.top, paksa=args.paksa_tele)


if __name__ == "__main__":
    main()
