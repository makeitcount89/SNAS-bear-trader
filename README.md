# SNAS Bear Trader

A selective, cash-default bear-market model for trading **SNAS.AX** (an
inverse/short geared Nasdaq product on the ASX). It is a sibling model to
[LNAS-SNAS](https://github.com/makeitcount89/LNAS-SNAS), reusing that
project's feature engineering and classifier, but with an inverted
philosophy and a much higher bar for taking a position.

## How this differs from LNAS-SNAS

| | LNAS-SNAS | SNAS Bear Trader |
|---|---|---|
| Default state | Always invested (LNAS or SNAS) | Cash / safe asset (`AAA.AX`) |
| Tradable assets | LNAS.AX and SNAS.AX | SNAS.AX only (LNAS is never bought) |
| Entry gate | 4 filters, majority of sessions traded | 8 conditions, all must agree simultaneously |
| Turnover | High — flips between LNAS/SNAS almost every rebalance | Low — long stretches in cash, few high-conviction entries |
| Objective | Beat buy-and-hold LNAS while always in the market | Preserve capital by default; only step in front of a confirmed, high-conviction downturn |

LNAS-SNAS is not modified by this project — it was only read for reference.
See its README/`scripts/engine.py` for the original design and iteration
history this project builds on.

## Philosophy

This model is built for a specific belief: that a multi-year Nasdaq bull run
can become extended/overbought, and that the highest-value trade is not
constantly rotating between long and short, but instead **sitting in cash
almost all the time** and only stepping into SNAS when a fall away from an
overbought high is actually confirmed — not merely "GMMA looks a bit
bearish."

Concretely, entering SNAS requires **all eight** of the following at once
(see `scripts/engine.py`, `evaluate_bear_gate`):

1. **Trend breakdown** — reference index closes below its 20-day MA, *and*
   the 20-day MA is below the 50-day MA (a confirmed breakdown, not just a
   dip).
2. **GMMA trend alignment** — the short-EMA group sits at least 0.25% below
   the long-EMA group (tighter than LNAS-SNAS's 0.10% margin).
3. **Relative strength** — both the 20-day *and* 60-day trailing returns of
   the reference index are negative (LNAS-SNAS only checks one lookback).
4. **Liquidity** — SNAS.AX volume is at least 80% of its trailing 20-day
   average (ensures the signal is tradable, not on a thin/illiquid day).
5. **Pullback not (yet) extended** — price is within 2.5% of the short EMA
   group (tighter than LNAS-SNAS's 3.5%), so entries aren't chasing a move
   that has already run.
6. **Volatility spike** — realized 10-day volatility is over 1.5x its 60-day
   baseline while price is below its 50-day MA (a genuine downside vol
   expansion, not just any elevated volatility).
7. **Fell from overbought** — price traded within 8% of its trailing 5-year
   high at some point in the last 60 sessions. This is the condition that
   most differs from LNAS-SNAS: it explicitly encodes "catching a fall from
   an overbought high" rather than shorting an already-well-established
   downtrend.
8. **k-NN confidence** — the from-scratch weighted k-NN classifier's raw
   prediction is DOWN *with at least 60% of the weighted vote* (LNAS-SNAS
   has no confidence threshold at all — any DOWN prediction plus its 4
   filters is enough).

While holding SNAS, conditions 1–5 are re-checked every session; if any one
fails, the position exits back to cash. Conditions 6–8 are entry-only
triggers (matching LNAS-SNAS's own asymmetric design, where the entry bar
and the hold bar differ).

After an exit, a **4-session cooldown** blocks immediate re-entry, to avoid
whipsawing back in right after being stopped out — LNAS-SNAS has no
cooldown since it is never flat.

## Shared machinery (reused from LNAS-SNAS)

- **GMMA (Guppy Multiple Moving Average) features**, computed only on the
  unleveraged reference index (`^NDX`, falling back to `^IXIC`) so the
  signal isn't contaminated by the geared products' own leverage decay:
  short EMA spans `(3, 5, 8, 10, 12, 15)`, long EMA spans
  `(30, 35, 40, 45, 50, 60)`, giving three features: short-group
  compression, long-group separation, and price-vs-short-group extension.
- **From-scratch k-NN** (k=3, Euclidean distance, inverse-distance-weighted
  vote) — no scikit-learn dependency, trained on next-session UP/DOWN/FLAT
  labels (±0.5% flat band) with a strictly no-lookahead expanding training
  pool.
- **Split-adjustment and data-artifact handling** — known splits are
  fetched live via `yfinance`'s `Ticker.splits` and applied surgically;
  any single-session move over 30% not explained by a recorded split is
  treated as a data artifact and the series is rebased, with a warning
  logged.

## Backtest methodology

Walk-forward, same shape as LNAS-SNAS:

- A 2-year (104-week) training floor before any decision is evaluated.
- Non-overlapping 52-week holdout windows, most recent first, each
  simulated independently from a fresh $500 seed.
- Benchmarks per window: buy-and-hold LNAS and buy-and-hold the reference
  index, both over the identical date range.
- Additionally reports **max drawdown** for this strategy vs. buy-and-hold
  LNAS's max drawdown over the same window (`avoidedDrawdownVsLnasPct`) —
  since the point of a cash-default strategy is capital preservation, not
  just raw return, this number is arguably the more important one to watch.

## Tickers

- `SNAS.AX` — the only asset this strategy ever buys.
- `AAA.AX` — BetaShares Australian High Interest Cash ETF, used as the
  cash/safe-asset default and its return series in the backtest (swap for a
  bond ETF such as `IAF.AX` in `scripts/engine.py`'s `SAFE_TICKER` constant
  if you'd rather model duration-driven bond gains during rate-cut bear
  markets — cash was chosen as the default here because it's resilient
  regardless of *why* the bear market happens).
- `LNAS.AX` — benchmark only, never traded.
- `^NDX` (fallback `^IXIC`) — reference index for feature engineering only.

## Known simplifications vs. LNAS-SNAS

- The live signal uses the latest available daily bar rather than
  LNAS-SNAS's intraday 14:00 Australia/Adelaide cutoff price resolution
  (which pulls 60-minute bars to get a same-day price ahead of the close).
  Daily closes are simpler and robust; if same-day intraday freshness turns
  out to matter, that logic can be ported over from LNAS-SNAS's
  `resolve_session_price`.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/engine.py    # writes public/strategy_data.json
```

An offline smoke test (no network required — monkey-patches `yfinance`
with synthetic data) is available at `scripts/test_offline_smoke.py`:

```bash
python3 scripts/test_offline_smoke.py
```

### GitHub Actions

`.github/workflows/run_strategy.yml` runs the engine on the same Tuesday/
Friday schedule as LNAS-SNAS and commits `public/strategy_data.json` back to
the repo. No secrets are required.

## Disclaimer

This is a research/backtesting tool, not financial advice. Geared/inverse
products carry leverage decay and tracking error; past backtest performance,
especially over a small number of holdout windows, is not a reliable
predictor of future results.
