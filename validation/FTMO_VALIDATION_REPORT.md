# Gold TS v0.1 — FTMO Historical Challenge Validation

## Executive conclusion

**Category 1 — Historical evidence currently insufficient.**

No XAUUSD 15-minute OHLC dataset exists in the repository or accessible workspace. The referenced public GitHub dataset could not be fetched because outbound GitHub access returned `CONNECT tunnel failed, response 403`. The available period is therefore **none: 0 bars, no start date, and no end date**. No trade result, pass rate, profitability result, robustness result, or FTMO-compatibility inference can honestly be calculated.

This is a data-availability conclusion, not a negative or positive finding about Gold TS.

## Dataset and date range

| Item | Available result |
|---|---:|
| Dataset | None available |
| XAUUSD 15-minute bars | 0 |
| Start | N/A |
| End | N/A |
| Trades | 0 |
| Costs | Zero-cost baseline specified, but not executed |

Machine-readable provenance is in `outputs/dataset_manifest.json`. No missing prices or dates were synthesized.

## Methodology implemented

`ftmo_validate.py` is a standalone validation layer; it does not modify the production Pine strategy. It mirrors the fixed conceptual rules: EMA 50/200 trend plus price position, 20-bar prior-range structure break, ATR(14), frozen 50% retracement entry, 0.10 ATR zone, 1 ATR stop, 2.3R target, 24 eligible post-detection bars, confirmed-bar zone revalidation, direction-matching three-candle FVG metadata, and no FVG filter.

The runner intentionally models the **Signal/Conceptual** entry, not TradingView's broker-emulator market fill. A touch is recognized only from a completed later OHLC candle; invalidation has priority when entry and stop occur in the same waiting candle. Outcomes begin on the bar after confirmed activation. A post-entry candle containing both SL and TP is `AMBIGUOUS` and is charged as **-1R** in capital and FTMO paths, never as a win.

Rolling starts are defined as every unique UTC dataset calendar date. A fresh account starts at each date for each predefined risk. Phase 2 starts at the next trade after a Phase 1 pass. Right-edge runs are `INCOMPLETE`, not failures. No optimization or selection path exists.

A causal volatility label is predefined as setup-time ATR/close above or below the median of up to the preceding 200 available ATR/close observations, requiring at least 20 prior observations. It is metadata only.

## Exact FTMO simulation assumptions

* Phase 1 target: +10% of initial balance.
* Phase 2 target: +5% of initial balance.
* Maximum daily loss: 5% of initial balance.
* Maximum total loss: 10% of initial balance.
* Minimum trading days: four distinct UTC entry dates.
* Trading period: unlimited in principle, right-censored at dataset end.
* Risk scenarios: 0.25%, 0.50%, 0.75%, and 1.00%; each risk amount is a fixed percentage of current balance at conceptual entry.
* Daily-loss reconstruction: day-start realized balance minus the worst reconstructed equity during the UTC day, including the active trade's adverse OHLC excursion and realized results. Because 15-minute OHLC cannot reveal the path inside a candle, adverse excursion is conservative but cannot reproduce tick-level FTMO equity exactly.
* Ambiguous same-bar SL/TP: -1R for challenge capital.
* Costs: spread 0, commission 0, slippage 0. This is explicitly a zero-cost baseline because no reliable broker/account cost schedule or bid/ask history was supplied.
* TradingView fills are excluded. The validation uses frozen projected conceptual Entry/SL/TP only.

## Aggregate results

No performance metrics were computed from market data.

| Risk/trade | Trades | Wins | Losses | Ambiguous | Win rate | Expectancy | Profit factor | Max DD | Worst day | Best day |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25% | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 0.50% | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 0.75% | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 1.00% | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

Monthly, yearly, long/short, FVG/no-FVG, and volatility-regime outputs are empty—not zero-performance claims.

## Rolling challenge results

| Risk | Phase 1 runs | Pass | Fail | Incomplete | Pass rate excl. incomplete | Phase 2 passes | Full completions | Full completion rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.25% | 0 | 0 | 0 | 0 | N/A | 0 | 0 | N/A |
| 0.50% | 0 | 0 | 0 | 0 | N/A | 0 | 0 | N/A |
| 0.75% | 0 | 0 | 0 | 0 | N/A | 0 | 0 | N/A |
| 1.00% | 0 | 0 | 0 | 0 | N/A | 0 | 0 | N/A |

The CSV contains its schema and zero rows. Zero simulations must not be interpreted as zero failures or a 0%/100% pass rate.

## Drawdown and loss streaks

Maximum drawdown in R/percent, consecutive wins/losses, worst/best day, and average trades per day/week are **N/A**. No market observations or trades exist from which to estimate them.

## OOS, walk-forward, and Monte Carlo

* Chronological split is predefined as the first 70% versus final 30% of trades, with no fitting. It was not run.
* Walk-forward fixed-rule time slicing requires sufficient calendar coverage and was not run.
* Monte Carlo is predefined with deterministic seed `20261001`. It shuffles fixed trade R outcomes only and explicitly destroys market chronology; it was not run because there are no trades.

## Machine-readable outputs

* `outputs/dataset_manifest.json` — explicit `NO_DATASET_AVAILABLE` status and null dates.
* `outputs/summary.json` — fixed assumptions, empty performance/robustness sections, and four `NOT_RUN_NO_DATA` risk scenarios.
* `outputs/rolling_challenges.csv` — rolling-result schema with zero fabricated runs.
* `outputs/conceptual_trades.csv` — trade schema with zero fabricated trades.

## Limitations and required next step

The primary limitation is total absence of price data. Additionally, even with 15-minute OHLC, intrabar ordering, bid/ask spread, slippage, exact FTMO server-midnight equity, and gap execution cannot be reconstructed perfectly. Dataset tick size and TradingView's exact early-series EMA/ATR behavior must be cross-checked before treating an external runner as numerically identical to Pine.

The next evidence-based step is to supply a vetted XAUUSD 15-minute CSV with UTC timestamps and OHLC columns, document its source/timezone/gap policy, run `python validation/ftmo_validate.py --data <file.csv>`, and reconcile a sample of setups against TradingView before interpreting the FTMO tables.
