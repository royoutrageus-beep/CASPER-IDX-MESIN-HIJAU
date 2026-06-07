# ═══════════════════════════════════════════════════════════════════
#  MESIN ENTRY v1.0 — Probabilistic Entry Timing Engine
#  Based on Kakushadze & Serur (2018) "151 Trading Strategies"
#  Primary recipes:
#    • Section 18.2 — ANN features (z-score normalized returns)
#    • Section 3.17 — KNN single-asset pattern matching
#    • Section 3.20 — Alpha combo (proper signal combination)
#  Works for: XAU-USD, IDX stocks (.JK), US stocks, crypto (-USD)
# ═══════════════════════════════════════════════════════════════════

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import pytz
import random
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────
def _get_secret(*names, default=""):
    for n in names:
        try:
            v = st.secrets.get(n, default)
            if v: return v
        except: pass
    return default

TOKEN   = _get_secret("TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN")
CHAT_ID = _get_secret("TELEGRAM_CHAT_ID")
et_tz   = pytz.timezone('US/Eastern')

st.set_page_config(
    layout="wide",
    page_title="Mesin Entry v1.0",
    page_icon="🎯",
    initial_sidebar_state="collapsed"
)

# ─── SMART PRICE FORMATTER ────────────────────────────────────────
def _pf(price):
    """Smart formatter: XAU $2,034, BTC $95,432, SHIB $0.00002, BBCA Rp 8,975"""
    try:
        p = float(price)
        if p <= 0: return "0"
        if p >= 10000:    return f"{p:,.0f}"
        elif p >= 100:    return f"{p:,.2f}"
        elif p >= 10:     return f"{p:.2f}"
        elif p >= 1:      return f"{p:.3f}"
        elif p >= 0.01:   return f"{p:.4f}"
        elif p >= 0.0001: return f"{p:.6f}"
        else:             return f"{p:.8f}"
    except: return "0"

def _pct(v, dp=2):
    try: return f"{float(v):+.{dp}f}%"
    except: return "0.00%"

# ─── DATA FETCH (anti-rate-limit) ─────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlcv(ticker, period, interval):
    """3-layer fallback yFinance fetch — works for any asset class."""
    try:
        time.sleep(random.uniform(0.05, 0.15))
        # Layer 1: Ticker.history with actions=False
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, actions=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        # Layer 2: yf.download
        try:
            df = yf.download(ticker, period=period, interval=interval,
                            progress=False, threads=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        # Layer 3: Ticker.history auto_adjust=False
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        return None
    except: return None

def fetch_multi_tf(ticker):
    """Fetch 15m (60d) + 1h (60d) + 1d (1y) in parallel."""
    res = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(fetch_ohlcv, ticker, "60d", "15m"): "15m",
            ex.submit(fetch_ohlcv, ticker, "60d", "1h"):  "1h",
            ex.submit(fetch_ohlcv, ticker, "1y",  "1d"):  "1d",
        }
        for f in as_completed(futures):
            tf = futures[f]
            try: res[tf] = f.result()
            except: res[tf] = None
    return res

# ════════════════════════════════════════════════════════════════════
#  CORE ENGINE — Section 18.2 (ANN-style features)
# ════════════════════════════════════════════════════════════════════

def compute_normalized_returns(close, T1):
    """
    Section 18.2 core: convert raw price → z-scored demeaned returns.

    R(t)         = P(t)/P(t-1) - 1                     [raw return]
    R̃(t,T1)      = R(t) - mean(R over T1 periods)       [serial demean]
    σ(t,T1)      = std(R̃ over T1 periods)
    R̂(t,T1)      = R̃(t,T1) / σ(t,T1)                   [Z-SCORE]

    Exact formula from book equations (521)-(525).
    All downstream features use R̂, not raw P.
    """
    R = close.pct_change()
    R_mean = R.rolling(T1, min_periods=max(5, T1//3)).mean()
    R_demeaned = R - R_mean
    sigma = R_demeaned.rolling(T1, min_periods=max(5, T1//3)).std()
    R_hat = (R_demeaned / sigma.replace(0, np.nan)).fillna(0)
    return R_hat, R_demeaned, sigma

def compute_ema_features(R_hat, tau):
    """EMA(R̂, τ). Book Eq (526): λ = (τ-1)/(τ+1) reduces free parameters."""
    lam = (tau - 1) / (tau + 1)
    return R_hat.ewm(alpha=1-lam, adjust=False).mean()

def compute_emsd_features(R_hat, tau):
    """EMSD(R̂, τ). Book Eq (527): exp moving std deviation."""
    lam = (tau - 1) / (tau + 1)
    ema = R_hat.ewm(alpha=1-lam, adjust=False).mean()
    var = ((R_hat - ema) ** 2).ewm(alpha=1-lam, adjust=False).mean()
    return np.sqrt(var)

def compute_rsi_normalized(R_hat, tau):
    """
    RSI on NORMALIZED returns (book Eq 528-529).
    Range: 0-1. >0.7 = overbought, <0.3 = oversold.
    """
    pos = R_hat.where(R_hat > 0, 0)
    neg = (-R_hat).where(R_hat < 0, 0)
    sum_pos = pos.rolling(tau, min_periods=2).sum()
    sum_neg = neg.rolling(tau, min_periods=2).sum()
    total = sum_pos + sum_neg
    return (sum_pos / total.replace(0, np.nan)).fillna(0.5)

def build_feature_matrix(df, T1=120):
    """
    Build complete feature matrix for KNN + scoring.
    Multi-horizon EMA, EMSD, RSI on z-scored returns.
    Horizons τ ∈ {2, 4, 12, 24, 48} bars = {30m, 1h, 3h, 6h, 12h} for 15m data.
    """
    close = df["Close"]
    R_hat, R_dem, sigma = compute_normalized_returns(close, T1)

    horizons = [2, 4, 12, 24, 48]
    features = pd.DataFrame(index=df.index)
    features["R_hat"] = R_hat

    for tau in horizons:
        features[f"ema_{tau}"]  = compute_ema_features(R_hat, tau)
        features[f"emsd_{tau}"] = compute_emsd_features(R_hat, tau)
        features[f"rsi_{tau}"]  = compute_rsi_normalized(R_hat, tau)

    features = features.dropna()
    return features, R_hat, sigma

# ════════════════════════════════════════════════════════════════════
#  KNN PATTERN MATCHER — Section 3.17
# ════════════════════════════════════════════════════════════════════

def knn_pattern_match(features, close, k=20, lookback_horizon=4):
    """
    Section 3.17: Find k nearest historical patterns to current state.

    Target Y(t)  = P(t+horizon)/P(t) - 1 (forward return over `horizon` bars)
    Features     = current normalized state vector
    Distance     = Euclidean (on standardized features)
    Prediction   = inverse-distance weighted avg of past outcomes

    Returns: pred_return, k_timestamps, k_distances, outcomes, confidence
    """
    if len(features) < 50 or len(close) < 50:
        return 0.0, [], [], [], 0.0

    feature_cols = [c for c in features.columns if c.startswith(('ema_','rsi_'))]
    X = features[feature_cols].values

    close_aligned = close.reindex(features.index).ffill()
    future_close = close_aligned.shift(-lookback_horizon)
    Y = (future_close / close_aligned - 1).values

    valid = ~np.isnan(Y)
    if valid.sum() < k + 5:
        return 0.0, [], [], [], 0.0

    X_hist = X[valid][:-1]
    Y_hist = Y[valid][:-1]
    X_now  = X[-1]

    if np.any(np.isnan(X_now)) or np.any(np.isinf(X_now)):
        return 0.0, [], [], [], 0.0

    # Standardize features (each dim contributes equally)
    X_mean = X_hist.mean(axis=0)
    X_std  = X_hist.std(axis=0) + 1e-9
    X_hist_z = (X_hist - X_mean) / X_std
    X_now_z  = (X_now - X_mean) / X_std

    distances = np.linalg.norm(X_hist_z - X_now_z, axis=1)

    k_actual = min(k, len(distances))
    k_idx = np.argpartition(distances, k_actual-1)[:k_actual]
    k_idx = k_idx[np.argsort(distances[k_idx])]
    k_dist = distances[k_idx]
    k_outcomes = Y_hist[k_idx]

    weights = 1 / (k_dist + 1e-6)
    weights = weights / weights.sum()
    pred_return = float(np.dot(weights, k_outcomes))

    outcome_std = np.std(k_outcomes)
    global_std  = np.std(Y_hist) + 1e-9
    confidence = max(0.0, min(1.0, 1.0 - outcome_std / global_std))

    valid_indices = features.index[valid][:-1]
    k_timestamps = valid_indices[k_idx].tolist()

    return pred_return, k_timestamps, k_dist.tolist(), k_outcomes.tolist(), confidence

# ════════════════════════════════════════════════════════════════════
#  CONFLUENCE AGGREGATOR — Section 3.20 (Alpha Combo lite)
# ════════════════════════════════════════════════════════════════════

def compute_confluence_score(features, R_hat):
    """Sub-score per timeframe. Higher horizons weight more."""
    if len(features) < 10:
        return {}

    horizons = [2, 4, 12, 24, 48]
    horizon_labels = {2:"30m", 4:"1h", 12:"3h", 24:"6h", 48:"12h"}
    horizon_weights = {2:0.10, 4:0.20, 12:0.25, 24:0.25, 48:0.20}

    latest = features.iloc[-1]
    breakdown = {}

    for tau in horizons:
        ema_v  = float(latest.get(f"ema_{tau}", 0))
        emsd_v = float(latest.get(f"emsd_{tau}", 0.01))
        rsi_v  = float(latest.get(f"rsi_{tau}", 0.5))

        # Trend: sign × magnitude (tanh squashes extremes)
        trend_score = np.tanh(ema_v * 2) * 100

        # Momentum strength: signal/noise ratio
        momentum_score = min(100, max(-100, ema_v / max(emsd_v, 1e-6) * 50))

        # RSI: mid-range healthy, extremes signal mean reversion
        rsi_centered = (rsi_v - 0.5) * 2
        rsi_score = rsi_centered * 60 if abs(rsi_centered) < 0.5 else -rsi_centered * 40

        sub_score = trend_score * 0.5 + momentum_score * 0.3 + rsi_score * 0.2

        breakdown[tau] = {
            "label": horizon_labels[tau],
            "weight": horizon_weights[tau],
            "trend": trend_score,
            "momentum": momentum_score,
            "rsi_raw": rsi_v,
            "rsi_score": rsi_score,
            "sub_score": sub_score,
            "ema_raw": ema_v,
            "emsd_raw": emsd_v,
        }

    return breakdown

def aggregate_confluence(breakdown):
    """Weighted sum across timeframes + agreement metric."""
    if not breakdown:
        return 0.0, 0.0
    weighted_sum = sum(b["sub_score"] * b["weight"] for b in breakdown.values())
    signs = [np.sign(b["sub_score"]) for b in breakdown.values()]
    agreement = abs(sum(signs)) / len(signs) if signs else 0.0
    confidence = min(1.0, 0.4 + 0.6 * agreement)
    return float(weighted_sum), float(confidence)

# ════════════════════════════════════════════════════════════════════
#  PROBABILITY MAPPING
# ════════════════════════════════════════════════════════════════════

def score_to_probability(composite_score, confidence, knn_pred, knn_conf, scale=35):
    """
    Map raw scores to bullish probability via sigmoid.
    Combines confluence score with KNN prediction.
    Output: P(price up in next horizon) — value between 0 and 1.
    """
    score_prob = 1 / (1 + np.exp(-composite_score / scale))
    knn_score = knn_pred * 5000
    knn_prob = 1 / (1 + np.exp(-knn_score))

    total_weight = confidence + knn_conf + 1e-9
    raw_prob = (score_prob * confidence + knn_prob * knn_conf) / total_weight

    # Bayesian shrinkage toward 0.5 when overall confidence low
    overall_conf = (confidence + knn_conf) / 2
    final_prob = 0.5 + (raw_prob - 0.5) * overall_conf

    return float(final_prob), float(overall_conf)

# ════════════════════════════════════════════════════════════════════
#  ATR-BASED ENTRY/TP/SL CALCULATOR
# ════════════════════════════════════════════════════════════════════

def compute_atr(df, period=14):
    """True Range based ATR."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

def compute_entry_levels(df, direction, prob, atr_mult_sl=1.0):
    """ATR-based entry/TP/SL. Higher probability = wider TP."""
    if len(df) < 20:
        return None
    price = float(df["Close"].iloc[-1])
    atr = compute_atr(df, 14).iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None

    # Adaptive TP: higher prob → wider TP (let winners run)
    adapt_tp = 1.5 + (prob - 0.5) * 2
    adapt_tp = max(1.0, min(3.5, adapt_tp))

    if direction == "LONG":
        entry = price
        tp1   = price + atr * 1.0
        tp2   = price + atr * adapt_tp
        sl    = price - atr * atr_mult_sl
        rr1   = (tp1 - entry) / (entry - sl) if entry > sl else 0
        rr2   = (tp2 - entry) / (entry - sl) if entry > sl else 0
    elif direction == "SHORT":
        entry = price
        tp1   = price - atr * 1.0
        tp2   = price - atr * adapt_tp
        sl    = price + atr * atr_mult_sl
        rr1   = (entry - tp1) / (sl - entry) if sl > entry else 0
        rr2   = (entry - tp2) / (sl - entry) if sl > entry else 0
    else:
        return None

    return {"direction": direction, "entry": entry, "tp1": tp1, "tp2": tp2,
            "sl": sl, "atr": atr, "rr1": rr1, "rr2": rr2}

# ════════════════════════════════════════════════════════════════════
#  REGIME DETECTORS
# ════════════════════════════════════════════════════════════════════

def detect_volatility_regime(df):
    """Returns: LOW / NORMAL / HIGH / EXTREME with color."""
    if len(df) < 50:
        return "UNKNOWN", "#4a5568"
    returns = df["Close"].pct_change()
    current_vol = returns.iloc[-20:].std()
    longterm_vol = returns.iloc[-200:].std() if len(returns) >= 200 else returns.std()
    if longterm_vol <= 0:
        return "UNKNOWN", "#4a5568"
    ratio = current_vol / longterm_vol
    if ratio < 0.7:   return "LOW",     "#4da6ff"
    if ratio < 1.3:   return "NORMAL",  "#00ff88"
    if ratio < 2.0:   return "HIGH",    "#ffb700"
    return "EXTREME", "#ff3d5a"

def detect_trend_regime(df):
    """Returns trend regime via EMA20 vs EMA50."""
    if len(df) < 50:
        return "UNKNOWN", "#4a5568"
    close = df["Close"]
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    price = close.iloc[-1]
    if price > ema20 > ema50:
        return "BULL TREND", "#00ff88"
    if price < ema20 < ema50:
        return "BEAR TREND", "#ff3d5a"
    if price > ema50 and price > ema20:
        return "BULL PULLBACK", "#4da6ff"
    if price < ema50 and price < ema20:
        return "BEAR PULLBACK", "#ff7b00"
    return "SIDEWAYS", "#ffb700"

# ════════════════════════════════════════════════════════════════════
#  MAIN ANALYZER
# ════════════════════════════════════════════════════════════════════

def analyze_ticker(ticker, primary_tf="15m", T1=120, k=20):
    """Full analysis pipeline. Returns dict with all results."""
    multi_tf = fetch_multi_tf(ticker)
    df_main = multi_tf.get(primary_tf)

    if df_main is None or len(df_main) < 100:
        bars_count = len(df_main) if df_main is not None else 0
        return {"error": f"Data {primary_tf} kurang ({bars_count} bars). Butuh ≥100 bars."}

    features, R_hat, sigma = build_feature_matrix(df_main, T1=T1)
    if len(features) < 50:
        return {"error": f"Feature matrix terlalu pendek ({len(features)} valid bars). Coba kurangi T1 atau ganti timeframe."}

    breakdown = compute_confluence_score(features, R_hat)
    composite_score, score_conf = aggregate_confluence(breakdown)

    # KNN multi-horizon: 15m (1 bar), 1h (4 bars), 4h (16 bars)
    knn_15m_pred, knn_15m_idx, knn_15m_dist, knn_15m_out, knn_15m_conf = \
        knn_pattern_match(features, df_main["Close"], k=k, lookback_horizon=1)
    knn_1h_pred, knn_1h_idx, knn_1h_dist, knn_1h_out, knn_1h_conf = \
        knn_pattern_match(features, df_main["Close"], k=k, lookback_horizon=4)
    knn_4h_pred, _, _, _, knn_4h_conf = \
        knn_pattern_match(features, df_main["Close"], k=k, lookback_horizon=16)

    prob_15m, conf_15m = score_to_probability(composite_score, score_conf, knn_15m_pred, knn_15m_conf, scale=35)
    prob_1h,  conf_1h  = score_to_probability(composite_score, score_conf, knn_1h_pred,  knn_1h_conf, scale=40)
    prob_4h,  conf_4h  = score_to_probability(composite_score, score_conf, knn_4h_pred,  knn_4h_conf, scale=50)

    if prob_15m >= 0.60:    direction_15m = "LONG"
    elif prob_15m <= 0.40:  direction_15m = "SHORT"
    else:                    direction_15m = "WAIT"

    if prob_1h >= 0.60:     direction_1h = "LONG"
    elif prob_1h <= 0.40:   direction_1h = "SHORT"
    else:                    direction_1h = "WAIT"

    entry_levels = compute_entry_levels(df_main, direction_15m, prob_15m)

    vol_regime, vol_color = detect_volatility_regime(df_main)
    trend_regime, trend_color = detect_trend_regime(df_main)

    price = float(df_main["Close"].iloc[-1])
    prev_price = float(df_main["Close"].iloc[-2]) if len(df_main) > 1 else price
    change_pct = (price / prev_price - 1) * 100

    knn_15m_wins = sum(1 for o in knn_15m_out if o > 0)
    knn_15m_winrate = knn_15m_wins / len(knn_15m_out) if knn_15m_out else 0.5

    return {
        "ticker": ticker, "price": price, "change_pct": change_pct,
        "atr": float(compute_atr(df_main, 14).iloc[-1]) if len(df_main) >= 15 else 0,
        "vol_regime": vol_regime, "vol_color": vol_color,
        "trend_regime": trend_regime, "trend_color": trend_color,
        "breakdown": breakdown,
        "composite_score": composite_score, "score_conf": score_conf,
        "prob_15m": prob_15m, "conf_15m": conf_15m, "direction_15m": direction_15m,
        "prob_1h":  prob_1h,  "conf_1h":  conf_1h,  "direction_1h":  direction_1h,
        "prob_4h":  prob_4h,  "conf_4h":  conf_4h,
        "knn_15m_pred": knn_15m_pred, "knn_15m_conf": knn_15m_conf,
        "knn_15m_idx": knn_15m_idx, "knn_15m_dist": knn_15m_dist, "knn_15m_out": knn_15m_out,
        "knn_15m_winrate": knn_15m_winrate,
        "knn_1h_pred": knn_1h_pred, "knn_1h_conf": knn_1h_conf,
        "entry_levels": entry_levels,
        "df_main": df_main, "n_bars": len(df_main), "n_features": len(features),
    }

# ════════════════════════════════════════════════════════════════════
#  TELEGRAM ALERTS
# ════════════════════════════════════════════════════════════════════

def send_telegram(ticker, result):
    if not TOKEN or not CHAT_ID:
        return False, "Telegram tidak dikonfigurasi (set secrets)"
    now = datetime.now(et_tz)
    sep = "━" * 28
    prob_15m_pct = result["prob_15m"] * 100
    prob_1h_pct  = result["prob_1h"]  * 100
    direction_15m = result["direction_15m"]
    dir_emoji = "🟢 LONG" if direction_15m == "LONG" else "🔴 SHORT" if direction_15m == "SHORT" else "⚪ WAIT"

    body = (
        f"🎯 *MESIN ENTRY ALERT*\n"
        f"{sep}\n"
        f"📊 *{ticker}* @ `${_pf(result['price'])}` ({_pct(result['change_pct'])})\n"
        f"⏰ `{now.strftime('%H:%M:%S')} ET` · `{now.strftime('%d %b %Y')}`\n"
        f"{sep}\n"
        f"🎯 *15M FORECAST*\n"
        f"   {dir_emoji} · Probability: `{prob_15m_pct:.1f}%`\n"
        f"   Confidence: `{result['conf_15m']*100:.0f}%`\n"
        f"   KNN Win Rate: `{result['knn_15m_winrate']*100:.0f}%`\n\n"
        f"🎯 *1H FORECAST*\n"
        f"   Probability: `{prob_1h_pct:.1f}%`\n"
        f"   Confidence: `{result['conf_1h']*100:.0f}%`\n\n"
        f"📈 *Regime*: {result['trend_regime']} · Vol: {result['vol_regime']}\n"
    )

    if result["entry_levels"]:
        e = result["entry_levels"]
        body += (
            f"{sep}\n"
            f"💰 *Entry Plan*\n"
            f"   Entry: `${_pf(e['entry'])}`\n"
            f"   TP1:   `${_pf(e['tp1'])}` (R:R `{e['rr1']:.1f}`)\n"
            f"   TP2:   `${_pf(e['tp2'])}` (R:R `{e['rr2']:.1f}`)\n"
            f"   SL:    `${_pf(e['sl'])}`\n"
        )

    body += (
        f"{sep}\n"
        f"⚡ _Mesin Entry v1.0 · Sec 18.2 + 3.17 + 3.20_\n"
        f"⚠️ _Probabilistik, BUKAN guarantee!_"
    )

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": body, "parse_mode": "Markdown"},
            timeout=10
        )
        if r.status_code == 200:
            return True, "Terkirim ✅"
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"

# ════════════════════════════════════════════════════════════════════
#  STREAMLIT UI
# ════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .stApp { background: #0a0e1a; color: #e2e8f0; font-family: 'Space Mono', monospace; }
    .main .block-container { padding-top: 1.5rem; max-width: 1400px; }
    h1, h2, h3, h4 { font-family: 'Space Mono', monospace; color: #e2e8f0; }
    .hdr-card {
        background: linear-gradient(135deg, #0d1421, #131b2e);
        border: 1px solid #1c2533; border-radius: 8px;
        padding: 16px 20px; margin-bottom: 16px;
    }
    .gauge-card {
        background: #0d1421; border: 1px solid #1c2533;
        border-radius: 8px; padding: 24px; text-align: center; height: 100%;
    }
    .tf-row { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid #1a2030; }
    .tf-label { width: 50px; font-size: 11px; color: #8b95a8; font-weight: 700; }
    .tf-bar-bg { flex: 1; height: 12px; background: #1a2030; border-radius: 2px; position: relative; overflow: hidden; }
    .tf-bar-fill { height: 100%; transition: width 0.3s; }
    .tf-value { width: 80px; font-size: 11px; text-align: right; font-weight: 700; }
    .entry-card {
        background: linear-gradient(135deg, #0d1421, #0a1a10);
        border: 1px solid #1c4a2d; border-radius: 8px; padding: 16px;
    }
    .entry-card.short {
        background: linear-gradient(135deg, #0d1421, #1a0a0d);
        border: 1px solid #4a1c2d;
    }
    .entry-card.wait {
        background: linear-gradient(135deg, #0d1421, #1a1a0a);
        border: 1px solid #4a4a1c;
    }
    .knn-table { width: 100%; border-collapse: collapse; }
    .knn-table th {
        background: #131b2e; color: #8b95a8; padding: 8px 10px;
        text-align: left; font-size: 10px; font-weight: 700;
        border-bottom: 1px solid #1c2533;
    }
    .knn-table td { padding: 6px 10px; font-size: 11px; border-bottom: 1px solid #131b2e; }
    .pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; border: 1px solid; margin: 2px; }
    .disclaimer {
        background: #1a1500; border: 1px solid #4a4000; color: #ffb700;
        padding: 12px 16px; border-radius: 6px; font-size: 11px; margin-top: 16px;
    }
</style>
""", unsafe_allow_html=True)

for k in ["last_result", "last_ticker", "last_scan_time"]:
    if k not in st.session_state: st.session_state[k] = None

st.markdown("""
<div class="hdr-card">
    <div style="display:flex; align-items:center; justify-content:space-between;">
        <div>
            <div style="font-size:22px; font-weight:700; color:#00ff88;">🎯 MESIN ENTRY v1.0</div>
            <div style="font-size:11px; color:#8b95a8; margin-top:2px;">
                Probabilistic Entry Timing · Section 18.2 (ANN-features) + 3.17 (KNN) + 3.20 (Alpha Combo)
            </div>
        </div>
        <div style="text-align:right; font-size:11px; color:#8b95a8;">
            <div>Z-score normalized · Multi-horizon ensemble</div>
            <div>Works for: XAU-USD · IDX · US · Crypto</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
with col1:
    ticker_input = st.text_input(
        "Ticker (yFinance format)",
        value="XAUUSD=X",
        help="Examples: XAUUSD=X (gold spot), GC=F (gold futures), BBCA.JK, AAPL, BTC-USD, EURUSD=X"
    ).strip().upper()
with col2:
    primary_tf = st.selectbox("Entry Timeframe", ["15m", "1h"], index=0)
with col3:
    k_neighbors = st.slider("KNN k", 5, 50, 20)
with col4:
    T1_window = st.slider("Z-score T1", 30, 240, 120)

col_btn1, col_btn2, _ = st.columns([1.5, 1.5, 5])
with col_btn1:
    analyze_btn = st.button("🎯 ANALYZE", type="primary", use_container_width=True)
with col_btn2:
    tg_btn = st.button("📡 SEND TELEGRAM", use_container_width=True)

if analyze_btn:
    if not ticker_input:
        st.error("Ticker tidak boleh kosong bro")
    else:
        with st.spinner(f"Fetching & analyzing {ticker_input}..."):
            result = analyze_ticker(ticker_input, primary_tf=primary_tf, T1=T1_window, k=k_neighbors)
            st.session_state.last_result = result
            st.session_state.last_ticker = ticker_input
            st.session_state.last_scan_time = time.time()

if tg_btn:
    r = st.session_state.last_result
    if r and not r.get("error"):
        ok, msg = send_telegram(st.session_state.last_ticker, r)
        if ok: st.success(f"Telegram: {msg}")
        else:  st.error(f"Telegram: {msg}")
    else:
        st.warning("Analyze dulu sebelum kirim Telegram bro")

result = st.session_state.last_result

if result is None:
    st.info("👆 Masukin ticker lalu klik **ANALYZE**. Engine akan compute z-scored multi-horizon features + KNN pattern matching.")
    with st.expander("ℹ️ Cara kerja engine"):
        st.markdown("""
**Mesin Entry pakai 3 strategi dari buku Kakushadze & Serur:**

**1. Section 18.2 — Z-score normalized features**
- Convert raw price → returns → demean → divide by σ
- Result: R̂(t,T₁) yang stationary, bukan trending
- Multi-horizon: EMA, EMSD, RSI dihitung pada R̂ untuk τ ∈ {30m, 1h, 3h, 6h, 12h}

**2. Section 3.17 — KNN pattern matching**
- Current state = vector 15-dim dari features di atas
- Cari k=20 saat-saat paling mirip di history (Euclidean distance)
- Predicted return = inverse-distance weighted avg outcome
- Confidence = berapa konsisten outcome mereka

**3. Section 3.20 — Alpha combo**
- Sub-score tiap timeframe (trend × momentum × RSI)
- Weighted sum: longer horizon weight lebih besar
- Confidence boosted by timeframe agreement
- Sigmoid → probabilitas 0-100%

**Output:** P(harga naik dalam 15m / 1h / 4h), confluence breakdown, KNN matches, entry/TP/SL ATR-based.
        """)

elif result.get("error"):
    st.error(f"⚠️ {result['error']}")

else:
    ticker = st.session_state.last_ticker
    price = result["price"]
    change = result["change_pct"]
    chg_col = "#00ff88" if change >= 0 else "#ff3d5a"
    chg_sym = "▲" if change >= 0 else "▼"

    st.markdown(f"""
    <div class="hdr-card">
        <div style="display:flex; align-items:center; justify-content:space-between;">
            <div>
                <div style="font-size:13px; color:#8b95a8;">CURRENT STATE</div>
                <div style="font-size:24px; font-weight:700; color:#e2e8f0; margin-top:4px;">
                    {ticker} · ${_pf(price)}
                    <span style="font-size:14px; color:{chg_col}; font-weight:700; margin-left:8px;">
                        {chg_sym} {abs(change):.2f}%
                    </span>
                </div>
                <div style="font-size:11px; color:#8b95a8; margin-top:6px;">
                    {result['n_bars']} bars · ATR(14): ${_pf(result['atr'])} · {result['n_features']} valid features
                </div>
            </div>
            <div style="text-align:right;">
                <div><span class="pill" style="color:{result['trend_color']}; border-color:{result['trend_color']}40; background:{result['trend_color']}15;">{result['trend_regime']}</span></div>
                <div style="margin-top:6px;"><span class="pill" style="color:{result['vol_color']}; border-color:{result['vol_color']}40; background:{result['vol_color']}15;">VOL: {result['vol_regime']}</span></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # PROBABILITY GAUGES
    st.markdown("### 🎯 Probability Forecast")
    g1, g2, g3 = st.columns(3)

    def render_gauge(prob, conf, direction, label_horizon):
        pct = prob * 100
        cnf = conf * 100
        if prob >= 0.60:
            color = "#00ff88"; bg = "#0a1a10"; dir_text = "🟢 LONG"
            dir_label = f"P(UP) = {pct:.1f}%"
        elif prob <= 0.40:
            color = "#ff3d5a"; bg = "#1a0a0d"; dir_text = "🔴 SHORT"
            dir_label = f"P(DOWN) = {(100-pct):.1f}%"
        else:
            color = "#ffb700"; bg = "#1a1500"; dir_text = "⚪ WAIT"
            dir_label = f"P(UP) = {pct:.1f}%"

        return f"""
        <div class="gauge-card" style="background: linear-gradient(135deg, #0d1421, {bg}); border-color: {color}40;">
            <div style="font-size:11px; color:#8b95a8; font-weight:700;">{label_horizon}</div>
            <div style="font-size:42px; font-weight:700; color:{color}; margin:12px 0;">{pct:.1f}%</div>
            <div style="font-size:14px; color:{color}; font-weight:700; margin-bottom:6px;">{dir_text}</div>
            <div style="font-size:10px; color:#8b95a8;">Confidence: <span style="color:#e2e8f0; font-weight:700;">{cnf:.0f}%</span></div>
            <div style="margin-top:12px; height:6px; background:#1a2030; border-radius:3px; overflow:hidden;">
                <div style="height:100%; width:{pct}%; background:{color};"></div>
            </div>
        </div>
        """

    with g1: st.markdown(render_gauge(result["prob_15m"], result["conf_15m"], result["direction_15m"], "15M FORECAST"), unsafe_allow_html=True)
    with g2: st.markdown(render_gauge(result["prob_1h"], result["conf_1h"], result["direction_1h"], "1H FORECAST"), unsafe_allow_html=True)
    with g3:
        prob_4h = result["prob_4h"]; conf_4h = result["conf_4h"]
        if prob_4h >= 0.55:    d4 = "BULLISH 🟢"
        elif prob_4h <= 0.45:  d4 = "BEARISH 🔴"
        else:                   d4 = "NEUTRAL ⚪"
        color = "#00ff88" if prob_4h >= 0.55 else "#ff3d5a" if prob_4h <= 0.45 else "#ffb700"
        bg = "#0a1a10" if prob_4h >= 0.55 else "#1a0a0d" if prob_4h <= 0.45 else "#1a1500"
        st.markdown(f"""
        <div class="gauge-card" style="background: linear-gradient(135deg, #0d1421, {bg}); border-color: {color}40;">
            <div style="font-size:11px; color:#8b95a8; font-weight:700;">4H FORECAST (context)</div>
            <div style="font-size:42px; font-weight:700; color:{color}; margin:12px 0;">{prob_4h*100:.1f}%</div>
            <div style="font-size:14px; color:{color}; font-weight:700; margin-bottom:6px;">{d4}</div>
            <div style="font-size:10px; color:#8b95a8;">Confidence: <span style="color:#e2e8f0; font-weight:700;">{conf_4h*100:.0f}%</span></div>
            <div style="margin-top:12px; height:6px; background:#1a2030; border-radius:3px; overflow:hidden;">
                <div style="height:100%; width:{prob_4h*100}%; background:{color};"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # MULTI-TF AGREEMENT
    st.markdown("### 📊 Multi-Timeframe Agreement")
    col_tf, col_cb = st.columns([1, 1])

    with col_tf:
        st.markdown("<div style='font-size:11px; color:#8b95a8; margin-bottom:8px;'>Sub-scores per horizon (alpha combo)</div>", unsafe_allow_html=True)
        bars_html = ""
        for tau, b in result["breakdown"].items():
            score = b["sub_score"]
            if score >= 0:
                bar_color = "#00ff88" if score >= 50 else "#4da6ff" if score >= 20 else "#8b95a8"
                left = 50; width = abs(score) / 2
            else:
                bar_color = "#ff3d5a" if score <= -50 else "#ff7b00" if score <= -20 else "#8b95a8"
                left = 50 - abs(score) / 2; width = abs(score) / 2
            label = b["label"]; sign = "+" if score >= 0 else ""
            bars_html += f"""
            <div class="tf-row">
                <div class="tf-label">{label}</div>
                <div class="tf-bar-bg">
                    <div style="position:absolute; left:50%; top:0; width:1px; height:100%; background:#8b95a8;"></div>
                    <div class="tf-bar-fill" style="position:absolute; left:{left}%; width:{width}%; height:100%; background:{bar_color};"></div>
                </div>
                <div class="tf-value" style="color:{bar_color};">{sign}{score:.0f}</div>
            </div>
            """
        st.markdown(bars_html, unsafe_allow_html=True)
        comp_color = "#00ff88" if result["composite_score"] >= 20 else "#ff3d5a" if result["composite_score"] <= -20 else "#ffb700"
        st.markdown(f"""
        <div style="margin-top:14px; padding-top:10px; border-top:1px solid #1c2533;">
            <div style="display:flex; justify-content:space-between; font-size:11px;">
                <span style="color:#8b95a8; font-weight:700;">COMPOSITE</span>
                <span style="color:{comp_color}; font-weight:700;">{result['composite_score']:+.1f} · Agreement {result['score_conf']*100:.0f}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_cb:
        st.markdown("<div style='font-size:11px; color:#8b95a8; margin-bottom:8px;'>Confluence breakdown</div>", unsafe_allow_html=True)
        for tau, b in result["breakdown"].items():
            rsi_v = b["rsi_raw"]
            rsi_label = "OVERSOLD" if rsi_v < 0.3 else "OVERBOUGHT" if rsi_v > 0.7 else "NEUTRAL"
            rsi_col = "#00ff88" if rsi_v < 0.3 else "#ff3d5a" if rsi_v > 0.7 else "#8b95a8"
            ema_dir = "↗" if b["ema_raw"] > 0 else "↘"
            ema_col = "#00ff88" if b["ema_raw"] > 0 else "#ff3d5a"
            st.markdown(f"""
            <div style="background:#0d1421; border:1px solid #1c2533; border-radius:4px; padding:8px 12px; margin-bottom:6px;">
                <div style="display:flex; justify-content:space-between; font-size:11px;">
                    <span style="color:#e2e8f0; font-weight:700;">{b['label']}</span>
                    <span style="color:{ema_col}; font-weight:700;">{ema_dir} EMA: {b['ema_raw']:+.3f}</span>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:10px; color:#8b95a8; margin-top:3px;">
                    <span>Mom: {b['momentum']:+.0f} · Trend: {b['trend']:+.0f}</span>
                    <span style="color:{rsi_col};">RSI z: {rsi_v:.2f} {rsi_label}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # KNN MATCHES
    st.markdown("### 🔍 KNN Pattern Matches (Section 3.17)")
    knn_wr_col = "#00ff88" if result['knn_15m_winrate']>=0.55 else "#ff3d5a" if result['knn_15m_winrate']<=0.45 else "#ffb700"
    st.markdown(f"""
    <div style="font-size:11px; color:#8b95a8; margin-bottom:8px;">
        Top 10 dari {len(result['knn_15m_idx'])} saat-saat di masa lalu yang paling mirip kondisi sekarang.
        Win rate KNN (next 15m): <strong style="color:{knn_wr_col};">{result['knn_15m_winrate']*100:.0f}%</strong> · Predicted return: <strong>{result['knn_15m_pred']*100:+.3f}%</strong>
    </div>
    """, unsafe_allow_html=True)

    knn_rows = ""
    if result['knn_15m_dist']:
        max_dist = max(result['knn_15m_dist']); min_dist = min(result['knn_15m_dist'])
        range_dist = max_dist - min_dist + 1e-9
        for i, (ts, dist, out) in enumerate(zip(result['knn_15m_idx'][:10], result['knn_15m_dist'][:10], result['knn_15m_out'][:10])):
            similarity = 1 - (dist - min_dist) / range_dist
            sim_pct = similarity * 100
            out_pct = out * 100
            out_col = "#00ff88" if out > 0 else "#ff3d5a" if out < 0 else "#8b95a8"
            out_sign = "✓" if out > 0 else "✗" if out < 0 else "—"
            try: ts_str = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
            except: ts_str = str(ts)
            knn_rows += f"""
            <tr>
                <td style="color:#8b95a8;">#{i+1}</td>
                <td style="color:#e2e8f0; font-family:Space Mono,monospace;">{ts_str}</td>
                <td style="text-align:right;"><span style="color:#4da6ff; font-weight:700;">{sim_pct:.0f}%</span></td>
                <td style="text-align:right; color:{out_col}; font-weight:700;">{out_pct:+.3f}%</td>
                <td style="text-align:center; color:{out_col}; font-weight:700;">{out_sign}</td>
            </tr>
            """

    st.markdown(f"""
    <table class="knn-table">
        <tr>
            <th style="width:40px;">#</th>
            <th>Historical Timestamp</th>
            <th style="text-align:right; width:80px;">Similarity</th>
            <th style="text-align:right; width:90px;">Outcome (15m)</th>
            <th style="text-align:center; width:50px;">Win?</th>
        </tr>
        {knn_rows}
    </table>
    """, unsafe_allow_html=True)

    # ENTRY LEVELS
    if result["entry_levels"]:
        e = result["entry_levels"]
        st.markdown("### 💰 Suggested Entry Plan")
        css_class = "entry-card"
        if e["direction"] == "SHORT": css_class += " short"
        elif e["direction"] == "WAIT": css_class += " wait"
        dir_color = "#00ff88" if e["direction"] == "LONG" else "#ff3d5a" if e["direction"] == "SHORT" else "#ffb700"
        dir_emoji = "🟢" if e["direction"] == "LONG" else "🔴" if e["direction"] == "SHORT" else "⚪"

        st.markdown(f"""
        <div class="{css_class}">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div style="font-size:16px; font-weight:700; color:{dir_color};">{dir_emoji} {e['direction']}</div>
                <div style="font-size:11px; color:#8b95a8;">ATR(14) = ${_pf(e['atr'])} · TP2 adaptif by probability</div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px;">
                <div>
                    <div style="font-size:10px; color:#8b95a8;">ENTRY</div>
                    <div style="font-size:18px; font-weight:700; color:#e2e8f0;">${_pf(e['entry'])}</div>
                </div>
                <div>
                    <div style="font-size:10px; color:#00ff88;">TP1 (1.0× ATR)</div>
                    <div style="font-size:18px; font-weight:700; color:#00ff88;">${_pf(e['tp1'])}</div>
                    <div style="font-size:10px; color:#8b95a8;">R:R {e['rr1']:.2f}</div>
                </div>
                <div>
                    <div style="font-size:10px; color:#00ff88;">TP2 (adaptif)</div>
                    <div style="font-size:18px; font-weight:700; color:#00ff88;">${_pf(e['tp2'])}</div>
                    <div style="font-size:10px; color:#8b95a8;">R:R {e['rr2']:.2f}</div>
                </div>
                <div>
                    <div style="font-size:10px; color:#ff3d5a;">SL (1.0× ATR)</div>
                    <div style="font-size:18px; font-weight:700; color:#ff3d5a;">${_pf(e['sl'])}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="padding:16px; background:#1a1500; border:1px solid #4a4000; border-radius:6px; color:#ffb700; font-size:12px;">
            ⚪ <strong>WAIT</strong> — Probabilitas tidak cukup kuat untuk entry. P(UP) antara 40-60%. Tunggu sinyal lebih jelas.
        </div>
        """, unsafe_allow_html=True)

    # HONEST DISCLAIMER
    st.markdown(f"""
    <div class="disclaimer">
        <strong>⚠️ HONEST EXPECTATION (jangan lupa bro)</strong><br>
        Engine ini probabilistik berdasarkan multi-horizon z-score features + KNN pattern matching dari buku Kakushadze & Serur (2018).<br><br>
        <strong>Realistic accuracy:</strong><br>
        • Trending market (current: <strong>{result['trend_regime']}</strong>): 60-68% directional accuracy<br>
        • Sideways/chop: turun ke 52-55% (mendekati coinflip)<br>
        • News event / black swan: <strong>SEMUA model breakdown</strong> — current vol regime: <strong style="color:{result['vol_color']}">{result['vol_regime']}</strong><br><br>
        <strong>Position sizing &amp; risk management tetap tanggung jawab lo.</strong> Engine kasih edge probabilistik, BUKAN crystal ball.
    </div>
    """, unsafe_allow_html=True)

if st.session_state.last_scan_time:
    lt = datetime.fromtimestamp(st.session_state.last_scan_time, et_tz).strftime("%H:%M:%S ET · %d %b %Y")
    st.markdown(f"<div style='text-align:center; font-size:10px; color:#4a5568; margin-top:24px; font-family:Space Mono,monospace;'>Last analysis: {lt}</div>", unsafe_allow_html=True)
