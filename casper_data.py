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

Jadi strateginya bukan "bikin Yahoo mau", tapi:

  SUMBER 1  Arjum /api/history/{code}   <- lo udah bayar ini, data resmi IDX
  SUMBER 2  Yahoo Finance                <- cadangan
  SUMBER 3  CACHE DISK                   <- jaring pengaman terakhir

CACHE-nya yang paling penting dan bisa dipakai HARI INI, tanpa nunggu
skema Arjum: tiap bar harian yang berhasil diambil disimpan ke
`cache_ohlcv/`. Kalau besok Yahoo ngeblok, scan tetap jalan pakai data
kemarin — dan dikasih label BASI dengan jelas, bukan diam-diam.

Itu beda besar sama v4.3: dulu Yahoo diblokir = `DataKosong` = nol sinyal
= lo nggak bisa bedain "pasar sepi" dari "datanya nggak kebaca".
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


# ════════════════════════════════════════════════════════════════════════
#  SUMBER 1 — ARJUM /api/history/{code}
# ════════════════════════════════════════════════════════════════════════
def dari_arjum(tickers, hari=520, worker=6, diam=False):
    """OHLCV dari Arjum. Skema-nya DIDETEKSI, bukan diasumsikan.

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


def ambil_ohlcv(tickers, periode="2y", sumber="auto", min_bar=200,
                pakai_cache=True, diam=False):
    """Ambil OHLCV dari sumber terbaik yang tersedia.

    sumber: "auto" (Arjum -> Yahoo -> cache) | "arjum" | "yahoo" | "cache"

    Balikin (data, laporan). `laporan` selalu nyebutin dari mana tiap
    bagian datang dan berapa yang gagal — supaya "nol sinyal" nggak pernah
    lagi ambigu antara 'pasar sepi' dan 'datanya nggak kebaca'.
    """
    tickers = list(tickers)
    laporan = {"sumber": [], "gagal": [], "n_minta": len(tickers),
               "cache_umur_hari": np.nan}
    data = None

    if sumber in ("auto", "arjum"):
        d, gagal = dari_arjum(tickers, diam=diam)
        if d is not None:
            data = d
            laporan["sumber"].append(f"Arjum ({len(d['Close'].columns)})")
            tickers_sisa = gagal
        else:
            tickers_sisa = tickers
        if sumber == "arjum":
            tickers_sisa = []
    else:
        tickers_sisa = tickers

    if sumber in ("auto", "yahoo") and tickers_sisa:
        d, gagal = dari_yahoo(tickers_sisa, periode=periode, diam=diam)
        if d is not None:
            laporan["sumber"].append(f"Yahoo ({len(d['Close'].columns)})")
            data = d if data is None else _gabung(data, d)
        laporan["gagal"] = gagal

    if data is not None and pakai_cache:
        n = simpan_cache(data)
        if not diam:
            print(f"[i] cache OHLCV diperbarui: {n} ticker")

    # jaring pengaman: kalau semua sumber online gagal, pakai cache
    if data is None or data["Close"].shape[1] == 0:
        if not pakai_cache:
            raise SemuaSumberGagal(
                "Semua sumber data gagal dan cache dimatiin.")
        d, kosong = muat_cache(tickers, min_bar=min_bar)
        if d is None:
            raise SemuaSumberGagal(
                f"Semua sumber gagal ({laporan['sumber'] or 'nggak ada'}) "
                "DAN cache disk kosong. Ini bukan 'nggak ada sinyal' — "
                "datanya emang nggak kebaca sama sekali.")
        umur = umur_cache_hari(tickers)
        laporan["sumber"].append(f"CACHE DISK ({d['Close'].shape[1]})")
        laporan["cache_umur_hari"] = umur
        if not diam:
            print(f"[!] Semua sumber online gagal — pakai CACHE DISK "
                  f"(umur {umur:.0f} hari). Sinyalnya berdasar data lama.")
        data = d

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
    ap.add_argument("--sumber", default="auto",
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
