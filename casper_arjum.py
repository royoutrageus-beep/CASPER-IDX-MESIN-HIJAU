# -*- coding: utf-8 -*-
"""
CASPER — ADAPTER BANDARMOLOGI (Arjum / IDX Edge PRO)
=====================================================
Disesuaikan ke SKEMA ASLI dari dokumentasi:

    GET https://stock.arjum.com/api/broker-summary/{code}
    header: X-API-Key: sk_live_...
    query : start_date, end_date, net, broker_limit, level_limit,
            all_data, flow (F=foreign / D=domestik / all)

    response:
      { "flow": "all", "stock_code": "BBCA", "latest_date": "2026-07-24",
        "broker_start": "...", "broker_end": "...",
        "brokers": [ {broker_code, broker_name, bval, sval, nval,
                      nvol, bfrq, sfrq}, ... ] }

DUA HAL PENTING YANG NENTUIN DESAIN FILE INI
-------------------------------------------------------------------------
1. `code` itu PATH PARAMETER -> satu request = SATU SAHAM.
   Nggak ada endpoint "semua saham sekaligus" di broker-summary. Nembak
   700 ticker tiap scan = 700 request, kena rate limit dan lama banget.
   Solusinya: SCAN DUA TAHAP (lihat `ambil_banyak` + `bandar_top` di
   engine) — seluruh universe di-rank dulu pakai OHLCV yang murah, baru
   kandidat teratas yang ditembak ke Arjum.

2. JUMLAH nval SELURUH BROKER ITU NOL.
   Tiap lembar yang dibeli seseorang, dijual orang lain. Jadi
   "net bandar = sum(nval)" itu ANGKA KOSONG — nol kalau datanya lengkap,
   dan angka acak kalau kepotong `broker_limit`. (Versi pertama adapter
   ini sempat ngitung gitu; ketahuan pas baca skema aslinya.)

   Yang PUNYA arti arah cuma:
     - `flow=F` -> net asing, ini beneran bisa positif/negatif
     - KONSENTRASI: beli numpuk di sedikit broker atau nyebar rata
     - DOMINASI broker #1
     - TIKET RATA-RATA (bval/bfrq): nilai per transaksi. Institusi
       nyicil gede, ritel nyicil receh. Ini sidik jari yang susah dipalsu.

FALLBACK: kalau key belum ada / API mati, `proxy_dari_ohlcv()` ngitung
perkiraan dari OHLCV doang (CMF, A/D, OBV). Kolom `bandar_sumber` SELALU
keisi biar nggak pernah ketuker sama data broker asli.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

KONFIG = "arjum_config.json"
CACHE_DIR = "cache_arjum"
TIMEOUT = 30
RETRY = 3
WORKER = 6            # request paralel; naikin kalau paket lo longgar

DEFAULT_KONFIG = {
    "base_url": "https://stock.arjum.com/api",
    "auth": {"tipe": "header", "nama": "X-API-Key", "prefix": ""},
    "endpoint": {
        # {code} diganti kode saham. Path param, bukan query.
        "broker_summary":     {"path": "/broker-summary/{code}",
                               "isi": "brokers"},
        "broker_accumulation": {"path": "/broker-accumulation/{code}",
                                "isi": None},
        "history":            {"path": "/history/{code}", "isi": None},
        "seasonal":           {"path": "/seasonal/{code}", "isi": None},
        "analysis":           {"path": "/analysis/{code}", "isi": None},
        "screener":           {"path": "/screener/latest", "isi": None},
        "health":             {"path": "/health", "isi": None},
    },
    "peta_field": {
        "broker":      ["broker_code", "broker", "bc", "kode_broker"],
        "broker_nama": ["broker_name", "nama_broker"],
        "buy_value":   ["bval", "buy_value", "nilai_beli"],
        "sell_value":  ["sval", "sell_value", "nilai_jual"],
        "net_value":   ["nval", "net_value", "netval", "net"],
        "net_volume":  ["nvol", "net_volume"],
        "buy_freq":    ["bfrq", "buy_freq", "freq_beli"],
        "sell_freq":   ["sfrq", "sell_freq", "freq_jual"],
    },
    # field top-level di response yang perlu ditarik ke tiap baris
    "field_induk": {"ticker": ["stock_code", "code", "symbol"],
                    "tanggal": ["latest_date", "broker_end", "date"]},
    "jalur_data": ["brokers", "data", "results", "items", "rows"],
    "broker_limit": 200,
    # /history/{code} isinya OHLCV, bukan broker — jadi peta field-nya
    # beda sendiri. Ditaruh di sini supaya casper_data.dari_arjum() dan
    # diagnosa_skema() pakai daftar yang SAMA; kalau kepisah, `--cek`
    # bisa bilang "kepetakan semua" sementara pengambilan datanya gagal
    # (atau sebaliknya) — dan itu bikin diagnosanya nggak bisa dipercaya.
    "peta_history": {
        "tanggal": ["date", "tanggal", "trade_date", "t", "timestamp"],
        "Open":    ["open", "o", "open_price", "pembukaan"],
        "High":    ["high", "h", "high_price", "tertinggi"],
        "Low":     ["low", "l", "low_price", "terendah"],
        "Close":   ["close", "c", "close_price", "penutupan"],
        "Volume":  ["volume", "v", "vol"],
    },
}


def muat_konfig(path=KONFIG) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_KONFIG))
    if os.path.exists(path):
        try:
            user = json.load(open(path, encoding="utf-8"))
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:                          # noqa: BLE001
            print(f"[!] {path} gagal dibaca ({e}) — pakai konfig default.")
    return cfg


def _secrets_tersedia() -> bool:
    """True cuma kalau file secrets.toml BENERAN ada.

    Kenapa perlu dicek duluan: di Streamlit versi lama, sekadar NYENTUH
    `st.secrets` waktu file-nya nggak ada bakal NGERENDER KOTAK MERAH di
    UI — sebelum exception-nya dilempar. Jadi bungkus try/except doang
    nggak nolong, kotaknya udah terlanjur nongol. Di laptop yang cuma
    pakai config_tele.json (tanpa secrets.toml), UI-nya jadi penuh
    "No secrets found" padahal semuanya normal.

    Path-nya persis yang disebut Streamlit di pesan error itu.
    """
    return any(os.path.exists(p) for p in (
        os.path.join(".streamlit", "secrets.toml"),
        os.path.expanduser("~/.streamlit/secrets.toml"),
        "/mount/src/.streamlit/secrets.toml"))


def ambil_key() -> str | None:
    """Key dari arjum_config.json > env ARJUM_KEY > st.secrets.
    JANGAN di-hardcode: file ini masuk repo."""
    if os.path.exists(KONFIG):
        try:
            k = json.load(open(KONFIG, encoding="utf-8")).get("api_key")
            if k and not str(k).startswith("ISI_"):
                return str(k)
        except Exception:                               # noqa: BLE001
            pass
    k = os.environ.get("ARJUM_KEY") or os.environ.get("ARJUM_API_KEY")
    if k:
        return k
    if not _secrets_tersedia():
        return None
    try:
        import streamlit as st
        for nama in ("arjum_key", "ARJUM_KEY"):
            if nama in st.secrets:
                return str(st.secrets[nama])
    except Exception:                                   # noqa: BLE001
        pass
    return None


def tersedia() -> bool:
    return ambil_key() is not None


# ════════════════════════════════════════════════════════════════════════
#  HTTP + CACHE
# ════════════════════════════════════════════════════════════════════════
def _path_cache(nama, kunci):
    os.makedirs(CACHE_DIR, exist_ok=True)
    aman = "".join(ch if ch.isalnum() or ch in "-_." else "_"
                   for ch in str(kunci))[:120]
    return os.path.join(CACHE_DIR, f"{nama}_{aman}.json")


def _panggil(endpoint, code=None, params=None, cfg=None, pakai_cache=True):
    cfg = cfg or muat_konfig()
    key = ambil_key()
    if key is None:
        # Kalau dijalanin dari terminal beneran, LANGSUNG TANYA — jangan
        # cuma ngasih error terus nyuruh jalanin perintah lain. Urutan
        # perintah yang harus diinget itu sendiri sumber kesalahan:
        # gampang banget kelewat, dan errornya keliatan kayak app rusak
        # padahal cuma belum disetel.
        import sys
        if sys.stdin.isatty() and sys.stdout.isatty():
            print("[!] API key Arjum belum disetel.")
            if set_key():
                key = ambil_key()
        if key is None:
            raise RuntimeError(
                "API key Arjum nggak ketemu.\n\n"
                "  Cara tercepat (key-nya diketik tersembunyi, nggak nyangkut\n"
                "  di history PowerShell):\n"
                "      python casper_arjum.py --set-key\n\n"
                "  Alternatif: env var buat sekali pakai —\n"
                "      $env:ARJUM_KEY = \"sk_live_...\"        (PowerShell)\n"
                "      set ARJUM_KEY=sk_live_...                (CMD)\n\n"
                "  Di Streamlit Cloud / GitHub Actions: pakai secret "
                "ARJUM_KEY.")
    ep = cfg["endpoint"].get(endpoint)
    if ep is None:
        raise KeyError(f"Endpoint '{endpoint}' nggak ada di {KONFIG}")

    params = dict(params or {})
    path = ep["path"].replace("{code}", str(code or "").replace(".JK", ""))
    ck = f"{code or 'x'}_{urllib.parse.urlencode(sorted(params.items()))}"
    fc = _path_cache(endpoint, ck)
    # Data EOD nggak berubah setelah bursa tutup -> aman di-cache.
    if pakai_cache and os.path.exists(fc):
        try:
            return json.load(open(fc, encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            pass

    headers = {"Accept": "application/json", "User-Agent": "casper-idx/4.2"}
    auth = cfg.get("auth", {})
    if auth.get("tipe") == "query":
        params[auth.get("nama", "api_key")] = key
    elif auth.get("tipe") == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    else:
        headers[auth.get("nama", "X-API-Key")] = \
            f"{auth.get('prefix', '')}{key}"

    url = cfg["base_url"].rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    galat = None
    for percobaan in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if pakai_cache:
                try:
                    json.dump(data, open(fc, "w", encoding="utf-8"))
                except Exception:                       # noqa: BLE001
                    pass
            return data
        except urllib.error.HTTPError as e:
            galat = f"HTTP {e.code} {e.reason}"
            if e.code in (401, 403):
                raise RuntimeError(
                    f"Arjum nolak API key ({galat}). Cek key & paket "
                    "langganan.") from e
            if e.code == 404:
                raise RuntimeError(
                    f"404 — {url}\nCek `path` di {KONFIG} atau kode "
                    "sahamnya.") from e
            if e.code == 429:
                # rate limit: mundur eksponensial, jangan ngotot
                time.sleep(2 ** percobaan * 2)
                continue
        except Exception as e:                          # noqa: BLE001
            galat = f"{type(e).__name__}: {e}"
        time.sleep(1.2 * (percobaan + 1))
    raise RuntimeError(f"Arjum gagal ({galat}) — {url}")


def cek_health():
    try:
        h = _panggil("health", pakai_cache=False)
        print(f"[i] Arjum health: {json.dumps(h)[:200]}")
        return True
    except Exception as e:                              # noqa: BLE001
        print(f"[!] Arjum health gagal: {e}")
        return False


def _cari(dct, alias):
    low = {str(k).lower(): k for k in dct}
    for a in alias:
        if a.lower() in low:
            return dct[low[a.lower()]]
    return None


def _isi_data(obj, cfg, endpoint=None):
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    ep = cfg["endpoint"].get(endpoint or "", {})
    if ep.get("isi") and isinstance(obj.get(ep["isi"]), list):
        return obj[ep["isi"]]
    for jalur in cfg.get("jalur_data", []):
        if isinstance(obj.get(jalur), list):
            return obj[jalur]
    for v in obj.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


# ════════════════════════════════════════════════════════════════════════
#  BROKER SUMMARY SATU SAHAM
# ════════════════════════════════════════════════════════════════════════
def broker_summary(code, start_date=None, end_date=None, flow="all",
                   broker_limit=None, cfg=None) -> pd.DataFrame:
    """Broker summary satu saham -> DataFrame berkolom baku.

    `stock_code` dan `latest_date` ada di TOP LEVEL response, bukan di
    tiap baris broker — jadi ditarik turun ke tiap baris di sini.
    """
    cfg = cfg or muat_konfig()
    # all_data=true: KONSENTRASI cuma ada artinya kalau dihitung dari
    # SELURUH broker. Dengan broker_limit, "top5 / total" itu jadi
    # "top5 dari 30 teratas" — dan angkanya otomatis mepet 100% buat
    # semua saham (di layar sempat kelihatan ICBP top5 = 97%, mustahil
    # buat saham selikuid itu). Jadi ambil lengkap, batasi di sisi kita.
    par = {"flow": flow, "all_data": "true",
           "broker_limit": broker_limit or cfg.get("broker_limit", 200)}
    if start_date:
        par["start_date"] = start_date
    if end_date:
        par["end_date"] = end_date
    mentah = _panggil("broker_summary", code=code, params=par, cfg=cfg)
    rows = _isi_data(mentah, cfg, "broker_summary")
    if not rows:
        return pd.DataFrame()

    induk = cfg.get("field_induk", {})
    tkr = (_cari(mentah, induk.get("ticker", [])) if isinstance(mentah, dict)
           else None) or str(code).replace(".JK", "")
    tgl = (_cari(mentah, induk.get("tanggal", []))
           if isinstance(mentah, dict) else None)

    out = []
    for r in rows:
        baris = {"ticker": str(tkr).replace(".JK", ""), "tanggal": tgl,
                 "flow": flow}
        for konsep, alias in cfg["peta_field"].items():
            v = _cari(r, alias)
            if v is not None:
                baris[konsep] = v
        out.append(baris)
    df = pd.DataFrame(out)
    for k in ("buy_value", "sell_value", "net_value", "net_volume",
              "buy_freq", "sell_freq"):
        if k in df.columns:
            df[k] = pd.to_numeric(df[k], errors="coerce")
    if "net_value" not in df.columns and {"buy_value", "sell_value"} <= set(df):
        df["net_value"] = df["buy_value"] - df["sell_value"]
    return df


def ambil_banyak(codes, start_date=None, end_date=None, flow="all",
                 worker=WORKER, diam=False) -> pd.DataFrame:
    """Broker summary BANYAK saham, paralel.

    Satu request per saham (code itu path param), jadi jumlah request =
    jumlah ticker. Makanya di engine cuma kandidat TERATAS yang ditembak
    ke sini, bukan seluruh universe.
    """
    cfg = muat_konfig()
    codes = [str(c).replace(".JK", "").upper() for c in codes]
    hasil, gagal = [], []
    with ThreadPoolExecutor(max_workers=worker) as ex:
        tugas = {ex.submit(broker_summary, c, start_date, end_date, flow,
                           None, cfg): c for c in codes}
        for i, fut in enumerate(as_completed(tugas), 1):
            c = tugas[fut]
            try:
                d = fut.result()
                if not d.empty:
                    hasil.append(d)
            except Exception as e:                      # noqa: BLE001
                gagal.append((c, str(e)[:70]))
            if not diam and i % 25 == 0:
                print(f"    bandar {i}/{len(codes)}")
    if gagal and not diam:
        print(f"[!] {len(gagal)} ticker gagal, contoh: {gagal[:3]}")
    return pd.concat(hasil, ignore_index=True) if hasil else pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════
#  FITUR BANDARMOLOGI
# ════════════════════════════════════════════════════════════════════════
def fitur_bandar(bs: pd.DataFrame, bs_asing: pd.DataFrame | None = None):
    """Broker summary mentah -> satu baris fitur per ticker.

    SENGAJA TIDAK ADA "total net value".
    Jumlah nval seluruh broker itu NOL — tiap lembar yang dibeli, dijual
    orang lain. Angka itu cuma keliatan berarti kalau datanya kepotong
    `broker_limit`, dan besarnya cuma nunjukin seberapa banyak yang
    kepotong. Yang di bawah ini semuanya punya arti sendiri:

      akum_jt        : total nval broker yang NET BELI (juta Rp) = seberapa
                       banyak barang yang pindah tangan ke pihak pengumpul
      konsentrasi_top5: share 5 broker pembeli terbesar dari total beli.
                       Tinggi = beli menumpuk (akumulasi terarah);
                       rendah = nyebar rata (ciri ritel)
      dominasi_1     : share broker pembeli #1 dari total akumulasi
      tiket_beli_jt  : rata-rata nilai per transaksi beli (bval/bfrq).
                       Institusi nyicil gede, ritel nyicil receh —
                       sidik jari yang susah dipalsu
      foreign_net_jt : net asing (BUTUH panggilan terpisah flow=F; di
                       flow=all nggak ada cara misahin asing/domestik)
      broker_top     : nama broker pembeli terbesar, buat dilihat manusia
    """
    if bs is None or bs.empty:
        return pd.DataFrame()
    baris = []
    for tkr, g in bs.groupby("ticker"):
        net = pd.to_numeric(g.get("net_value"), errors="coerce").fillna(0)
        bval = pd.to_numeric(g.get("buy_value"), errors="coerce").fillna(0)
        bfrq = pd.to_numeric(g.get("buy_freq"), errors="coerce").fillna(0)
        akum = float(net[net > 0].sum())
        total_beli = float(bval.sum())
        top5 = float(bval.nlargest(5).sum())
        pembeli = g.loc[net > 0]
        d = {
            "ticker": tkr,
            "akum_jt": akum / 1e6,
            "konsentrasi_top5": (top5 / total_beli if total_beli > 0
                                 else np.nan),
            "dominasi_1": (float(net.max()) / akum if akum > 0 else np.nan),
            "tiket_beli_jt": (total_beli / float(bfrq.sum()) / 1e6
                              if bfrq.sum() > 0 else np.nan),
            "n_broker_beli": int(len(pembeli)),
            "broker_top": (str(pembeli.sort_values("net_value",
                                                   ascending=False)
                               .iloc[0].get("broker_nama",
                                            pembeli.iloc[0].get("broker")))
                           if len(pembeli) else "-"),
            "tanggal_bandar": (str(g["tanggal"].iloc[0])
                               if "tanggal" in g.columns else ""),
        }
        baris.append(d)
    out = pd.DataFrame(baris).set_index("ticker")

    # Net asing: cuma bisa dari panggilan flow=F. Di flow=all, broker asing
    # dan domestik campur dan sum-nya tetap nol.
    out["foreign_net_jt"] = np.nan
    if bs_asing is not None and not bs_asing.empty:
        fa = (pd.to_numeric(bs_asing["net_value"], errors="coerce")
              .groupby(bs_asing["ticker"]).sum() / 1e6)
        out["foreign_net_jt"] = fa.reindex(out.index)
    out["bandar_sumber"] = "Arjum ✅"
    return out


def skor_bandar(df: pd.DataFrame) -> pd.Series:
    """Satu angka faktor `f_bandar` (0..1) dari kolom yang ADA."""
    if df is None or df.empty:
        return pd.Series(dtype=float)

    def r(kol, balik=False):
        if kol not in df.columns:
            return None
        s = pd.to_numeric(df[kol], errors="coerce")
        if s.notna().sum() < 2:
            return None
        p = s.rank(pct=True)
        return (1 - p) if balik else p

    if "akum_jt" in df.columns and df["akum_jt"].notna().any():
        bagian = [x for x in (
            r("akum_jt"),              # makin banyak barang terserap
            r("konsentrasi_top5"),     # terarah, bukan nyebar
            r("tiket_beli_jt"),        # tiket gede = institusi
            r("foreign_net_jt"),       # asing net beli
        ) if x is not None]
    else:
        bagian = [x for x in (r("cmf"), r("ad_slope"), r("obv_slope"))
                  if x is not None]
    if not bagian:
        return pd.Series(0.5, index=df.index)
    return pd.concat(bagian, axis=1).mean(axis=1).fillna(0.5)


# ════════════════════════════════════════════════════════════════════════
#  FALLBACK: PROKSI AKUMULASI DARI OHLCV
# ════════════════════════════════════════════════════════════════════════
def proxy_dari_ohlcv(high, low, close, volume, n=20) -> pd.DataFrame:
    """Perkiraan tekanan akumulasi TANPA broker summary.

    Chaikin Money Flow: MFM = ((C−L) − (H−C)) / (H−L), MFV = MFM × Volume,
    CMF = ΣMFV(n) / ΣVol(n). Kalau close konsisten nutup di bagian ATAS
    range harian sambil volume gede, itu jejak ada yang nyerap.

    INI BUKAN BANDARMOLOGI. Dia nggak tau broker mana yang beli — cuma
    baca jejak di harga & volume. Ditandai `proksi OHLCV ⚠️`.
    """
    rng = (high - low).replace(0, np.nan)
    mfv = (((close - low) - (high - close)) / rng) * volume
    cmf = mfv.rolling(n).sum() / volume.rolling(n).sum().replace(0, np.nan)
    ad = mfv.fillna(0).cumsum()
    obv = (np.sign(close.diff().fillna(0)) * volume).cumsum()

    def kemiringan(s, k=n):
        y = s.iloc[-k:]
        xc = np.arange(k) - (k - 1) / 2
        b = y.sub(y.mean()).mul(xc, axis=0).sum() / (xc ** 2).sum()
        return b / y.abs().mean().replace(0, np.nan)

    out = pd.DataFrame({"cmf": cmf.iloc[-1], "ad_slope": kemiringan(ad),
                        "obv_slope": kemiringan(obv)})
    out.index = [str(i).replace(".JK", "") for i in out.index]
    for k in ("akum_jt", "konsentrasi_top5", "dominasi_1", "tiket_beli_jt",
              "foreign_net_jt"):
        out[k] = np.nan
    out["broker_top"] = "-"
    out["bandar_sumber"] = "proksi OHLCV ⚠️"
    return out


# ════════════════════════════════════════════════════════════════════════
#  DIAGNOSA
# ════════════════════════════════════════════════════════════════════════
def peta_untuk(endpoint: str, cfg=None) -> dict:
    """Peta field yang cocok buat endpoint ini.

    `/history` isinya OHLCV, `/broker-summary` isinya baris broker — dua
    skema yang beda. Sebelum ini, `--cek --endpoint history` ngecek pakai
    peta broker dan ngelaporin `kepetakan: []` padahal response-nya
    sempurna. Diagnosa yang bohong itu lebih buruk dari nggak ada
    diagnosa: lo jadi ngira endpoint-nya rusak.
    """
    cfg = cfg or muat_konfig()
    if endpoint == "history":
        return cfg.get("peta_history", DEFAULT_KONFIG["peta_history"])
    return cfg["peta_field"]


def diagnosa_skema(endpoint="broker_summary", code="BBCA", **params):
    """Jalanin ini DULUAN waktu nyambungin/ngecek API."""
    cfg = muat_konfig()
    mentah = _panggil(endpoint, code=code, params=params, cfg=cfg,
                      pakai_cache=False)
    print(f"— endpoint : {endpoint}  (code={code})")
    if isinstance(mentah, dict):
        atas = {k: v for k, v in mentah.items() if not isinstance(v, list)}
        print(f"— field top-level: {atas}")
    rows = _isi_data(mentah, cfg, endpoint)
    print(f"— jumlah baris: {len(rows)}")
    if not rows:
        print("— response mentah:", json.dumps(mentah)[:600])
        return
    print(f"— field per baris: {sorted(rows[0].keys())}")
    peta = peta_untuk(endpoint, cfg)
    ketemu = {k: _cari(rows[0], al) for k, al in peta.items()}
    ada = [k for k, v in ketemu.items() if v is not None]
    kurang = [k for k, v in ketemu.items() if v is None]
    print(f"— kepetakan  : {ada}")
    print(f"— BELUM kepetakan: {kurang}")
    if not kurang:
        print("— ✅ SEMUA field kepetakan. Endpoint ini siap dipakai.")
    else:
        print(f"— ⚠️  Tambahin nama aslinya ke `{ 'peta_history' if peta is cfg.get('peta_history') else 'peta_field' }`"
              f" di {KONFIG}.")
    print(f"— contoh baris: {json.dumps(rows[0], ensure_ascii=False)[:300]}")


def set_key(key: str | None = None, path=KONFIG):
    """Simpan API key ke arjum_config.json tanpa perlu ngedit JSON manual.

    Kalau `key` kosong, dimintanya lewat getpass — key-nya NGGAK keketik
    di layar dan NGGAK nyangkut di riwayat perintah. PowerShell nyimpen
    history ke ConsoleHost_history.txt di disk, jadi ngetik
    `--set-key sk_live_...` langsung di command line itu bikin key lo
    kesimpen dalam bentuk teks polos.

    Konfig yang udah ada digabung, bukan ditimpa.
    """
    import getpass
    if not key:
        key = getpass.getpass("Tempel API key Arjum (nggak kelihatan): ")
    key = key.strip()
    if not key:
        print("[!] Kosong — dibatalin.")
        return False
    if not key.startswith("sk_"):
        print(f"[!] Peringatan: key biasanya diawali 'sk_live_' / 'sk_test_', "
              f"punya lo diawali '{key[:8]}...'. Tetap disimpan.")

    cfg = {}
    if os.path.exists(path):
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            print(f"[!] {path} rusak — ditulis ulang dari awal.")
    cfg["api_key"] = key
    cfg.setdefault("base_url", DEFAULT_KONFIG["base_url"])
    json.dump(cfg, open(path, "w", encoding="utf-8"), indent=2)
    print(f"[i] Key disimpan ke {path} (…{key[-4:]})")

    # Cek .gitignore — file ini isinya rahasia dan gampang kebawa commit
    gi = ".gitignore"
    aman = os.path.exists(gi) and any(
        ln.strip().split("#")[0].strip() == path
        for ln in open(gi, encoding="utf-8"))
    if aman:
        print(f"[i] {path} udah ada di .gitignore — aman. ✅")
    else:
        print(f"[!] BAHAYA: {path} BELUM ada di .gitignore. "
              f"Tambahin barisnya sekarang sebelum commit:")
        print(f"        echo {path} >> .gitignore")

    print("\n[i] Nyoba sambungan...")
    ok = cek_health()
    if ok:
        print("[i] Lanjut cek skema:")
        print("      python casper_arjum.py --cek --endpoint history --code BBCA")
    return ok


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Cek sambungan & skema Arjum")
    ap.add_argument("--set-key", nargs="?", const="", default=None,
                    metavar="KEY",
                    help="simpan API key ke arjum_config.json. Tanpa nilai "
                         "= diminta tersembunyi (disaranin, biar key nggak "
                         "nyangkut di history PowerShell)")
    ap.add_argument("--cek", action="store_true")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--endpoint", default="broker_summary")
    ap.add_argument("--code", default="BBCA")
    ap.add_argument("--flow", default="all")
    ap.add_argument("--tulis-konfig", action="store_true")
    a = ap.parse_args()

    if a.set_key is not None:
        set_key(a.set_key or None)
    elif a.tulis_konfig:
        contoh = json.loads(json.dumps(DEFAULT_KONFIG))
        contoh["api_key"] = "ISI_KEY_LO_DI_SINI"
        json.dump(contoh, open(KONFIG, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        print(f"[i] {KONFIG} ditulis. Isi api_key-nya "
              "(dan JANGAN commit file ini).")
    elif a.health:
        cek_health()
    elif a.cek:
        diagnosa_skema(a.endpoint, code=a.code, flow=a.flow)
    else:
        ada = tersedia()
        print("API key ketemu:", "YA ✅" if ada else "BELUM ❌")
        print("base_url     :", muat_konfig()["base_url"])
        print("config file  :",
              f"{KONFIG} (ada)" if os.path.exists(KONFIG)
              else f"{KONFIG} (belum ada)")
        if not ada:
            print("\nIsi key-nya dulu:")
            print("    python casper_arjum.py --set-key")
        else:
            print("\nLangkah berikutnya:")
            print("    python casper_arjum.py --health")
            print("    python casper_arjum.py --cek --endpoint history --code BBCA")
