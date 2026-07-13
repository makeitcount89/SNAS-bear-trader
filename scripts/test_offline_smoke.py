"""
Offline smoke test: monkey-patches yfinance with synthetic OHLCV data so
engine.py's full pipeline (data cleaning, GMMA features, k-NN, bearish gate,
walk-forward backtest, JSON assembly) can be exercised without network
access. Not part of the shipped repo - dev-only verification harness.
"""
import sys
import types
import numpy as np
import pandas as pd

np.random.seed(7)

N = 2600  # ~10 trading years
dates = pd.bdate_range("2015-01-01", periods=N)

# Build a synthetic ^NDX-like series with a multi-year bull run, a blow-off top,
# and a sharp bear leg near the end, so the overbought-then-breakdown gate has
# something real to catch in the backtest.
returns = np.random.normal(0.0006, 0.011, N)
returns[int(N * 0.85):int(N * 0.85) + 40] += 0.004   # blow-off top / overbought melt-up
returns[int(N * 0.85) + 40:int(N * 0.85) + 140] -= 0.010  # subsequent bear leg
ndx_close = 15000 * np.cumprod(1 + returns)

# SNAS (inverse-geared) roughly tracks -2x NDX daily return with decay/noise
snas_returns = -2.0 * returns + np.random.normal(-0.0003, 0.004, N)
snas_close = 10 * np.cumprod(1 + snas_returns)
snas_volume = np.random.randint(50_000, 500_000, N).astype(float)

# LNAS (long-geared) roughly tracks +2x NDX daily return
lnas_returns = 2.0 * returns + np.random.normal(-0.0003, 0.004, N)
lnas_close = 10 * np.cumprod(1 + lnas_returns)

# AAA.AX cash-like: tiny steady positive drift, near-zero vol
safe_returns = np.random.normal(0.00012, 0.0003, N)
safe_close = 10 * np.cumprod(1 + safe_returns)


def make_df(close, volume=None):
    vol = volume if volume is not None else np.random.randint(1000, 10000, N).astype(float)
    return pd.DataFrame({
        "Open": close, "High": close * 1.001, "Low": close * 0.999,
        "Close": close, "Volume": vol,
    }, index=dates)


fake_data = {
    "SNAS.AX": make_df(snas_close, snas_volume),
    "AAA.AX": make_df(safe_close),
    "LNAS.AX": make_df(lnas_close),
    "^NDX": make_df(ndx_close),
}


def fake_download(ticker, period=None, interval=None, auto_adjust=None, progress=None):
    return fake_data[ticker].copy()


class FakeTicker:
    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def splits(self):
        return pd.Series(dtype=float)


fake_yf = types.ModuleType("yfinance")
fake_yf.download = fake_download
fake_yf.Ticker = FakeTicker
sys.modules["yfinance"] = fake_yf

sys.path.insert(0, "scripts")
import engine  # noqa: E402

engine.main()

import json
with open(engine.OUTPUT_PATH) as f:
    data = json.load(f)

print("generatedAt:", data["generatedAt"])
print("liveSignal:", json.dumps(data["liveSignal"], indent=2)[:1200])
print("portfolio summary:", {k: v for k, v in data["portfolio"].items() if k != "ledger"})
print("num validation windows:", len(data["validation"]["windows"]))
print("validation summary:", data["validation"]["summary"])
print("total decided sessions (ledger len):", len(data["portfolio"]["ledger"]))
n_snas = sum(1 for r in data["portfolio"]["ledger"] if r["asset"] == "SNAS")
n_safe = sum(1 for r in data["portfolio"]["ledger"] if r["asset"] == "SAFE")
print(f"sessions in SNAS: {n_snas}, sessions in SAFE/cash: {n_safe}")
n_entries = sum(1 for r in data["portfolio"]["ledger"] if r["action"] == "ENTER")
n_exits = sum(1 for r in data["portfolio"]["ledger"] if r["action"] == "EXIT")
print(f"ENTER events: {n_entries}, EXIT events: {n_exits}")
