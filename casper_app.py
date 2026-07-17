# -*- coding: utf-8 -*-
"""
CASPER IDX — MESIN HIJAU (UI Streamlit)
=======================================
Jalankan:  streamlit run casper_app.py
Butuh:     pip install streamlit yfinance pandas numpy
File lain: casper_engine.py + .streamlit/config.toml (satu folder)
"""

import os
import pandas as pd
import streamlit as st
import casper_engine as ce

st.set_page_config(page_title="Casper IDX — Mesin Hijau", page_icon="👻",
                   layout="wide")

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
  border-radius:8px; padding:6px 12px; background:#0e1a0a; }
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
.kartu .hrg { color:#A3E635; font-size:14px; margin:2px 0 8px 0; }
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
.stButton>button { background:#A3E635 !important; color:#0a0f0a !important;
  font-weight:800 !important; border:0 !important; }
.stButton>button:hover { box-shadow:0 0 16px rgba(163,230,53,.5); }
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown(f"""
<div class="banner">
  <div>
    <div class="logo">👻 CASPER <span>IDX</span> — MESIN HIJAU</div>
    <div class="sub">EDUKASI • DATA • SISTEM • DISIPLIN</div>
  </div>
  <div class="live">● LIVE {ce.now_wib():%H:%M:%S} WIB<br>
  {ce.now_wib():%d %b %Y}</div>
</div>""", unsafe_allow_html=True)

# ------------------------------ SIDEBAR ---------------------------------
with st.sidebar:
    st.markdown("### ⚙️ SCANNER SETTINGS")
    sumber = st.radio("Sumber data", ["Live (Yahoo Finance)", "Demo (simulasi)"])
    universe = st.radio("Cakupan", ["12 default", "Semua IDX (~700)", "Custom"])
    custom = st.text_area("Ticker custom (tanpa .JK juga boleh)",
                          "BBCA BBRI TLKM",
                          disabled=universe != "Custom")
    mode = st.selectbox("Mode sinyal",
                        ["Scalping", "Momentum", "Intraday", "Swing",
                         "Bagger"])
    min_to = st.number_input("Min turnover/hari (juta Rp)",
                             min_value=0, value=500, step=100)
    hanya_buy = st.toggle("Hanya tampilkan BUY", value=False)
    tombol_scan = st.button("🚀 MULAI SCAN SEKARANG", use_container_width=True)
    st.divider()
    st.markdown("### 🔄 AUTO-SCAN")
    auto_on = st.toggle("Auto-Scan berkala", value=False)
    interval = st.selectbox("Interval Auto-Scan",
                            ["15 menit", "30 menit", "60 menit"],
                            disabled=not auto_on)
    auto_tele = st.toggle("Kirim ke Telegram tiap selesai scan", value=True)
    st.divider()
    st.markdown("### 📨 TELEGRAM")
    ada = ce.ambil_config_tele() is not None
    st.caption(("✅ kredensial Telegram ditemukan" if ada else
                "❌ isi config_tele.json / secrets dulu"))
    st.caption("🗄️ Jurnal: " + ce.backend_label())
    tombol_tele = st.button("🔔 Kirim sinyal ke Telegram",
                            use_container_width=True,
                            disabled="hasil" not in st.session_state)

# ------------------------------- SCAN -----------------------------------
if tombol_scan:
    demo = sumber.startswith("Demo")
    tickers, semua = None, False
    if universe == "Custom":
        tickers = custom.split()
    elif universe.startswith("Semua"):
        semua = True
    with st.spinner("👻 Casper lagi mindai pasar... (Semua IDX ± 10-20 mnt)"):
        df = ce.scan(tickers=tickers, demo=demo, semua=semua,
                     mode=mode, min_turnover_jt=min_to)
        ce.catat_jurnal(df)
        ev = ce.evaluasi_jurnal(ce.LAST_CLOSE)
    st.session_state["hasil"], st.session_state["eval"] = df, ev
    st.session_state["cfg"] = {"tickers": tickers, "demo": demo,
                               "semua": semua, "mode": mode,
                               "min_turnover_jt": min_to}
    st.session_state["last_scan"] = ce.now_wib()
    st.success(f"✅ {len(df)} saham lolos filter — otomatis ke-log di Journal.")
    if auto_tele:
        if ce.kirim_tele(df):
            st.success("🚀 Hasil scan langsung terkirim ke Telegram!")
        else:
            st.warning("❌ Gagal kirim Telegram — cek kredensial")

if tombol_tele and "hasil" in st.session_state:
    ok = ce.kirim_tele(st.session_state["hasil"])
    if ok:
        st.toast("🚀 Terkirim ke Telegram!")
    else:
        st.toast("❌ Gagal — cek kredensial Telegram")

# --------------------------- AUTO-SCAN BERKALA ---------------------------
_menit = int(interval.split()[0])

@st.fragment(run_every=_menit * 60
             if (auto_on and "cfg" in st.session_state) else None)
def auto_scan():
    ss = st.session_state
    if not auto_on or "cfg" not in ss:
        return
    last = ss.get("last_scan")
    if last is not None and \
       (ce.now_wib() - last).total_seconds() < _menit * 60 - 10:
        return                      # belum waktunya, tunggu jadwal
    df = ce.scan(**ss["cfg"])
    ce.catat_jurnal(df)
    ss["hasil"] = df
    ss["eval"] = ce.evaluasi_jurnal(ce.LAST_CLOSE)
    ss["last_scan"] = ce.now_wib()
    if auto_tele:
        ce.kirim_tele(df)
    st.rerun(scope="app")

auto_scan()

if "last_scan" in st.session_state:
    st.caption(f"🕒 Scan terakhir {st.session_state['last_scan']:%H:%M:%S} WIB"
               + (f" · 🔄 Auto-Scan ON tiap {interval}"
                  + (" + auto-Telegram" if auto_tele else "")
                  if auto_on else " · Auto-Scan OFF"))

tab1, tab2, tab3 = st.tabs(["🔥 Scanner", "📓 Journal", "✅ Bukti Statistik"])

# ------------------------------ SCANNER ----------------------------------
with tab1:
    if "hasil" not in st.session_state:
        st.info("Klik **MULAI SCAN SEKARANG** di sidebar.")
    else:
        df = st.session_state["hasil"]
        tampil = df[df["iq_verdict"] == "BUY"] if hanya_buy else df
        if hanya_buy and tampil.empty:
            st.warning("⚠️ Nggak ada sinyal BUY di scan ini — semua hasil "
                       "ditampilkan. (Toggle 'Hanya tampilkan BUY' di "
                       "sidebar yang bikin tabel kosong tadi.)")
            tampil = df

        n_buy = int((df["iq_verdict"] == "BUY").sum())
        n_gcr = int(df["signal"].str.startswith("GACOR").sum())
        n_pot = int(df["signal"].str.startswith("POTENSIAL").sum())
        st.markdown(f"""
<div class="statgrid">
 <div class="stat"><div class="lbl">Lolos Filter</div><div class="val">{len(df)}</div></div>
 <div class="stat"><div class="lbl">Sinyal BUY</div><div class="val">{n_buy}</div></div>
 <div class="stat"><div class="lbl">Gacor ⚡</div><div class="val">{n_gcr}</div></div>
 <div class="stat"><div class="lbl">Potensial 🔥</div><div class="val">{n_pot}</div></div>
 <div class="stat"><div class="lbl">Avg RSI-EMA</div><div class="val">{df["rsi_ema"].mean():.1f}</div></div>
 <div class="stat"><div class="lbl">Skor Top</div><div class="val">{df["score"].max():.1f}</div></div>
</div>""", unsafe_allow_html=True)

        st.markdown("#### 🎯 TOP SIGNALS")
        kartu = ""
        for _, r in tampil.head(10).iterrows():
            g = r["mesin_grade"]
            warna = ("c-biru" if "BANDAR" in g else
                     "c-hijau" if ("PRESISI" in g or "KUAT" in g) else
                     "c-merah" if "WAIT" in g else "c-abu")
            vw = "Above VWAP" if r["above_vwap"] else "Below VWAP"
            kartu += f"""
<div class="kartu">
  <span class="ms">{r['mesin_score']:.0f}</span>
  <div class="tkr">{r['ticker']}</div>
  <div class="hrg">Rp{r['price']:,.0f} · ATR {r['atr_pct']}%</div>
  <span class="chip {warna}">{g}</span>
  <span class="chip c-hijau">TT:{r['signal']}</span>
  <span class="chip {'c-hijau' if r['iq_verdict']=='BUY' else 'c-abu'}">
    {r['iq_verdict']} · IQ {r['iq_score']:.0f}</span>
  <div class="tpsl">🎯 TP <b class="tp">{r['tp']:,.0f}</b> ·
    🔴 SL <b class="sl">{r['sl']:,.0f}</b> · R:R {r['rr']}</div>
  <div class="insight">💡 RSI-EMA {r['rsi_ema']} · RVOL {r['rvol']}x ·
    {vw} · {r['sinyal_v2']} · ½K {r['kelly_%']}%</div>
</div>"""
        st.markdown(f'<div class="cardgrid">{kartu}</div>',
                    unsafe_allow_html=True)

        st.markdown("#### 📋 FULL SIGNAL TABLE")
        def warnai(x):
            s = str(x)
            if any(k in s for k in ("GACOR", "HAKA", "BUY", "NAIK", "BANDAR",
                                    "PRESISI", "KUAT", "True")):
                return f"color:{HIJAU};font-weight:700"
            if any(k in s for k in ("WAIT", "TURUN", "False", "SPIKE")):
                return "color:#ff7b6b"
            if "POTENSIAL" in s or "HOLD" in s:
                return "color:#ffc44d"
            return ""
        styler = (tampil.style
                  .map(warnai, subset=["signal", "sinyal_v2", "mesin_grade",
                                       "iq_verdict", "above_vwap",
                                       "vol_regime"])
                  .format({"price": "{:,.0f}", "tp": "{:,.0f}",
                           "sl": "{:,.0f}"}))
        st.dataframe(styler, use_container_width=True, height=520,
                     hide_index=True,
                     column_config={
                         "score": st.column_config.ProgressColumn(
                             "score", min_value=0, max_value=10, format="%.1f"),
                         "mesin_score": st.column_config.ProgressColumn(
                             "mesin_score", min_value=0, max_value=100,
                             format="%.0f")})

        with st.expander("🧮 Audit matematika — rumus & bobot skor"):
            st.markdown("""
| Komponen | Bobot | Syarat |
|---|---|---|
| Trend naik | 2.0 | close > MA cepat > MA lambat (sesuai mode) |
| Relative volume | 2.0 | min(rvol/2, 1) |
| Momentum RSI | 2.0 | RSI-EMA(9) di zona mode |
| Di atas VWAP20 | 1.0 | close > VWAP 20 hari |
| Return periode mode | 2.0 | min(retN/target, 1) jika positif |
| ATR layak | 1.0 | ATR% di zona mode |

`signal` GACOR ≥ 6 · POTENSIAL ≥ 4.5 — `mesin_score` = score/10×60 +
min(rvol/3,1)×25 + 15×(>VWAP) — `iq_verdict` **BUY jika iq ≥ 65 + trend naik
+ di atas VWAP + RVOL ≥ 1.5** — TP = harga + 1.9×ATR, SL = harga − 1×ATR

**Lapisan risiko kuantitatif:** `vol_regime` = vol EWMA λ0.94 vs rata2 60
hari (volatility clustering) · `var5_pct` = VaR 5% empiris dari distribusi
asli (fat tails) · `max_order_jt` = order maks agar impact σ√(Q/ADV) ≤ 0.5%
(square-root law) · `kelly_%` = half-Kelly dari rekam jejak jurnal sendiri,
cap 10% (Kelly criterion, aktif setelah ≥ 10 sampel evaluasi per label).

Tiap mode (Scalping ⚡ / Momentum 🚀 / Intraday 🌤️ / Swing 🌙 / Bagger 💎)
punya rentang RSI, ATR, periode return, dan pasangan MA sendiri. Saham dengan
turnover harian di bawah ambang likuiditas dibuang sebelum dinilai.
""")

# ------------------------------ JOURNAL ----------------------------------
with tab2:
    j = ce.baca_jurnal()
    if j is not None and len(j):
        st.caption(f"📓 {len(j)} sinyal terekam otomatis di "
                   f"{ce.backend_label()} — sistem nggak bisa "
                   "pilih-pilih atau 'lupa'. Semua kebukti di sini.")
        st.dataframe(j.sort_values(["date", "ts"], ascending=False),
                     use_container_width=True, height=520, hide_index=True)
    else:
        st.info("Belum ada jurnal. Scan minimal sekali dulu.")

# --------------------------- BUKTI STATISTIK -----------------------------
with tab3:
    ev = st.session_state.get("eval")
    if ev is None:
        ev = ce.baca_evaluasi()
    if ev is not None and len(ev):
        g = ce.ringkas_evaluasi(ev)
        st.markdown("#### 🏆 WIN RATE PER LABEL — sinyal lama vs harga kini")
        st.caption("Di sinilah kelihatan apakah GACOR beneran lebih sering "
                   "naik daripada WATCH. Data yang bicara, bukan feeling.")
        st.dataframe(g, use_container_width=True, hide_index=True)
        st.markdown("#### 📜 Detail per sinyal")
        st.dataframe(ev.sort_values("return_%", ascending=False),
                     use_container_width=True, height=400, hide_index=True)
    else:
        st.info("Evaluasi muncul setelah ada sinyal berumur ≥ 1 hari "
                "dan lo scan ulang.")

st.markdown('<div class="quote">💬 "Sistem yang baik mengalahkan keputusan '
            'yang emosional." — Insight Casper · bukan rekomendasi '
            'beli/jual</div>', unsafe_allow_html=True)
