# ═══════════════════════════════════════════════════════════════════
#  MESIN ENTRY v1.1 — Probabilistic Entry Timing Engine
#  Based on Kakushadze & Serur (2018) "151 Trading Strategies"
#  Primary recipes:
#    • Section 18.2 — ANN features (z-score normalized returns)
#    • Section 3.17 — KNN single-asset pattern matching
#    • Section 3.20 — Alpha combo (proper signal combination)
#  Supports: Scalping (5m) → Intraday (15-30m) → Swing (1h-1d) → Bagger (1wk)
#  Markets:  IDX (auto .JK), US, Crypto (auto -USD), FX (auto =X), Commodity
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
    page_title="Mesin Entry v1.1",
    page_icon="🎯",
    initial_sidebar_state="collapsed"
)

# ─── MARKET AUTO-SUFFIX ────────────────────────────────────────────
MARKET_SUFFIX = {
    "IDX (Indonesia)":   ".JK",   # BBCA → BBCA.JK
    "US Stocks":         "",      # AAPL stays AAPL
    "Crypto":            "-USD",  # BTC → BTC-USD
    "FX / Forex":        "=X",    # EURUSD → EURUSD=X
    "Commodity":         "",      # GC=F, XAUUSD=X stays as-is
}

# ─── COMMODITY ALIAS MAP ──────────────────────────────────────────
# yFinance punya known issues dengan FX-style commodity spot (XAUUSD=X dll):
# data sub-hourly sering kosong walaupun ticker valid. Solusi: auto-remap ke
# futures equivalent (GC=F, SI=F, dll) yang DATA-NYA RELIABLE di yFinance.
COMMODITY_ALIAS = {
    # Precious metals
    "XAUUSD": "GC=F",   # Gold spot → Gold futures (yFinance reliable)
    "GOLD":   "GC=F",
    "XAGUSD": "SI=F",   # Silver spot → Silver futures
    "SILVER": "SI=F",
    "XPTUSD": "PL=F",   # Platinum
    "PLATINUM": "PL=F",
    "XPDUSD": "PA=F",   # Palladium
    # Energy
    "WTIUSD":  "CL=F",  # WTI Crude
    "USOIL":   "CL=F",
    "OIL":     "CL=F",
    "WTI":     "CL=F",
    "BCOUSD":  "BZ=F",  # Brent Crude
    "UKOIL":   "BZ=F",
    "BRENT":   "BZ=F",
    "NGAS":    "NG=F",  # Natural Gas
    "NATGAS":  "NG=F",
    "GASOIL":  "HO=F",  # Heating oil
    # Base metals
    "COPPER":  "HG=F",
    "HGUSD":   "HG=F",
    # Agriculturals
    "CORN":    "ZC=F",
    "WHEAT":   "ZW=F",
    "SOYBEAN": "ZS=F",
    "COFFEE":  "KC=F",
    "SUGAR":   "SB=F",
    "COCOA":   "CC=F",
    "COTTON":  "CT=F",
}

def format_ticker(raw_ticker, market):
    """Auto-add suffix based on selected market. Idempotent."""
    t = raw_ticker.strip().upper()
    if not t: return ""
    # If user already typed full yFinance format (with suffix), keep it
    has_suffix = any(s in t for s in [".JK", "-USD", "=X", "=F", "^"])
    if has_suffix: return t

    # Smart suffix logic per market
    if market == "Commodity":
        # PRIORITY 1: Known alias map (XAUUSD→GC=F because yFinance spot data unreliable)
        if t in COMMODITY_ALIAS:
            return COMMODITY_ALIAS[t]
        # PRIORITY 2: 5+ letter ending in currency code = spot pair (try =X for less common pairs)
        currency_endings = ("USD","EUR","JPY","GBP","CHF","AUD","CAD","CNY","SGD","HKD")
        if len(t) >= 5 and t.endswith(currency_endings):
            return f"{t}=X"
        # PRIORITY 3: Exactly 2 letters alpha = futures code (GC, SI, CL, HG, NG, ES, NQ, etc.)
        if len(t) == 2 and t.isalpha():
            return f"{t}=F"
        # FALLBACK: 3+ letter codes = ETF or stock-like (GLD, IAU, USO, SLV, DBA) → no suffix
        return t

    suffix = MARKET_SUFFIX.get(market, "")
    return f"{t}{suffix}" if suffix else t

# ─── TIMEFRAME CONFIG — driven by trading style ────────────────────
# Each TF defines: data period, multi-horizon τ for features,
# forecast horizons (how far ahead to predict), and default T1 window.
TF_CONFIG = {
    "5m": {
        "label": "Scalping ⚡",
        "period": "60d",  # yFinance max for 5m
        "min_bars": 200,
        "tau_bars":   [3, 6, 12, 24, 48],          # 15m, 30m, 1h, 2h, 4h
        "tau_labels": ["15m", "30m", "1h", "2h", "4h"],
        "forecast_bars":   [1, 3, 12],              # 5m, 15m, 1h
        "forecast_labels": ["5M", "15M", "1H"],
        "default_T1": 96,                           # ~8 hours
    },
    "15m": {
        "label": "Intraday 📊",
        "period": "60d",
        "min_bars": 150,
        "tau_bars":   [2, 4, 12, 24, 48],          # 30m, 1h, 3h, 6h, 12h
        "tau_labels": ["30m", "1h", "3h", "6h", "12h"],
        "forecast_bars":   [1, 4, 16],              # 15m, 1h, 4h
        "forecast_labels": ["15M", "1H", "4H"],
        "default_T1": 120,                          # ~30 hours
    },
    "30m": {
        "label": "Intraday 📊",
        "period": "60d",
        "min_bars": 100,
        "tau_bars":   [2, 4, 8, 16, 32],           # 1h, 2h, 4h, 8h, 16h
        "tau_labels": ["1h", "2h", "4h", "8h", "16h"],
        "forecast_bars":   [1, 2, 8],               # 30m, 1h, 4h
        "forecast_labels": ["30M", "1H", "4H"],
        "default_T1": 96,                           # ~2 days
    },
    "1h": {
        "label": "Swing Entry 🎯",
        "period": "730d",
        "min_bars": 80,
        "tau_bars":   [2, 4, 8, 24, 48],           # 2h, 4h, 8h, 1d, 2d
        "tau_labels": ["2h", "4h", "8h", "1d", "2d"],
        "forecast_bars":   [1, 4, 24],              # 1h, 4h, 1d
        "forecast_labels": ["1H", "4H", "1D"],
        "default_T1": 120,                          # ~5 days
    },
    "1d": {
        "label": "Swing/Position 📈",
        "period": "10y",
        "min_bars": 80,
        "tau_bars":   [2, 5, 10, 20, 60],          # 2d, 1w, 2w, 1mo, 3mo
        "tau_labels": ["2d", "1w", "2w", "1mo", "3mo"],
        "forecast_bars":   [1, 5, 22],              # 1d, 1w, 1mo
        "forecast_labels": ["1D", "1W", "1MO"],
        "default_T1": 100,                          # ~5 months
    },
    "1wk": {
        "label": "Bagger 💎",
        "period": "10y",
        "min_bars": 50,
        "tau_bars":   [2, 4, 8, 13, 26],           # 2w, 1mo, 2mo, 3mo, 6mo
        "tau_labels": ["2w", "1mo", "2mo", "3mo", "6mo"],
        "forecast_bars":   [1, 4, 13],              # 1w, 1mo, 3mo
        "forecast_labels": ["1W", "1MO", "3MO"],
        "default_T1": 60,                           # ~1.3 years
    },
}

# ─── SMART PRICE FORMATTER ────────────────────────────────────────
def _curr(market):
    """Currency symbol: Rp for IDX (user trades in Rupiah), $ for everything else."""
    return "Rp" if market == "IDX (Indonesia)" else "$"

def _pf(price):
    """Smart number formatter (handles wide price range: $0.00001 to $100,000)."""
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

def _pf_idx(price):
    """IDR formatter - integer with thousand separators (saham IDR jarang ada desimal)."""
    try:
        p = float(price)
        if p <= 0: return "0"
        return f"{p:,.0f}"
    except: return "0"

def _price(price, market):
    """Final formatter: 'Rp 8,975' for IDX, '$2,034.50' for others."""
    sym = _curr(market)
    if market == "IDX (Indonesia)":
        return f"{sym} {_pf_idx(price)}"
    return f"{sym}{_pf(price)}"

def _pct(v, dp=2):
    try: return f"{float(v):+.{dp}f}%"
    except: return "0.00%"

# ─── DATA FETCH (anti-rate-limit) ─────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlcv(ticker, period, interval):
    """3-layer fallback yFinance fetch."""
    try:
        time.sleep(random.uniform(0.05, 0.15))
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, actions=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        try:
            df = yf.download(ticker, period=period, interval=interval,
                            progress=False, threads=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        try:
            df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and len(df) > 0:
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
        except: pass
        return None
    except: return None

def fetch_primary(ticker, tf):
    """Fetch primary timeframe based on TF_CONFIG."""
    cfg = TF_CONFIG[tf]
    return fetch_ohlcv(ticker, cfg["period"], tf)

# ════════════════════════════════════════════════════════════════════
#  CORE ENGINE — Section 18.2 (ANN-style features)
# ════════════════════════════════════════════════════════════════════

def compute_normalized_returns(close, T1):
    """Z-score normalize returns: R̂(t,T1) = (R(t) - meanR_T1) / σ_T1"""
    R = close.pct_change()
    R_mean = R.rolling(T1, min_periods=max(5, T1//3)).mean()
    R_demeaned = R - R_mean
    sigma = R_demeaned.rolling(T1, min_periods=max(5, T1//3)).std()
    R_hat = (R_demeaned / sigma.replace(0, np.nan)).fillna(0)
    return R_hat, R_demeaned, sigma

def compute_ema_features(R_hat, tau):
    lam = (tau - 1) / (tau + 1)
    return R_hat.ewm(alpha=1-lam, adjust=False).mean()

def compute_emsd_features(R_hat, tau):
    lam = (tau - 1) / (tau + 1)
    ema = R_hat.ewm(alpha=1-lam, adjust=False).mean()
    var = ((R_hat - ema) ** 2).ewm(alpha=1-lam, adjust=False).mean()
    return np.sqrt(var)

def compute_rsi_normalized(R_hat, tau):
    pos = R_hat.where(R_hat > 0, 0)
    neg = (-R_hat).where(R_hat < 0, 0)
    sum_pos = pos.rolling(tau, min_periods=2).sum()
    sum_neg = neg.rolling(tau, min_periods=2).sum()
    total = sum_pos + sum_neg
    return (sum_pos / total.replace(0, np.nan)).fillna(0.5)

def build_feature_matrix(df, T1, tau_bars):
    """Build feature matrix with DYNAMIC τ list per timeframe config."""
    close = df["Close"]
    R_hat, R_dem, sigma = compute_normalized_returns(close, T1)
    features = pd.DataFrame(index=df.index)
    features["R_hat"] = R_hat
    for tau in tau_bars:
        features[f"ema_{tau}"]  = compute_ema_features(R_hat, tau)
        features[f"emsd_{tau}"] = compute_emsd_features(R_hat, tau)
        features[f"rsi_{tau}"]  = compute_rsi_normalized(R_hat, tau)
    features = features.dropna()
    return features, R_hat, sigma

# ════════════════════════════════════════════════════════════════════
#  KNN PATTERN MATCHER — Section 3.17
# ════════════════════════════════════════════════════════════════════

def knn_pattern_match(features, close, k=20, lookback_horizon=4):
    if len(features) < 30 or len(close) < 30:
        return 0.0, [], [], [], 0.0
    feature_cols = [c for c in features.columns if c.startswith(('ema_','rsi_'))]
    X = features[feature_cols].values
    close_aligned = close.reindex(features.index).ffill()
    future_close = close_aligned.shift(-lookback_horizon)
    Y = (future_close / close_aligned - 1).values
    valid = ~np.isnan(Y)
    if valid.sum() < k + 5:
        return 0.0, [], [], [], 0.0
    X_hist = X[valid][:-1]; Y_hist = Y[valid][:-1]; X_now = X[-1]
    if np.any(np.isnan(X_now)) or np.any(np.isinf(X_now)):
        return 0.0, [], [], [], 0.0
    X_mean = X_hist.mean(axis=0); X_std = X_hist.std(axis=0) + 1e-9
    X_hist_z = (X_hist - X_mean) / X_std
    X_now_z = (X_now - X_mean) / X_std
    distances = np.linalg.norm(X_hist_z - X_now_z, axis=1)
    k_actual = min(k, len(distances))
    k_idx = np.argpartition(distances, k_actual-1)[:k_actual]
    k_idx = k_idx[np.argsort(distances[k_idx])]
    k_dist = distances[k_idx]; k_outcomes = Y_hist[k_idx]
    weights = 1 / (k_dist + 1e-6); weights = weights / weights.sum()
    pred_return = float(np.dot(weights, k_outcomes))
    outcome_std = np.std(k_outcomes); global_std = np.std(Y_hist) + 1e-9
    confidence = max(0.0, min(1.0, 1.0 - outcome_std / global_std))
    valid_indices = features.index[valid][:-1]
    k_timestamps = valid_indices[k_idx].tolist()
    return pred_return, k_timestamps, k_dist.tolist(), k_outcomes.tolist(), confidence

# ════════════════════════════════════════════════════════════════════
#  CONFLUENCE AGGREGATOR — Section 3.20
# ════════════════════════════════════════════════════════════════════

def compute_confluence_score(features, tau_bars, tau_labels):
    """Sub-score per horizon with DYNAMIC labels."""
    if len(features) < 10:
        return {}
    # Weight schema: middle horizons get more weight (sweet spot)
    n = len(tau_bars)
    raw_weights = [0.10, 0.20, 0.25, 0.25, 0.20][:n]
    total = sum(raw_weights)
    horizon_weights = {tau: w/total for tau, w in zip(tau_bars, raw_weights)}
    horizon_labels_map = dict(zip(tau_bars, tau_labels))

    latest = features.iloc[-1]
    breakdown = {}
    for tau in tau_bars:
        ema_v  = float(latest.get(f"ema_{tau}", 0))
        emsd_v = float(latest.get(f"emsd_{tau}", 0.01))
        rsi_v  = float(latest.get(f"rsi_{tau}", 0.5))

        trend_score = np.tanh(ema_v * 2) * 100
        momentum_score = min(100, max(-100, ema_v / max(emsd_v, 1e-6) * 50))
        rsi_centered = (rsi_v - 0.5) * 2
        rsi_score = rsi_centered * 60 if abs(rsi_centered) < 0.5 else -rsi_centered * 40
        sub_score = trend_score * 0.5 + momentum_score * 0.3 + rsi_score * 0.2

        breakdown[tau] = {
            "label": horizon_labels_map[tau],
            "weight": horizon_weights[tau],
            "trend": trend_score, "momentum": momentum_score,
            "rsi_raw": rsi_v, "rsi_score": rsi_score,
            "sub_score": sub_score,
            "ema_raw": ema_v, "emsd_raw": emsd_v,
        }
    return breakdown

def aggregate_confluence(breakdown):
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
    score_prob = 1 / (1 + np.exp(-composite_score / scale))
    knn_score = knn_pred * 5000
    knn_prob = 1 / (1 + np.exp(-knn_score))
    total_weight = confidence + knn_conf + 1e-9
    raw_prob = (score_prob * confidence + knn_prob * knn_conf) / total_weight
    overall_conf = (confidence + knn_conf) / 2
    final_prob = 0.5 + (raw_prob - 0.5) * overall_conf
    return float(final_prob), float(overall_conf)

# ════════════════════════════════════════════════════════════════════
#  ATR-BASED ENTRY/TP/SL
# ════════════════════════════════════════════════════════════════════

def compute_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

def compute_entry_levels(df, direction, prob, atr_mult_sl=1.0):
    if len(df) < 20:
        return None
    price = float(df["Close"].iloc[-1])
    atr = compute_atr(df, 14).iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None
    adapt_tp = 1.5 + (prob - 0.5) * 2
    adapt_tp = max(1.0, min(3.5, adapt_tp))
    if direction == "LONG":
        entry = price; tp1 = price + atr * 1.0; tp2 = price + atr * adapt_tp
        sl = price - atr * atr_mult_sl
        rr1 = (tp1 - entry) / (entry - sl) if entry > sl else 0
        rr2 = (tp2 - entry) / (entry - sl) if entry > sl else 0
    elif direction == "SHORT":
        entry = price; tp1 = price - atr * 1.0; tp2 = price - atr * adapt_tp
        sl = price + atr * atr_mult_sl
        rr1 = (entry - tp1) / (sl - entry) if sl > entry else 0
        rr2 = (entry - tp2) / (sl - entry) if sl > entry else 0
    else:
        return None
    return {"direction": direction, "entry": entry, "tp1": tp1, "tp2": tp2,
            "sl": sl, "atr": atr, "rr1": rr1, "rr2": rr2}

# ═══ REGIME DETECTORS ════════════════════════════════════════════════
def detect_volatility_regime(df):
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
    if len(df) < 50:
        return "UNKNOWN", "#4a5568"
    close = df["Close"]
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    price = close.iloc[-1]
    if price > ema20 > ema50: return "BULL TREND", "#00ff88"
    if price < ema20 < ema50: return "BEAR TREND", "#ff3d5a"
    if price > ema50 and price > ema20: return "BULL PULLBACK", "#4da6ff"
    if price < ema50 and price < ema20: return "BEAR PULLBACK", "#ff7b00"
    return "SIDEWAYS", "#ffb700"

# ════════════════════════════════════════════════════════════════════
#  MAIN ANALYZER (driven by TF_CONFIG)
# ════════════════════════════════════════════════════════════════════

def analyze_ticker(ticker, primary_tf="15m", T1=None, k=20, market="IDX (Indonesia)"):
    """Full analysis pipeline driven by TF_CONFIG."""
    cfg = TF_CONFIG[primary_tf]
    if T1 is None:
        T1 = cfg["default_T1"]

    df_main = fetch_primary(ticker, primary_tf)
    if df_main is None or len(df_main) < cfg["min_bars"] // 3:
        bars_count = len(df_main) if df_main is not None else 0
        return {"error": f"Data {primary_tf} kurang ({bars_count} bars). Butuh ≥{cfg['min_bars']//3} bars. Coba ticker lain atau timeframe lebih besar."}

    # Auto-adjust T1 jika data terbatas
    auto_T1 = min(T1, max(20, len(df_main) // 4))
    T1_used = auto_T1
    t1_note = f" (auto-adjusted from {T1})" if auto_T1 < T1 else ""

    features, R_hat, sigma = build_feature_matrix(df_main, T1_used, cfg["tau_bars"])
    if len(features) < 30:
        return {"error": f"Feature matrix terlalu pendek ({len(features)} valid bars). Coba timeframe lebih besar."}

    breakdown = compute_confluence_score(features, cfg["tau_bars"], cfg["tau_labels"])
    composite_score, score_conf = aggregate_confluence(breakdown)

    # Auto-adjust k
    k_used = min(k, max(5, len(features) // 4))

    # KNN for each forecast horizon defined in config
    forecasts = []
    for h_bars, h_label in zip(cfg["forecast_bars"], cfg["forecast_labels"]):
        # Wider sigmoid scale for longer horizons (more uncertainty)
        scale = 35 + (h_bars ** 0.5) * 5
        pred, knn_idx, knn_dist, knn_out, knn_conf = \
            knn_pattern_match(features, df_main["Close"], k=k_used, lookback_horizon=h_bars)
        prob, total_conf = score_to_probability(composite_score, score_conf, pred, knn_conf, scale=scale)

        if prob >= 0.60:    direction = "LONG"
        elif prob <= 0.40:  direction = "SHORT"
        else:                direction = "WAIT"

        wins = sum(1 for o in knn_out if o > 0)
        winrate = wins / len(knn_out) if knn_out else 0.5

        forecasts.append({
            "h_bars": h_bars, "label": h_label,
            "prob": prob, "conf": total_conf, "direction": direction,
            "knn_pred": pred, "knn_conf": knn_conf,
            "knn_idx": knn_idx, "knn_dist": knn_dist, "knn_out": knn_out,
            "winrate": winrate,
        })

    # Primary direction = first forecast (shortest horizon)
    primary_fc = forecasts[0]
    entry_levels = compute_entry_levels(df_main, primary_fc["direction"], primary_fc["prob"])

    vol_regime, vol_color = detect_volatility_regime(df_main)
    trend_regime, trend_color = detect_trend_regime(df_main)

    price = float(df_main["Close"].iloc[-1])
    prev_price = float(df_main["Close"].iloc[-2]) if len(df_main) > 1 else price
    change_pct = (price / prev_price - 1) * 100

    return {
        "ticker": ticker, "primary_tf": primary_tf, "tf_label": cfg["label"],
        "market": market,
        "price": price, "change_pct": change_pct,
        "atr": float(compute_atr(df_main, 14).iloc[-1]) if len(df_main) >= 15 else 0,
        "vol_regime": vol_regime, "vol_color": vol_color,
        "trend_regime": trend_regime, "trend_color": trend_color,
        "breakdown": breakdown,
        "composite_score": composite_score, "score_conf": score_conf,
        "forecasts": forecasts,
        "entry_levels": entry_levels,
        "df_main": df_main, "n_bars": len(df_main), "n_features": len(features),
        "T1_used": T1_used, "k_used": k_used, "t1_note": t1_note,
    }

# ════════════════════════════════════════════════════════════════════
#  TELEGRAM ALERTS
# ════════════════════════════════════════════════════════════════════

def send_telegram(ticker, result):
    if not TOKEN or not CHAT_ID:
        return False, "Telegram tidak dikonfigurasi (set secrets)"
    now = datetime.now(et_tz); sep = "━" * 28

    primary = result["forecasts"][0]
    secondary = result["forecasts"][1] if len(result["forecasts"]) > 1 else None
    dir_emoji = "🟢 LONG" if primary["direction"] == "LONG" else "🔴 SHORT" if primary["direction"] == "SHORT" else "⚪ WAIT"

    body = (
        f"🎯 *MESIN ENTRY ALERT*\n"
        f"{sep}\n"
        f"📊 *{ticker}* @ `{_price(result['price'], result['market'])}` ({_pct(result['change_pct'])})\n"
        f"🎚 TF: *{result['primary_tf']}* — {result['tf_label']}\n"
        f"⏰ `{now.strftime('%H:%M:%S')} ET` · `{now.strftime('%d %b %Y')}`\n"
        f"{sep}\n"
        f"🎯 *{primary['label']} FORECAST*\n"
        f"   {dir_emoji} · Probability: `{primary['prob']*100:.1f}%`\n"
        f"   Confidence: `{primary['conf']*100:.0f}%`\n"
        f"   KNN Win Rate: `{primary['winrate']*100:.0f}%`\n"
    )
    if secondary:
        body += (
            f"\n🎯 *{secondary['label']} FORECAST*\n"
            f"   Probability: `{secondary['prob']*100:.1f}%`\n"
            f"   Confidence: `{secondary['conf']*100:.0f}%`\n"
        )
    body += f"\n📈 *Regime*: {result['trend_regime']} · Vol: {result['vol_regime']}\n"

    if result["entry_levels"]:
        e = result["entry_levels"]
        body += (
            f"{sep}\n"
            f"💰 *Entry Plan*\n"
            f"   Entry: `{_price(e['entry'], result['market'])}`\n"
            f"   TP1:   `{_price(e['tp1'], result['market'])}` (R:R `{e['rr1']:.1f}`)\n"
            f"   TP2:   `{_price(e['tp2'], result['market'])}` (R:R `{e['rr2']:.1f}`)\n"
            f"   SL:    `{_price(e['sl'], result['market'])}`\n"
        )
    body += (
        f"{sep}\n"
        f"⚡ _Mesin Entry v1.1 · {result['tf_label']}_\n"
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
    .entry-card { background: linear-gradient(135deg, #0d1421, #0a1a10); border: 1px solid #1c4a2d; border-radius: 8px; padding: 16px; }
    .entry-card.short { background: linear-gradient(135deg, #0d1421, #1a0a0d); border: 1px solid #4a1c2d; }
    .entry-card.wait { background: linear-gradient(135deg, #0d1421, #1a1a0a); border: 1px solid #4a4a1c; }
    .knn-table { width: 100%; border-collapse: collapse; }
    .knn-table th { background: #131b2e; color: #8b95a8; padding: 8px 10px; text-align: left; font-size: 10px; font-weight: 700; border-bottom: 1px solid #1c2533; }
    .knn-table td { padding: 6px 10px; font-size: 11px; border-bottom: 1px solid #131b2e; }
    .pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 700; border: 1px solid; margin: 2px; }
    .disclaimer { background: #1a1500; border: 1px solid #4a4000; color: #ffb700; padding: 12px 16px; border-radius: 6px; font-size: 11px; margin-top: 16px; }
</style>
""", unsafe_allow_html=True)

for k in ["last_result", "last_ticker", "last_scan_time"]:
    if k not in st.session_state: st.session_state[k] = None

st.markdown("""
<div class="hdr-card">
    <div style="display:flex; align-items:center; justify-content:space-between;">
        <div>
            <div style="font-size:22px; font-weight:700; color:#00ff88;">🎯 MESIN ENTRY v1.1</div>
            <div style="font-size:11px; color:#8b95a8; margin-top:2px;">
                Probabilistic Entry Timing · Multi-style timeframes · Section 18.2 + 3.17 + 3.20
            </div>
        </div>
        <div style="text-align:right; font-size:11px; color:#8b95a8;">
            <div>Scalping ⚡ · Intraday 📊 · Swing 🎯 · Position 📈 · Bagger 💎</div>
            <div>IDX · US · Crypto · FX · Commodity</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── INPUT ROW ────────────────────────────────────────────────────
col_t, col_m, col_tf, col_k = st.columns([2.5, 2, 2.5, 1])
with col_t:
    ticker_raw = st.text_input("Ticker", value="BBCA",
        help="Cukup ketik kode-nya: BBCA (IDX), AAPL (US), BTC (Crypto), XAUUSD (FX). Suffix akan auto-append.")
with col_m:
    market = st.selectbox("Market",
        list(MARKET_SUFFIX.keys()), index=0,
        help="Auto-append suffix:\n• IDX → .JK\n• Crypto → -USD\n• FX → =X\n• Commodity: smart (XAUUSD→=X spot, GC→=F futures, GLD→ETF as-is)")
with col_tf:
    tf_options = list(TF_CONFIG.keys())
    tf_display = [f"{tf} — {TF_CONFIG[tf]['label']}" for tf in tf_options]
    tf_choice = st.selectbox("Timeframe (style)", tf_display, index=1)
    primary_tf = tf_choice.split(" — ")[0]
with col_k:
    k_neighbors = st.slider("KNN k", 5, 50, 20)

# Auto-format ticker for display
ticker_formatted = format_ticker(ticker_raw, market)

# Check if commodity alias remap happened (for user transparency)
remap_note = ""
raw_upper = ticker_raw.strip().upper()
if market == "Commodity" and raw_upper in COMMODITY_ALIAS:
    remap_note = f' <span style="color:#ffb700; font-size:10px;">⚡ auto-remapped from <code>{raw_upper}</code> — yFinance data lebih reliable di futures</span>'

st.markdown(f"""
<div style="font-size:11px; color:#8b95a8; margin-top:-8px;">
    Resolved ticker: <code style="color:#00ff88; background:#0d1421; padding:2px 6px; border-radius:3px;">{ticker_formatted}</code>
    · Default T1 for {primary_tf}: <code style="color:#4da6ff;">{TF_CONFIG[primary_tf]['default_T1']}</code> bars
    {remap_note}
</div>
""", unsafe_allow_html=True)

col_btn1, col_btn2, _ = st.columns([1.5, 1.5, 5])
with col_btn1:
    analyze_btn = st.button("🎯 ANALYZE", type="primary", use_container_width=True)
with col_btn2:
    tg_btn = st.button("📡 SEND TELEGRAM", use_container_width=True)

if analyze_btn:
    if not ticker_formatted:
        st.error("Ticker tidak boleh kosong bro")
    else:
        with st.spinner(f"Fetching & analyzing {ticker_formatted} on {primary_tf} ({TF_CONFIG[primary_tf]['label']})..."):
            result = analyze_ticker(ticker_formatted, primary_tf=primary_tf, T1=None, k=k_neighbors, market=market)
            st.session_state.last_result = result
            st.session_state.last_ticker = ticker_formatted
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
    st.info("👆 Pilih ticker, market, timeframe. Klik **ANALYZE**.")
    with st.expander("ℹ️ Style → Timeframe mapping"):
        st.markdown("""
| Trading Style | Timeframe | Horizon (Forecast) | Use Case |
|---|---|---|---|
| **Scalping ⚡** | 5m | 5m / 15m / 1h | Quick in-out, target ATR×1 |
| **Intraday 📊** | 15m / 30m | 15-30m / 1h / 4h | Same-day, multi-touch ATR |
| **Swing Entry 🎯** | 1h | 1h / 4h / 1d | Multi-day hold |
| **Swing/Position 📈** | 1d | 1d / 1w / 1mo | Weekly hold |
| **Bagger 💎** | 1wk | 1w / 1mo / 3mo | Wyckoff accumulation, longer thesis |

**Auto-suffix per market:**
- IDX → BBCA → `BBCA.JK`
- US → AAPL → `AAPL`
- Crypto → BTC → `BTC-USD`
- FX → EURUSD → `EURUSD=X`
- Commodity → GC=F / XAUUSD=X → as-is (already complete format)
        """)

elif result.get("error"):
    st.error(f"⚠️ {result['error']}")

else:
    ticker = st.session_state.last_ticker
    price = result["price"]; change = result["change_pct"]
    chg_col = "#00ff88" if change >= 0 else "#ff3d5a"
    chg_sym = "▲" if change >= 0 else "▼"

    st.markdown(f"""
    <div class="hdr-card">
        <div style="display:flex; align-items:center; justify-content:space-between;">
            <div>
                <div style="font-size:13px; color:#8b95a8;">CURRENT STATE · TF: <strong style="color:#00ff88">{result['primary_tf']}</strong> ({result['tf_label']})</div>
                <div style="font-size:24px; font-weight:700; color:#e2e8f0; margin-top:4px;">
                    {ticker} · {_price(price, result['market'])}
                    <span style="font-size:14px; color:{chg_col}; font-weight:700; margin-left:8px;">{chg_sym} {abs(change):.2f}%</span>
                </div>
                <div style="font-size:11px; color:#8b95a8; margin-top:6px;">
                    {result['n_bars']} bars · ATR(14): {_price(result['atr'], result['market'])} · {result['n_features']} valid features · T1={result['T1_used']}{result['t1_note']} · k={result['k_used']}
                </div>
            </div>
            <div style="text-align:right;">
                <div><span class="pill" style="color:{result['trend_color']}; border-color:{result['trend_color']}40; background:{result['trend_color']}15;">{result['trend_regime']}</span></div>
                <div style="margin-top:6px;"><span class="pill" style="color:{result['vol_color']}; border-color:{result['vol_color']}40; background:{result['vol_color']}15;">VOL: {result['vol_regime']}</span></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # PROBABILITY GAUGES — DYNAMIC per timeframe
    st.markdown("### 🎯 Probability Forecast")
    forecasts = result["forecasts"]
    cols = st.columns(len(forecasts))

    def render_gauge(fc, is_primary=False):
        prob = fc["prob"]; conf = fc["conf"]; direction = fc["direction"]
        pct = prob * 100; cnf = conf * 100
        if prob >= 0.60:
            color = "#00ff88"; bg = "#0a1a10"; dir_text = "🟢 LONG"
        elif prob <= 0.40:
            color = "#ff3d5a"; bg = "#1a0a0d"; dir_text = "🔴 SHORT"
        else:
            color = "#ffb700"; bg = "#1a1500"; dir_text = "⚪ WAIT"
        primary_badge = '<div style="font-size:9px; color:#00ff88; font-weight:700; margin-bottom:4px;">▼ PRIMARY ENTRY</div>' if is_primary else ''
        return (
            f'<div class="gauge-card" style="background: linear-gradient(135deg, #0d1421, {bg}); border-color: {color}40;">'
            f'{primary_badge}'
            f'<div style="font-size:11px; color:#8b95a8; font-weight:700;">{fc["label"]} FORECAST</div>'
            f'<div style="font-size:42px; font-weight:700; color:{color}; margin:12px 0;">{pct:.1f}%</div>'
            f'<div style="font-size:14px; color:{color}; font-weight:700; margin-bottom:6px;">{dir_text}</div>'
            f'<div style="font-size:10px; color:#8b95a8;">'
            f'Confidence: <span style="color:#e2e8f0; font-weight:700;">{cnf:.0f}%</span>'
            f' · Win: <span style="color:#e2e8f0; font-weight:700;">{fc["winrate"]*100:.0f}%</span>'
            f'</div>'
            f'<div style="margin-top:12px; height:6px; background:#1a2030; border-radius:3px; overflow:hidden;">'
            f'<div style="height:100%; width:{pct}%; background:{color};"></div>'
            f'</div>'
            f'</div>'
        )

    for i, (col, fc) in enumerate(zip(cols, forecasts)):
        with col:
            st.markdown(render_gauge(fc, is_primary=(i==0)), unsafe_allow_html=True)

    # MULTI-TF AGREEMENT — DYNAMIC labels
    st.markdown("### 📊 Multi-Horizon Feature Agreement")
    col_tf, col_cb = st.columns([1, 1])

    with col_tf:
        st.markdown(f"<div style='font-size:11px; color:#8b95a8; margin-bottom:8px;'>Sub-scores per τ-horizon (relative to {result['primary_tf']} entry)</div>", unsafe_allow_html=True)
        bars_html = ""
        for tau, b in result["breakdown"].items():
            score = b["sub_score"]
            if score >= 0:
                bar_color = "#00ff88" if score >= 50 else "#4da6ff" if score >= 20 else "#8b95a8"
                left = 50; width = abs(score) / 2
            else:
                bar_color = "#ff3d5a" if score <= -50 else "#ff7b00" if score <= -20 else "#8b95a8"
                left = 50 - abs(score) / 2; width = abs(score) / 2
            sign = "+" if score >= 0 else ""
            bars_html += (
                f'<div class="tf-row">'
                f'<div class="tf-label">{b["label"]}</div>'
                f'<div class="tf-bar-bg">'
                f'<div style="position:absolute; left:50%; top:0; width:1px; height:100%; background:#8b95a8;"></div>'
                f'<div class="tf-bar-fill" style="position:absolute; left:{left}%; width:{width}%; height:100%; background:{bar_color};"></div>'
                f'</div>'
                f'<div class="tf-value" style="color:{bar_color};">{sign}{score:.0f}</div>'
                f'</div>'
            )
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
            st.markdown(
                f'<div style="background:#0d1421; border:1px solid #1c2533; border-radius:4px; padding:8px 12px; margin-bottom:6px;">'
                f'<div style="display:flex; justify-content:space-between; font-size:11px;">'
                f'<span style="color:#e2e8f0; font-weight:700;">{b["label"]}</span>'
                f'<span style="color:{ema_col}; font-weight:700;">{ema_dir} EMA: {b["ema_raw"]:+.3f}</span>'
                f'</div>'
                f'<div style="display:flex; justify-content:space-between; font-size:10px; color:#8b95a8; margin-top:3px;">'
                f'<span>Mom: {b["momentum"]:+.0f} · Trend: {b["trend"]:+.0f}</span>'
                f'<span style="color:{rsi_col};">RSI z: {rsi_v:.2f} {rsi_label}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    # KNN MATCHES — uses PRIMARY forecast (shortest horizon)
    primary = result["forecasts"][0]
    st.markdown(f"### 🔍 KNN Pattern Matches — {primary['label']} horizon")
    knn_wr_col = "#00ff88" if primary['winrate']>=0.55 else "#ff3d5a" if primary['winrate']<=0.45 else "#ffb700"
    st.markdown(f"""
    <div style="font-size:11px; color:#8b95a8; margin-bottom:8px;">
        Top 10 dari {len(primary['knn_idx'])} saat-saat di masa lalu yang paling mirip kondisi sekarang.
        Win rate KNN (next {primary['label']}): <strong style="color:{knn_wr_col};">{primary['winrate']*100:.0f}%</strong>
        · Predicted return: <strong>{primary['knn_pred']*100:+.3f}%</strong>
    </div>
    """, unsafe_allow_html=True)

    knn_rows = ""
    if primary['knn_dist']:
        max_dist = max(primary['knn_dist']); min_dist = min(primary['knn_dist'])
        range_dist = max_dist - min_dist + 1e-9
        for i, (ts, dist, out) in enumerate(zip(primary['knn_idx'][:10], primary['knn_dist'][:10], primary['knn_out'][:10])):
            similarity = 1 - (dist - min_dist) / range_dist
            sim_pct = similarity * 100; out_pct = out * 100
            out_col = "#00ff88" if out > 0 else "#ff3d5a" if out < 0 else "#8b95a8"
            out_sign = "✓" if out > 0 else "✗" if out < 0 else "—"
            try: ts_str = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
            except: ts_str = str(ts)
            knn_rows += (
                f'<tr>'
                f'<td style="color:#8b95a8;">#{i+1}</td>'
                f'<td style="color:#e2e8f0; font-family:Space Mono,monospace;">{ts_str}</td>'
                f'<td style="text-align:right;"><span style="color:#4da6ff; font-weight:700;">{sim_pct:.0f}%</span></td>'
                f'<td style="text-align:right; color:{out_col}; font-weight:700;">{out_pct:+.3f}%</td>'
                f'<td style="text-align:center; color:{out_col}; font-weight:700;">{out_sign}</td>'
                f'</tr>'
            )

    table_html = (
        '<table class="knn-table">'
        '<tr>'
        '<th style="width:40px;">#</th>'
        '<th>Historical Timestamp</th>'
        '<th style="text-align:right; width:80px;">Similarity</th>'
        f'<th style="text-align:right; width:90px;">Outcome ({primary["label"]})</th>'
        '<th style="text-align:center; width:50px;">Win?</th>'
        '</tr>'
        f'{knn_rows}'
        '</table>'
    )
    st.markdown(table_html, unsafe_allow_html=True)

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
                <div style="font-size:16px; font-weight:700; color:{dir_color};">{dir_emoji} {e['direction']} · {primary['label']} horizon</div>
                <div style="font-size:11px; color:#8b95a8;">ATR(14) = {_price(e['atr'], result['market'])} · TP2 adaptif by probability</div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px;">
                <div><div style="font-size:10px; color:#8b95a8;">ENTRY</div><div style="font-size:18px; font-weight:700; color:#e2e8f0;">{_price(e['entry'], result['market'])}</div></div>
                <div><div style="font-size:10px; color:#00ff88;">TP1 (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp1'], result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr1']:.2f}</div></div>
                <div><div style="font-size:10px; color:#00ff88;">TP2 (adaptif)</div><div style="font-size:18px; font-weight:700; color:#00ff88;">{_price(e['tp2'], result['market'])}</div><div style="font-size:10px; color:#8b95a8;">R:R {e['rr2']:.2f}</div></div>
                <div><div style="font-size:10px; color:#ff3d5a;">SL (1.0× ATR)</div><div style="font-size:18px; font-weight:700; color:#ff3d5a;">{_price(e['sl'], result['market'])}</div></div>
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
    fc_labels = " / ".join([f['label'] for f in result["forecasts"]])
    st.markdown(f"""
    <div class="disclaimer">
        <strong>⚠️ HONEST EXPECTATION (jangan lupa bro)</strong><br>
        Engine ini probabilistik berdasarkan multi-horizon z-score features + KNN pattern matching dari buku Kakushadze &amp; Serur (2018).<br>
        Forecast horizons: <strong>{fc_labels}</strong> · Style: <strong>{result['tf_label']}</strong><br><br>
        <strong>Realistic accuracy:</strong><br>
        • Trending market (current: <strong>{result['trend_regime']}</strong>): 60-68% directional accuracy<br>
        • Sideways/chop: turun ke 52-55% (mendekati coinflip)<br>
        • News event / black swan: <strong>SEMUA model breakdown</strong> — current vol: <strong style="color:{result['vol_color']}">{result['vol_regime']}</strong><br><br>
        <strong>Position sizing &amp; risk management tetap tanggung jawab lo.</strong> Engine kasih edge probabilistik, BUKAN crystal ball.
    </div>
    """, unsafe_allow_html=True)

if st.session_state.last_scan_time:
    lt = datetime.fromtimestamp(st.session_state.last_scan_time, et_tz).strftime("%H:%M:%S ET · %d %b %Y")
    st.markdown(f"<div style='text-align:center; font-size:10px; color:#4a5568; margin-top:24px; font-family:Space Mono,monospace;'>Last analysis: {lt}</div>", unsafe_allow_html=True)
