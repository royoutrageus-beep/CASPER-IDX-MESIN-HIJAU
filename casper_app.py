# -*- coding: utf-8 -*-
"""
CASPER IDX — MESIN HIJAU (UI Streamlit) — v4.4.2
============================================================================
Jalankan:  streamlit run casper_app.py
Butuh:     pip install streamlit yfinance pandas numpy pytz
File lain: casper_engine.py + casper_arjum.py (versi sama) di folder yang sama

BEDA DARI v2:
  * Panel FUNNEL — kalau nol sinyal BUY, keliatan GERBANG MANA yang nutup.
    Dulu cuma muncul "nggak ada sinyal BUY" dan lo cuma bisa nebak.
  * Tier NYARIS — saham yang cuma gagal di SATU syarat, plus syarat mana.
  * Telegram: status dipisah 'terkirim' / 'diam (nggak ada yang baru)' /
    'gagal kredensial'. Dulu ketiganya sama-sama nongol "❌ Gagal kirim".
  * Kolom baru: event, bar_since (umur sinyal), pola candle, fase Wyckoff,
    tp_dari/sl_dari (level TP/SL itu asalnya dari mana), risiko_pct.
  * Header nampilin TANGGAL BAR DATA + status bar (TUTUP / BERJALAN / BASI)
    — jadi ketahuan kalau lagi mindai data basi atau candle yang belum jadi.
"""

import numpy as np
import pandas as pd
import streamlit as st

import casper_engine as ce

st.set_page_config(page_title="Casper IDX — Mesin Hijau", page_icon="👻",
                   layout="wide")

# ══════════════════════════════════════════════════════════════════════
#  PENJAGA VERSI — UI v4 butuh engine v4
# ══════════════════════════════════════════════════════════════════════
# Kalau cuma salah satu file yang ke-push ke repo (kejadian pas deploy
# pertama: app.py v4 + engine v3.1), dulu yang muncul cuma
# `AttributeError: module 'casper_engine' has no attribute 'VERSI'` —
# traceback yang nggak nyeritain apa-apa. Sekarang dicek eksplisit.
_WAJIB = ["VERSI", "DataKosong", "LAST_TELE", "FAKTOR", "COOLDOWN_JAM",
          "MIN_HARGA", "FRESH_MAX_BAR", "bar_sejak_nyala", "tick_size",
          "pilih_untuk_kirim", "porsi_sesi",
          # v4.1+
          "FAKTOR_BSJP", "pasang_bandar", "proyeksi_bagger",
          "jalankan_eod", "kirim_tele_eod",
          # v4.3
          "tandai_kebaruan"]
_WAJIB_MODUL = ["casper_data", "casper_arjum"]
_hilang = [a for a in _WAJIB if not hasattr(ce, a)]
if _hilang:
    st.error(
        "### ⚠️ Versi engine nggak cocok\n\n"
        f"`casper_app.py` ini versi **4.4.2**, tapi `casper_engine.py` yang "
        f"ke-load versi **{getattr(ce, 'VERSI', '3.x (lama)')}** — "
        f"kurang: `{'`, `'.join(_hilang[:5])}`"
        + (f" (+{len(_hilang) - 5} lagi)" if len(_hilang) > 5 else "")
        + "\n\n**Penyebab paling umum:** nggak semua file ke-push ke repo. "
        "`casper_engine.py`, `casper_app.py`, dan `casper_arjum.py` harus "
        "sama-sama versi terbaru dan ada di folder yang sama.\n\n"
        "Cek dari mesin lo:\n"
        "```bash\n"
        "grep -m1 VERSI casper_engine.py    # harus: VERSI = \"4.4.2\"\n"
        "git add casper_*.py requirements.txt .gitignore\n"
        "git commit -m 'Casper v4.4.2'\n"
        "git push\n"
        "```\n"
        "Habis push, Streamlit Cloud auto-redeploy ~1 menit. Kalau nggak "
        "gerak: menu ⋮ di pojok kanan atas → **Reboot app**.")
    st.caption(f"engine ter-load dari: `{getattr(ce, '__file__', '?')}`")
    st.stop()

# ══════════════════════════════════════════════════════════════════════
#  SHIM LEBAR — `use_container_width` vs `width`
# ══════════════════════════════════════════════════════════════════════
# Streamlit lagi mindahin `use_container_width=True` ke `width="stretch"`,
# TAPI nggak serentak: `st.dataframe` udah dapat `width` jauh lebih dulu
# daripada `st.button`. Jadi versi mana pun yang dipilih bakal salah di
# salah satu tempat:
#
#   - pakai use_container_width  -> Streamlit Cloud (versi baru) ngewarning
#     terus, dan tanggal hapusnya (2025-12-31) udah lewat
#   - pakai width                -> Python 3.12 + Streamlit lama di mesin
#     lokal langsung mati: "button() got an unexpected keyword argument
#     'width'"
#
# Naikin requirements bukan jawaban: kode yang sama harus jalan di Cloud
# DAN di laptop, dan lo nggak selalu mau update Streamlit cuma buat ini.
# Jadi dideteksi PER FUNGSI, sekali, terus di-cache.
import inspect                                          # noqa: E402
from functools import lru_cache                         # noqa: E402


@lru_cache(maxsize=None)
def _punya_width(nama_fn: str) -> bool:
    """True kalau `width` di fungsi ini nerima "stretch".

    JEBAKAN: adanya parameter `width` NGGAK cukup jadi patokan. Di
    Streamlit 1.40, `st.dataframe` udah punya `width` — tapi tipenya
    `int | None` (lebar dalam PIXEL). Ngoper "stretch" ke situ salah
    tipe, dan bisa gagal diam-diam. Baru di versi yang lebih baru
    tipenya berubah jadi Literal["stretch","content"] | int.
    Jadi yang dicek nilai yang DITERIMA, bukan sekadar nama parameternya.
    """
    fn = getattr(st, nama_fn, None)
    if fn is None:
        return False
    asli = getattr(fn, "__wrapped__", fn)
    try:
        p = inspect.signature(asli).parameters
    except (TypeError, ValueError):
        return False
    if "width" not in p:
        return False
    tipe = f"{p['width'].annotation}".lower()
    doc = (asli.__doc__ or "").lower()
    terima_stretch = ("stretch" in tipe) or ("stretch" in doc)
    if terima_stretch:
        return True
    # `width` ada tapi cuma nerima pixel -> pakai jalur lama selama masih
    # tersedia. Kalau dua-duanya nggak cocok, mendingan nggak ngoper
    # apa-apa daripada ngirim nilai yang salah tipe.
    return "use_container_width" not in p


def lebar(nama_fn: str, stretch: bool = True) -> dict:
    """Kwarg lebar yang cocok buat versi Streamlit yang lagi jalan.

    Balikin dict kosong kalau dua-duanya nggak ada — nggak ngoper apa-apa
    itu selalu lebih baik daripada bikin app mati gara-gara kosmetik.
    """
    if _punya_width(nama_fn):
        return {"width": "stretch" if stretch else "content"}
    fn = getattr(st, nama_fn, None)
    asli = getattr(fn, "__wrapped__", fn)
    try:
        if "use_container_width" in inspect.signature(asli).parameters:
            return {"use_container_width": stretch}
    except (TypeError, ValueError):
        pass
    return {}


HIJAU = "#A3E635"
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
html, body, [class*="css"], .stApp, p, span, div, label, input, textarea {
    font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stIconMaterial"], .material-symbols-rounded,
span[class*="material-symbols"] {
    font-family: 'Material Symbols Rounded' !important; }
.stApp { background: radial-gradient(1200px 500px at 20% -10%,
         #16240f 0%, #0a0f0a 55%) fixed; }
h1,h2,h3 { color:#e7f5e1 !important; letter-spacing:.5px; }
[data-testid="stSidebar"] { background:#0d140c; border-right:1px solid #223318; }
.banner { border:1px solid #A3E635; border-radius:14px; padding:18px 26px;
  background:linear-gradient(90deg,#101b0c 0%,#0b120a 100%);
  display:flex; justify-content:space-between; align-items:center;
  box-shadow:0 0 24px rgba(163,230,53,.15); margin-bottom:14px; }
.banner .logo { font-size:26px; font-weight:800; color:#fff; }
.banner .logo span { color:#A3E635; }
.banner .sub { color:#7a9a6a; font-size:12px; letter-spacing:3px; }
.banner .live { color:#A3E635; font-size:13px; border:1px solid #35521f;
  border-radius:8px; padding:6px 12px; background:#0e1a0a; text-align:right; }
.statgrid { display:grid; grid-template-columns:repeat(6,1fr); gap:10px;
  margin:6px 0 16px 0; }
.stat { background:#0e150c; border:1px solid #223318; border-top:3px solid
  #A3E635; border-radius:10px; padding:12px 14px; }
.stat .lbl { color:#7a9a6a; font-size:10px; letter-spacing:2px;
  text-transform:uppercase; }
.stat .val { color:#eaffdd; font-size:24px; font-weight:800; margin-top:2px; }
.cardgrid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px;
  margin-bottom:18px; }
.kartu { background:#0e150c; border:1px solid #2f4a1d; border-radius:12px;
  padding:14px 16px; box-shadow:0 0 14px rgba(163,230,53,.07); }
.kartu:hover { border-color:#A3E635; }
.kartu .tkr { font-size:20px; font-weight:800; color:#fff; }
.kartu .ms { float:right; color:#A3E635; font-weight:800; font-size:20px; }
.kartu .hrg { color:#A3E635; font-size:14px; margin:2px 0 4px 0; }
.kartu .ev { color:#ffc44d; font-size:11px; font-weight:700; margin-bottom:6px; }
.chip { display:inline-block; font-size:11px; font-weight:700;
  border-radius:6px; padding:2px 8px; margin:2px 4px 2px 0; }
.c-hijau { background:#1d310f; color:#A3E635; border:1px solid #4d7c22; }
.c-biru  { background:#0f2231; color:#5ec9ff; border:1px solid #22557c; }
.c-abu   { background:#1a2318; color:#93a58c; border:1px solid #35452f; }
.c-merah { background:#311414; color:#ff7b6b; border:1px solid #7c2a22; }
.kartu .tpsl { font-size:12px; color:#cfe8bf; margin-top:6px; }
.kartu .tpsl b.tp { color:#A3E635; } .kartu .tpsl b.sl { color:#ff7b6b; }
.kartu .insight { font-size:10.5px; color:#7a9a6a; margin-top:6px;
  border-top:1px dashed #2c421c; padding-top:6px; }
.quote { border-left:3px solid #A3E635; background:#0e150c; color:#cfe8bf;
  padding:10px 16px; border-radius:0 10px 10px 0; font-size:13px;
  margin-top:18px; }
.regime-box { border:1px solid #35521f44; border-left:4px solid #A3E635;
  border-radius:8px; padding:10px 14px; margin-bottom:10px;
  background:rgba(0,0,0,.25); font-size:11px; color:#cfe8bf; }
.barwarn { border-left:4px solid #ffc44d; background:rgba(255,196,77,.08);
  color:#ffe2a8; padding:8px 14px; border-radius:0 8px 8px 0;
  font-size:12px; margin-bottom:10px; }
.stButton>button { background:#A3E635 !important; color:#0a0f0a !important;
  font-weight:800 !important; border:0 !important; }
.stButton>button:hover { box-shadow:0 0 16px rgba(163,230,53,.5); }
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown(f"""
<div class="banner">
  <div>
    <div class="logo">👻 CASPER <span>IDX</span> — MESIN HIJAU</div>
    <div class="sub">EDUKASI • DATA • SISTEM • DISIPLIN — engine v{ce.VERSI}</div>
  </div>
  <div class="live">● LIVE {ce.now_wib():%H:%M:%S} WIB<br>
  {ce.now_wib():%d %b %Y}</div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════ SIDEBAR ═════════════════════════════════
with st.sidebar:
    st.markdown("### ⚙️ SCANNER SETTINGS")
    sumber = st.radio("Sumber data", ["Live", "Demo (simulasi)"])
    sumber_ohlcv = st.selectbox(
        "Asal OHLCV", ["auto", "arjum", "yahoo", "cache"],
        disabled=sumber.startswith("Demo"),
        help="auto = Arjum dulu, kalau gagal Yahoo, kalau dua-duanya "
             "gagal pakai cache disk. Yahoo makin sering nolak IP "
             "datacenter (Streamlit Cloud & GitHub Actions), jadi "
             "'auto' yang paling aman.")
    universe = st.radio("Cakupan", ["Semua IDX (~700)", "Custom"])
    custom = st.text_area("Ticker custom (tanpa .JK juga boleh)",
                          "BBCA BBRI TLKM", disabled=universe != "Custom")

    st.markdown("### 🎯 MODE SINYAL")
    auto_mode_on = st.toggle("🤖 Auto-Mode (ikuti regime IHSG)", value=True,
                             key="auto_mode_on")
    if auto_mode_on:
        _m, _p, _ef, _es, _label = ce.get_market_regime(ce.LAST_CLOSE)
        mode = _m
        st.markdown(f'<div class="regime-box">🎯 Auto: <b>{mode}</b> '
                    f'{ce.MODES.get(mode, {}).get("emoji", "")}<br>{_label}'
                    f'</div>', unsafe_allow_html=True)
    else:
        mode = st.selectbox(
            "Mode sinyal (manual)", list(ce.MODES), index=4,
            format_func=lambda m: f"{m} {ce.MODES[m]['emoji']}")
        if ce.MODES[mode].get("overnight"):
            st.caption("🌆 **BSJP** — beli sore ini, jual besok pagi. "
                       "Faktornya beda sendiri (kekuatan penutupan + "
                       "rekam jejak gap overnight + akumulasi bandar), "
                       "SL di bawah low hari ini. Sinyalnya BASI besok "
                       "pagi — jangan dipakai buat entry siang.")

    st.markdown("### 🔬 FILTER")
    min_to = st.number_input("Min turnover/hari — MEDIAN (juta Rp)",
                             min_value=0, value=int(ce.MIN_TURNOVER_JT),
                             step=100)
    min_harga = st.number_input("Harga minimum (Rp)", min_value=0,
                                value=int(ce.MIN_HARGA), step=25)
    min_iq = st.slider("Ambang alpha (persentil lintas saham)", 0, 100, 70,
                       step=5,
                       help="Sinyal BUY minimal masuk persentil ini. 70 = "
                            "top 30% saham berdasarkan gabungan faktor.")
    fresh = st.slider("Umur maksimal event (bar)", 0, 10, int(ce.FRESH_MAX_BAR),
                      help="Sinyal cuma dianggap valid kalau kejadiannya "
                           "(breakout / golden cross / reclaim pivot) terjadi "
                           "dalam sekian bar terakhir. Inilah yang bikin "
                           "saham yang sama nggak nongol terus tiap hari.")
    max_risiko = st.slider("Risiko maksimal ke SL (%)", 1.0, 20.0, 8.0, 0.5)
    min_rr = st.slider("R:R minimal", 1.0, 4.0, 1.5, 0.1)

    tombol_scan = st.button("🚀 SCAN MANUAL SEKARANG", **lebar("button"))
    st.divider()

    st.markdown("### 🔄 AUTO-SCAN")
    auto_on = st.toggle("Auto-Scan aktif", value=True, key="auto_on")
    interval = st.selectbox("Interval Auto-Scan",
                            ["15 menit", "30 menit", "60 menit"],
                            disabled=not auto_on)
    auto_tele = st.toggle("Kirim ke Telegram tiap ada sinyal BARU", value=True)
    st.caption("Telegram cuma bunyi kalau ada sinyal yang BENERAN baru. "
               f"Ticker + event yang sama nggak dikirim ulang dalam "
               f"{ce.COOLDOWN_JAM} jam.")
    st.divider()

    st.markdown("### 🕵️ BANDARMOLOGI")
    try:
        import casper_arjum as ar
        if ar.tersedia():
            st.caption("✅ API key Arjum ketemu — broker summary asli")
            hari_bandar = st.slider("Akumulasi berapa hari bursa", 1, 20, 5)
            bandar_top = st.slider(
                "Berapa kandidat teratas yang ditembak ke Arjum", 10, 150, 40,
                step=10,
                help="`code` di API Arjum itu path parameter — satu "
                     "request = satu saham. Nembak ~700 ticker tiap scan "
                     "bakal kena rate limit. Jadi seluruh universe di-rank "
                     "dulu pakai OHLCV, baru sekian teratas yang ditarik "
                     "data brokernya. Sisanya pakai proksi.")
        else:
            st.caption("⚠️ Key Arjum belum ada — pakai **proksi OHLCV** "
                       "(CMF + A/D). Itu nebak tekanan beli dari harga & "
                       "volume, BUKAN data broker.")
            st.code("python casper_arjum.py --set-key", language="bash")
            hari_bandar, bandar_top = 5, 40
    except Exception:                                   # noqa: BLE001
        st.caption("❌ casper_arjum.py nggak ketemu")
        hari_bandar, bandar_top = 5, 40

    st.markdown("### 📨 TELEGRAM")
    ada = ce.ambil_config_tele() is not None
    st.caption("✅ kredensial ditemukan" if ada
               else "❌ isi config_tele.json / secrets dulu")
    st.caption("🗄️ Jurnal: " + ce.backend_label())
    tombol_tele = st.button("🔔 Kirim top-8 sekarang (paksa)",
                            **lebar("button"),
                            disabled="hasil" not in st.session_state)

# ══════════════════════════════ SCAN ════════════════════════════════════
_menit = int(interval.split()[0])


def jalankan_scan(cfg):
    df = ce.scan(**cfg)
    ce.catat_jurnal(df)
    ev = ce.evaluasi_jurnal()
    return df, ev


auto_trigger = False
if auto_on:
    if "last_scan" not in st.session_state:
        auto_trigger = True
    else:
        _el = (ce.now_wib() - st.session_state["last_scan"]).total_seconds()
        auto_trigger = _el >= _menit * 60 - 10

if tombol_scan or auto_trigger:
    cfg = {"tickers": custom.split() if universe == "Custom" else None,
           "demo": sumber.startswith("Demo"),
           "semua": universe != "Custom",
           "mode": mode, "min_turnover_jt": min_to, "min_harga": min_harga,
           "sumber": sumber_ohlcv,
           "fresh_max": fresh, "min_iq": float(min_iq),
           "max_risiko": float(max_risiko), "min_rr": float(min_rr),
           "hari_bandar": hari_bandar, "bandar_top": bandar_top}
    with st.spinner(f"👻 Casper lagi mindai pasar (mode {mode})..."):
        try:
            df, ev = jalankan_scan(cfg)
        except ce.DataKosong as e:
            st.error(f"📡 {e}")
            df, ev = None, None
        except Exception as e:                          # noqa: BLE001
            st.error(f"💥 Scan gagal: {type(e).__name__}: {e}")
            df, ev = None, None
    if df is not None:
        # JANGAN nulis key `auto_mode_on` ke session_state: key itu udah
        # dipakai sama st.toggle di sidebar. Streamlit ngelarang nimpa
        # session_state buat key yang udah ke-bind ke widget, dan dia
        # ngelempar StreamlitAPIException yang pesan aslinya DISENSOR di
        # Streamlit Cloud — jadi yang kelihatan cuma traceback tanpa sebab.
        # Nilai toggle-nya tetap kebaca kok lewat st.session_state
        # ["auto_mode_on"] di auto_scan(); nggak perlu disalin.
        st.session_state.update(hasil=df, eval=ev, cfg=cfg,
                                meta=dict(ce.LAST_META),
                                last_scan=ce.now_wib())
        st.success(f"✅ {len(df)} saham lolos filter kualitas (mode {mode}).")
        if auto_tele:
            ok = ce.kirim_tele(df)
            stt = ce.LAST_TELE.get("status")
            if ok:
                st.success(f"🚀 {ce.LAST_TELE['n']} sinyal BARU dikirim "
                           "ke Telegram.")
            elif stt == "diam":
                st.info("🔕 Nggak ada sinyal baru — Telegram sengaja diam "
                        "(anti-spam).")
            else:
                st.warning(f"❌ Telegram: {stt}")

if tombol_tele and "hasil" in st.session_state:
    ce.kirim_tele(st.session_state["hasil"], paksa=True)
    st.toast(f"Telegram: {ce.LAST_TELE.get('status')}")


@st.fragment(run_every=_menit * 60
             if (auto_on and "cfg" in st.session_state) else None)
def auto_scan():
    ss = st.session_state
    if not auto_on or "cfg" not in ss:
        return
    last = ss.get("last_scan")
    if last is not None and \
       (ce.now_wib() - last).total_seconds() < _menit * 60 - 10:
        return
    cfg = dict(ss["cfg"])
    if ss.get("auto_mode_on"):
        cfg["mode"], *_ = ce.get_market_regime(ce.LAST_CLOSE)
    try:
        df, ev = jalankan_scan(cfg)
    except Exception as e:                              # noqa: BLE001
        ss["scan_error"] = f"{type(e).__name__}: {e}"
        ss["last_scan"] = ce.now_wib()
        return
    ss.update(hasil=df, eval=ev, cfg=cfg, meta=dict(ce.LAST_META),
              last_scan=ce.now_wib(), scan_error=None)
    if auto_tele:
        ce.kirim_tele(df)
    st.rerun(scope="app")


auto_scan()

meta = st.session_state.get("meta", {})
if "last_scan" in st.session_state:
    st.caption(
        f"🕒 Scan terakhir {st.session_state['last_scan']:%H:%M:%S} WIB · "
        f"📅 bar data **{meta.get('data_date', '?')}** "
        f"({meta.get('bar', '?')}) · 🔌 {meta.get('sumber_data', '?')}"
        + (f" · {meta['n_gagal_data']} ticker gagal diambil"
           if meta.get("n_gagal_data") else "")
        + (f" · 🔄 Auto tiap {interval}" if auto_on else " · Auto OFF"))
if "CACHE DISK" in str(meta.get("sumber_data", "")):
    _umur = meta.get("cache_umur_hari")
    st.markdown(
        '<div class="barwarn">🛑 <b>Semua sumber online gagal</b> — '
        'scan ini jalan pakai <b>cache disk</b>'
        + (f' (umur {_umur:.0f} hari)' if _umur == _umur else '')
        + '. Sinyalnya berdasar data lama, jangan dipakai buat entry. '
        'Yahoo lagi nolak, dan Arjum belum kesetel / ikut gagal.</div>',
        unsafe_allow_html=True)
if str(meta.get("bar", "")).startswith("BASI"):
    st.markdown(
        f'<div class="barwarn">⚠️ Data terakhir dari '
        f'<b>{meta.get("data_date")}</b> — {meta.get("bar")}. Sinyal '
        'dihitung dari bar itu, bukan dari harga hari ini. Kalau bursa '
        'lagi buka, kemungkinan feed Yahoo lagi telat.</div>',
        unsafe_allow_html=True)
elif str(meta.get("bar", "")).startswith("BERJALAN"):
    st.markdown(
        f'<div class="barwarn">🕘 Candle hari ini <b>belum selesai</b> '
        f'({meta.get("bar")}). RVOL udah diskalakan ke porsi sesi yang '
        'lewat, tapi close/high/low masih bisa berubah sampai penutupan.'
        '</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(
    ["🔥 Scanner", "🔬 Kenapa segini", "📓 Journal", "✅ Bukti Statistik"])

# ══════════════════════════════ SCANNER ═════════════════════════════════
with tab1:
    if "hasil" not in st.session_state:
        st.info("👻 Menunggu scan pertama jalan otomatis...")
    else:
        df = st.session_state["hasil"]
        buy = df[df["iq_verdict"] == "BUY"].copy()
        nyaris = df[df["iq_verdict"] == "NYARIS"].copy()

        st.markdown(f"""
<div class="statgrid">
 <div class="stat"><div class="lbl">Discan</div><div class="val">{len(df)}</div></div>
 <div class="stat"><div class="lbl">Sinyal BUY</div><div class="val">{len(buy)}</div></div>
 <div class="stat"><div class="lbl">Nyaris (kurang 1)</div><div class="val">{len(nyaris)}</div></div>
 <div class="stat"><div class="lbl">Event fresh</div><div class="val">{int(df['event_kuat'].sum())}</div></div>
 <div class="stat"><div class="lbl">Median R:R</div><div class="val">{df['rr'].median():.2f}</div></div>
 <div class="stat"><div class="lbl">Median risiko</div><div class="val">{df['risiko_pct'].median():.1f}%</div></div>
</div>""", unsafe_allow_html=True)

        # Sumber bandarmologi ditempel besar-besar. Kolom net_bandar_jt /
        # cmf keisi dua-duanya baik dari Arjum maupun proksi — tanpa
        # penanda ini gampang banget salah sangka lagi lihat data broker
        # asli padahal cuma tebakan dari harga & volume.
        _src = str(df["bandar_sumber"].iloc[0]) if len(df) else "-"
        if "Arjum" in _src:
            st.success(f"🕵️ Bandarmologi: **{_src}** — broker summary asli.")
        elif "proksi" in _src:
            st.info("🕵️ Bandarmologi: **proksi OHLCV ⚠️** — kolom "
                    "`cmf` dihitung dari posisi close di dalam range "
                    "harian, **bukan** data broker. Isi API key Arjum "
                    "buat dapat net-buy per broker beneran.")
        else:
            st.warning("🕵️ Bandarmologi: tidak ada.")

        if buy.empty:
            st.warning("⚠️ Nol sinyal BUY. Itu **bukan** error — buka tab "
                       "**🔬 Kenapa segini** buat lihat gerbang mana yang "
                       "nutup, dan lihat daftar NYARIS di bawah.")

        if not buy.empty:
            n_baru = int(buy["baru"].sum())
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("#### 🎯 SINYAL")
            with c2:
                cuma_baru = st.toggle(
                    f"Cuma yang belum pernah nongol ({n_baru} dari "
                    f"{len(buy)})", value=True, key="cuma_baru",
                    help="Scanner ini nampilin KEADAAN sekarang. Saham yang "
                         "lagi trending bisa lolos semua gerbang beberapa "
                         "hari berturut-turut — di layar kelihatannya "
                         "'itu-itu aja' padahal sistemnya normal. Toggle "
                         "ini nyaring yang udah pernah muncul sebagai BUY "
                         "dalam 5 hari terakhir (sumbernya jurnal).")
            if cuma_baru:
                buy = buy[buy["baru"]]
                if buy.empty:
                    st.info("🔁 Semua sinyal hari ini **udah pernah nongol** "
                            "beberapa hari terakhir — nggak ada yang baru. "
                            "Matiin toggle di atas buat lihat semuanya.")
            kartu = ""
            for _, r in buy.head(10).iterrows():
                g = str(r["mesin_grade"])
                warna = ("c-biru" if "BANDAR" in g else
                         "c-hijau" if ("PRESISI" in g or "LAYAK" in g) else
                         "c-merah" if "WAIT" in g else "c-abu")
                rr = f"{r['rr']:.2f}" if np.isfinite(r["rr"]) else "-"
                lencana = ("" if r.get("baru", True)
                           else f" · <span style='color:#7a9a6a'>tayang "
                                f"ke-{int(r.get('tayang_ke', 1))}</span>")
                if r.get("konfirmasi"):
                    lencana += f" · 🕯️ {r['konfirmasi']}"
                # baris ekstra sesuai horizon modenya
                ekstra = ""
                if np.isfinite(pd.to_numeric(r.get("ov_menang_pct"),
                                             errors="coerce")) \
                        and ce.MODES.get(mode, {}).get("overnight"):
                    ekstra = (f"<br>🌆 overnight 120h: menang "
                              f"{r['ov_menang_pct']:.0f}% · rata "
                              f"{r['ov_rata_pct']:+.2f}% · close-str "
                              f"{r['close_str']:.2f}")
                if np.isfinite(pd.to_numeric(r.get("proj_p50"),
                                             errors="coerce")):
                    ekstra += (f"<br>💎 12bln {r['proj_p25']:+.0f}% / "
                               f"<b>{r['proj_p50']:+.0f}%</b> / "
                               f"{r['proj_p75']:+.0f}% · 2x "
                               f"{r['p_2x']:.0f}%")
                if np.isfinite(pd.to_numeric(r.get("akum_jt"),
                                             errors="coerce")):
                    ekstra += (f"<br>🕵️ akum {r['akum_jt']:,.0f}jt · "
                               f"top5 {r['konsentrasi_top5']:.0%} · "
                               f"{r['broker_top']}")
                kartu += f"""
<div class="kartu">
  <span class="ms">{r['iq_score']:.0f}</span>
  <div class="tkr">{r['ticker']}</div>
  <div class="hrg">Rp{r['price']:,.0f} · ATR {r['atr_pct']}%</div>
  <div class="ev">⚡ {r['event']} · {int(r['bar_since'])} bar lalu{lencana}</div>
  <span class="chip {warna}">{g}</span>
  <span class="chip c-hijau">{r['signal']}</span>
  <div class="tpsl">🎯 TP <b class="tp">{r['tp']:,.0f}</b>
    <span style="font-size:10px">({r['tp_dari']})</span> ·
    🔴 SL <b class="sl">{r['sl']:,.0f}</b>
    <span style="font-size:10px">({r['sl_dari']})</span><br>
    R:R {rr} · risiko {r['risiko_pct']}%</div>
  <div class="insight">🕯️ {r['pola'] or '—'} · {r['fase']}<br>
    RSI {r['rsi_ema']} · RVOL {r['rvol']}x · ½K {r['kelly_%']}% ·
    maks Rp{r['max_order_jt']}jt{ekstra}</div>
</div>"""
            st.markdown(f'<div class="cardgrid">{kartu}</div>',
                        unsafe_allow_html=True)

        if not nyaris.empty:
            st.markdown("#### 🟡 NYARIS — gagal cuma di satu syarat")
            st.dataframe(
                nyaris[["ticker", "iq_score", "event", "bar_since", "kurang",
                        "baru", "tayang_ke",
                        "price", "tp", "sl", "rr", "risiko_pct", "rvol",
                        "rsi_ema", "pola", "fase"]],
                **lebar("dataframe"), hide_index=True, height=240)

        if df["proj_p50"].notna().any():
            st.markdown("#### 💎 PROYEKSI 12 BULAN — sebaran, bukan ramalan")
            st.caption("Block bootstrap (blok 20 hari, jaga volatility "
                       "clustering) dari return 2 tahun terakhir. Bacanya: "
                       "*kalau perilaku harga ke depan mirip 2 tahun "
                       "kebelakang, sebarannya segini.* Jarak p25→p75 yang "
                       "lebar = ketidakpastiannya emang gede, bukan "
                       "modelnya jelek. Kalau fundamental atau "
                       "likuiditasnya berubah, angka ini nggak berlaku.")
            st.dataframe(
                df.dropna(subset=["proj_p50"]).nlargest(25, "iq_score")[
                    ["ticker", "iq_score", "price", "proj_p25", "proj_p50",
                     "proj_p75", "p_2x", "p_setengah", "atr_pct", "fase",
                     "bandar_sumber"]],
                **lebar("dataframe"), hide_index=True, height=300,
                column_config={
                    "proj_p50": st.column_config.NumberColumn(
                        "median 12bln", format="%+.0f%%"),
                    "proj_p25": st.column_config.NumberColumn(
                        "p25", format="%+.0f%%"),
                    "proj_p75": st.column_config.NumberColumn(
                        "p75", format="%+.0f%%"),
                    "p_2x": st.column_config.NumberColumn(
                        "peluang 2x", format="%.0f%%"),
                    "p_setengah": st.column_config.NumberColumn(
                        "peluang -50%", format="%.0f%%")})

        st.markdown("#### 📋 SEMUA HASIL SCAN")
        pilih_v = st.multiselect("Filter verdict",
                                 ["BUY", "NYARIS", "HOLD", "WAIT"],
                                 default=["BUY", "NYARIS", "HOLD"])
        tampil = df[df["iq_verdict"].isin(pilih_v)]

        def warnai(x):
            s = str(x)
            if any(k in s for k in ("GACOR", "HAKA", "BUY", "BANDAR",
                                    "PRESISI", "LAYAK", "BREAKOUT",
                                    "GOLDEN", "True")):
                return f"color:{HIJAU};font-weight:700"
            if any(k in s for k in ("WAIT", "False", "SPIKE", "Mark-Down")):
                return "color:#ff7b6b"
            if any(k in s for k in ("POTENSIAL", "HOLD", "NYARIS", "⚠️",
                                    "Distribusi")):
                return "color:#ffc44d"
            return ""

        st.dataframe(
            tampil.style.map(warnai,
                             subset=["signal", "sinyal_v2", "mesin_grade",
                                     "iq_verdict", "event", "above_vwap",
                                     "vol_regime", "fase"]),
            **lebar("dataframe"), height=520, hide_index=True,
            column_config={
                "iq_score": st.column_config.ProgressColumn(
                    "alpha (0-100)", min_value=0, max_value=100,
                    format="%.0f"),
                "mesin_score": st.column_config.ProgressColumn(
                    "eksekusi", min_value=0, max_value=100, format="%.0f")})

# ══════════════════════════ KENAPA SEGINI ═══════════════════════════════
with tab2:
    st.markdown("#### 🔬 FUNNEL — gerbang mana yang nutup")
    st.caption("`lolos sendiri` = berapa saham lolos syarat ini kalau "
               "syarat lain diabaikan. `lolos kumulatif` = yang lolos "
               "syarat ini DAN semua syarat di atasnya. Baris yang bikin "
               "kumulatifnya anjlok — itu penyebabnya.")
    f = st.session_state.get("meta", {}).get("funnel")
    if f:
        fd = pd.DataFrame([{"syarat": k, "lolos sendiri": v["lolos_sendiri"],
                            "lolos kumulatif": v["lolos_kumulatif"]}
                           for k, v in f.items()])
        fd["sisa setelah gerbang ini"] = fd["lolos kumulatif"]
        fd["dipangkas di sini"] = (fd["lolos kumulatif"].shift(1)
                                   .fillna(fd["lolos kumulatif"].iloc[0])
                                   - fd["lolos kumulatif"]).astype(int)
        st.dataframe(fd[["syarat", "lolos sendiri", "lolos kumulatif",
                         "dipangkas di sini"]],
                     **lebar("dataframe"), hide_index=True)
        biang = fd.sort_values("dipangkas di sini", ascending=False).iloc[0]
        if biang["dipangkas di sini"] > 0:
            st.info(f"🎯 Gerbang paling menggigit: **{biang['syarat']}** — "
                    f"mangkas {int(biang['dipangkas di sini'])} saham.")
    else:
        st.info("Scan dulu sekali.")

    with st.expander("🧮 Audit matematika — rumus, sumber, dan bobot",
                     expanded=False):
        st.markdown(f"""
**Satu skor, bukan tiga.** v3.1 punya `score`, `mesin_score`, `iq_score`
yang korelasinya 0.89–0.98 — tiga kolom berisi informasi yang sama, dan
`rvol` dihitung dua kali di dalamnya. Sekarang:

| Kolom | Ngukur apa | Sumber |
|---|---|---|
| `iq_score` / `alpha` | seberapa bagus sahamnya **relatif ke saham lain** | gabungan faktor, demeaned rank |
| `mesin_score` | seberapa layak sinyalnya **dieksekusi** (likuiditas, lebar stop, R:R) | mikro-struktur |
| `event` + `bar_since` | **kejadian apa** yang baru terjadi & berapa bar lalu | 3.12–3.15 |

**Gabungan faktor — demeaned rank (buku eq. 276–277):**

```
s_Ai = rank(f_Ai) − (1/N) Σ_j rank(f_Aj)
s_i  = Σ_A w_A · s_Ai  /  Σ_A w_A
```

| Faktor | Rumus | Bab buku | Bobot |
|---|---|---|---|
| `f_mom` | R^risk.adj = R^mean / σ, formation T, skip S | 3.1 (eq. 268–269) | {ce.FAKTOR['f_mom']} |
| `f_resmom` | momentum dari residual regresi ke IHSG | 3.7 (eq. 278–281) | {ce.FAKTOR['f_resmom']} |
| `f_lowvol` | −σ 126 hari | 3.4 | {ce.FAKTOR['f_lowvol']} |
| `f_meanrev` | −(R_i − R̄) lintas cluster | 3.9 (eq. 292–294) | {ce.FAKTOR['f_meanrev']} |
| `f_trend` | EMA_cepat / EMA_lambat − 1 | 3.11–3.13 | {ce.FAKTOR['f_trend']} |
| `f_vol` | log(RVOL) | poster: konfirmasi volume | {ce.FAKTOR['f_vol']} |

Rank kebal outlier — itu sebabnya buku pakai ini, dan sebabnya saham
gorengan ATR 14% nggak bisa lagi ngisi skor sempurna kayak di v3.1.

**Kenapa `f_resmom` penting buat IDX:** kalau IHSG lagi rally, hampir semua
saham momentumnya positif. Tanpa membuang beta pasar, scanner nggak bisa
bedain "saham ini kuat" dari "pasarnya lagi naik" — dan hasilnya sinyal
numpuk seragam.

**Event, bukan keadaan.** Sinyal cuma valid kalau kejadiannya masih fresh:
- `BREAKOUT 🚀` — close > Donchian ceiling {'{'}T{'}'} bar (eq. 329–331) **+ RVOL ≥ 1.5**
- `GOLDEN CROSS ✨` — EMA cepat nyilang EMA lambat (eq. 322), kuat kalau 3 MA searah (eq. 324)
- `RECLAIM PIVOT 🎯` — close ≥ pivot C setelah ≥3 bar di bawahnya (eq. 325–328)
- pola candle bullish **dengan** trend + volume + di atas pivot

**TP/SL.** Stop dulu dari struktur (pivot S / Donchian floor, dibatasi 3 ATR),
target = resistance struktural pertama yang jaraknya ≥ 1R, kalau nggak ada
pakai 2R murni — dan labelnya jujur di kolom `tp_dari`. Semua di-snap ke
fraksi harga IDX (1/2/5/10/25) biar bisa beneran dipasang di order book.

**Risiko.** `vol_regime` = EWMA λ0.94 vs realized σ 60 hari · `var5_pct` =
VaR 5% empiris · `max_order_jt` = square-root law, impact σ√(Q/ADV) ≤ 0.5%,
dicap 5% ADV · `kelly_%` = half-Kelly dari jurnal sendiri, **butuh ≥ 30
sampel** (v3.1 pakai 10 — di n=10 standard error win-rate ±16 poin, itu
noise yang dipoles).
""")

# ══════════════════════════════ JOURNAL ═════════════════════════════════
with tab3:
    j = ce.baca_jurnal()
    if j is not None and len(j):
        dup = len(j) - len(j.drop_duplicates(
            subset=[c for c in ("date", "ticker", "mode") if c in j.columns]))
        st.caption(f"📓 {len(j)} baris di {ce.backend_label()} · "
                   f"duplikat (date+ticker+mode): {dup}")
        if dup:
            st.warning(f"⚠️ Ada {dup} baris duplikat — itu peninggalan "
                       "jurnal v3.1. Baris baru dari v4.0 udah di-dedup. "
                       "Bersihin dengan: hapus/arsipkan `jurnal_sinyal.csv` "
                       "atau de-dup manual sebelum dipakai buat statistik.")
        sort_cols = [c for c in ("date", "ts") if c in j.columns]
        st.dataframe(j.sort_values(sort_cols, ascending=False)
                     if sort_cols else j,
                     **lebar("dataframe"), height=520, hide_index=True)
    else:
        st.info("Belum ada jurnal. Scan minimal sekali dulu.")

# ═══════════════════════════ BUKTI STATISTIK ════════════════════════════
with tab4:
    ev = st.session_state.get("eval")
    if ev is None:
        ev = ce.baca_evaluasi()
    if ev is not None and len(ev):
        per = st.radio("Kelompokkan per", ["event", "signal", "mesin_grade"],
                       horizontal=True)
        g = ce.ringkas_evaluasi(ev, per=per)
        st.markdown("#### 🏆 WIN RATE — horizon T+1 / T+3 / T+5 hari bursa")
        st.caption("Diukur dari **tanggal bar data**, bukan tanggal scan. "
                   "Kelompokkan per `event` buat jawab pertanyaan yang "
                   "beneran penting: breakout beneran lebih baik dari "
                   "golden cross, nggak? Kalau BUY nggak konsisten lebih "
                   "baik dari WAIT di semua horizon, berarti belum ada edge "
                   "— dan itu informasi yang berharga, bukan aib.")
        if g is not None:
            hz = st.radio("Horizon", ["T1", "T3", "T5"], index=1,
                          horizontal=True)
            st.dataframe(g[g["horizon"] == hz], **lebar("dataframe"),
                         hide_index=True)
            with st.expander("Semua horizon sekaligus"):
                st.dataframe(g, **lebar("dataframe"), hide_index=True)
        st.markdown("#### 📜 Detail per sinyal")
        sc = "t3_ret" if "t3_ret" in ev.columns else ev.columns[-1]
        st.dataframe(ev.sort_values(sc, ascending=False, na_position="last"),
                     **lebar("dataframe"), height=400, hide_index=True)
    else:
        st.info("Evaluasi muncul setelah ada sinyal berumur ≥ 1 hari bursa "
                "dan lo scan ulang.")

st.markdown('<div class="quote">💬 Scanner ini ngasih <b>kandidat + '
            'alasan + level</b>, bukan ramalan. Kalau nol sinyal, itu '
            'jawaban yang sah — bukan kerusakan. · bukan rekomendasi '
            'beli/jual</div>', unsafe_allow_html=True)
