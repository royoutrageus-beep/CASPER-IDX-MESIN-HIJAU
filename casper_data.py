# -*- coding: utf-8 -*-
"""
CASPER — LAPISAN SUMBER DATA OHLCV
==================================
Kenapa file ini ada
-------------------------------------------------------------------------
Yahoo Finance makin sering nolak. Isu 429 di yfinance ditutup maintainer
sebagai **"not planned"** — mereka nganggap itu batasan dari sisi Yahoo,
bukan bug library. Artinya: nambal yfinance nggak bakal nyelesaiin, dan
naikin versi juga percuma.

Tiga hal yang bikin makin parah di setup lo:
  1. Streamlit Cloud & GitHub Actions jalan dari IP DATACENTER. Yahoo
     nyaring IP datacenter jauh lebih galak daripada IP rumahan — makanya
     di laptop kadang jalan, di Cloud mati terus.
  2. Auto-scan tiap 15 menit x ~700 ticker = ribuan request/hari dari satu
     IP. Itu memang kelihatan kayak scraper.
  3. Sekali diblokir, SEMUA saham hilang sekaligus, dan scan-nya balik
     kosong — bukan cuma sebagian.

Jadi strateginya bukan "bikin Yahoo mau", tapi bikin dia JARANG dipanggil:

  SUMBER 1  Yahoo Finance   <- tetap sumber utama; gratis, cakupannya penuh
  SUMBER 2  CACHE DISK      <- jaring pengaman + pengurang beban

ARJUM SENGAJA TIDAK DIPAKAI BUAT OHLCV.
Paket FREE-nya 1.000 request/hari, sementara `/history/{code}` itu satu
request PER SAHAM — sekali scan ~700 ticker langsung ngabisin kuota
sehari. Kejadian beneran: kuota ludes, dan bandarmologi ikut mati karena
kuotanya kepakai duluan sama OHLCV. Arjum jauh lebih berharga dipakai
buat broker summary (~80 request/hari) daripada dibakar buat data harga
yang Yahoo kasih gratis.

DUA HAL YANG BIKIN YAHOO JAUH LEBIH JARANG KENA BLOKIR:

  1. INKREMENTAL. Kalau cache udah punya riwayat panjang, yang diminta
     cuma beberapa bar terakhir (`period=1mo`), bukan 2 tahun penuh.
     Payload-nya jauh lebih kecil dan jarang timeout.
  2. LEWATI YANG UDAH SEGAR. Auto-scan tiap 15 menit dulu narik ulang
     SELURUH universe tiap siklus. Buat data HARIAN itu sia-sia — bar
     hari ini nggak berubah tiap 15 menit. Sekarang ticker yang cache-nya
     udah punya bar terbaru dilewati.

CACHE-nya juga jaring pengaman: kalau Yahoo ngeblok, scan tetap jalan
pakai data kemarin — dan dikasih label BASI dengan jelas, bukan
diam-diam. Itu beda besar sama v4.3: dulu Yahoo diblokir = nol sinyal =
lo nggak bisa bedain "pasar sepi" dari "datanya nggak kebaca".
"""

from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd

CACHE_OHLCV = "cache_ohlcv"
KOLOM = ("Open", "High", "Low", "Close", "Volume")


# ════════════════════════════════════════════════════════════════════════
#  CACHE DISK — satu file parquet/csv per ticker
# ════════════════════════════════════════════════════════════════════════
def _file_cache(ticker: str) -> str:
    os.makedirs(CACHE_OHLCV, exist_ok=True)
    aman = str(ticker).replace(".JK", "").upper()
    return os.path.join(CACHE_OHLCV, f"{aman}.csv")


def simpan_cache(data: dict, tickers=None):
    """Simpan OHLCV per ticker. Digabung sama yang udah ada, bukan ditimpa —
    jadi riwayat panjang kebentuk pelan-pelan walau tiap kali cuma dapat
    sedikit."""
    if not data or "Close" not in data:
        return 0
    n = 0
    for t in (tickers or data["Close"].columns):
        try:
            df = pd.DataFrame({k: data[k][t] for k in KOLOM if k in data})
            df = df.dropna(how="all")
            if df.empty:
                continue
            f = _file_cache(t)
            if os.path.exists(f):
                lama = pd.read_csv(f, index_col=0, parse_dates=True)
                df = pd.concat([lama, df])
                df = df[~df.index.duplicated(keep="last")].sort_index()
            df.to_csv(f)
            n += 1
        except Exception:                               # noqa: BLE001
            continue
    return n


def muat_cache(tickers, min_bar=200):
    """Baca cache disk -> dict OHLCV seperti hasil unduh biasa."""
    bag = {k: {} for k in KOLOM}
    kosong = []
    for t in tickers:
        f = _file_cache(t)
        if not os.path.exists(f):
            kosong.append(t)
            continue
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            if len(df) < min_bar:
                kosong.append(t)
                continue
            for k in KOLOM:
                if k in df.columns:
                    bag[k][t] = df[k]
        except Exception:                               # noqa: BLE001
            kosong.append(t)
    if not bag["Close"]:
        return None, tickers
    return {k: pd.DataFrame(v) for k, v in bag.items() if v}, kosong


def umur_cache_hari(tickers) -> float:
    """Berapa hari umur bar terbaru di cache. np.nan kalau cache kosong."""
    tgl = []
    for t in list(tickers)[:50]:                        # sampel aja, cukup
        f = _file_cache(t)
        if os.path.exists(f):
            try:
                d = pd.read_csv(f, index_col=0, parse_dates=True)
                if len(d):
                    tgl.append(pd.Timestamp(d.index[-1]).normalize())
            except Exception:                           # noqa: BLE001
                pass
    if not tgl:
        return float("nan")
    return (pd.Timestamp.today().normalize() - max(tgl)).days


def status_cache(tickers, min_bar=200, segar_hari=1):
    """Bagi ticker jadi tiga: udah segar / tinggal ditambal / harus penuh.

    Ini inti penghematan request. Data HARIAN nggak berubah tiap 15 menit,
    jadi narik ulang 2 tahun penuh tiap siklus auto-scan itu murni bakar
    kuota dan reputasi IP.
    """
    segar, tambal, penuh = [], [], []
    batas = pd.Timestamp.today().normalize() - pd.Timedelta(days=segar_hari)
    for t in tickers:
        f = _file_cache(t)
        if not os.path.exists(f):
            penuh.append(t)
            continue
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:                               # noqa: BLE001
            penuh.append(t)
            continue
        if len(df) < min_bar:
            penuh.append(t)
        elif len(df) and pd.Timestamp(df.index[-1]).normalize() >= batas:
            segar.append(t)
        else:
            tambal.append(t)
    return segar, tambal, penuh


# ════════════════════════════════════════════════════════════════════════
#  ARJUM /api/history — ADA tapi TIDAK dipakai default (boros kuota)
# ════════════════════════════════════════════════════════════════════════
def dari_arjum(tickers, hari=520, worker=6, diam=False):
    """OHLCV dari Arjum. HATI-HATI: BOROS KUOTA.

    Satu request per saham. Buat universe ~700 ticker itu 700 request —
    sementara paket FREE cuma 1.000/hari. Cuma masuk akal buat watchlist
    kecil (< 50 saham). Nggak pernah dipanggil kalau `sumber="yahoo"`
    (default).

    Skema-nya DIDETEKSI, bukan diasumsikan.

    Gue belum punya contoh response `/api/history/{code}`, jadi field-nya
    dicocokin lewat daftar alias (sama polanya kayak broker-summary yang
    udah kebukti jalan). Kalau nggak ada yang cocok, fungsinya BILANG
    field apa aja yang ada — bukan diam-diam balikin kosong.

    Cek dulu sebelum dipakai serius:
        python casper_arjum.py --cek --endpoint history --code BBCA
    """
    try:
        import casper_arjum as ar
    except Exception:                                   # noqa: BLE001
        return None, list(tickers)
    if not ar.tersedia():
        return None, list(tickers)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    cfg = ar.muat_konfig()
    # Daftar alias diambil dari casper_arjum, BUKAN disalin ke sini.
    # Kalau kepisah, `--cek` bisa bilang "kepetakan semua" sementara
    # pengambilan datanya gagal karena daftarnya beda — diagnosanya jadi
    # nggak bisa dipercaya.
    alias = ar.peta_untuk("history", cfg)

    def satu(code):
        mentah = ar._panggil("history", code=code,
                             params={"limit": hari}, cfg=cfg)
        rows = ar._isi_data(mentah, cfg, "history")
        if not rows:
            return code, None
        low = {str(k).lower(): k for k in rows[0]}
        peta = {}
        for konsep, kand in alias.items():
            for a in kand:
                if a in low:
                    peta[konsep] = low[a]
                    break
        kurang = [k for k in ("tanggal", "Close") if k not in peta]
        if kurang:
            raise KeyError(
                f"/history/{code}: field {kurang} nggak ketemu. "
                f"Yang ADA: {sorted(rows[0].keys())}. Tambahin nama "
                "aslinya ke `alias` di casper_data.dari_arjum().")
        df = pd.DataFrame(rows)
        out = pd.DataFrame(index=pd.to_datetime(df[peta["tanggal"]]))
        for k in KOLOM:
            if k in peta:
                out[k] = pd.to_numeric(df[peta[k]], errors="coerce").values
        return code, out.sort_index()

    hasil, gagal = {}, []
    codes = [str(t).replace(".JK", "").upper() for t in tickers]
    with ThreadPoolExecutor(max_workers=worker) as ex:
        tugas = {ex.submit(satu, c): c for c in codes}
        for i, fut in enumerate(as_completed(tugas), 1):
            c = tugas[fut]
            try:
                _, df = fut.result()
                if df is not None and len(df):
                    hasil[c] = df
                else:
                    gagal.append(c)
            except Exception as e:                      # noqa: BLE001
                gagal.append(c)
                if i == 1 and not diam:                 # laporin sekali aja
                    print(f"    [!] Arjum history: {e}")
            if not diam and i % 50 == 0:
                print(f"    history {i}/{len(codes)}")
    if not hasil:
        return None, list(tickers)
    bag = {k: pd.DataFrame({c: d[k] for c, d in hasil.items() if k in d})
           for k in KOLOM}
    bag = {k: v for k, v in bag.items() if not v.empty}
    return bag, gagal


# ════════════════════════════════════════════════════════════════════════
#  SUMBER 2 — YAHOO, dibikin sesabar mungkin
# ════════════════════════════════════════════════════════════════════════
def _sesi_yahoo():
    """Sesi dengan impersonasi browser kalau curl_cffi ada.

    Bukan obat mujarab — Yahoo tetap bisa nolak — tapi request yang bawa
    sidik jari TLS browser beneran lebih jarang kena saring daripada
    request python-requests polos.
    """
    try:
        from curl_cffi import requests as cr
        return cr.Session(impersonate="chrome")
    except Exception:                                   # noqa: BLE001
        return None


def dari_yahoo(tickers, periode="2y", batch=25, jeda=2.0, diam=False):
    """Batch kecil + jeda + backoff. Batch 50 tanpa jeda itu yang bikin
    kelihatan kayak scraper dan mempercepat diblokir."""
    import yfinance as yf
    sesi = _sesi_yahoo()
    bag = {k: [] for k in KOLOM}
    gagal = []
    tickers = list(tickers)
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        df = None
        for percobaan in range(3):
            try:
                kw = {"period": periode, "auto_adjust": True,
                      "progress": False, "threads": False}
                if sesi is not None:
                    kw["session"] = sesi
                df = yf.download(chunk, **kw)
                if df is not None and not df.empty:
                    break
            except Exception as e:                      # noqa: BLE001
                if not diam and percobaan == 0:
                    print(f"    [!] Yahoo batch gagal: "
                          f"{type(e).__name__}: {str(e)[:80]}")
            time.sleep(jeda * (2 ** percobaan))         # backoff
        if df is None or df.empty:
            gagal += chunk
            continue
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_product([df.columns, [chunk[0]]])
        for k in bag:
            if k in df.columns.get_level_values(0):
                bag[k].append(df[k])
        if not diam:
            print(f"    yahoo {min(i + batch, len(tickers))}/{len(tickers)}"
                  + (f"  ({len(gagal)} gagal)" if gagal else ""))
        if i + batch < len(tickers):
            time.sleep(jeda)
    if not bag["Close"]:
        return None, tickers
    out = {k: pd.concat(v, axis=1) for k, v in bag.items() if v}
    out = {k: v.loc[:, ~v.columns.duplicated()] for k, v in out.items()}
    return out, gagal


# ════════════════════════════════════════════════════════════════════════
#  ORKESTRATOR
# ════════════════════════════════════════════════════════════════════════
class SemuaSumberGagal(RuntimeError):
    pass


def ambil_ohlcv(tickers, periode="2y", sumber="yahoo", min_bar=200,
                pakai_cache=True, diam=False, segar_hari=1):
    """Ambil OHLCV se-hemat mungkin.

    sumber: "yahoo" (default) | "auto" | "arjum" | "cache"

    Alurnya buat "yahoo"/"auto":
      1. Ticker yang cache-nya UDAH punya bar terbaru  -> nggak ditembak
         sama sekali
      2. Ticker yang cache-nya ketinggalan beberapa hari -> minta 1 bulan
         terakhir aja (payload kecil)
      3. Ticker baru / riwayat kurang                  -> minta penuh
      4. Kalau semuanya gagal                          -> cache disk,
         dilabeli BASI

    Balikin (data, laporan). `laporan` selalu nyebutin asal tiap bagian —
    supaya "nol sinyal" nggak pernah lagi ambigu antara 'pasar sepi' dan
    'datanya nggak kebaca'.
    """
    tickers = list(tickers)
    laporan = {"sumber": [], "gagal": [], "n_minta": len(tickers),
               "cache_umur_hari": np.nan, "hemat": 0,
               "gagal_online": False}
    bagian = []

    if sumber == "cache":
        d0, _ = muat_cache(tickers, min_bar=min_bar)
        if d0 is None:
            raise SemuaSumberGagal("Cache disk kosong.")
        laporan["sumber"].append(f"CACHE DISK ({d0['Close'].shape[1]})")
        laporan["cache_umur_hari"] = umur_cache_hari(tickers)
        return _rapikan(d0, min_bar, laporan)

    if sumber == "arjum":
        d0, gagal = dari_arjum(tickers, diam=diam)
        if d0 is None:
            raise SemuaSumberGagal("Arjum nggak balikin data apa pun.")
        laporan["sumber"].append(f"Arjum ({d0['Close'].shape[1]})")
        laporan["gagal"] = gagal
        if pakai_cache:
            simpan_cache(d0)
        return _rapikan(d0, min_bar, laporan)

    # ---- jalur normal: Yahoo, se-irit mungkin --------------------------
    segar, tambal, penuh = ([], [], tickers)
    if pakai_cache:
        segar, tambal, penuh = status_cache(tickers, min_bar, segar_hari)
        laporan["hemat"] = len(segar)
        if segar and not diam:
            print(f"[i] {len(segar)} ticker cache-nya udah terbaru — "
                  "nggak ditembak ulang.")

    if sumber == "auto" and penuh:
        # Arjum cuma dipakai kalau universe-nya KECIL — kalau nggak,
        # kuotanya habis dan bandarmologi ikut mati.
        try:
            import casper_arjum as ar
            muat = ar.tersedia() and len(penuh) <= 50 and ar.sisa_kuota() > len(penuh)
        except Exception:                               # noqa: BLE001
            muat = False
        if muat:
            d0, sisa = dari_arjum(penuh, diam=diam)
            if d0 is not None:
                bagian.append(d0)
                laporan["sumber"].append(f"Arjum ({d0['Close'].shape[1]})")
                penuh = sisa

    for grup, per, label in ((tambal, "1mo", "tambal"), (penuh, periode, "penuh")):
        if not grup:
            continue
        if not diam:
            print(f"[i] Yahoo {label}: {len(grup)} ticker (period={per})")
        d0, gagal = dari_yahoo(grup, periode=per, diam=diam)
        laporan["gagal"] += gagal
        if d0 is not None:
            bagian.append(d0)
            laporan["sumber"].append(f"Yahoo-{label} ({d0['Close'].shape[1]})")

    data = None
    for b in bagian:
        data = b if data is None else _gabung(data, b)
    if data is not None and pakai_cache:
        n = simpan_cache(data)
        if not diam:
            print(f"[i] cache OHLCV diperbarui: {n} ticker")

    # gabung sama cache (buat yang segar + jaring pengaman)
    if pakai_cache:
        d_cache, _ = muat_cache(tickers, min_bar=min_bar)
        if d_cache is not None:
            if data is None:
                # BEDAKAN dua hal yang kelihatannya sama:
                #   (a) semua ticker cache-nya udah SEGAR -> sengaja nggak
                #       narik apa-apa. Ini sehat.
                #   (b) Yahoo GAGAL -> kepaksa pakai data lama. Ini bahaya.
                # Kalau dua-duanya dilabeli "CACHE DISK", UI munculin
                # peringatan merah tiap auto-scan padahal nggak ada yang
                # rusak — dan peringatan yang sering salah bakal diabaikan
                # pas dia beneran penting.
                if not tambal and not penuh:
                    laporan["sumber"].append(
                        f"cache segar ({d_cache['Close'].shape[1]})")
                    if not diam:
                        print("[i] Semua ticker udah terbaru — nol request "
                              "ke Yahoo.")
                else:
                    umur = umur_cache_hari(tickers)
                    laporan["cache_umur_hari"] = umur
                    laporan["gagal_online"] = True
                    laporan["sumber"].append(
                        f"CACHE DISK ({d_cache['Close'].shape[1]})")
                    if not diam:
                        print(f"[!] Yahoo gagal total — pakai CACHE DISK "
                              f"(umur {umur:.0f} hari). Sinyal berdasar "
                              "data lama.")
                data = d_cache
            else:
                data = _gabung(d_cache, data)   # data baru menang
                if segar:
                    laporan["sumber"].append(f"cache segar ({len(segar)})")

    if data is None:
        raise SemuaSumberGagal(
            "Yahoo gagal DAN cache disk kosong. Ini bukan 'nggak ada "
            "sinyal' — datanya emang nggak kebaca sama sekali.")
    return _rapikan(data, min_bar, laporan)


def _rapikan(data, min_bar, laporan):
    ok = data["Close"].dropna(axis=1, thresh=min_bar).columns
    ok = [c for c in ok if all(c in data[k].columns for k in data)]
    if not ok:
        raise SemuaSumberGagal(
            f"Data kebaca tapi nggak ada yang punya >= {min_bar} bar.")
    laporan["n_dapat"] = len(ok)
    return {k: v[ok] for k, v in data.items()}, laporan


def _gabung(a, b):
    out = {}
    for k in set(a) | set(b):
        bagian = [x[k] for x in (a, b) if k in x]
        df = pd.concat(bagian, axis=1)
        out[k] = df.loc[:, ~df.columns.duplicated()]
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Cek sumber data OHLCV")
    ap.add_argument("--tickers", nargs="+",
                    default=["BBCA", "BBRI", "TLKM", "ANTM"])
    ap.add_argument("--sumber", default="yahoo",
                    choices=["auto", "arjum", "yahoo", "cache"])
    a = ap.parse_args()
    try:
        d, lap = ambil_ohlcv([t + ".JK" for t in a.tickers], sumber=a.sumber)
        print("\n=== HASIL ===")
        print("sumber :", " + ".join(lap["sumber"]) or "-")
        print("dapat  :", lap["n_dapat"], "dari", lap["n_minta"])
        print("gagal  :", lap["gagal"][:10])
        print("bar terakhir:", d["Close"].index[-1].date())
        print(d["Close"].tail(3).to_string())
    except SemuaSumberGagal as e:
        print("[X]", e)
