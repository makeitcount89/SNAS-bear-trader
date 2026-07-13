#!/usr/bin/env python3
"""
SNAS Bear Trader - selective bear-market engine.

Sibling model to LNAS-SNAS. Reuses its GMMA (Guppy Multiple Moving Average)
feature set and from-scratch k-NN classifier trained on ^NDX, but the
decision philosophy is inverted:

  LNAS-SNAS is long-biased: it holds LNAS or SNAS at all times (no cash),
  defaulting to LNAS and only rotating into SNAS when a bearish gate opens.

  SNAS Bear Trader is cash-biased: it defaults to a safe asset (a cash-like
  ETF) and only rotates into SNAS when a *stack* of independent bearish
  conditions all agree simultaneously, including a precondition that the
  index was recently trading near a 5-year high (an "overbought, now
  rolling over" regime) rather than already deep in an established
  downtrend. It never holds LNAS. The result trades far less often, and
  spends most of its time in cash/bonds -- the tradeoff is fewer, higher
  conviction entries in exchange for lower turnover and lower drawdown risk
  relative to a strategy that is always fully invested.

Data: yfinance. No external ML dependency (k-NN is hand-written, same as
LNAS-SNAS, for transparency).
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("snas_bear_trader")

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

BEAR_TICKER = "SNAS.AX"        # short/inverse geared Nasdaq product (only tradable risk asset)
SAFE_TICKER = "AAA.AX"         # BetaShares Australian High Interest Cash ETF (cash/safe-asset proxy)
LNAS_TICKER = "LNAS.AX"        # long geared Nasdaq product - benchmark only, never traded here
REF_TICKER = "^NDX"            # unleveraged reference index for feature engineering
REF_FALLBACK_TICKER = "^IXIC"

TIMEZONE = "Australia/Adelaide"
REBALANCE_DAYS = {1, 4}        # Tuesday=1, Friday=4 (Python weekday())
DECISION_CUTOFF_LOCAL = "14:00"

INITIAL_CAPITAL = 500.0

HISTORY_PERIOD = "10y"

# GMMA spans (identical to LNAS-SNAS, computed on the unleveraged reference index only)
SHORT_EMA_SPANS = (3, 5, 8, 10, 12, 15)
LONG_EMA_SPANS = (30, 35, 40, 45, 50, 60)

# k-NN
K_NEIGHBORS = 3
FLAT_BAND_PCT = 0.5             # next-session |return| <= this -> FLAT label
MIN_KNN_CONFIDENCE = 0.60       # weighted-vote share required for DOWN entries (LNAS-SNAS has no such gate)

# Bearish gate thresholds - tightened relative to LNAS-SNAS to be more selective
ALIGNMENT_MARGIN_PCT = 0.25          # LNAS-SNAS uses 0.10
RS_LOOKBACK_DAYS = 20
RS_LOOKBACK_DAYS_LONG = 60           # second, longer confirmation window (new)
LIQUIDITY_MIN_RATIO = 0.80
LIQUIDITY_LOOKBACK_DAYS = 20
PULLBACK_MAX_EXTENSION_PCT = 2.5     # LNAS-SNAS uses 3.5 - entries must be caught earlier, less "already extended"

SHORT_TERM_MA_DAYS = 20
VOL_REGIME_MA_DAYS = 50
REALIZED_VOL_LOOKBACK_DAYS = 10
VOL_BASELINE_LOOKBACK_DAYS = 60
VOL_SPIKE_MULTIPLIER = 1.5

# "Fell from overbought" precondition - new, encodes the 5-year-overbought bear thesis
OVERBOUGHT_LOOKBACK_DAYS = 1260       # ~5 trading years
OVERBOUGHT_ZONE_PCT = -8.0            # within 8% of the trailing 5y high counts as "overbought"
OVERBOUGHT_RECENCY_WINDOW = 60        # must have been in that zone within the last ~3 months

# Reduces whipsaw re-entries immediately after being stopped out
COOLDOWN_SESSIONS_AFTER_EXIT = 4

TRAIN_WEEKS = 2 * 52
MIN_TRAIN_SAMPLES = 20
HOLDOUT_WEEKS = 52
MAX_HOLDOUT_WINDOWS = 50

MAX_PLAUSIBLE_INTERVAL_MOVE = 0.30    # 30%, treated as a data artifact absent a recorded split

KNOWN_SPLITS_NOTE = "Split ratios are pulled live via yfinance Ticker.splits; no hardcoded table is required."

OUTPUT_PATH = "public/strategy_data.json"


# --------------------------------------------------------------------------
# Data acquisition
# --------------------------------------------------------------------------

def fetch_daily(ticker: str, period: str = HISTORY_PERIOD) -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def fetch_splits(ticker: str) -> pd.Series:
    try:
        s = yf.Ticker(ticker).splits
        if s is None or s.empty:
            return pd.Series(dtype=float)
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("Could not fetch splits for %s: %s", ticker, exc)
        return pd.Series(dtype=float)


def apply_split_adjustment(df: pd.DataFrame, splits: pd.Series) -> pd.DataFrame:
    """Back-adjust Close/Open/High/Low by known split ratios only (not yfinance's
    opaque combined split+dividend auto-adjust), leaving Volume raw."""
    if df.empty or splits.empty:
        return df
    df = df.copy()
    factor = pd.Series(1.0, index=df.index)
    for split_date, ratio in splits.items():
        if ratio == 0:
            continue
        factor.loc[df.index < split_date] /= ratio
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col] * factor
    return df


def desplit_session_prices(df: pd.DataFrame, splits: pd.Series) -> pd.DataFrame:
    """Safety net: any single-session move beyond MAX_PLAUSIBLE_INTERVAL_MOVE that
    isn't explained by a recorded split is treated as a data artifact and the
    series is rebased at that point, with a warning logged."""
    if df.empty:
        return df
    df = df.copy()
    close = df["Close"]
    returns = close.pct_change()
    known_split_dates = set(pd.to_datetime(splits.index).normalize()) if not splits.empty else set()
    factor = 1.0
    factors = []
    for date, ret in zip(df.index, returns):
        if pd.notna(ret) and abs(ret) > MAX_PLAUSIBLE_INTERVAL_MOVE and date.normalize() not in known_split_dates:
            log.warning("Unexplained >%.0f%% move on %s (%.1f%%) - treating as data artifact, rebasing.",
                        MAX_PLAUSIBLE_INTERVAL_MOVE * 100, date.date(), ret * 100)
            factor *= (1.0 - ret)
        factors.append(factor)
    adj = pd.Series(factors, index=df.index)
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col] * adj
    return df


def load_clean_series(ticker: str, fallback: str | None = None) -> pd.DataFrame:
    df = fetch_daily(ticker)
    used = ticker
    if df.empty and fallback:
        log.warning("%s returned no data, falling back to %s", ticker, fallback)
        df = fetch_daily(fallback)
        used = fallback
    if df.empty:
        raise RuntimeError(f"No data available for {ticker} (fallback {fallback})")
    splits = fetch_splits(used)
    df = apply_split_adjustment(df, splits)
    df = desplit_session_prices(df, splits)
    return df


# --------------------------------------------------------------------------
# Feature engineering (GMMA on the reference index only)
# --------------------------------------------------------------------------

def compute_gmma_features(ref_close: pd.Series) -> pd.DataFrame:
    short_emas = pd.DataFrame({
        p: ref_close.ewm(span=p, min_periods=p, adjust=False).mean() for p in SHORT_EMA_SPANS
    })
    long_emas = pd.DataFrame({
        p: ref_close.ewm(span=p, min_periods=p, adjust=False).mean() for p in LONG_EMA_SPANS
    })
    short_mean = short_emas.mean(axis=1)
    long_mean = long_emas.mean(axis=1)

    features = pd.DataFrame(index=ref_close.index)
    features["short_group_compression"] = (short_emas.std(axis=1) / short_mean) * 100
    features["long_group_separation"] = (long_emas.std(axis=1) / long_mean) * 100
    features["price_vs_short_group"] = ((ref_close - short_mean) / short_mean) * 100
    features["short_mean"] = short_mean
    features["long_mean"] = long_mean
    features["center_gap_pct"] = (short_mean - long_mean) / long_mean * 100
    return features


def compute_trend_indicators(ref_close: pd.Series) -> pd.DataFrame:
    ind = pd.DataFrame(index=ref_close.index)
    ind["ma_short"] = ref_close.rolling(SHORT_TERM_MA_DAYS).mean()
    ind["ma_vol_regime"] = ref_close.rolling(VOL_REGIME_MA_DAYS).mean()
    ind["ret_rs_short"] = ref_close.pct_change(RS_LOOKBACK_DAYS) * 100
    ind["ret_rs_long"] = ref_close.pct_change(RS_LOOKBACK_DAYS_LONG) * 100

    daily_ret = ref_close.pct_change()
    ind["realized_vol"] = daily_ret.rolling(REALIZED_VOL_LOOKBACK_DAYS).std()
    ind["vol_baseline"] = daily_ret.rolling(VOL_BASELINE_LOOKBACK_DAYS).std()

    rolling_5y_high = ref_close.rolling(OVERBOUGHT_LOOKBACK_DAYS, min_periods=252).max()
    ind["dist_from_5y_high_pct"] = (ref_close - rolling_5y_high) / rolling_5y_high * 100
    ind["was_overbought_recently"] = (
        ind["dist_from_5y_high_pct"].rolling(OVERBOUGHT_RECENCY_WINDOW, min_periods=1).max() >= OVERBOUGHT_ZONE_PCT
    )
    return ind


def compute_liquidity_ratio(bear_volume: pd.Series) -> pd.Series:
    avg_vol = bear_volume.rolling(LIQUIDITY_LOOKBACK_DAYS).mean().shift(1)
    return bear_volume / avg_vol


# --------------------------------------------------------------------------
# k-NN (from scratch, no external ML dependency - same design as LNAS-SNAS)
# --------------------------------------------------------------------------

FEATURE_COLS = ["short_group_compression", "long_group_separation", "price_vs_short_group"]


def build_labeled_pool(features: pd.DataFrame, ref_close: pd.Series) -> pd.DataFrame:
    next_ret = ref_close.pct_change().shift(-1) * 100
    pool = features[FEATURE_COLS].copy()
    pool["label"] = np.select(
        [next_ret > FLAT_BAND_PCT, next_ret < -FLAT_BAND_PCT],
        ["UP", "DOWN"],
        default="FLAT",
    )
    # a row's label is only "known" as of the following session - used to prevent lookahead
    pool["label_known_date"] = pool.index.to_series().shift(-1)
    return pool.dropna(subset=FEATURE_COLS)


def standardize(train_pool: pd.DataFrame, query: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    mean = train_pool[FEATURE_COLS].mean()
    std = train_pool[FEATURE_COLS].std().replace(0, 1.0)
    train_z = ((train_pool[FEATURE_COLS] - mean) / std).to_numpy()
    query_z = ((query[FEATURE_COLS] - mean) / std).to_numpy()
    return train_z, query_z


def knn_predict(train_pool: pd.DataFrame, query: pd.Series) -> tuple[str, float]:
    if len(train_pool) < MIN_TRAIN_SAMPLES:
        return "FLAT", 0.0
    train_z, query_z = standardize(train_pool, query)
    dists = np.sqrt(((train_z - query_z) ** 2).sum(axis=1))
    k = min(K_NEIGHBORS, len(dists))
    nearest_idx = np.argsort(dists)[:k]
    labels = train_pool["label"].to_numpy()[nearest_idx]
    weights = 1.0 / (dists[nearest_idx] + 1e-9)

    scores: dict[str, float] = {"UP": 0.0, "DOWN": 0.0, "FLAT": 0.0}
    for label, weight in zip(labels, weights):
        scores[label] += weight
    total = sum(scores.values())
    predicted = max(scores, key=scores.get)
    confidence = scores[predicted] / total if total > 0 else 0.0
    return predicted, confidence


# --------------------------------------------------------------------------
# Bearish gate - every condition below must agree before entering SNAS.
# This stack is deliberately stricter/larger than LNAS-SNAS's 4-filter gate:
# LNAS-SNAS only needs its 4 filters to flip a long-biased default; this
# model needs all of these to justify leaving cash altogether.
# --------------------------------------------------------------------------

@dataclass
class FilterCheck:
    passed: bool
    detail: str

    def to_json(self):
        return {"pass": self.passed, "detail": self.detail}


@dataclass
class BearGate:
    trend_breakdown: FilterCheck
    trend_alignment: FilterCheck
    relative_strength: FilterCheck
    liquidity: FilterCheck
    pullback_not_extended: FilterCheck
    volatility_spike: FilterCheck
    overbought_precondition: FilterCheck
    knn_confidence: FilterCheck

    def all_pass(self) -> bool:
        return all(c.passed for c in self.__dict__.values())

    def continuation_pass(self) -> bool:
        """Subset re-checked every session to decide whether to stay in SNAS.
        Overbought-precondition and vol-spike are entry-only triggers, not
        held-position requirements (matches LNAS-SNAS's own asymmetric design,
        where entry and hold conditions differ)."""
        return (
            self.trend_breakdown.passed
            and self.trend_alignment.passed
            and self.relative_strength.passed
            and self.liquidity.passed
            and self.pullback_not_extended.passed
        )

    def to_json(self):
        return {k: v.to_json() for k, v in self.__dict__.items()}


def evaluate_bear_gate(
    features_row: pd.Series,
    trend_row: pd.Series,
    liquidity_ratio: float,
    ref_close_today: float,
    knn_prediction: str,
    knn_confidence: float,
) -> BearGate:
    trend_breakdown = FilterCheck(
        bool(ref_close_today < trend_row["ma_short"] and trend_row["ma_short"] < trend_row["ma_vol_regime"]),
        f"close {ref_close_today:.1f} vs MA{SHORT_TERM_MA_DAYS} {trend_row['ma_short']:.1f} "
        f"vs MA{VOL_REGIME_MA_DAYS} {trend_row['ma_vol_regime']:.1f}",
    )
    trend_alignment = FilterCheck(
        bool(features_row["center_gap_pct"] <= -ALIGNMENT_MARGIN_PCT),
        f"GMMA center gap {features_row['center_gap_pct']:.2f}% <= -{ALIGNMENT_MARGIN_PCT}%",
    )
    relative_strength = FilterCheck(
        bool(trend_row["ret_rs_short"] < 0 and trend_row["ret_rs_long"] < 0),
        f"{RS_LOOKBACK_DAYS}d {trend_row['ret_rs_short']:.2f}% / "
        f"{RS_LOOKBACK_DAYS_LONG}d {trend_row['ret_rs_long']:.2f}% both negative",
    )
    liquidity = FilterCheck(
        bool(pd.notna(liquidity_ratio) and liquidity_ratio >= LIQUIDITY_MIN_RATIO),
        f"SNAS volume ratio {liquidity_ratio:.2f} >= {LIQUIDITY_MIN_RATIO}",
    )
    pullback_not_extended = FilterCheck(
        bool(abs(features_row["price_vs_short_group"]) <= PULLBACK_MAX_EXTENSION_PCT),
        f"|price vs short group| {abs(features_row['price_vs_short_group']):.2f}% <= {PULLBACK_MAX_EXTENSION_PCT}%",
    )
    vol_ratio = (
        trend_row["realized_vol"] / trend_row["vol_baseline"]
        if pd.notna(trend_row["vol_baseline"]) and trend_row["vol_baseline"] > 0
        else np.nan
    )
    volatility_spike = FilterCheck(
        bool(pd.notna(vol_ratio) and vol_ratio > VOL_SPIKE_MULTIPLIER and ref_close_today < trend_row["ma_vol_regime"]),
        f"realized/baseline vol ratio {vol_ratio:.2f} > {VOL_SPIKE_MULTIPLIER} while below MA{VOL_REGIME_MA_DAYS}",
    )
    overbought_precondition = FilterCheck(
        bool(trend_row["was_overbought_recently"]),
        f"traded within {OVERBOUGHT_ZONE_PCT}% of its {OVERBOUGHT_LOOKBACK_DAYS // 252}y high "
        f"within the last {OVERBOUGHT_RECENCY_WINDOW} sessions",
    )
    knn_gate = FilterCheck(
        bool(knn_prediction == "DOWN" and knn_confidence >= MIN_KNN_CONFIDENCE),
        f"k-NN raw={knn_prediction} confidence={knn_confidence:.2f} >= {MIN_KNN_CONFIDENCE}",
    )
    return BearGate(
        trend_breakdown, trend_alignment, relative_strength, liquidity,
        pullback_not_extended, volatility_spike, overbought_precondition, knn_gate,
    )


# --------------------------------------------------------------------------
# Decision state machine - CASH-default, SNAS only on high-conviction entries
# --------------------------------------------------------------------------

@dataclass
class Decision:
    asset: str            # "SNAS" or "SAFE"
    action: str            # "ENTER" | "HOLD" | "EXIT" | "CASH"
    gate: BearGate
    knn_prediction: str
    knn_confidence: float


def resolve_decision(
    currently_holding: str,
    sessions_since_exit: int | None,
    gate: BearGate,
) -> Decision:
    cooldown_active = sessions_since_exit is not None and sessions_since_exit < COOLDOWN_SESSIONS_AFTER_EXIT

    if currently_holding == "SNAS":
        if gate.continuation_pass():
            return Decision("SNAS", "HOLD", gate, "DOWN", 1.0)
        return Decision("SAFE", "EXIT", gate, "FLAT", 0.0)

    # currently in SAFE (or no position yet)
    if not cooldown_active and gate.all_pass():
        return Decision("SNAS", "ENTER", gate, "DOWN", 1.0)
    return Decision("SAFE", "CASH", gate, "FLAT", 0.0)


# --------------------------------------------------------------------------
# Walk-forward backtest
# --------------------------------------------------------------------------

def chunk_into_windows(dates: pd.DatetimeIndex, weeks: int, max_windows: int) -> list[pd.DatetimeIndex]:
    sessions_per_window = weeks * 5
    windows = [dates[i:i + sessions_per_window] for i in range(0, len(dates), sessions_per_window)]
    windows = [w for w in windows if len(w) > 0]
    return windows[-max_windows:]


def max_drawdown_pct(values: list[float]) -> float:
    peak = -np.inf
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak * 100)
    return worst


def simulate_window(
    window_dates: pd.DatetimeIndex,
    decisions: dict[pd.Timestamp, Decision],
    bear_returns: pd.Series,
    safe_returns: pd.Series,
) -> dict:
    value = INITIAL_CAPITAL
    values = [value]
    ledger = []
    wins = losses = cash_sessions = 0
    current_streak_type = None
    current_streak_len = 0
    asset_stats = {"SNAS": {"trades": 0, "wins": 0, "losses": 0, "dollar_pnl": 0.0},
                   "SAFE": {"trades": 0, "wins": 0, "losses": 0, "dollar_pnl": 0.0}}

    for date in window_dates:
        decision = decisions.get(date)
        if decision is None:
            continue
        asset = decision.asset
        ret = bear_returns.get(date, 0.0) if asset == "SNAS" else safe_returns.get(date, 0.0)
        ret = 0.0 if pd.isna(ret) else ret
        before = value
        value = value * (1 + ret / 100)

        traded = asset == "SNAS"
        if traded:
            outcome_win = ret > 0
            if outcome_win:
                wins += 1
                asset_stats["SNAS"]["wins"] += 1
                streak_type = "W"
            else:
                losses += 1
                asset_stats["SNAS"]["losses"] += 1
                streak_type = "L"
            asset_stats["SNAS"]["trades"] += 1
            asset_stats["SNAS"]["dollar_pnl"] += value - before
            if current_streak_type == streak_type:
                current_streak_len += 1
            else:
                current_streak_type, current_streak_len = streak_type, 1
        else:
            cash_sessions += 1
            asset_stats["SAFE"]["trades"] += 1
            asset_stats["SAFE"]["dollar_pnl"] += value - before

        values.append(value)
        ledger.append({
            "date": str(date.date()),
            "asset": asset,
            "action": decision.action,
            "rawPrediction": decision.knn_prediction,
            "rawConfidence": round(decision.knn_confidence, 4),
            "gate": decision.gate.to_json(),
            "intervalReturnPct": round(ret, 4),
            "portfolioValueBefore": round(before, 2),
            "portfolioValueAfter": round(value, 2),
        })

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    return {
        "initialCapital": INITIAL_CAPITAL,
        "currentValue": round(value, 2),
        "totalReturnPct": round((value / INITIAL_CAPITAL - 1) * 100, 2),
        "totalTrades": total_trades,
        "wins": wins,
        "losses": losses,
        "cashSessions": cash_sessions,
        "winRatePct": round(win_rate, 2),
        "maxDrawdownPct": round(max_drawdown_pct(values), 2),
        "currentStreak": {"type": current_streak_type, "length": current_streak_len} if current_streak_type else None,
        "assetBreakdown": {
            asset_name: {
                "trades": s["trades"],
                "wins": s["wins"],
                "losses": s["losses"],
                "winRatePct": round((s["wins"] / s["trades"] * 100) if s["trades"] else 0.0, 2),
                "dollarPnl": round(s["dollar_pnl"], 2),
            }
            for asset_name, s in asset_stats.items()
        },
        "ledger": ledger,
    }


def buy_and_hold_return_and_dd(close: pd.Series, dates: pd.DatetimeIndex) -> tuple[float, float]:
    series = close.reindex(dates).dropna()
    if len(series) < 2:
        return 0.0, 0.0
    ret_pct = (series.iloc[-1] / series.iloc[0] - 1) * 100
    values = (series / series.iloc[0] * INITIAL_CAPITAL).tolist()
    return round(ret_pct, 2), round(max_drawdown_pct(values), 2)


def walk_forward_backtest(
    trading_dates: pd.DatetimeIndex,
    features: pd.DataFrame,
    trend: pd.DataFrame,
    labeled_pool: pd.DataFrame,
    liquidity_ratio: pd.Series,
    ref_close: pd.Series,
    bear_returns: pd.Series,
    safe_returns: pd.Series,
    lnas_close: pd.Series,
    ndx_close: pd.Series,
):
    train_floor = TRAIN_WEEKS * 5
    if len(trading_dates) <= train_floor:
        raise RuntimeError("Not enough history to clear the training floor")

    eval_dates = trading_dates[train_floor:]
    decisions: dict[pd.Timestamp, Decision] = {}
    currently_holding = "SAFE"
    sessions_since_exit: int | None = None

    for date in eval_dates:
        if date not in features.index or date not in trend.index:
            continue
        row_features = features.loc[date]
        row_trend = trend.loc[date]
        if row_features.isna().any() or row_trend[["ma_short", "ma_vol_regime", "ret_rs_short", "ret_rs_long"]].isna().any():
            continue

        train_pool = labeled_pool[labeled_pool["label_known_date"] < date]
        prediction, confidence = knn_predict(train_pool, row_features)

        gate = evaluate_bear_gate(
            row_features, row_trend, liquidity_ratio.get(date, np.nan),
            ref_close.loc[date], prediction, confidence,
        )
        decision = resolve_decision(currently_holding, sessions_since_exit, gate)
        decisions[date] = decision

        if decision.action == "EXIT":
            sessions_since_exit = 0
        elif sessions_since_exit is not None:
            sessions_since_exit += 1
        currently_holding = decision.asset

    decided_dates = pd.DatetimeIndex(sorted(decisions.keys()))
    windows = chunk_into_windows(decided_dates, HOLDOUT_WEEKS, MAX_HOLDOUT_WINDOWS)

    validation_windows = []
    for i, window_dates in enumerate(windows):
        result = simulate_window(window_dates, decisions, bear_returns, safe_returns)
        lnas_ret, lnas_dd = buy_and_hold_return_and_dd(lnas_close, window_dates)
        ndx_ret, ndx_dd = buy_and_hold_return_and_dd(ndx_close, window_dates)
        result.update({
            "windowIndex": i,
            "startDate": str(window_dates[0].date()),
            "endDate": str(window_dates[-1].date()),
            "buyHoldLnasReturnPct": lnas_ret,
            "buyHoldLnasMaxDrawdownPct": lnas_dd,
            "beatBuyHoldLnas": result["totalReturnPct"] > lnas_ret,
            "avoidedDrawdownVsLnasPct": round(lnas_dd - result["maxDrawdownPct"], 2),
            "buyHoldNdxReturnPct": ndx_ret,
            "beatBuyHoldNdx": result["totalReturnPct"] > ndx_ret,
        })
        validation_windows.append(result)

    full_result = simulate_window(decided_dates, decisions, bear_returns, safe_returns)
    lnas_ret_full, lnas_dd_full = buy_and_hold_return_and_dd(lnas_close, decided_dates)
    ndx_ret_full, ndx_dd_full = buy_and_hold_return_and_dd(ndx_close, decided_dates)
    full_result.update({
        "buyHoldLnasReturnPct": lnas_ret_full,
        "buyHoldLnasMaxDrawdownPct": lnas_dd_full,
        "beatBuyHoldLnas": full_result["totalReturnPct"] > lnas_ret_full,
        "avoidedDrawdownVsLnasPct": round(lnas_dd_full - full_result["maxDrawdownPct"], 2),
        "buyHoldNdxReturnPct": ndx_ret_full,
        "beatBuyHoldNdx": full_result["totalReturnPct"] > ndx_ret_full,
    })

    return full_result, validation_windows, decisions, currently_holding, sessions_since_exit


def summarize_validation_windows(windows: list[dict]) -> dict:
    if not windows:
        return {"windowsEvaluated": 0}
    win_rates = [w["winRatePct"] for w in windows if w["totalTrades"] > 0]
    returns = [w["totalReturnPct"] for w in windows]
    return {
        "windowsEvaluated": len(windows),
        "meanWinRatePct": round(float(np.mean(win_rates)), 2) if win_rates else None,
        "stdDevWinRatePct": round(float(np.std(win_rates)), 2) if win_rates else None,
        "meanTotalReturnPct": round(float(np.mean(returns)), 2),
        "stdDevTotalReturnPct": round(float(np.std(returns)), 2),
        "meanTradesPerWindow": round(float(np.mean([w["totalTrades"] for w in windows])), 2),
        "meanCashSessionsPerWindow": round(float(np.mean([w["cashSessions"] for w in windows])), 2),
        "meanBuyHoldLnasReturnPct": round(float(np.mean([w["buyHoldLnasReturnPct"] for w in windows])), 2),
        "windowsBeatingBuyHoldLnas": sum(1 for w in windows if w["beatBuyHoldLnas"]),
        "meanAvoidedDrawdownVsLnasPct": round(float(np.mean([w["avoidedDrawdownVsLnasPct"] for w in windows])), 2),
        "meanBuyHoldNdxReturnPct": round(float(np.mean([w["buyHoldNdxReturnPct"] for w in windows])), 2),
        "windowsBeatingBuyHoldNdx": sum(1 for w in windows if w["beatBuyHoldNdx"]),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    log.info("Fetching data...")
    bear = load_clean_series(BEAR_TICKER)
    safe = load_clean_series(SAFE_TICKER)
    lnas = load_clean_series(LNAS_TICKER)
    ref = load_clean_series(REF_TICKER, fallback=REF_FALLBACK_TICKER)

    ref_close = ref["Close"]
    features = compute_gmma_features(ref_close)
    trend = compute_trend_indicators(ref_close)
    labeled_pool = build_labeled_pool(features, ref_close)
    liquidity_ratio = compute_liquidity_ratio(bear["Volume"])

    bear_returns = bear["Close"].pct_change() * 100
    safe_returns = safe["Close"].pct_change() * 100

    trading_dates = ref_close.index.intersection(bear.index).intersection(safe.index)
    trading_dates = trading_dates.sort_values()

    log.info("Running walk-forward backtest over %d sessions...", len(trading_dates))
    full_result, validation_windows, decisions, currently_holding, sessions_since_exit = walk_forward_backtest(
        trading_dates, features, trend, labeled_pool, liquidity_ratio,
        ref_close, bear_returns, safe_returns, lnas["Close"], ref_close,
    )

    validation_summary = summarize_validation_windows(validation_windows)

    chart_series = []
    cumulative = INITIAL_CAPITAL
    for row in full_result["ledger"]:
        chart_series.append({
            "date": row["date"],
            "portfolioValue": row["portfolioValueAfter"],
            "cumulativeProfit": round(row["portfolioValueAfter"] - INITIAL_CAPITAL, 2),
        })

    last_date = trading_dates[-1]
    last_decision = decisions.get(last_date)
    now_local = datetime.now(ZoneInfo(TIMEZONE))

    live_signal = None
    if last_decision is not None:
        live_signal = {
            "asOfSessionDate": str(last_date.date()),
            "asOfTimestamp": now_local.isoformat(),
            "rawPrediction": last_decision.knn_prediction,
            "recommendedAsset": last_decision.asset,
            "action": last_decision.action,
            "currentlyHolding": currently_holding,
            "confidence": round(last_decision.knn_confidence, 4),
            "sessionsSinceLastExit": sessions_since_exit,
            "cooldownActive": sessions_since_exit is not None and sessions_since_exit < COOLDOWN_SESSIONS_AFTER_EXIT,
            "gate": last_decision.gate.to_json(),
            "lastPrices": {
                "SNAS": round(float(bear["Close"].iloc[-1]), 4),
                "SAFE": round(float(safe["Close"].iloc[-1]), 4),
                "LNAS": round(float(lnas["Close"].iloc[-1]), 4),
            },
            "trainingSamples": int((labeled_pool["label_known_date"] < last_date).sum()),
        }

    output = {
        "generatedAt": now_local.isoformat(),
        "meta": {
            "strategy": "SNAS Bear Trader - selective cash-default bear rotation, sibling to LNAS-SNAS",
            "relationToLnasSnas": (
                "Shares LNAS-SNAS's GMMA feature set (on ^NDX/^IXIC) and from-scratch weighted k-NN "
                "classifier. LNAS-SNAS is always invested (LNAS or SNAS, long-biased default). This "
                "model defaults to a cash-like safe asset and only enters SNAS when every one of 8 "
                "independent bearish conditions agree, including a precondition that price recently "
                "traded near a 5-year high before rolling over. LNAS-SNAS is never traded here."
            ),
            "tickers": {"bear": BEAR_TICKER, "safe": SAFE_TICKER, "lnasBenchmark": LNAS_TICKER, "reference": REF_TICKER},
            "model": {
                "type": "GMMA feature set + from-scratch weighted k-NN + 8-condition bearish gate",
                "k": K_NEIGHBORS,
                "distance": "euclidean, inverse-distance weighted vote",
                "classes": ["UP", "DOWN", "FLAT"],
                "flatBandPct": FLAT_BAND_PCT,
                "minKnnConfidence": MIN_KNN_CONFIDENCE,
                "features": FEATURE_COLS,
                "entryGate": [
                    "trendBreakdown (close < MA20 < MA50)",
                    f"trendAlignment (GMMA center gap <= -{ALIGNMENT_MARGIN_PCT}%)",
                    f"relativeStrength ({RS_LOOKBACK_DAYS}d & {RS_LOOKBACK_DAYS_LONG}d both negative)",
                    f"liquidity (SNAS volume >= {LIQUIDITY_MIN_RATIO}x {LIQUIDITY_LOOKBACK_DAYS}d avg)",
                    f"pullbackNotExtended (|price vs short group| <= {PULLBACK_MAX_EXTENSION_PCT}%)",
                    f"volatilitySpike (realized/baseline vol > {VOL_SPIKE_MULTIPLIER}x, below MA{VOL_REGIME_MA_DAYS})",
                    f"overboughtPrecondition (within {OVERBOUGHT_ZONE_PCT}% of 5y high in last {OVERBOUGHT_RECENCY_WINDOW} sessions)",
                    f"knnConfidence (raw=DOWN, confidence >= {MIN_KNN_CONFIDENCE})",
                ],
                "continuationGate": "trendBreakdown, trendAlignment, relativeStrength, liquidity, pullbackNotExtended re-checked every session",
                "cooldownSessionsAfterExit": COOLDOWN_SESSIONS_AFTER_EXIT,
            },
            "rebalanceSchedule": "Tuesdays and Fridays",
            "decisionCutoffLocal": DECISION_CUTOFF_LOCAL,
            "trainWindowWeeks": TRAIN_WEEKS,
            "holdoutWindowWeeks": HOLDOUT_WEEKS,
            "timezone": TIMEZONE,
            "brokerageFees": 0,
            "splitHandling": KNOWN_SPLITS_NOTE,
        },
        "liveSignal": live_signal,
        "portfolio": full_result,
        "chartSeries": chart_series,
        "validation": {
            "windows": validation_windows,
            "summary": validation_summary,
        },
    }

    import os
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=_json_default)
    log.info("Wrote %s", OUTPUT_PATH)


def _json_default(obj):
    """Comparisons/arithmetic over pandas Series produce numpy scalar types
    (np.bool_, np.float64, np.int64), which the stdlib json encoder cannot
    serialize natively - coerce them to their Python equivalents rather than
    falling back to str() and silently corrupting booleans/numbers into
    quoted strings."""
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return str(obj)


if __name__ == "__main__":
    main()
