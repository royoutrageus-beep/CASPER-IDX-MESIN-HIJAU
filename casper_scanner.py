# -*- coding: utf-8 -*-
"""
CASPER IDX SCANNER — 7 Ilmu Matematika dalam 1 Sistem
======================================================
  01 Aljabar Linear    -> Matriks korelasi antar saham
  02 Probabilitas      -> Win rate, expected return sistem trading
  03 Statistika        -> Backtest: profit factor, expectancy, Sharpe ratio
  04 Deret Waktu       -> Trend MA50 vs MA200 (Golden/Death Cross)
  05 Kalkulus Stokastik-> Monte Carlo simulation (GBM) portofolio
  06 Optimisasi        -> Max-Sharpe portfolio (random search 10.000 kombinasi)
  07 Metode Numerik    -> Screening funnel: teknikal -> fundamental -> kandidat

Cara pakai:
  pip install yfinance pandas numpy openpyxl
  python casper_scanner.py                  # 12 saham default
  python casper_scanner.py --all            # SEMUA saham IDX (~700, lama!)
  python casper_scanner.py --demo           # data simulasi (tanpa internet)
  python casper_scanner.py --tickers BBCA.JK BBRI.JK TLKM.JK
  python casper_scanner.py --file daftar.txt   # ticker dari file teks

Catatan mode --all:
  * Daftar ticker diunduh otomatis (cache: tickers_idx.txt). Edit file itu
    kalau mau menambah/mengurangi saham.
  * Harga diunduh per batch 50; fundamental hanya di-request untuk saham
    yang lolos filter trend (hemat kuota API Yahoo).
  * Korelasi/Monte Carlo/optimisasi dijalankan pada subset fokus
    (kandidat, atau top-12 trend terkuat) supaya hasilnya terbaca.

Output: hasil_scan_casper.xlsx
"""

import argparse
import os
import time
import numpy as np
import pandas as pd

# ----------------------------- KONFIGURASI -----------------------------
DEFAULT_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK",
    "TLKM.JK", "ASII.JK", "UNVR.JK", "ICBP.JK",
    "ANTM.JK", "ADRO.JK", "PGAS.JK", "GOTO.JK",
]
URL_DAFTAR_IDX = ("https://raw.githubusercontent.com/wildangunawan/"
                  "Dataset-Saham-IDX/master/List%20Emiten/all.csv")
CACHE_TICKER = "tickers_idx.txt"
PERIODE = "2y"
MODAL_AWAL = 100_000_000
N_MONTE_CARLO = 10_000
N_PORTO_SIM = 10_000
TAHUN_SIMULASI = 10
RISK_FREE = 0.055
BATCH_HARGA = 50               # ticker per request harga
JEDA_BATCH = 1.0               # detik antar batch harga
JEDA_INFO = 0.4                # detik antar request fundamental
MAKS_FOKUS = 12                # jumlah saham untuk korelasi/MC/optimisasi

KRITERIA = {"ROE_MIN": 0.15, "PBV_MAX": 3.0, "DER_MAX": 1.0, "NPM_MIN": 0.10}


# ----------------------------- DAFTAR TICKER ---------------------------
def muat_ticker_semua():
    """Unduh daftar semua emiten IDX (sekali), simpan ke cache lokal."""
    if os.path.exists(CACHE_TICKER):
        with open(CACHE_TICKER) as fh:
            t = [b.strip() for b in fh if b.strip()]
        print(f"[i] {len(t)} ticker dimuat dari {CACHE_TICKER}")
        return t
    print("[i] Mengunduh daftar emiten IDX ...")
    import urllib.request
    data = urllib.request.urlopen(URL_DAFTAR_IDX, timeout=30).read().decode()
    kode = [ln.split(",")[0].strip() for ln in data.splitlines()[1:] if ln.strip()]
    tickers = sorted({k + ".JK" for k in kode if len(k) == 4 and k.isalpha()})
    with open(CACHE_TICKER, "w") as fh:
        fh.write("\n".join(tickers))
    print(f"[i] {len(tickers)} ticker tersimpan di {CACHE_TICKER}")
    return tickers


# ----------------------------- AMBIL DATA ------------------------------
def unduh_harga(tickers, periode):
    """Unduh harga close per batch, buang saham yang datanya < 200 hari."""
    import yfinance as yf
    frames = []
    for i in range(0, len(tickers), BATCH_HARGA):
        chunk = tickers[i:i + BATCH_HARGA]
        df = yf.download(chunk, period=periode, auto_adjust=True,
                         progress=False)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(chunk[0])
        frames.append(df)
        print(f"    harga {min(i + BATCH_HARGA, len(tickers))}/{len(tickers)}")
        if i + BATCH_HARGA < len(tickers):
            time.sleep(JEDA_BATCH)
    harga = pd.concat(frames, axis=1)
    harga = harga.loc[:, ~harga.columns.duplicated()]
    harga = harga.dropna(axis=1, thresh=200)      # minimal 200 hari data
    print(f"[i] {harga.shape[1]} saham punya data memadai (>=200 hari)")
    return harga


def ambil_fundamental(tickers):
    """Request .info hanya untuk daftar terbatas (hemat rate limit)."""
    import yfinance as yf
    hasil = {}
    for i, t in enumerate(tickers, 1):
        try:
            info = yf.Ticker(t).info
            hasil[t] = {
                "ROE": info.get("returnOnEquity", np.nan),
                "PBV": info.get("priceToBook", np.nan),
                "DER": (info.get("debtToEquity") or np.nan) / 100
                       if info.get("debtToEquity") else np.nan,
                "NPM": info.get("profitMargins", np.nan),
            }
        except Exception:
            hasil[t] = {k: np.nan for k in ["ROE", "PBV", "DER", "NPM"]}
        if i % 10 == 0 or i == len(tickers):
            print(f"    fundamental {i}/{len(tickers)}")
        time.sleep(JEDA_INFO)
    return pd.DataFrame(hasil).T


def ambil_data_demo(tickers, n_hari=504, seed=42):
    """Data simulasi GBM — buat tes sistem tanpa internet."""
    rng = np.random.default_rng(seed)
    tanggal = pd.bdate_range(end=pd.Timestamp.today(), periods=n_hari)
    n = len(tickers)
    A = rng.normal(0, 1, (n, n))
    korr = A @ A.T
    d = np.sqrt(np.diag(korr))
    korr = korr / np.outer(d, d)
    korr = 0.5 * korr + 0.5 * np.eye(n)
    L = np.linalg.cholesky(korr)
    mu = rng.uniform(0.02, 0.25, n) / 252
    sigma = rng.uniform(0.18, 0.45, n) / np.sqrt(252)
    z = rng.normal(0, 1, (n_hari, n)) @ L.T
    harga0 = rng.uniform(500, 10000, n)
    harga = pd.DataFrame(harga0 * np.exp(np.cumsum(mu + sigma * z, axis=0)),
                         index=tanggal, columns=tickers)
    fundamental = pd.DataFrame({
        "ROE": rng.uniform(0.03, 0.30, n),
        "PBV": rng.uniform(0.5, 6.0, n),
        "DER": rng.uniform(0.1, 2.5, n),
        "NPM": rng.uniform(0.02, 0.35, n),
    }, index=tickers)
    sehat = rng.choice(n, size=max(3, n // 3), replace=False)
    fundamental.iloc[sehat] = np.column_stack([
        rng.uniform(0.16, 0.30, len(sehat)),
        rng.uniform(0.8, 2.8, len(sehat)),
        rng.uniform(0.2, 0.9, len(sehat)),
        rng.uniform(0.11, 0.30, len(sehat)),
    ])
    return harga, fundamental


# ------------------- 01 ALJABAR LINEAR: KORELASI ------------------------
def modul_korelasi(harga):
    ret = harga.pct_change().dropna()
    korr = ret.corr().round(2)
    korr.index.name = None
    korr.columns.name = None
    pasangan = (korr.where(np.triu(np.ones(korr.shape), 1).astype(bool))
                .stack().sort_values(ascending=False))
    top = pasangan.head(5).reset_index()
    top.columns = ["Saham A", "Saham B", "Korelasi (r)"]
    return korr, top


# ------------- 04 DERET WAKTU: TREND MA50 vs MA200 ----------------------
def modul_trend(harga):
    rows = []
    for t in harga.columns:
        s = harga[t].dropna()
        if len(s) < 200:
            continue
        ma50, ma200 = s.rolling(50).mean(), s.rolling(200).mean()
        if np.isnan(ma200.iloc[-1]):
            continue
        naik = ma50.iloc[-1] > ma200.iloc[-1]
        rows.append({
            "Ticker": t,
            "Harga": round(s.iloc[-1], 0),
            "MA50": round(ma50.iloc[-1], 0),
            "MA200": round(ma200.iloc[-1], 0),
            "Gap MA (%)": round((ma50.iloc[-1] / ma200.iloc[-1] - 1) * 100, 1),
            "Di Atas MA50": bool(s.iloc[-1] > ma50.iloc[-1]),
            "Trend": "NAIK (Bullish)" if naik else "TURUN (Bearish)",
        })
    return pd.DataFrame(rows)


# ------- 02+03 PROBABILITAS & STATISTIKA: BACKTEST MA CROSS --------------
def modul_backtest(harga):
    rows = []
    for t in harga.columns:
        s = harga[t].dropna()
        if len(s) < 200:
            continue
        ma50, ma200 = s.rolling(50).mean(), s.rolling(200).mean()
        sinyal = (ma50 > ma200).astype(int)
        ganti = sinyal.diff().fillna(0)
        trades, beli = [], None
        for tgl in s.index:
            if ganti[tgl] == 1:
                beli = s[tgl]
            elif ganti[tgl] == -1 and beli:
                trades.append(s[tgl] / beli - 1)
                beli = None
        if beli:
            trades.append(s.iloc[-1] / beli - 1)
        if not trades:
            continue
        tr = np.array(trades)
        menang, kalah = tr[tr > 0], tr[tr <= 0]
        win_rate = len(menang) / len(tr)
        avg_p = menang.mean() if len(menang) else 0
        avg_l = abs(kalah.mean()) if len(kalah) else 0
        expectancy = win_rate * avg_p - (1 - win_rate) * avg_l
        pf = (menang.sum() / abs(kalah.sum())) if len(kalah) and kalah.sum() != 0 else np.inf
        ret_h = s.pct_change().dropna()
        sharpe = ((ret_h.mean() * 252 - RISK_FREE)
                  / (ret_h.std() * np.sqrt(252))) if ret_h.std() > 0 else 0
        rows.append({
            "Ticker": t, "Total Transaksi": len(tr),
            "Win Rate": f"{win_rate:.0%}",
            "Avg Profit": f"{avg_p:+.1%}", "Avg Loss": f"{-avg_l:.1%}",
            "Expectancy": f"{expectancy:+.2%}",
            "Profit Factor": round(pf, 2) if np.isfinite(pf) else "∞",
            "Sharpe Ratio": round(sharpe, 2),
            "Edge": "POSITIF" if expectancy > 0 else "NEGATIF",
        })
    return pd.DataFrame(rows)


# ---------- 05 KALKULUS STOKASTIK: MONTE CARLO (GBM) ---------------------
def modul_monte_carlo(harga, bobot, modal=MODAL_AWAL,
                      tahun=TAHUN_SIMULASI, n_sim=N_MONTE_CARLO, seed=7):
    ret = harga.pct_change().dropna()
    port_ret = (ret * bobot).sum(axis=1)
    mu, sigma = port_ret.mean() * 252, port_ret.std() * np.sqrt(252)
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1, n_sim)
    akhir = modal * np.exp((mu - 0.5 * sigma**2) * tahun
                           + sigma * np.sqrt(tahun) * z)
    p5, p50, p95 = np.percentile(akhir, [5, 50, 95])
    return pd.DataFrame({
        "Metrik": ["Modal Awal", "Expected Return/thn", "Volatilitas/thn",
                   "Durasi", "Jumlah Simulasi",
                   "TERBAIK (P95)", "MEDIAN (P50)", "TERBURUK (P5)"],
        "Nilai": [f"Rp{modal:,.0f}", f"{mu:.1%}", f"{sigma:.1%}",
                  f"{tahun} tahun", f"{n_sim:,}",
                  f"Rp{p95:,.0f}", f"Rp{p50:,.0f}", f"Rp{p5:,.0f}"],
    })


# ------------- 06 OPTIMISASI: MAX-SHARPE PORTFOLIO -----------------------
def modul_optimisasi(harga, n_sim=N_PORTO_SIM, seed=11):
    ret = harga.pct_change().dropna()
    mu, cov = ret.mean() * 252, ret.cov() * 252
    n = len(harga.columns)
    rng = np.random.default_rng(seed)
    W = rng.dirichlet(np.ones(n), n_sim)
    ret_p = W @ mu.values
    vol_p = np.sqrt(np.einsum("ij,jk,ik->i", W, cov.values, W))
    sharpe = (ret_p - RISK_FREE) / vol_p
    best = sharpe.argmax()
    bobot = pd.Series(W[best], index=harga.columns)
    alokasi = pd.DataFrame({
        "Bobot (%)": (bobot * 100).round(1),
        "Alokasi (Rp)": (bobot * MODAL_AWAL).round(0),
    }).sort_values("Bobot (%)", ascending=False)
    alokasi.index.name = None
    ringkas = pd.DataFrame({
        "Metrik": ["Expected Return", "Volatilitas (Risiko)", "Sharpe Ratio"],
        "Nilai": [f"{ret_p[best]:.1%}", f"{vol_p[best]:.1%}",
                  f"{sharpe[best]:.2f}"],
    })
    return bobot, alokasi, ringkas


# --------- 07 METODE NUMERIK: SCREENING FUNNEL ---------------------------
def modul_screening(fundamental, trend_df, total_awal):
    f = fundamental.copy()
    f["Lolos Fundamental"] = (
        (f["ROE"] >= KRITERIA["ROE_MIN"]) &
        (f["PBV"] <= KRITERIA["PBV_MAX"]) &
        (f["DER"] <= KRITERIA["DER_MAX"]) &
        (f["NPM"] >= KRITERIA["NPM_MIN"])
    )
    trend_map = trend_df.set_index("Ticker") if len(trend_df) else pd.DataFrame()
    f["Trend Naik"] = f.index.map(
        lambda t: trend_map.loc[t, "Trend"].startswith("NAIK")
        if t in trend_map.index else False)
    f["KANDIDAT"] = f["Lolos Fundamental"] & f["Trend Naik"]
    f.index.name = None
    tabel = f.reset_index().rename(columns={"index": "Ticker"})
    for c in ["ROE", "NPM"]:
        tabel[c] = tabel[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "-")
    for c in ["PBV", "DER"]:
        tabel[c] = tabel[c].map(lambda x: round(x, 2) if pd.notna(x) else "-")
    funnel = pd.DataFrame({
        "Tahap": ["Seluruh saham dipindai",
                  "Lolos Tahap 1 (Teknikal: trend naik)",
                  "Lolos Tahap 2 (+ Fundamental) = KANDIDAT"],
        "Jumlah": [total_awal, int(f["Trend Naik"].sum()),
                   int(f["KANDIDAT"].sum())],
    })
    return tabel, funnel


# ------------------------------- MAIN ------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="pakai data simulasi")
    ap.add_argument("--all", action="store_true",
                    help="scan semua saham IDX (~700, butuh waktu lama)")
    ap.add_argument("--tickers", nargs="+", default=None)
    ap.add_argument("--file", default=None, help="file teks berisi ticker")
    ap.add_argument("--output", default="hasil_scan_casper.xlsx")
    args = ap.parse_args()

    # --- tentukan daftar ticker ---
    if args.file:
        with open(args.file) as fh:
            tickers = [b.strip() for b in fh if b.strip()]
    elif args.all:
        tickers = muat_ticker_semua()
    elif args.tickers:
        tickers = args.tickers
    else:
        tickers = DEFAULT_TICKERS

    print(f"=== CASPER IDX SCANNER — 7 Ilmu, 1 Sistem ({len(tickers)} saham) ===")

    # --- ambil data harga ---
    if args.demo:
        print("[MODE DEMO] Data simulasi (bukan harga riil).")
        harga, fundamental_semua = ambil_data_demo(tickers)
    else:
        try:
            harga = unduh_harga(tickers, PERIODE)
            if harga.empty:
                raise RuntimeError("data kosong")
            fundamental_semua = None
        except Exception as e:
            print(f"[!] Gagal ambil data live ({e}). Beralih ke mode demo.")
            harga, fundamental_semua = ambil_data_demo(tickers)

    # --- teknikal dulu (murah), fundamental belakangan (mahal) ---
    trend = modul_trend(harga)                                   # 04
    backtest = modul_backtest(harga)                             # 02+03

    naik = trend[trend["Trend"].str.startswith("NAIK")]["Ticker"].tolist()
    print(f"[i] {len(naik)} saham trend naik dari {harga.shape[1]} yang discan")

    if fundamental_semua is not None:                 # mode demo
        fundamental = fundamental_semua.loc[
            [t for t in naik if t in fundamental_semua.index]]
    else:
        print("[i] Mengambil fundamental untuk saham trend naik ...")
        fundamental = ambil_fundamental(naik)

    screening, funnel = modul_screening(fundamental, trend, harga.shape[1])  # 07
    kandidat = screening[screening["KANDIDAT"]]["Ticker"].tolist()

    # --- subset fokus untuk korelasi / optimisasi / Monte Carlo ---
    if len(kandidat) >= 3:
        fokus = kandidat[:MAKS_FOKUS]
        ket_fokus = "kandidat screening"
    else:
        urut = trend.sort_values("Gap MA (%)", ascending=False)
        fokus = urut["Ticker"].head(MAKS_FOKUS).tolist()
        ket_fokus = f"top-{MAKS_FOKUS} trend terkuat (kandidat < 3)"
    harga_fokus = harga[fokus].dropna()

    korr, top_korr = modul_korelasi(harga_fokus)                 # 01
    bobot, alokasi, porto_ringkas = modul_optimisasi(harga_fokus)  # 06
    monte = modul_monte_carlo(harga_fokus, bobot)                # 05

    ringkasan = pd.DataFrame({
        "Item": ["Tanggal Scan", "Saham Discan", "Mode Data",
                 "Trend Naik", "Kandidat Investasi", "Subset Fokus", "Pesan"],
        "Nilai": [pd.Timestamp.today().strftime("%d %b %Y"),
                  harga.shape[1],
                  "DEMO (simulasi)" if args.demo else "LIVE (Yahoo Finance)",
                  len(naik),
                  ", ".join(kandidat) if kandidat else "(tidak ada)",
                  f"{', '.join(fokus)}  [{ket_fokus}]",
                  "Sistem yang baik mengalahkan keputusan yang emosional."],
    })

    with pd.ExcelWriter(args.output, engine="openpyxl") as xl:
        ringkasan.to_excel(xl, sheet_name="0_Ringkasan", index=False)
        screening.to_excel(xl, sheet_name="7_Screening_Funnel", index=False)
        funnel.to_excel(xl, sheet_name="7_Screening_Funnel", index=False,
                        startrow=len(screening) + 3)
        trend.to_excel(xl, sheet_name="4_Trend_MA", index=False)
        backtest.to_excel(xl, sheet_name="2-3_Backtest", index=False)
        korr.to_excel(xl, sheet_name="1_Korelasi")
        top_korr.to_excel(xl, sheet_name="1_Korelasi", index=False,
                          startrow=len(korr) + 3)
        monte.to_excel(xl, sheet_name="5_MonteCarlo", index=False)
        porto_ringkas.to_excel(xl, sheet_name="6_Portofolio", index=False)
        alokasi.to_excel(xl, sheet_name="6_Portofolio",
                         startrow=len(porto_ringkas) + 3)

    print(f"\nKandidat investasi : {kandidat if kandidat else 'tidak ada'}")
    print(f"Hasil lengkap      : {args.output}")


if __name__ == "__main__":
    main()
