"""
IDX QUANT BOT — Streamlit Edition
Bloomberg Dark Terminal Style
Based on "151 Trading Strategies" — Kakushadze & Serur (2018)

Run: streamlit run idx_quant_bot.py
"""

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import streamlit as st

# ─── SECRETS — baca dari .streamlit/secrets.toml ─────────────────────────────
def get_secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

TELEGRAM_BOT_TOKEN   = get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = get_secret("TELEGRAM_CHAT_ID")

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="IDX QUANT BOT",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── GLOBAL CSS ──────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Toggle */
div[data-testid="stToggle"] span {
    background: linear-gradient(135deg,#a855f7,#7c3aed) !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: #0f1217; }
::-webkit-scrollbar-thumb { background: #a855f7; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: #c084fc; }

/* Selection */
::selection { background: rgba(168,85,247,0.3); color: #fff; }

@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Space Mono', monospace !important;
    background-color: #090b0e !important;
    color: #dde1ea !important;
}
.stApp { background-color: #090b0e !important; }

#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem 2rem !important; max-width: 1400px !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid rgba(255,255,255,0.08) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 11px !important;
    letter-spacing: 1px !important;
    color: #5a6478 !important;
    background: transparent !important;
    border: none !important;
    padding: 8px 20px !important;
    border-bottom: 2px solid transparent !important;
}
.stTabs [aria-selected="true"] {
    color: #c084fc !important;
    border-bottom: 2px solid #a855f7 !important;
    text-shadow: 0 0 8px rgba(168,85,247,0.6) !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.2rem !important;
    background: transparent !important;
}

/* Inputs */
.stTextInput input, .stNumberInput input {
    font-family: 'Space Mono', monospace !important;
    font-size: 12px !important;
    background: #161a20 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 4px !important;
    color: #dde1ea !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #a855f7 !important;
    box-shadow: none !important;
}
.stTextInput label, .stSelectbox label, .stNumberInput label, .stTextArea label {
    font-family: 'Space Mono', monospace !important;
    font-size: 9px !important;
    letter-spacing: 1px !important;
    color: #3d4554 !important;
    text-transform: uppercase !important;
}

/* Selectbox */
div[data-baseweb="select"] > div {
    font-family: 'Space Mono', monospace !important;
    font-size: 11px !important;
    background: #161a20 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 4px !important;
    color: #dde1ea !important;
}
div[data-baseweb="select"] > div:focus-within {
    border-color: #a855f7 !important;
    box-shadow: none !important;
}
div[data-baseweb="popover"] {
    background: #161a20 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
}
li[role="option"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 11px !important;
    color: #dde1ea !important;
    background: #161a20 !important;
}
li[role="option"]:hover { background: rgba(168,85,247,0.08) !important; }

/* Buttons */
.stButton > button {
    font-family: 'Space Mono', monospace !important;
    font-size: 11px !important;
    letter-spacing: 0.5px !important;
    background: linear-gradient(135deg,#a855f7,#7c3aed) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 4px !important;
    padding: 6px 20px !important;
    font-weight: 700 !important;
}
.stButton > button:hover {
    opacity: 0.85 !important;
    border: none !important;
    color: #090b0e !important;
}

/* Radio */
.stRadio > div { gap: 6px !important; }
.stRadio label {
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
    color: #5a6478 !important;
    background: #161a20 !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 3px !important;
    padding: 3px 10px !important;
    cursor: pointer !important;
}
.stRadio label:has(input:checked) {
    color: #c084fc !important;
    border-color: rgba(168,85,247,0.5) !important;
    background: rgba(168,85,247,0.1) !important;
    box-shadow: 0 0 8px rgba(168,85,247,0.2) !important;
}

/* Progress */
.stProgress > div > div { background: linear-gradient(90deg,#7c3aed,#a855f7,#c084fc) !important; }

/* Text area */
.stTextArea textarea {
    font-family: 'Space Mono', monospace !important;
    font-size: 11px !important;
    background: #161a20 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #dde1ea !important;
}

/* Metric override */
[data-testid="stMetricValue"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 20px !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 9px !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    color: #3d4554 !important;
}
[data-testid="stMetricDelta"] {
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
}

/* Caption */
.stCaption {
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
    color: #3d4554 !important;
}

/* Divider */
hr { border-color: rgba(255,255,255,0.06) !important; }

/* Card containers */
.card {
    background: #161a20;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 5px;
    padding: 12px 14px;
    margin-bottom: 8px;
}
.section-lbl {
    font-size: 9px;
    color: #7c3aed;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 8px;
    font-family: 'Space Mono', monospace;
}
</style>
""", unsafe_allow_html=True)

# ─── REUSABLE HTML SNIPPETS (statik / non-dynamic) ──────────────────────────

def slabel(text):
    """Section label — pure static HTML ok"""
    st.markdown(f'<p class="section-lbl">{text}</p>', unsafe_allow_html=True)

def hspacer(px=8):
    st.markdown(f'<div style="margin-top:{px}px"></div>', unsafe_allow_html=True)

def colored_text(text, color):
    """Inline colored span — safe karena teks bukan dari user HTML"""
    return f'<span style="color:{color};font-family:Space Mono,monospace;font-size:12px">{text}</span>'

def render_metric_card(label, value, color="#dde1ea", sub=""):
    """Metric card pakai st.markdown dengan konten simple"""
    sub_part = f'<div style="font-size:9px;color:#5a6478;margin-top:2px">{sub}</div>' if sub else ""
    st.markdown(f"""
    <div class="card" style="text-align:left">
      <div style="font-size:9px;color:#3d4554;letter-spacing:1px;margin-bottom:4px;font-family:Space Mono,monospace">{label}</div>
      <div style="font-size:18px;font-weight:700;color:{color};font-family:Space Mono,monospace">{value}</div>
      {sub_part}
    </div>""", unsafe_allow_html=True)

def render_verdict_card(ticker, verdict, score, tp, sl, pivot, r1, s1, vol_ann):
    """Verdict card — semua nilai di-escape dulu"""
    v_colors = {"BUY": ("#22c55e","rgba(34,197,94,.12)","rgba(34,197,94,.3)"),
                "HOLD": ("#8b5cf6","rgba(139,92,246,.1)","rgba(139,92,246,.25)"),
                "WAIT": ("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
    vc, vbg, vborder = v_colors.get(verdict, ("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
    sc_color = "#22c55e" if score>=65 else "#8b5cf6" if score>=45 else "#ef4444"

    def srow(lbl, val, c="#dde1ea"):
        return f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-family:Space Mono,monospace"><span style="font-size:9px;color:#3d4554;letter-spacing:.5px">{lbl}</span><span style="font-size:12px;color:{c}">{val}</span></div>'

    pivot_str = str(int(pivot)) if pivot else "N/A"
    r1s1_str  = f"{int(r1)} / {int(s1)}" if r1 and s1 else "N/A"
    vol_str   = f"{vol_ann}%" if vol_ann else "N/A"

    st.markdown(f"""
    <div class="card">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
        <div style="width:52px;height:52px;border-radius:50%;border:2px solid {sc_color};display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:{sc_color};flex-shrink:0;font-family:Space Mono,monospace">{int(score)}</div>
        <div>
          <div style="font-size:13px;font-weight:700;color:{sc_color};font-family:Space Mono,monospace">{ticker}</div>
          <div style="margin-top:4px"><span style="font-size:10px;font-weight:700;padding:2px 9px;border-radius:3px;background:{vbg};color:{vc};border:1px solid {vborder};letter-spacing:.5px;font-family:Space Mono,monospace">{verdict}</span></div>
          <div style="font-size:9px;color:#5a6478;margin-top:4px;font-family:Space Mono,monospace">score {score}/100</div>
        </div>
      </div>
      {srow("TP TARGET", f"+{tp}%", "#22c55e")}
      {srow("STOP LOSS", f"-{sl}%", "#ef4444")}
      {srow("PIVOT", pivot_str)}
      {srow("R1 / S1", r1s1_str)}
      {srow("VOL ANN", vol_str)}
    </div>""", unsafe_allow_html=True)

def render_meter(label, value, color="#5b8df8"):
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;font-family:Space Mono,monospace">
      <span style="font-size:10px;color:#5a6478;width:90px;flex-shrink:0">{label}</span>
      <div style="flex:1;height:3px;background:#1c2028;border-radius:2px">
        <div style="width:{value}%;height:3px;background:{color};border-radius:2px"></div>
      </div>
      <span style="font-size:10px;color:#dde1ea;width:28px;text-align:right">{value}</span>
    </div>""", unsafe_allow_html=True)

def render_signal_line(label, value, color="#dde1ea"):
    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-family:Space Mono,monospace">
      <span style="font-size:9px;color:#3d4554;letter-spacing:.5px">{label}</span>
      <span style="font-size:12px;color:{color};font-weight:500">{value}</span>
    </div>""", unsafe_allow_html=True)

def render_badge(text, kind="momentum"):
    cfg = {
        "bagger":   ("#00d4aa","rgba(0,212,170,.1)","rgba(0,212,170,.25)"),
        "momentum": ("#5b8df8","rgba(91,141,248,.12)","rgba(91,141,248,.25)"),
        "scalp":    ("#a855f7","rgba(168,85,247,.1)","rgba(168,85,247,.25)"),
        "risk":     ("#e05c5c","rgba(224,92,92,.1)","rgba(224,92,92,.25)"),
    }.get(kind, ("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
    return f'<span style="font-size:9px;padding:2px 7px;border-radius:3px;background:{cfg[1]};color:{cfg[0]};border:1px solid {cfg[2]};letter-spacing:.5px;margin:2px;font-family:Space Mono,monospace;display:inline-block">{text}</span>'

def render_chat_bubble(role, text):
    if role == "user":
        st.markdown(f"""
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px;margin-bottom:10px">
          <div style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">KAMU</div>
          <div style="max-width:85%;padding:8px 12px;border-radius:8px 8px 2px 8px;background:rgba(168,85,247,.1);border:1px solid rgba(168,85,247,.2);font-size:12px;line-height:1.6;color:#dde1ea;font-family:Space Mono,monospace">{text}</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:10px">
          <div style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">IDX QUANT BOT</div>
          <div style="max-width:85%;padding:8px 12px;border-radius:8px 8px 8px 2px;background:#161a20;border:1px solid rgba(255,255,255,.07);font-size:12px;line-height:1.6;color:#dde1ea;font-family:Space Mono,monospace">{text}</div>
        </div>""", unsafe_allow_html=True)

# ─── HEADER ──────────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex;align-items:center;gap:12px;padding-bottom:14px;border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:20px">
  <div style="width:36px;height:36px;border-radius:6px;background:linear-gradient(135deg,#a855f7,#7c3aed);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;flex-shrink:0">⚡</div>
  <div>
    <div style="font-size:15px;font-weight:700;letter-spacing:.5px;color:#dde1ea;font-family:Space Mono,monospace">IDX QUANT BOT</div>
    <div style="font-size:10px;color:#5a6478;margin-top:1px;font-family:Space Mono,monospace">Powered by 151 Trading Strategies (Kakushadze & Serur, 2018)</div>
  </div>
  <div style="margin-left:auto;font-size:9px;background:linear-gradient(135deg,rgba(168,85,247,.15),rgba(124,58,237,.15));color:#c084fc;border:1px solid rgba(168,85,247,.4);padding:4px 10px;border-radius:3px;letter-spacing:1.5px;font-family:Space Mono,monospace;box-shadow:0 0 8px rgba(168,85,247,.2)">CLAUDE AI</div>
</div>
""", unsafe_allow_html=True)

# ─── STRATEGY ENGINE ─────────────────────────────────────────────────────────

def calc_ema(prices, n):
    if len(prices) < n: return None
    k = 2 / (n + 1); ema = prices[-n]
    for p in prices[-n+1:]: ema = p * k + ema * (1 - k)
    return round(ema, 2)

def calc_sma(prices, n):
    if len(prices) < n: return None
    return round(sum(prices[-n:]) / n, 2)

def calc_rsi(prices, n=14):
    if len(prices) < n + 1: return None
    deltas = [prices[i+1]-prices[i] for i in range(len(prices)-1)]
    gains = [d for d in deltas[-n:] if d > 0]
    losses = [-d for d in deltas[-n:] if d < 0]
    ag = sum(gains)/n if gains else 0
    al = sum(losses)/n if losses else 1e-9
    return round(100 - 100/(1 + ag/al), 1)

def calc_momentum_score(prices):
    n = len(prices); score = 50; signals = []
    if n >= 20:
        r = (prices[-1]-prices[-20])/prices[-20]*100
        score += 15 if r > 5 else -15 if r < -5 else 0
        signals.append(f"1M return: {r:+.1f}%")
    if n >= 60:
        r = (prices[-1]-prices[-60])/prices[-60]*100
        score += 12 if r > 10 else -12 if r < -10 else 0
        signals.append(f"3M return: {r:+.1f}%")
    if n >= 120:
        r = (prices[-1]-prices[-120])/prices[-120]*100
        score += 10 if r > 20 else -10 if r < -15 else 0
        signals.append(f"6M return: {r:+.1f}%")
    return {"score": min(100, max(0, score)), "signals": signals}

def calc_ma_signal(prices):
    e5=calc_ema(prices,5); e13=calc_ema(prices,13); e34=calc_ema(prices,34)
    s20=calc_sma(prices,20); s50=calc_sma(prices,50)
    score=50; signals=[]; label="MIXED"
    if e5 and e13:
        if e5>e13: score+=15; signals.append("EMA5 > EMA13 ✓")
        else: score-=15; signals.append("EMA5 < EMA13 ✗")
    if e13 and e34:
        if e13>e34: score+=12; signals.append("EMA13 > EMA34 ✓")
        else: score-=12; signals.append("EMA13 < EMA34 ✗")
    if s20 and s50:
        if s20>s50: score+=8; signals.append("SMA20 > SMA50 ✓")
        else: score-=8; signals.append("SMA20 < SMA50 ✗")
    if e5 and e13 and e34:
        if e5>e13>e34: label="BULLISH"
        elif e5<e13<e34: label="BEARISH"
    return {"score":min(100,max(0,score)),"label":label,
            "ema5":e5,"ema13":e13,"ema34":e34,"sma20":s20,"sma50":s50,"signals":signals}

def calc_pivot(high, low, close):
    if not (high and low and close): return {}
    ph=max(high[-5:]); pl=min(low[-5:]); pc=close[-1]
    if ph==pl: return {}
    pivot=(ph+pl+pc)/3; r1=2*pivot-pl; s1=2*pivot-ph
    cur=close[-1]
    return {"pivot":round(pivot),"r1":round(r1),"s1":round(s1),
            "above":cur>pivot,
            "dist_r1":round((r1-cur)/cur*100,2) if cur else 0,
            "dist_s1":round((cur-s1)/cur*100,2) if cur else 0}

def calc_volatility(prices, n=20):
    if len(prices)<n+1: return None
    rets=[(prices[i+1]-prices[i])/prices[i] for i in range(len(prices)-n-1,len(prices)-1)]
    mean=sum(rets)/len(rets)
    var=sum((r-mean)**2 for r in rets)/(len(rets)-1)
    return round(math.sqrt(var)*math.sqrt(252)*100,1)

def calc_volume_signal(volumes, n=20):
    if len(volumes)<n: return {"label":"N/A","ratio":None}
    avg=sum(volumes[-n:])/n
    if avg==0: return {"label":"NO DATA","ratio":None}
    cur=volumes[-1]; ratio=round(cur/avg,2)
    label="SPIKE ⚡" if ratio>=2 else "ABOVE AVG" if ratio>=1.3 else "VERY LOW" if ratio<=0.5 else "NORMAL"
    return {"label":label,"ratio":ratio}

def calc_bagger(momentum, ma, vol_ann, prices):
    score=0; signals=[]
    score+=momentum["score"]/100*40
    if momentum["score"]>=60: signals.append("✓ Price momentum kuat (Strategy 3.1)")
    score+=ma["score"]/100*25
    if ma["label"]=="BULLISH": signals.append("✓ Full MA stack bullish (3.12/3.13)")
    if vol_ann:
        if 25<=vol_ann<=70: score+=20; signals.append(f"✓ Vol {vol_ann}% — sweet spot bagger")
        elif vol_ann<25: score+=10
        else: score+=5
    n=len(prices)
    if n>=60:
        h=max(prices[-min(252,n):]); l=min(prices[-min(252,n):]); cur=prices[-1]
        rng=h-l
        if rng>0:
            pct=(cur-l)/rng*100
            if pct<35: score+=15; signals.append(f"✓ Near 52W low — akumulasi zone (3.3)")
            elif pct<55: score+=8
        else:
            signals.append("Harga flat — range terlalu sempit")
    return {"score":round(min(100,score),1),"signals":signals}

def calc_scalp(prices, volumes, pivot, rsi):
    score=50; signals=[]; tp=2.0; sl=1.5
    if rsi:
        if 30<=rsi<=40: score+=20; signals.append(f"RSI {rsi} — oversold recovery ✓")
        elif 60<=rsi<=70: score+=15; signals.append(f"RSI {rsi} — momentum bullish ✓")
        elif rsi<30: score+=10; signals.append(f"RSI {rsi} — extreme oversold, wait confirm")
        elif rsi>75: score-=15; signals.append(f"RSI {rsi} — overbought, high risk!")
    if pivot.get("dist_s1") is not None:
        d=pivot["dist_s1"]
        if 0<d<1.5: score+=20; sl=max(d+0.3,1.0); signals.append(f"Harga {d:.1f}% di atas S1 ✓")
    if len(volumes)>=5:
        avg_v=sum(volumes[-5:])
        if avg_v>0:
            avg_v/=5
            if avg_v>5_000_000: score+=15; signals.append("Volume likuid ✓")
            elif avg_v>1_000_000: score+=5; signals.append("Volume cukup")
            else: score-=20; signals.append("Volume rendah — slippage risk!")
        else: signals.append("Volume data kosong")
    if len(prices)>=5:
        ranges=[abs(prices[-i]-prices[-i-1])/prices[-i-1]*100
                for i in range(1,min(5,len(prices))) if prices[-i-1]!=0]
        if ranges:
            avg_r=sum(ranges)/len(ranges)
            if 1<=avg_r<=4: score+=10; signals.append(f"Daily range {avg_r:.1f}% — scalp-able ✓")
    return {"score":min(100,max(0,score)),"signals":signals,"tp":round(tp,1),"sl":round(sl,1)}

def analyze(ticker, prices, volumes, highs, lows, mode="deep"):
    if len(prices)<5: return {"ticker":ticker,"error":"data kurang"}
    mom=calc_momentum_score(prices)
    ma=calc_ma_signal(prices)
    vol_ann=calc_volatility(prices)
    vol_sig=calc_volume_signal(volumes)
    pivot=calc_pivot(highs,lows,prices)
    rsi=calc_rsi(prices)
    bag=calc_bagger(mom,ma,vol_ann,prices)
    scl=calc_scalp(prices,volumes,pivot,rsi)
    comp=round(mom["score"]*0.35+ma["score"]*0.30+bag["score"]*0.20+scl["score"]*0.15,1)
    verdict="BUY" if comp>=65 else "HOLD" if comp>=45 else "WAIT"
    active=[]
    if mom["score"]>=60: active.append(("3.1 Price-Momentum","bagger"))
    if ma["label"]=="BULLISH": active.append(("3.12/3.13 MA Stack","momentum"))
    if pivot.get("above"): active.append(("3.14 Above Pivot","scalp"))
    if rsi and 30<=rsi<=45: active.append(("RSI Oversold","scalp"))
    if vol_sig["ratio"] and vol_sig["ratio"]>=1.5: active.append(("3.19 Vol Spike","momentum"))
    if bag["score"]>=65: active.append(("3.7 Bagger","bagger"))
    chg=round((prices[-1]-prices[-2])/prices[-2]*100,2) if len(prices)>=2 else 0
    return {
        "ticker":ticker,"price":round(prices[-1]),"chg":chg,
        "score":comp,"verdict":verdict,
        "momentum_score":mom["score"],"ma_label":ma["label"],
        "bagger_score":bag["score"],"scalp_score":scl["score"],
        "rsi":rsi,"vol_label":vol_sig["label"],"vol_ratio":vol_sig["ratio"],
        "vol_ann":vol_ann,
        "ema5":ma["ema5"],"ema13":ma["ema13"],"ema34":ma["ema34"],
        "sma20":ma["sma20"],"sma50":ma["sma50"],
        "pivot":pivot.get("pivot"),"r1":pivot.get("r1"),"s1":pivot.get("s1"),
        "tp":scl["tp"],"sl":scl["sl"],
        "active_strategies":active,
        "momentum_signals":mom["signals"],
        "ma_signals":ma["signals"],
        "bagger_signals":bag["signals"],
        "scalp_signals":scl["signals"],
        "error":None,
    }

# ─── FETCH DATA ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def fetch_one(ticker, period="6mo"):
    try:
        import yfinance as yf
        t = yf.Ticker(ticker+".JK")
        df = t.history(period=period, auto_adjust=True)
        if df.empty or len(df)<5: return None
        return {
            "close":  df["Close"].tolist(),
            "volume": df["Volume"].tolist(),
            "high":   df["High"].tolist(),
            "low":    df["Low"].tolist(),
        }
    except Exception:
        return None

# ─── TELEGRAM NOTIF ──────────────────────────────────────────────────────────

def tg_send(message: str, bot_token: str, chat_id: str) -> bool:
    """Send plain Telegram message"""
    import urllib.request, urllib.parse, json as _j
    if not bot_token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = _j.dumps({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return _j.loads(r.read()).get("ok", False)
    except Exception:
        return False

def tg_build_scan_summary(results: list, mode: str, elapsed: float) -> str:
    """Build formatted Telegram scan summary message"""
    ok    = [r for r in results if not r.get("error")]
    err   = [r for r in results if r.get("error")]
    buys  = sorted([r for r in ok if r["verdict"]=="BUY"],  key=lambda x:-x["score"])
    holds = sorted([r for r in ok if r["verdict"]=="HOLD"], key=lambda x:-x["score"])
    waits = sorted([r for r in ok if r["verdict"]=="WAIT"], key=lambda x:-x["score"])
    baggers = [r for r in ok if r["bagger_score"]>=65]
    scalps  = [r for r in ok if r["scalp_score"]>=60]
    now = datetime.now().strftime("%d %b %Y %H:%M WIB")

    lines = []
    lines.append(f"⚡ <b>IDX QUANT BOT — SCAN SELESAI</b>")
    lines.append(f"📅 {now}  |  Mode: {mode.upper()}")
    lines.append(f"⏱ Elapsed: {elapsed:.0f}s  |  Total: {len(ok)} ticker")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    # BUY signals
    if buys:
        lines.append(f"\n✅ <b>BUY SIGNAL ({len(buys)})</b>")
        for r in buys[:8]:  # max 8 supaya gak kepanjangan
            bag_tag  = " 🌟" if r["bagger_score"]>=65 else ""
            scl_tag  = " ⚡" if r["scalp_score"]>=60 else ""
            strats   = ", ".join([s[0] for s in r["active_strategies"][:2]]) or "—"
            chg_str  = f"+{r['chg']:.1f}%" if r["chg"]>=0 else f"{r['chg']:.1f}%"
            lines.append(
                f"\n🟢 <b>{r['ticker']}</b>{bag_tag}{scl_tag}  <code>Score: {r['score']}/100</code>\n"
                f"   💰 Harga: Rp {r['price']:,}  ({chg_str})\n"
                f"   📊 Mom: {r['momentum_score']} | Bag: {r['bagger_score']} | Scalp: {r['scalp_score']}\n"
                f"   🎯 TP: +{r['tp']}%  🛑 SL: -{r['sl']}%  |  RSI: {r['rsi'] or '—'}\n"
                f"   📌 {strats}"
            )
        if len(buys)>8:
            lines.append(f"   <i>...dan {len(buys)-8} ticker BUY lainnya</i>")
    else:
        lines.append("\n⬜ Tidak ada BUY signal saat ini")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")

    # Bagger candidates
    if baggers:
        lines.append(f"\n🌟 <b>BAGGER CANDIDATES ({len(baggers)})</b>")
        for r in sorted(baggers, key=lambda x:-x["bagger_score"])[:5]:
            lines.append(
                f"   ★ <b>{r['ticker']}</b>  Bagger: <code>{r['bagger_score']}/100</code>  |  {r['verdict']}\n"
                f"     TP: +{r['tp']}%  |  RSI: {r['rsi'] or '—'}  |  Vol: {r['vol_label']}"
            )

    # Scalp ready
    if scalps:
        lines.append(f"\n⚡ <b>SCALP READY ({len(scalps)})</b>")
        for r in sorted(scalps, key=lambda x:-x["scalp_score"])[:5]:
            chg_str = f"+{r['chg']:.1f}%" if r["chg"]>=0 else f"{r['chg']:.1f}%"
            lines.append(
                f"   ⚡ <b>{r['ticker']}</b>  Scalp: <code>{r['scalp_score']}/100</code>  ({chg_str})\n"
                f"     Entry: Rp {r['price']:,}  |  TP: +{r['tp']}%  |  SL: -{r['sl']}%"
            )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")

    # HOLD (ringkas)
    if holds:
        hold_str = "  ".join([f"<code>{r['ticker']}</code>" for r in holds[:10]])
        lines.append(f"\n🟡 <b>HOLD ({len(holds)})</b>: {hold_str}")

    # WAIT (ringkas)
    if waits:
        wait_str = "  ".join([f"<code>{r['ticker']}</code>" for r in waits[:10]])
        lines.append(f"🔴 <b>WAIT ({len(waits)})</b>: {wait_str}")

    # Error (ringkas)
    if err:
        err_str = ", ".join([r["ticker"] for r in err[:5]])
        lines.append(f"\n⚠️ <i>Gagal fetch: {err_str}{'...' if len(err)>5 else ''}</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<i>IDX Quant Bot • 151 Trading Strategies Framework</i>")
    lines.append(f"<i>Bukan rekomendasi investasi. DYOR. Manage your risk.</i>")

    return "\n".join(lines)

def tg_build_single_alert(r: dict, alert_type: str = "buy") -> str:
    """Build single ticker alert — untuk notif real-time per ticker"""
    emoji  = {"buy":"🟢","bagger":"🌟","scalp":"⚡","wait":"🔴"}.get(alert_type,"📢")
    title  = {"buy":"BUY SIGNAL","bagger":"BAGGER DETECTED","scalp":"SCALP SETUP","wait":"WAIT/AVOID"}.get(alert_type,"ALERT")
    strats = ", ".join([s[0] for s in r["active_strategies"]]) or "—"
    chg_str= f"+{r['chg']:.2f}%" if r["chg"]>=0 else f"{r['chg']:.2f}%"
    now    = datetime.now().strftime("%d %b %Y %H:%M WIB")
    return (
        f"{emoji} <b>{r['ticker']} — {title}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📅 {now}\n"
        f"💰 Harga : Rp {r['price']:,}  ({chg_str})\n"
        f"📊 Score : <code>{r['score']}/100</code>  |  {r['verdict']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 Momentum : {r['momentum_score']}/100  ({r['ma_label']})\n"
        f"🌟 Bagger   : {r['bagger_score']}/100{'  ★ CANDIDATE' if r['bagger_score']>=65 else ''}\n"
        f"⚡ Scalp    : {r['scalp_score']}/100{'  ⚡ READY' if r['scalp_score']>=60 else ''}\n"
        f"🔢 RSI      : {r['rsi'] or '—'}\n"
        f"📦 Volume   : {r['vol_label']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 TP  : +{r['tp']}%\n"
        f"🛑 SL  : -{r['sl']}%\n"
        f"📌 Pivot : {r['pivot'] or '—'}  |  R1: {r['r1'] or '—'}  |  S1: {r['s1'] or '—'}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔧 Strategies:\n{strats}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>IDX Quant Bot • DYOR. Bukan rekomendasi investasi.</i>"
    )

# ─── SESSION STATE ────────────────────────────────────────────────────────────

if "scan_results"  not in st.session_state: st.session_state.scan_results=[]
if "ana_results"   not in st.session_state: st.session_state.ana_results=[]
if "bag_results"   not in st.session_state: st.session_state.bag_results=[]
if "scl_results"   not in st.session_state: st.session_state.scl_results=[]

PRESETS={
    "Watchlist Gw":   ["ACES","ACRO","ACST","ADHI","ADMF","ADMG","AEGS","AGII","AHAP","AKKU","AKPI","AKSI","ALDO","ALKA","ALMI","ALTO","AMAG","AMAN","AMFG","AMIN","AMMS","AMOR","AMRT","ANTM","APIC","APII","APLI","ARCI","AREA","ARGO","ARKA","ARKO","ARMY","ARNA","ARTA","ARTO","ASBI","ASDM","ASGR","ASHA","ASII","ASJT","ASLI","ASLC","ASMI","ASPI","ASPR","ASRM","ASSA","ATAP","ATIC","AUTO","AVIA","AWAN","AXIO","AYLS","BABA","BAIK","BAJA","BATA","BAUT","BAYU","BBLD","BBRM","BBSS","BCAP","BDKR","BEBS","BELI","BELL","BFIN","BHAT","BHIT","BIAS","BIKA","BIKE","BIMA","BINO","BIRD","BISI","BIWA","BLES","BLOG","BLTA","BLTZ","BLUE","BMBL","BMHS","BMSR","BMTR","BOAT","BOLT","BPFI","BPII","BPTR","BRAM","BREN","BRMS","BRNA","BRPT","BRRC","BTEK","BTON","BUDI","BUKA","BUKK","CAKK","CARS","CASA","CASH","CASS","CBDK","CBPE","CBMF","CCSI","CDIA","CFIN","CHEK","CHEM","CHIP","CINT","CITA","CLAY","CLPI","CMNP","CMNT","CMPP","CNMA","CNTX","COIN","CPRI","CRSN","CSAP","CSIS","CSMI","CSRA","CTBN","CTTH","CYBR","DAAZ","DATA","DAYA","DCII","DEAL","DEFI","DEPO","DFAM","DGNS","DGWG","DGIK","DIGI","DIVA","DKFT","DKHH","DMMX","DOOH","DOSS","DPNS","DPUM","DRMA","DVLA","DYAN","EAST","ECII","EDGE","EKAD","ELIT","ERAL","ERAA","ERTX","ESIP","ESSA","ESTA","ESTI","ETWA","EURO","FAST","FASW","FILM","FIMP","FITT","FLMC","FOLK","FORE","FORU","FPNI","FUJI","FUTR","GAMA","GDST","GDYR","GEMA","GGRP","GIAA","GJTL","GLOB","GLVA","GMFI","GOLF","GOLD","GOTO","GRPH","GRII","GSMF","HADE","HALO","HBAT","HDFA","HDIT","HEAL","HELI","HERO","HEXA","HGII","HKMU","HOMI","HOPE","HRTA","IBFN","IBOS","ICON","IDEA","IDPR","IFII","IFSH","IGAR","IIKP","IKAI","IKBI","IMAS","IMJS","IMPC","INAF","INAI","INCF","INCI","INCO","INDO","INDR","INDS","INDX","INET","INKP","INOV","INPP","INPS","INRU","INTA","INTD","INTP","IPAC","IPCC","IPCM","IPOL","IPPE","IPTV","IRRA","IRSX","ISEA","ISSP","ITIC","JAAS","JAST","JATI","JAYA","JECC","JGLE","JKON","JMAS","JSKY","JSMR","JTPE","KAEF","KAQI","KARW","KARY","KAST","KAYU","KBLI","KBLM","KBRI","KDSI","KDTN","KEEN","KETR","KIAS","KICI","KING","KIOS","KJEN","KKES","KLAS","KLBF","KLIN","KOBX","KOIN","KOKA","KONI","KRAH","KRAS","KREN","KSIX","KUAS","LABA","LABS","LAJU","LAND","LAPD","LIFE","LION","LIVE","LMAS","LMPI","LMSH","LOPI","LPGI","LPIN","LPLI","LPPF","LPPS","LRNA","LTLS","LUCK","LUCY","MAAS","MABA","MADA","MAPA","MAPI","MARI","MARK","MASA","MBMA","MCAS","MDIA","MDKA","MDKI","MDRN","MEDS","MEJA","MENN","MERI","MERK","META","MFMI","MGNA","MHKI","MICE","MIDI","MIKA","MINA","MINE","MIRA","MITI","MLIA","MLPL","MLPT","MMIX","MNCN","MOLI","MPOW","MPMX","MPPA","MPXL","MREI","MSIE","MSIN","MSJA","MSKY","MSTI","MTDL","MTFN","MTMH","MTPS","MTRA","MTRN","MTWI","MUTU","MYTX","NAIK","NANO","NASA","NATO","NCKL","NELY","NEST","NETV","NICE","NICK","NICL","NIKL","NINE","NPGF","NRCA","NZIA","OBAT","OBMD","OCAP","OLIV","OMED","OPMS","PACK","PADA","PANS","PART","PBSA","PBRX","PCAR","PDES","PEGE","PEHA","PELI","PENT","PERW","PEVE","PGLI","PICO","PIPA","PJAA","PJHB","PLAN","PLAS","PMJS","PMUI","PNLF","PNSE","POLA","POLI","POLU","POLY","PORT","POSA","POWR","PPGL","PPRI","PPRE","PRAY","PRDA","PRIM","PSAB","PSAT","PSDN","PTDU","PTMP","PTMR","PTPP","PTPW","PTSN","PURA","PURE","PYFA","PZZA","RAAM","RALS","RANC","RCCC","RELI","RICY","RLCO","ROCK","ROLI","RONY","RSCH","RSGK","RUNS","SAFE","SAGI","SAME","SANO","SAPX","SATU","SBAT","SBMA","SCCO","SCMA","SCNP","SCPI","SDMU","SDPC","SDRA","SFAN","SGGH","SGJL","SILO","SIPD","SKYB","SLIS","SMGA","SMGR","SMKM","SMKL","SMLE","SMMA","SMSM","SNLK","SOFA","SOHO","SOLA","SOSS","SOTS","SOUL","SPMA","SPRE","SPTO","SQMI","SRAJ","SRIL","SRSN","SRTG","SSTM","SUGI","SULI","SWAT","SWID","SYAI","TALF","TAMA","TAXI","TBMS","TCID","TDPM","TECH","TELE","TFAS","TFCO","TGKA","TGRA","TIFA","TINS","TIRA","TIRT","TKIM","TMAS","TMPO","TNCA","TOOL","TOPS","TOSK","TOTL","TOTO","TOYS","TPAI","TPIA","TRIL","TRIM","TRIO","TRIS","TRJA","TRON","TRST","TRUK","TRUS","TSPC","TUGU","TULT","TYRE","UANG","UCID","UFOE","UNIC","UNIT","UNTR","UVCR","VATE","VERN","VINS","VISA","VISI","VIVA","VKTR","VOKS","VOSS","VRNA","VTNY","WAPO","WBSA","WEGE","WEHA","WGSH","WICO","WIDI","WIFI","WIIM","WIKA","WIRG","WITA","WOMF","WOOD","WPOW","WSKT","WTON","YELO","YOII","YPAS","YULE","ZATA","ZBRA","ZENI","ZINC","ZONE","ZYRX","KOTA","ASSA","BKSL","HRUM","WINS","LCKM","BBCA","BBRI","TLKM","ASII","BMRI","UNVR","ICBP","KLBF","EXCL","TOWR"],
    "LQ45 Top 10":    ["BBCA","BBRI","TLKM","ASII","BMRI","UNVR","ICBP","KLBF","EXCL","TOWR"],
    "Big 4 Banks":    ["BBCA","BBRI","BMRI","BNGA"],
    "Gorengan Hot":   ["TOOL","KOTA","ARCI","ASSA","BKSL","SMKL","HRUM","WINS","LCKM","AWAN"],
    "Sektor Leaders": ["BBCA","TLKM","ADRO","ASII","UNVR","WIKA","CPIN","SMGR","INDF","MNCN"],
    "Sektor Bank":    ["AGRO","AGRS","AMAR","BABP","BACA","BANK","BBCA","BBHI","BBKP","BBMD","BBNI","BBRI","BBTN","BBYB","BCIC","BDMN","BEKS","BGTG","BINA","BJBR","BJTM","BMAS","BMRI","BNBA","BNGA","BNII","BNLI","BRIS","BSIM","BSWD","BTPN","BTPS","BVIC","DNAR","INPC","MASB","MAYA","MCOR","MEGA","NISP","NOBU","NTBK","PNBN","PNBS"],    
    "Sektor Energi":  ["AADI","ABMM","ADMR","ADRO","AIMS","AKRA","ALII","APEX","ARII","ARTI","ATLA","BBRM","BESS","BIPI","BOSS","BSML","BSSR","BULL","BUMI","BYAN","CANI","CBRE","CGAS","CNKO","COAL","CUAN","DEWA","DOID","DSSA","DWGL","ELPI","ELSA","ENRG","FIRE","GEMS","GTBO","GTSI","HAIS","HILL","HITS","HRUM","HUMI","IATA","INDY","ITMA","ITMG","JARR","KKGI","KOPI","LEAD","MAHA","MBAP","MBSS","MCOL","MEDC","MKAP","MYOH","PGAS","PGEO","PKPK","PSSI","PTBA","PTIS","PTRO","RAJA","RGAS","RIGS","RMKE","RMKO","RUIS","SEMA","SGER","SHIP","SICO","SMMT","SMRU","SOCI","SUGI","SUNI","SURE","TAMU","TCPI","TEBE","TOBA","TPMA","TRAM","UNIQ","WINS","WOWS"],
    "Sektor Properti":["ADCP","APLN","ASRI","BAPA","BAPI","BCIP","BEST","BIPP","BKDP","BKSL","BKSW","BSBK","BSDE","BUVA","CITY","COWL","CTRA","DADA","DART","DILD","DMAS","DUTI","EMDE","EMTK","GMTD","GPRA","GRIA","GWSA","HOME","HOTL","HRME","JIHD","JRPT","JSPT","KBAG","KIJA","KPIG","LAND","LCGP","LPCK","LPKR","MDLA","MDLN","MKPI","MMLP","MPRO","MTLA","MTSM","NIRO","NUSA","OMRE","PADI","PAMG","PANI","PANR","PLIN","POLL","POOL","PPRO","PUDP","PURI","PWON","RATU","RBMS","RDTX","REAL","RELF","REPP","RIMO","RISE","RODA","SAGE","SAMR","SHID","SIER","SIMA","SINI","SMDM","SMRA","SONA","SREI","SSIA","STAR","STRK","TARA","TRIN","TRUE","URBN","VAST","VICO","WINR","WSBP"],
    "Sektor Konsumer":["AALI","ADES","AGAR","AISA","ANDI","ANJT","AYAM","BABY","BATR","BEEF","BEER","BOBA","BOGA","BUAH","BWPT","CAMP","CBUT","CEKA","CLEO","CMRY","COCO","CPIN","CPRO","CRAB","DEWI","DLTA","DMND","DSFI","DSNG","DUCK","ENAK","ENZO","FAPA","FISH","FOOD","FWCT","GGRM","GOOD","GOLL","GPSO","GRPM","GULA","GUNA","GZCO","HAMP","HATM","HMSP","HOKI","ICBP","IKAN","IKPM","INDF","IOTF","ISAP","JAVA","JPFA","KEJU","KINO","KMDS","KOCI","LFLO","LSIP","MAGP","MAIN","MAPB","MBTO","MGRO","MLBI","MRAT","MYOR","NASI","NAYZ","NPGF","NSSS","OILS","PALM","PBID","PDPP","PGUN","PMMP","PNGO","PSGO","PTPS","PTSP","RAFI","RMBA","ROTI","SAMF","SAMP","SGRO","SIDO","SIMP","SKBM","SKLT","SMAR","SSMS","STAA","STTP","SUPA","TAPG","TAYS","TBLA","TGUK","TLDN","TRGU","UDNG","ULTJ","UNSP","UNVR","VCOK","VICI","WINE","WMPP","WMUU","WONS","YUPI"],
    "Sektor Telko":   ["BALI","BTEL","CENT","EXCL","GHON","IBST","ISAT","JAST","KBLV","LINK","LCKM","MORA","MTEL","OASA","SUPR","TBIG","TLKM","TOWR"],
}

ALL_IDX_TICKERS = [
    "AADI","AALI","ABBA","ABDA","ABMM","ACES","ACRO","ACST","ADCP","ADES",
    "ADHI","ADMF","ADMG","ADMR","ADRO","AEGS","AGAR","AGII","AGRO","AGRS",
    "AHAP","AIMS","AISA","AKKU","AKPI","AKRA","AKSI","ALDO","ALII","ALKA",
    "ALMI","ALTO","AMAG","AMAN","AMAR","AMFG","AMIN","AMMN","AMMS","AMOR",
    "AMRT","ANDI","ANJT","ANTM","APEX","APIC","APII","APLI","APLN","ARCI",
    "AREA","ARGO","ARII","ARKA","ARKO","ARMY","ARNA","ARTA","ARTI","ARTO",
    "ASBI","ASDM","ASGR","ASHA","ASII","ASJT","ASLI","ASLC","ASMI","ASPI",
    "ASPR","ASRI","ASRM","ASSA","ATAP","ATIC","ATLA","AUTO","AVIA","AWAN",
    "AXIO","AYAM","AYLS","BABA","BABP","BABY","BACA","BAIK","BAJA","BALI",
    "BANK","BAPA","BAPI","BATA","BATR","BAUT","BAYU","BBCA","BBHI","BBKP",
    "BBLD","BBMD","BBNI","BBRI","BBRM","BBSI","BBSS","BBTN","BBYB","BCAP",
    "BCIC","BCIP","BDKR","BDMN","BEBS","BEEF","BEER","BEKS","BELI","BELL",
    "BESS","BEST","BFIN","BGTG","BHAT","BHIT","BIAS","BIKA","BIKE","BIMA",
    "BINA","BINO","BIPI","BIPP","BIRD","BISI","BIWA","BJBR","BJTM","BKDP",
    "BKSL","BKSW","BLES","BLOG","BLTA","BLTZ","BLUE","BMAS","BMBL","BMHS",
    "BMRI","BMSR","BMTR","BNBA","BNBR","BNGA","BNII","BNLI","BOAT","BOBA",
    "BOGA","BOLA","BOLT","BOSS","BPFI","BPII","BPTR","BRAM","BREN","BRIS",
    "BRMS","BRNA","BRPT","BRRC","BSBK","BSDE","BSIM","BSML","BSSR","BSWD",
    "BTEK","BTEL","BTON","BTPN","BTPS","BUAH","BUDI","BUKA","BUKK","BULL",
    "BUMI","BUVA","BVIC","BWPT","BYAN","CAKK","CAMP","CANI","CARE","CARS",
    "CASA","CASH","CASS","CBDK","CBPE","CBRE","CBUT","CBMF","CCSI","CDIA",
    "CEKA","CENT","CFIN","CGAS","CHEK","CHEM","CHIP","CINT","CITA","CITY",
    "CLAY","CLEO","CLPI","CMNP","CMNT","CMPP","CMRY","CNKO","CNMA","CNTX",
    "COAL","COCO","COIN","COWL","CPIN","CPRI","CPRO","CRAB","CRSN","CSAP",
    "CSIS","CSMI","CSRA","CTBN","CTRA","CTTH","CUAN","CYBR","DAAZ","DADA",
    "DART","DATA","DAYA","DCII","DEAL","DEFI","DEPO","DEWA","DEWI","DFAM",
    "DGNS","DGWG","DGIK","DIGI","DILD","DIVA","DKFT","DKHH","DLTA","DMAS",
    "DMMX","DMND","DNAR","DNET","DOID","DOOH","DOSS","DPNS","DPUM","DRMA",
    "DSFI","DSNG","DSSA","DUCK","DUTI","DVLA","DWGL","DYAN","EAST","ECII",
    "EDGE","EKAD","ELIT","ELPI","ELSA","ELTY","EMAS","EMDE","EMTK","ENAK",
    "ENRG","ENVY","ENZO","EPAC","EPMT","ERAL","ERAA","ERTX","ESIP","ESSA",
    "ESTA","ESTI","ETWA","EURO","EXCL","FAPA","FAST","FASW","FILM","FIMP",
    "FIRE","FISH","FITT","FLMC","FOLK","FOOD","FORE","FORU","FPNI","FUJI",
    "FUTR","FWCT","GAMA","GDST","GDYR","GEMA","GEMS","GGRP","GGRM","GHON",
    "GIAA","GJTL","GLOB","GLVA","GMFI","GMTD","GOLF","GOLD","GOLL","GOOD",
    "GOTO","GPRA","GPSO","GRIA","GRPH","GRPM","GRII","GSMF","GTBO","GTRA",
    "GTSI","GULA","GUNA","GWSA","GZCO","HADE","HAIS","HAJJ","HALO","HATM",
    "HBAT","HDFA","HDIT","HEAL","HELI","HERO","HEXA","HGII","HILL","HITS",
    "HKMU","HMSP","HOKI","HOME","HOMI","HOPE","HOTL","HRME","HRTA","HRUM",
    "HUMI","HYGN","IATA","IBFN","IBOS","IBST","ICBP","ICON","IDEA","IDPR",
    "IFII","IFSH","IGAR","IIKP","IKAI","IKAN","IKBI","IKPM","IMAS","IMJS",
    "IMPC","INAF","INAI","INCF","INCI","INCO","INDF","INDO","INDR","INDS",
    "INDX","INDY","INET","INKP","INOV","INPC","INPP","INPS","INRU","INTA",
    "INTD","INTP","IOTF","IPAC","IPCC","IPCM","IPOL","IPPE","IPTV","IRRA",
    "IRSX","ISAP","ISAT","ISEA","ISSP","ITIC","ITMA","ITMG","JAAS","JARR",
    "JAST","JATI","JAVA","JAYA","JECC","JGLE","JIHD","JKON","JMAS","JPFA",
    "JRPT","JSKY","JSMR","JSPT","JTPE","KAEF","KAQI","KARW","KARY","KAST",
    "KAYU","KBAG","KBLI","KBLM","KBLV","KBRI","KDSI","KDTN","KEEN","KEJU",
    "KETR","KIAS","KICI","KIJA","KING","KINO","KIOS","KJEN","KKES","KKGI",
    "KLAS","KLBF","KLIN","KMDS","KMTR","KOBX","KOCI","KOIN","KOKA","KONI",
    "KOPI","KOTA","KPIG","KRAH","KRAS","KREN","KSIX","KUAS","LABA","LABS",
    "LAJU","LAND","LAPD","LCGP","LCKM","LEAD","LFLO","LIFE","LINK","LION",
    "LIVE","LMAS","LMPI","LMSH","LOPI","LPCK","LPGI","LPIN","LPKR","LPLI",
    "LPPF","LPPS","LRNA","LSIP","LTLS","LUCK","LUCY","MAAS","MABA","MADA",
    "MAGP","MAHA","MAIN","MANG","MAPA","MAPB","MAPI","MARI","MARK","MASA",
    "MASB","MAYA","MBAP","MBMA","MBSS","MBTO","MCAS","MCOL","MCOR","MDIA",
    "MDKA","MDKI","MDLA","MDLN","MDRN","MEDC","MEDS","MEGA","MEJA","MENN",
    "MERI","MERK","META","MFMI","MGNA","MGRO","MHKI","MICE","MIDI","MIKA",
    "MINA","MINE","MIRA","MITI","MKAP","MKPI","MKTR","MLBI","MLIA","MLPL",
    "MLPT","MMLP","MMIX","MNCN","MOLI","MORA","MPOW","MPMX","MPPA","MPRO",
    "MPXL","MRAT","MREI","MSIE","MSIN","MSJA","MSKY","MSTI","MTDL","MTEL",
    "MTFN","MTLA","MTMH","MTPS","MTRA","MTRN","MTSM","MTWI","MUTU","MYOH",
    "MYOR","MYTX","NAIK","NANO","NASA","NASI","NATO","NAYZ","NCKL","NELY",
    "NEST","NETV","NICE","NICK","NICL","NIKL","NINE","NIRO","NISP","NOBU",
    "NPGF","NRCA","NSSS","NTBK","NUSA","NZIA","OASA","OBAT","OBMD","OCAP",
    "OILS","OKAS","OLIV","OMED","OMRE","OPMS","PACK","PADA","PADI","PALM",
    "PAMG","PANI","PANR","PANS","PART","PBID","PBSA","PBRX","PCAR","PDES",
    "PDPP","PEGE","PEHA","PELI","PENT","PERW","PEVE","PGAS","PGEO","PGJO",
    "PGLI","PGUN","PICO","PIPA","PJAA","PJHB","PKPK","PLAN","PLAS","PLIN",
    "PMJS","PMMP","PMUI","PNBN","PNBS","PNGO","PNIN","PNLF","PNSE","POLA",
    "POLI","POLL","POLU","POLY","POOL","PORT","POSA","POWR","PPGL","PPRI",
    "PPRE","PPRO","PRAY","PRDA","PRIM","PSAB","PSAT","PSDN","PSGO","PSKT",
    "PSSI","PTBA","PTDU","PTIS","PTMP","PTMR","PTPP","PTPS","PTPW","PTRO",
    "PTSN","PTSP","PUDP","PURA","PURE","PURI","PWON","PYFA","PZZA","RAAM",
    "RAFI","RAJA","RALS","RANC","RATU","RBMS","RCCC","RDTX","REAL","RELF",
    "RELI","REPP","RGAS","RICY","RIGS","RIMO","RISE","RLCO","RMBA","RMKE",
    "RMKO","RMLP","ROCK","RODA","ROLI","RONY","ROTI","RSCH","RSGK","RUIS",
    "RUNS","SAFE","SAGE","SAGI","SAME","SAMF","SAMR","SAMP","SANO","SAPX",
    "SATU","SBAT","SBMA","SCCO","SCMA","SCNP","SCPI","SDMU","SDPC","SDRA",
    "SEMA","SFAN","SGER","SGGH","SGJL","SGRO","SHID","SHIP","SICO","SIDO",
    "SIER","SILO","SIMA","SIMP","SINI","SIPD","SKBM","SKLT","SKRN","SKYB",
    "SLIS","SMAR","SMDM","SMDR","SMGA","SMGR","SMKM","SMKL","SMLE","SMMA",
    "SMMT","SMRA","SMRU","SMSM","SNLK","SOCI","SOFA","SOHO","SOLA","SONA",
    "SOSS","SOTS","SOUL","SPMA","SPRE","SPTO","SQMI","SRAJ","SREI","SRIL",
    "SRSN","SRTG","SSIA","SSMS","SSTM","STAA","STAR","STRK","STTP","SUGI",
    "SULI","SUNI","SUPA","SUPR","SURE","SWAT","SWID","SYAI","TALF","TAMA",
    "TAMU","TAPG","TARA","TAXI","TAYS","TBIG","TBLA","TBMS","TCID","TCPI",
    "TDPM","TEBE","TECH","TELE","TFAS","TFCO","TGKA","TGRA","TGUK","TIFA",
    "TINS","TIRA","TIRT","TKIM","TLDN","TLKM","TMAS","TMPO","TNCA","TOBA",
    "TOOL","TOPS","TOSK","TOTL","TOTO","TOWR","TOYS","TPAI","TPIA","TPMA",
    "TRAM","TRGU","TRIL","TRIM","TRIN","TRIO","TRIS","TRJA","TRON","TRST",
    "TRUE","TRUK","TRUS","TSPC","TUGU","TULT","TYRE","UANG","UCID","UDNG",
    "UFOE","ULTJ","UNIC","UNIQ","UNIT","UNSP","UNTR","UNVR","URBN","UVCR",
    "VAST","VATE","VCOK","VERN","VICI","VICO","VINS","VISA","VISI","VIVA",
    "VKTR","VOKS","VOSS","VRNA","VTNY","WAPO","WBSA","WEGE","WEHA","WGSH",
    "WICO","WIDI","WIFI","WIIM","WIKA","WINE","WINR","WINS","WIRG","WITA",
    "WMPP","WMUU","WOMF","WONS","WOOD","WOWS","WPOW","WSBP","WSKT","WTON",
    "YELO","YOII","YPAS","YULE","YUPI","ZATA","ZBRA","ZENI","ZINC","ZONE","ZYRX"
]

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('''<div style="font-size:13px;font-weight:700;color:#a855f7;letter-spacing:.5px;font-family:Space Mono,monospace;margin-bottom:4px">⚡ IDX QUANT BOT</div>
    <div style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace;margin-bottom:14px">151 Trading Strategies Framework</div>''', unsafe_allow_html=True)

    # TELEGRAM

    st.markdown('<p class="section-lbl">TELEGRAM NOTIF</p>', unsafe_allow_html=True)
    tg_enabled = st.toggle("Aktifkan Notif", value=bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID), key="tg_enabled")
    tg_token   = st.text_input("BOT TOKEN", value=TELEGRAM_BOT_TOKEN, type="password",
                                placeholder="123456789:AAxxxxxx", key="tg_token",
                                help="Dari @BotFather — atau set di secrets.toml")
    tg_chat_id = st.text_input("CHAT ID", value=TELEGRAM_CHAT_ID,
                                placeholder="-1001234567890", key="tg_chat_id",
                                help="Dari @userinfobot — atau set di secrets.toml")

    if tg_token and tg_chat_id:
        st.markdown('<div style="font-size:9px;padding:3px 8px;border-radius:3px;background:rgba(34,197,94,.1);color:#22c55e;border:1px solid rgba(34,197,94,.3);font-family:Space Mono,monospace">✓ Token & Chat ID ready</div>', unsafe_allow_html=True)
    else:
        missing = ([] if tg_token else ["Bot Token"]) + ([] if tg_chat_id else ["Chat ID"])
        st.markdown(f'<div style="font-size:9px;padding:3px 8px;border-radius:3px;background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.3);font-family:Space Mono,monospace">✗ Missing: {', '.join(missing)}</div>', unsafe_allow_html=True)

    st.markdown('<p class="section-lbl" style="margin-top:10px">TRIGGER</p>', unsafe_allow_html=True)
    tg_on_buy     = st.checkbox("🟢 BUY signal",   value=True, key="tg_buy")
    tg_on_bagger  = st.checkbox("🌟 Bagger ≥ 65",  value=True, key="tg_bagger")
    tg_on_scalp   = st.checkbox("⚡ Scalp ≥ 60",   value=True, key="tg_scalp")
    tg_on_summary = st.checkbox("📊 Scan summary", value=True, key="tg_summary")
    tg_min_score  = st.slider("Min Score", 0, 100, 55, key="tg_score")

    if tg_enabled and tg_token and tg_chat_id:
        if st.button("🔔 Test Notif", key="tg_test", use_container_width=True):
            ok = tg_send(f"⚡ <b>IDX Quant Bot</b> — Test berhasil!\nAI: <b>{st.session_state.get('ai_model','Gemini')}</b> ✅\nTelegram connected ✅", tg_token, tg_chat_id)
            st.success("✓ Terkirim!") if ok else st.error("✗ Gagal — cek token & chat_id")

    st.divider()
    st.markdown(f'<p style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">IDX Tickers: {len(ALL_IDX_TICKERS)}<br>Kakushadze & Serur (2018)</p>', unsafe_allow_html=True)

# ─── TABS ─────────────────────────────────────────────────────────────────────
tabs = st.tabs(["  ANALYZER  ","  BAGGER DETECT  ","  SCALP SIGNAL  ","  MULTI SCREENER  ","  STRATEGY LIB  "])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ANALYZER
# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — ANALYZER (multi-ticker)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    slabel("Multi-Strategy Analyzer")
    c1,c2,c3 = st.columns([3,2,1])
    with c1:
        ana_input = st.text_input("KODE SAHAM (pisah koma)", value="BBCA, TLKM, TOOL, KOTA", key="ana_tickers")
    with c2:
        tf_ana  = st.selectbox("TIMEFRAME", ["Scalping (intraday)","Swing (1-5 hari)","Bagger Hunt"], key="ana_tf")
        per_ana = st.selectbox("PERIOD DATA", ["1mo","3mo","6mo","1y"], key="ana_period", index=2)
    with c3:
        hspacer(24)
        run_ana = st.button("▶ ANALYZE", key="btn_ana", use_container_width=True)

    if run_ana:
        tickers_ana = [t.strip().upper() for t in ana_input.split(",") if t.strip()]
        if not tickers_ana:
            st.error("Masukin minimal 1 ticker")
        else:
            prog_ana = st.progress(0, text=f"Fetching 0/{len(tickers_ana)}...")
            ana_results = []; done_a=[0]
            def fetch_ana(t):
                raw = fetch_one(t, per_ana)
                if raw: return analyze(t, raw["close"], raw["volume"], raw["high"], raw["low"])
                return {"ticker":t,"error":"fetch failed","score":0,"verdict":"—","bagger_score":0,
                        "scalp_score":0,"momentum_score":0,"chg":0,"price":0,"rsi":None,
                        "vol_label":"N/A","vol_ratio":None,"vol_ann":None,"tp":0,"sl":0,
                        "pivot":None,"r1":None,"s1":None,"ma_label":"—","active_strategies":[],
                        "momentum_signals":[],"ma_signals":[],"bagger_signals":[],"scalp_signals":[]}
            from concurrent.futures import ThreadPoolExecutor, as_completed as _ac
            with ThreadPoolExecutor(max_workers=8) as exe:
                futs={exe.submit(fetch_ana,t):t for t in tickers_ana}
                for f in _ac(futs):
                    ana_results.append(f.result()); done_a[0]+=1
                    prog_ana.progress(done_a[0]/len(tickers_ana), text=f"Fetching {done_a[0]}/{len(tickers_ana)} ({futs[f]})...")
            prog_ana.empty()
            st.session_state.ana_results = sorted(ana_results, key=lambda x:-x.get("score",0))

    if st.session_state.get("ana_results"):
        results_a = st.session_state.ana_results
        ok_a = [r for r in results_a if not r.get("error")]
        err_a = [r for r in results_a if r.get("error")]

        if len(ok_a) == 1:
            # ── Single ticker detail view ──
            r = ok_a[0]; sc = r["score"]
            hspacer(4)
            c1,c2,c3,c4 = st.columns(4)
            mom_color = "#22c55e" if r["ma_label"]=="BULLISH" else "#ef4444" if r["ma_label"]=="BEARISH" else "#8b5cf6"
            vol_color = "#a855f7" if "SPIKE" in r["vol_label"] else "#22c55e" if "ABOVE" in r["vol_label"] else "#5a6478"
            chg_color = "#22c55e" if r["chg"]>0 else "#ef4444"
            chg_str   = f"+{r['chg']:.2f}%" if r["chg"]>0 else f"{r['chg']:.2f}%"
            rsi_color = "#22c55e" if r["rsi"] and r["rsi"]<40 else "#ef4444" if r["rsi"] and r["rsi"]>70 else "#a855f7"
            with c1: render_metric_card("MA STACK", r["ma_label"], mom_color, "EMA5/EMA13/EMA34")
            with c2: render_metric_card("RSI", str(r["rsi"]) if r["rsi"] else "N/A", rsi_color, "14-period")
            with c3: render_metric_card("VOLUME", r["vol_label"], vol_color, f"Ratio {r['vol_ratio']}x vs 20D")
            with c4: render_metric_card("CHG%", chg_str, chg_color, "vs prev close")
            hspacer(12)
            left,right = st.columns([3,2])
            with left:
                slabel("STRENGTH METERS")
                render_meter("MOMENTUM",  r["momentum_score"], "#5b8df8")
                render_meter("BAGGER",    r["bagger_score"],   "#00d4aa")
                render_meter("SCALP",     r["scalp_score"],    "#a855f7")
                render_meter("COMPOSITE", int(sc),             "#dde1ea")
                hspacer(12)
                slabel("ACTIVE STRATEGIES")
                if r["active_strategies"]:
                    st.markdown("".join([render_badge(s[0],s[1]) for s in r["active_strategies"]]), unsafe_allow_html=True)
                else:
                    st.caption("— tidak ada signal kuat")
            with right:
                slabel("VERDICT")
                render_verdict_card(r["ticker"],r["verdict"],sc,r["tp"],r["sl"],r["pivot"],r["r1"],r["s1"],r["vol_ann"])
        else:
            # ── Multi ticker table view ──
            hspacer(8)
            v_colors={"BUY":("#22c55e","rgba(34,197,94,.12)","rgba(34,197,94,.3)"),
                      "HOLD":("#8b5cf6","rgba(139,92,246,.1)","rgba(139,92,246,.25)"),
                      "WAIT":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
            st.markdown('''<div style="display:grid;grid-template-columns:70px 90px 60px 55px 70px 65px 65px 60px 55px 55px 1fr;padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:2px">
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">TICKER</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">PRICE</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">CHG%</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">SCORE</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">VERDICT</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">MOMENTUM</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">BAGGER</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">SCALP</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">RSI</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">TP%</span>
              <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">STRATEGIES</span>
            </div>''', unsafe_allow_html=True)
            for r in ok_a:
                sc_color  = "#22c55e" if r["score"]>=65 else "#8b5cf6" if r["score"]>=45 else "#ef4444"
                chg_color = "#22c55e" if r["chg"]>0 else "#ef4444" if r["chg"]<0 else "#5a6478"
                chg_str   = f"+{r['chg']:.1f}" if r["chg"]>0 else f"{r['chg']:.1f}"
                mom_color = "#22c55e" if r.get("ma_label")=="BULLISH" else "#ef4444" if r.get("ma_label")=="BEARISH" else "#5a6478"
                bag_color = "#00d4aa" if r["bagger_score"]>=65 else "#dde1ea"
                scl_color = "#a855f7" if r["scalp_score"]>=60 else "#dde1ea"
                rsi_str   = str(r["rsi"]) if r.get("rsi") else "—"
                strats    = "".join([render_badge(s[0][:14],s[1]) for s in r.get("active_strategies",[])[:3]])
                vc,vbg,vbd = v_colors.get(r["verdict"],("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
                st.markdown(f'''<div style="display:grid;grid-template-columns:70px 90px 60px 55px 70px 65px 65px 60px 55px 55px 1fr;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);align-items:center">
                  <span style="font-size:12px;font-weight:700;color:#c084fc;font-family:Space Mono,monospace">{r['ticker']}</span>
                  <span style="font-size:11px;font-family:Space Mono,monospace">Rp {r['price']:,}</span>
                  <span style="font-size:11px;color:{chg_color};font-family:Space Mono,monospace">{chg_str}%</span>
                  <span style="font-size:13px;font-weight:700;color:{sc_color};font-family:Space Mono,monospace">{r['score']}</span>
                  <span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px;background:{vbg};color:{vc};border:1px solid {vbd};font-family:Space Mono,monospace;display:inline-block">{r['verdict']}</span>
                  <span style="font-size:11px;color:{mom_color};font-family:Space Mono,monospace">{r['momentum_score']}</span>
                  <span style="font-size:11px;color:{bag_color};font-family:Space Mono,monospace">{r['bagger_score']}{"★" if r['bagger_score']>=65 else ""}</span>
                  <span style="font-size:11px;color:{scl_color};font-family:Space Mono,monospace">{r['scalp_score']}{"⚡" if r['scalp_score']>=60 else ""}</span>
                  <span style="font-size:11px;font-family:Space Mono,monospace">{rsi_str}</span>
                  <span style="font-size:11px;color:#22c55e;font-family:Space Mono,monospace">+{r['tp']}%</span>
                  <span>{strats}</span>
                </div>''', unsafe_allow_html=True)

        if err_a:
            st.markdown(f"<div style='margin-top:6px;font-size:10px;color:#3d4554'>⚠️ Gagal: {', '.join([r['ticker'] for r in err_a])}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — BAGGER DETECT (multi-ticker)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    slabel("Bagger Detection — Strategy 3.1 + 3.7 + 3.3")
    c1,c2,c3,c4 = st.columns([3,1,1,1])
    with c1:
        bag_input   = st.text_input("KODE SAHAM (pisah koma)", value="KOTA, TOOL, ARCI, ASSA", key="bag_tickers")
    with c2:
        bag_target  = st.selectbox("TARGET", ["2x","3x","5x","10x"], key="bag_tgt", index=1)
    with c3:
        bag_horizon = st.selectbox("HORIZON", ["1 Bln","3 Bln","6 Bln","1 Thn"], key="bag_hor", index=1)
    with c4:
        hspacer(24)
        run_bag = st.button("▶ DETECT", key="btn_bag", use_container_width=True)

    if run_bag:
        tickers_bag = [t.strip().upper() for t in bag_input.split(",") if t.strip()]
        if not tickers_bag:
            st.error("Masukin minimal 1 ticker")
        else:
            prog_bag = st.progress(0)
            bag_results=[]; done_b=[0]
            def fetch_bag(t):
                raw=fetch_one(t,"1y")
                if raw: return analyze(t,raw["close"],raw["volume"],raw["high"],raw["low"])
                return {"ticker":t,"error":"fetch failed","bagger_score":0,"score":0,"verdict":"—",
                        "momentum_score":0,"ma_label":"—","scalp_score":0,"chg":0,"price":0,
                        "rsi":None,"vol_label":"N/A","vol_ratio":None,"vol_ann":None,"tp":0,"sl":0,
                        "pivot":None,"r1":None,"s1":None,"active_strategies":[],"bagger_signals":[],
                        "momentum_signals":[],"ma_signals":[],"scalp_signals":[]}
            from concurrent.futures import ThreadPoolExecutor, as_completed as _ac
            with ThreadPoolExecutor(max_workers=8) as exe:
                futs={exe.submit(fetch_bag,t):t for t in tickers_bag}
                for f in _ac(futs):
                    bag_results.append(f.result()); done_b[0]+=1
                    prog_bag.progress(done_b[0]/len(tickers_bag))
            prog_bag.empty()
            st.session_state.bag_results = sorted(bag_results, key=lambda x:-x.get("bagger_score",0))

    if st.session_state.get("bag_results"):
        results_b = [r for r in st.session_state.bag_results if not r.get("error")]
        err_b     = [r for r in st.session_state.bag_results if r.get("error")]

        # Summary cards
        cols_b = st.columns(min(len(results_b),4))
        for col,r in zip(cols_b, results_b[:4]):
            bc = "#00d4aa" if r["bagger_score"]>=65 else "#8b5cf6" if r["bagger_score"]>=45 else "#ef4444"
            with col: render_metric_card(r["ticker"], f"{r['bagger_score']}/100", bc, f"{r['verdict']} | Mom:{r['momentum_score']}")

        hspacer(12)
        slabel("BAGGER RANKING")
        # Full table
        v_colors={"BUY":("#22c55e","rgba(34,197,94,.12)","rgba(34,197,94,.3)"),
                  "HOLD":("#8b5cf6","rgba(139,92,246,.1)","rgba(139,92,246,.25)"),
                  "WAIT":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
        st.markdown('''<div style="display:grid;grid-template-columns:70px 70px 60px 80px 70px 70px 60px 60px 1fr;padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.1)">
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">TICKER</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">BAGGER</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">SCORE</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">VERDICT</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">MOMENTUM</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">52W POS</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">VOL ANN</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">TP%</span>
          <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">BAGGER SIGNALS</span>
        </div>''', unsafe_allow_html=True)
        for r in results_b:
            bc    = "#00d4aa" if r["bagger_score"]>=65 else "#8b5cf6" if r["bagger_score"]>=45 else "#ef4444"
            sc_c  = "#22c55e" if r["score"]>=65 else "#8b5cf6" if r["score"]>=45 else "#ef4444"
            vc,vbg,vbd = v_colors.get(r["verdict"],("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
            mom_c = "#22c55e" if r.get("ma_label")=="BULLISH" else "#ef4444" if r.get("ma_label")=="BEARISH" else "#5a6478"
            # 52W position
            raw52 = fetch_one(r["ticker"],"1y")
            if raw52:
                p52=raw52["close"]; hi52=max(p52); lo52=min(p52); cur52=p52[-1]
                pct52=round((cur52-lo52)/max(hi52-lo52,1)*100)
                pos_color="#00d4aa" if pct52<35 else "#8b5cf6" if pct52<55 else "#ef4444"
                pos_str=f"{pct52}% from low"
            else:
                pos_str="—"; pos_color="#5a6478"
            sigs = " | ".join(r.get("bagger_signals",["—"])[:2])
            vol_str = f"{r['vol_ann']}%" if r.get("vol_ann") else "—"
            st.markdown(f'''<div style="display:grid;grid-template-columns:70px 70px 60px 80px 70px 70px 60px 60px 1fr;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);align-items:center">
              <span style="font-size:12px;font-weight:700;color:#c084fc;font-family:Space Mono,monospace">{r['ticker']}</span>
              <span style="font-size:13px;font-weight:700;color:{bc};font-family:Space Mono,monospace">{r['bagger_score']}{"★" if r['bagger_score']>=65 else ""}</span>
              <span style="font-size:12px;color:{sc_c};font-family:Space Mono,monospace">{r['score']}</span>
              <span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px;background:{vbg};color:{vc};border:1px solid {vbd};font-family:Space Mono,monospace;display:inline-block">{r['verdict']}</span>
              <span style="font-size:11px;color:{mom_c};font-family:Space Mono,monospace">{r['momentum_score']}</span>
              <span style="font-size:10px;color:{pos_color};font-family:Space Mono,monospace">{pos_str}</span>
              <span style="font-size:10px;color:#5a6478;font-family:Space Mono,monospace">{vol_str}</span>
              <span style="font-size:11px;color:#22c55e;font-family:Space Mono,monospace">+{r['tp']}%</span>
              <span style="font-size:10px;color:#3d4554;font-family:Space Mono,monospace">{sigs}</span>
            </div>''', unsafe_allow_html=True)

        if err_b:
            st.markdown(f"<div style='margin-top:6px;font-size:10px;color:#3d4554'>⚠️ Gagal: {', '.join([r['ticker'] for r in err_b])}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SCALP SIGNAL (multi-ticker)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    slabel("Scalping Signal Generator — Strategy 3.14 + 3.19")
    c1,c2,c3,c4 = st.columns([3,2,2,1])
    with c1:
        scl_input = st.text_input("KODE SAHAM (pisah koma)", value="TOOL, KOTA, ARCI", key="scl_tickers")
    with c2:
        scl_risk  = st.selectbox("RISK TOLERANCE", ["Tight (1-1.5%)","Normal (2-3%)","Wide (3-5%)"], key="scl_r", index=1)
    with c3:
        scl_note  = st.text_input("ENTRY PRICE (opsional, 1 ticker)", placeholder="mis: 500", key="scl_price_manual")
    with c4:
        hspacer(24)
        run_scl = st.button("▶ SIGNAL", key="btn_scl", use_container_width=True)

    if run_scl:
        tickers_scl = [t.strip().upper() for t in scl_input.split(",") if t.strip()]
        risk_pct = {"Tight (1-1.5%)":1.2,"Normal (2-3%)":2.0,"Wide (3-5%)":3.5}[scl_risk]
        if not tickers_scl:
            st.error("Masukin minimal 1 ticker")
        else:
            prog_scl = st.progress(0)
            scl_results=[]; done_s=[0]
            def fetch_scl(t):
                raw=fetch_one(t,"1mo")
                if not raw: return {"ticker":t,"error":"fetch failed","scalp_score":0,"score":0,
                                    "verdict":"—","momentum_score":0,"ma_label":"—","bagger_score":0,
                                    "chg":0,"price":0,"rsi":None,"vol_label":"N/A","vol_ratio":None,
                                    "vol_ann":None,"tp":risk_pct*1.5,"sl":risk_pct,"pivot":None,
                                    "r1":None,"s1":None,"active_strategies":[],"scalp_signals":[],
                                    "momentum_signals":[],"ma_signals":[],"bagger_signals":[]}
                r=analyze(t,raw["close"],raw["volume"],raw["high"],raw["low"],mode="scalp")
                # Recalculate TP/SL berdasarkan harga actual
                entry = raw["close"][-1]
                r["entry"]    = round(entry)
                r["tp1"]      = round(entry*(1+risk_pct*1.5/100))
                r["tp2"]      = round(entry*(1+risk_pct*2.5/100))
                r["sl_abs"]   = round(entry*(1-risk_pct/100))
                r["rr_ratio"] = round((r["tp1"]-entry)/max(entry-r["sl_abs"],1),2)
                return r
            from concurrent.futures import ThreadPoolExecutor, as_completed as _ac
            with ThreadPoolExecutor(max_workers=8) as exe:
                futs={exe.submit(fetch_scl,t):t for t in tickers_scl}
                for f in _ac(futs):
                    scl_results.append(f.result()); done_s[0]+=1
                    prog_scl.progress(done_s[0]/len(tickers_scl))
            prog_scl.empty()
            st.session_state.scl_results = sorted(scl_results, key=lambda x:-x.get("scalp_score",0))

    if st.session_state.get("scl_results"):
        results_s = [r for r in st.session_state.scl_results if not r.get("error")]
        err_s     = [r for r in st.session_state.scl_results if r.get("error")]

        if len(results_s)==1:
            # ── Single detail view ──
            r = results_s[0]
            c1,c2,c3,c4,c5 = st.columns(5)
            with c1: render_metric_card("ENTRY",     f"Rp {r['entry']:,}", "#5b8df8")
            with c2: render_metric_card("TP 1",      f"Rp {r['tp1']:,}",  "#22c55e")
            with c3: render_metric_card("TP 2",      f"Rp {r['tp2']:,}",  "#00d4aa")
            with c4: render_metric_card("STOP LOSS", f"Rp {r['sl_abs']:,}","#ef4444")
            with c5: render_metric_card("R/R RATIO", f"{r['rr_ratio']}x", "#a855f7")
            hspacer(12)
            l,rr = st.columns(2)
            with l:
                slabel("SCALP SIGNALS")
                for s in (r.get("scalp_signals") or ["— tidak ada signal"]):
                    color="#a855f7" if "✓" in s else "#e05c5c" if "!" in s else "#5a6478"
                    st.markdown(f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:12px;color:{color};font-family:Space Mono,monospace">{s}</div>', unsafe_allow_html=True)
            with rr:
                slabel("PIVOT LEVELS")
                st.markdown('<div class="card">', unsafe_allow_html=True)
                render_signal_line("PIVOT",      str(r["pivot"]) if r.get("pivot") else "N/A")
                render_signal_line("R1 (TP ref)", str(r["r1"])   if r.get("r1")    else "N/A","#22c55e")
                render_signal_line("S1 (SL ref)", str(r["s1"])   if r.get("s1")    else "N/A","#ef4444")
                render_signal_line("SCALP SCORE", f"{r['scalp_score']}/100","#a855f7")
                render_signal_line("RSI",         str(r["rsi"])  if r.get("rsi")   else "N/A")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            # ── Multi table view ──
            slabel("SCALP RANKING — sorted by Scalp Score")
            v_colors={"BUY":("#22c55e","rgba(34,197,94,.12)","rgba(34,197,94,.3)"),
                      "HOLD":("#8b5cf6","rgba(139,92,246,.1)","rgba(139,92,246,.25)"),
                      "WAIT":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
            st.markdown('''<div style="display:grid;grid-template-columns:70px 90px 65px 55px 70px 65px 80px 80px 65px 65px 1fr;padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.1)">
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">TICKER</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">ENTRY</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">SCALP</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">RSI</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">VERDICT</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">VOL</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">TP 1</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">TP 2</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">SL</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">R/R</span>
              <span style="font-size:9px;color:#3d4554;font-family:Space Mono,monospace">SIGNALS</span>
            </div>''', unsafe_allow_html=True)
            for r in results_s:
                sc_c  = "#a855f7" if r["scalp_score"]>=60 else "#dde1ea"
                rsi_s = str(r["rsi"]) if r.get("rsi") else "—"
                vol_c = "#a855f7" if "SPIKE" in r.get("vol_label","") else "#22c55e" if "ABOVE" in r.get("vol_label","") else "#5a6478"
                vc,vbg,vbd = v_colors.get(r["verdict"],("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
                sigs = (r.get("scalp_signals") or ["—"])[0][:30]
                st.markdown(f'''<div style="display:grid;grid-template-columns:70px 90px 65px 55px 70px 65px 80px 80px 65px 65px 1fr;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);align-items:center">
                  <span style="font-size:12px;font-weight:700;color:#c084fc;font-family:Space Mono,monospace">{r['ticker']}</span>
                  <span style="font-size:11px;font-family:Space Mono,monospace">Rp {r.get('entry',r['price']):,}</span>
                  <span style="font-size:13px;font-weight:700;color:{sc_c};font-family:Space Mono,monospace">{r['scalp_score']}{"⚡" if r['scalp_score']>=60 else ""}</span>
                  <span style="font-size:11px;font-family:Space Mono,monospace">{rsi_s}</span>
                  <span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px;background:{vbg};color:{vc};border:1px solid {vbd};font-family:Space Mono,monospace;display:inline-block">{r['verdict']}</span>
                  <span style="font-size:10px;color:{vol_c};font-family:Space Mono,monospace">{r.get('vol_label','—')}</span>
                  <span style="font-size:11px;color:#22c55e;font-family:Space Mono,monospace">Rp {r.get('tp1',0):,}</span>
                  <span style="font-size:11px;color:#00d4aa;font-family:Space Mono,monospace">Rp {r.get('tp2',0):,}</span>
                  <span style="font-size:11px;color:#ef4444;font-family:Space Mono,monospace">Rp {r.get('sl_abs',0):,}</span>
                  <span style="font-size:11px;color:#a855f7;font-family:Space Mono,monospace">{r.get('rr_ratio',0)}x</span>
                  <span style="font-size:10px;color:#3d4554;font-family:Space Mono,monospace">{sigs}</span>
                </div>''', unsafe_allow_html=True)

        if err_s:
            st.markdown(f"<div style='margin-top:6px;font-size:10px;color:#3d4554'>⚠️ Gagal: {', '.join([r['ticker'] for r in err_s])}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    slabel("Parallel Multi-Ticker Screener — SAT SET MODE")
    c1,c2,c3 = st.columns([3,2,1])
    with c1:
        preset_opts = ["— Custom —","⚡ ALL IDX (~900 ticker)"]+list(PRESETS.keys())
        preset = st.selectbox("QUICK PRESET", preset_opts, key="preset_sel")

        # Update session_state SEBELUM render text_input — ini fix auto-fill
        if preset == "⚡ ALL IDX (~900 ticker)":
            st.session_state["multi_tickers"] = ", ".join(ALL_IDX_TICKERS)
            st.caption(f"⚠️ {len(ALL_IDX_TICKERS)} ticker — workers max & siapkan kopi ☕")
        elif preset != "— Custom —":
            st.session_state["multi_tickers"] = ", ".join(PRESETS[preset])
        elif "multi_tickers" not in st.session_state:
            st.session_state["multi_tickers"] = "TOOL, KOTA, ARCI, ASSA, BBCA, GOTO"

        ticker_input = st.text_input("TICKER LIST (pisah koma)", key="multi_tickers")
    with c2:
        mode_sel    = st.selectbox("MODE", ["deep","bagger","scalp","quick"], key="multi_mode")
        period_sel  = st.selectbox("PERIOD DATA", ["1mo","3mo","6mo","1y"], key="multi_period", index=2)
        workers_sel = st.slider("PARALLEL WORKERS", 3, 20, 10, key="multi_workers")
    with c3:
        hspacer(24)
        run_multi = st.button("▶▶ SCAN ALL", key="btn_multi", use_container_width=True)

    if run_multi:
        tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]
        if not tickers:
            st.error("Masukin minimal 1 ticker bro")
        else:
            t_start = time.time()
            prog = st.progress(0, text=f"Scanning 0/{len(tickers)}...")
            results_list = []; done=[0]

            def scan_one(t):
                raw = fetch_one(t, period_sel)
                if raw: return analyze(t, raw["close"], raw["volume"], raw["high"], raw["low"], mode_sel)
                return {"ticker":t,"error":"fetch failed","score":0,"verdict":"—",
                        "bagger_score":0,"scalp_score":0,"momentum_score":0,"chg":0,
                        "price":0,"rsi":None,"vol_label":"N/A","vol_ratio":None,
                        "vol_ann":None,"tp":0,"sl":0,"pivot":None,"r1":None,"s1":None,
                        "ma_label":"—","active_strategies":[],"momentum_signals":[],
                        "ma_signals":[],"bagger_signals":[],"scalp_signals":[]}

            with ThreadPoolExecutor(max_workers=workers_sel) as exe:
                futures={exe.submit(scan_one,t):t for t in tickers}
                for f in as_completed(futures):
                    results_list.append(f.result()); done[0]+=1
                    prog.progress(done[0]/len(tickers), text=f"Scanning {done[0]}/{len(tickers)} ({futures[f]})...")

            elapsed = time.time()-t_start
            prog.empty()
            st.session_state.scan_results = results_list

            # ── Telegram notif ──────────────────────────────────────────────
            tg_tok = st.session_state.get("tg_token","") or TELEGRAM_BOT_TOKEN
            tg_cid = st.session_state.get("tg_chat_id","") or TELEGRAM_CHAT_ID
            tg_on  = st.session_state.get("tg_enabled", False)
            min_sc = st.session_state.get("tg_score", 55)
            MAX_ALERTS = 20  # rate limit guard — maks 20 single alert per scan

            # Debug info — selalu tampil biar tau statusnya
            tg_debug = []
            tg_debug.append(f"Telegram toggle: {'ON ✅' if tg_on else 'OFF ❌ — nyalain di sidebar dulu!'}")
            tg_debug.append(f"Bot Token: {'✅ ada' if tg_tok else '❌ kosong'}")
            tg_debug.append(f"Chat ID: {'✅ ada' if tg_cid else '❌ kosong'}")

            if tg_on and tg_tok and tg_cid:
                ok_r = sorted(
                    [r for r in results_list if not r.get("error") and r.get("score",0) >= min_sc],
                    key=lambda x: -x.get("score",0)
                )
                notif_count = 0
                failed_count = 0

                for r in ok_r:
                    if notif_count >= MAX_ALERTS:
                        tg_debug.append(f"⚠️ Maks {MAX_ALERTS} alert tercapai — sisanya di-skip")
                        break

                    sent = False
                    # BUY alert
                    if st.session_state.get("tg_buy", True) and r.get("verdict")=="BUY":
                        ok_send = tg_send(tg_build_single_alert(r,"buy"), tg_tok, tg_cid)
                        if ok_send: notif_count+=1; sent=True
                        else: failed_count+=1
                        time.sleep(0.35)

                    # Bagger alert (termasuk yang BUY juga boleh dapet notif bagger)
                    if st.session_state.get("tg_bagger", True) and r.get("bagger_score",0)>=65 and not sent:
                        ok_send = tg_send(tg_build_single_alert(r,"bagger"), tg_tok, tg_cid)
                        if ok_send: notif_count+=1; sent=True
                        else: failed_count+=1
                        time.sleep(0.35)

                    # Scalp alert
                    if st.session_state.get("tg_scalp", True) and r.get("scalp_score",0)>=60 and not sent:
                        ok_send = tg_send(tg_build_single_alert(r,"scalp"), tg_tok, tg_cid)
                        if ok_send: notif_count+=1
                        else: failed_count+=1
                        time.sleep(0.35)

                # Summary selalu dikirim terakhir
                if st.session_state.get("tg_summary", True):
                    ok_sum = tg_send(tg_build_scan_summary(results_list, mode_sel, elapsed), tg_tok, tg_cid)
                    tg_debug.append(f"Summary: {'✅ terkirim' if ok_sum else '❌ gagal'}")

                tg_debug.append(f"Alert terkirim: {notif_count} | Gagal: {failed_count}")

                if notif_count > 0:
                    st.success(f"📱 Telegram: {notif_count} alert terkirim! Cek HP lo bro.")
                elif failed_count > 0:
                    st.error(f"📱 Telegram: semua gagal kirim ({failed_count}x) — cek token & chat_id")
                else:
                    st.info("📱 Telegram: tidak ada ticker yang memenuhi threshold untuk dikirim")

            elif not tg_on:
                st.warning("📱 Telegram belum aktif — nyalain toggle di sidebar kiri dulu ya bro!")
            else:
                st.error("📱 Token atau Chat ID kosong — isi di sidebar atau secrets.toml")

            # Tampilkan debug info di expander
            with st.expander("📋 Debug Telegram", expanded=not tg_on):
                for line in tg_debug:
                    st.text(line)

    if st.session_state.scan_results:
        results = st.session_state.scan_results
        ok = [r for r in results if not r.get("error")]
        n_buy=sum(1 for r in ok if r["verdict"]=="BUY")
        n_hold=sum(1 for r in ok if r["verdict"]=="HOLD")
        n_wait=sum(1 for r in ok if r["verdict"]=="WAIT")
        n_bag=sum(1 for r in ok if r["bagger_score"]>=65)
        n_scl=sum(1 for r in ok if r["scalp_score"]>=60)

        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1: render_metric_card("TOTAL",    len(ok),  "#dde1ea")
        with c2: render_metric_card("BUY",      n_buy,    "#22c55e")
        with c3: render_metric_card("HOLD",     n_hold,   "#8b5cf6")
        with c4: render_metric_card("WAIT",     n_wait,   "#ef4444")
        with c5: render_metric_card("BAGGER ★", n_bag,    "#00d4aa")
        with c6: render_metric_card("SCALP ⚡",  n_scl,    "#a855f7")

        hspacer(14)
        fc1,fc2 = st.columns([4,2])
        with fc1:
            filter_opt = st.radio("", ["ALL","BUY","HOLD","WAIT","BAGGER ★","SCALP ⚡"],
                                  horizontal=True, key="multi_filter", label_visibility="collapsed")
        with fc2:
            sort_opt = st.selectbox("", ["Score ↓","Bagger ↓","Scalp ↓","Momentum ↓","Ticker A-Z"],
                                    key="multi_sort", label_visibility="collapsed")

        filtered = ok[:]
        if filter_opt=="BUY":        filtered=[r for r in ok if r["verdict"]=="BUY"]
        elif filter_opt=="HOLD":     filtered=[r for r in ok if r["verdict"]=="HOLD"]
        elif filter_opt=="WAIT":     filtered=[r for r in ok if r["verdict"]=="WAIT"]
        elif filter_opt=="BAGGER ★": filtered=[r for r in ok if r["bagger_score"]>=65]
        elif filter_opt=="SCALP ⚡":  filtered=[r for r in ok if r["scalp_score"]>=60]
        key_map={"Score ↓":lambda x:-x["score"],"Bagger ↓":lambda x:-x["bagger_score"],
                 "Scalp ↓":lambda x:-x["scalp_score"],"Momentum ↓":lambda x:-x["momentum_score"],
                 "Ticker A-Z":lambda x:x["ticker"]}
        filtered.sort(key=key_map.get(sort_opt,lambda x:-x["score"]))
        st.caption(f"Showing {len(filtered)} / {len(ok)} ticker")

        st.markdown('''<div style="display:grid;grid-template-columns:70px 90px 60px 55px 70px 65px 65px 60px 55px 55px 1fr;padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:2px">
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">TICKER</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">PRICE</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">CHG%</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">SCORE</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">VERDICT</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">MOMENTUM</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">BAGGER</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">SCALP</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">RSI</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">TP%</span>
          <span style="font-size:9px;color:#3d4554;letter-spacing:1px;font-family:Space Mono,monospace">STRATEGIES</span>
        </div>''', unsafe_allow_html=True)

        v_colors={"BUY":("#22c55e","rgba(34,197,94,.12)","rgba(34,197,94,.3)"),
                  "HOLD":("#8b5cf6","rgba(139,92,246,.1)","rgba(139,92,246,.25)"),
                  "WAIT":("#ef4444","rgba(239,68,68,.1)","rgba(239,68,68,.3)")}
        for r in filtered:
            sc_color  = "#22c55e" if r["score"]>=65 else "#8b5cf6" if r["score"]>=45 else "#ef4444"
            chg_color = "#22c55e" if r["chg"]>0 else "#ef4444" if r["chg"]<0 else "#5a6478"
            chg_str   = f"+{r['chg']:.1f}" if r["chg"]>0 else f"{r['chg']:.1f}"
            mom_color = "#22c55e" if r.get("ma_label")=="BULLISH" else "#ef4444" if r.get("ma_label")=="BEARISH" else "#5a6478"
            bag_color = "#00d4aa" if r["bagger_score"]>=65 else "#dde1ea"
            scl_color = "#a855f7" if r["scalp_score"]>=60 else "#dde1ea"
            bag_star  = " ★" if r["bagger_score"]>=65 else ""
            scl_bolt  = " ⚡" if r["scalp_score"]>=60 else ""
            rsi_str   = str(r["rsi"]) if r.get("rsi") else "—"
            strats    = "".join([render_badge(s[0][:14],s[1]) for s in r.get("active_strategies",[])[:3]])
            vc,vbg,vbd = v_colors.get(r["verdict"],("#5a6478","rgba(255,255,255,.05)","rgba(255,255,255,.1)"))
            st.markdown(f'''<div style="display:grid;grid-template-columns:70px 90px 60px 55px 70px 65px 65px 60px 55px 55px 1fr;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.04);align-items:center">
              <span style="font-size:12px;font-weight:700;color:#c084fc;letter-spacing:.5px;font-family:Space Mono,monospace">{r['ticker']}</span>
              <span style="font-size:11px;font-family:Space Mono,monospace">Rp {r['price']:,}</span>
              <span style="font-size:11px;color:{chg_color};font-family:Space Mono,monospace">{chg_str}%</span>
              <span style="font-size:13px;font-weight:700;color:{sc_color};font-family:Space Mono,monospace">{r['score']}</span>
              <span style="font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px;background:{vbg};color:{vc};border:1px solid {vbd};letter-spacing:.5px;font-family:Space Mono,monospace;display:inline-block">{r['verdict']}</span>
              <span style="font-size:11px;color:{mom_color};font-family:Space Mono,monospace">{r['momentum_score']}</span>
              <span style="font-size:11px;color:{bag_color};font-family:Space Mono,monospace">{r['bagger_score']}{bag_star}</span>
              <span style="font-size:11px;color:{scl_color};font-family:Space Mono,monospace">{r['scalp_score']}{scl_bolt}</span>
              <span style="font-size:11px;font-family:Space Mono,monospace">{rsi_str}</span>
              <span style="font-size:11px;color:#22c55e;font-family:Space Mono,monospace">+{r['tp']}%</span>
              <span>{strats}</span>
            </div>''', unsafe_allow_html=True)

        errs = [r["ticker"] for r in results if r.get("error")]
        if errs:
            st.markdown(f"<div style='margin-top:8px;font-size:10px;color:#3d4554'>⚠️ Gagal: {', '.join(errs[:10])}{'...' if len(errs)>10 else ''}</div>", unsafe_allow_html=True)


# TAB 5 — AI CHAT
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    slabel("151 Trading Strategies — Relevan Buat IDX Trader")

    LIBRARY={
        "BAGGER / SWING":[
            ("3.1","Price-Momentum","Beli winner 12M-1M, jual loser. Formation + skip period.","bagger"),
            ("3.2","Earnings-Momentum (SUE)","Standardized Unexpected Earnings — antisipasi EPS surprise.","bagger"),
            ("3.3","Value — Book-to-Price","B/P tinggi = undervalued. Long top decile B/P ratio.","bagger"),
            ("3.6","Multifactor Portfolio","Kombinasi momentum + value + low-vol. Alpha lebih stabil.","bagger"),
            ("3.7","Residual Momentum","Momentum post-factor strip. Lebih murni dari price momentum.","bagger"),
            ("4.1","Sector Momentum Rotation","Rotasi ke sektor terkuat. IDX: bank, energi, konsumer.","bagger"),
            ("4.1.2","Dual-Momentum Rotation","Absolute + relative momentum. Masuk sektor yang naik absolut.","bagger"),
        ],
        "MOMENTUM / TREND":[
            ("3.11","Single Moving Average","Price cross MA. EMA lebih responsif dari SMA.","momentum"),
            ("3.12","Two Moving Averages","Crossover MA pendek > panjang = buy. Klasik dan reliable.","momentum"),
            ("3.13","Three Moving Averages","EMA5 > EMA13 > EMA34 = full bullish stack. Strongest signal.","momentum"),
            ("3.14","Support & Resistance","Pivot: C=(H+L+C)/3, R1=2C-L, S1=2C-H. Dasar scalping.","momentum"),
            ("3.15","Channel Trading","Buy floor, sell ceiling. Cocok saham sideways.","momentum"),
            ("10.4","Trend Following","Momentum kuat → hold. Momentum lemah → exit.","momentum"),
        ],
        "MEAN REVERSION":[
            ("3.8","Pairs Trading","Spread 2 saham sejenis. BBCA vs BMRI, TLKM vs EXCL.","scalp"),
            ("3.9","Mean-Reversion Cluster","Short di atas mean, long di bawah. Sektor-based.","scalp"),
            ("10.3","Contrarian Trading","Sell overbought, buy oversold. Anti-trend tapi profitable.","scalp"),
        ],
        "SCALPING / INTRADAY":[
            ("3.19","Market-Making","Capture bid-ask. Kunci: deteksi smart vs dumb orderflow.","scalp"),
            ("3.14","Intraday Pivot","Pivot intraday, TP di resistance, SL di bawah support.","scalp"),
            ("3.12","Fast MA Crossover","EMA5/EMA13 cross untuk entry scalp cepat.","scalp"),
        ],
        "MACHINE LEARNING":[
            ("3.17","KNN Single-Stock","K-nearest neighbor predict return dari price+volume.","momentum"),
            ("3.20","Alpha Combos","Combine banyak weak signal jadi mega-alpha.","momentum"),
            ("18.2","Neural Network","ANN predict harga. Butuh data banyak dan compute power.","momentum"),
        ],
    }

    for cat, strats in LIBRARY.items():
        st.markdown(f'<div style="font-size:10px;color:#a855f7;letter-spacing:1.5px;border-bottom:1px solid rgba(168,85,247,.15);padding-bottom:5px;margin:16px 0 8px;font-family:Space Mono,monospace">{cat}</div>', unsafe_allow_html=True)
        for num,name,desc,kind in strats:
            badge=render_badge(kind.upper(),kind)
            st.markdown(f"""
            <div style="display:flex;align-items:flex-start;gap:10px;padding:8px 10px;background:#161a20;border-radius:4px;margin-bottom:4px;border:1px solid rgba(255,255,255,.04)">
              <span style="font-size:10px;color:#3d4554;width:32px;flex-shrink:0;margin-top:1px;font-family:Space Mono,monospace">{num}</span>
              <div style="flex:1">
                <div style="font-size:12px;color:#dde1ea;margin-bottom:2px;font-family:Space Mono,monospace">{name}</div>
                <div style="font-size:10px;color:#5a6478;font-family:Space Mono,monospace">{desc}</div>
              </div>
              {badge}
            </div>""", unsafe_allow_html=True)
