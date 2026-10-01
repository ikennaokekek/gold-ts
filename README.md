# Gold TS v0.1

Gold TS is a research/beta TradingView strategy for XAUUSD. It implements the causal sequence **Trend → Structure → projected Entry/SL/TP → wait → revalidate → valid/invalid**. It makes no claim of profitability, elevated probability, or prop-firm suitability.

## Install and run

1. Open `gold_ts_strategy.pine` in TradingView's Pine Editor and add it to an XAUUSD chart (the exploratory baseline used 15-minute bars).
2. Leave **Backtesting / Research Mode** off for the compact live view; turn it on for historical event marks and subgroup totals.
3. To receive the one actionable notification, create a TradingView alert for the strategy and select **Any alert() function call**. With **Enable non-entry lifecycle alerts** left OFF (the default), the dynamic JSON stream emits only when a touched entry zone passes revalidation. Optional lifecycle messages are research-only, carry `actionable: false`, and must be deliberately enabled.
4. Treat results as research. Validate settings across broader and unseen periods rather than optimizing the cited short sample.

## Exact baseline rules

### Trend

The confirmed bar is bullish when EMA(50) is above EMA(200) **and** close is above EMA(50); bearish is the inverse. Both lengths are inputs. Trend grants direction only and cannot create a setup without structure.

### Structure

A bullish structure event occurs when the confirmed close exceeds the highest high of the preceding 20 bars. A bearish event occurs when it closes below the lowest low of those preceding bars. The window is adjustable. It excludes the current bar, uses no pivots, and consumes no future bars.

### Projected entry zone

At a structure event, the script freezes a 50% retracement from the breakout close toward the broken prior-range boundary. The displayed zone is the frozen center ± 0.10 setup-time ATR. Both values are inputs. Entry cannot activate on the detection bar; touches begin on the following confirmed bar.

This is an explicit neutral research baseline, not a claimed optimum. OHLC bars do not reveal the exact path through the zone, so activation is evaluated at the touch bar's close.

### Stop, target, invalidation, and expiry

* Stop is the entry center ± 1.0 setup-time ATR: below for long, above for short.
* Risk is `abs(entry center - stop)`. TP is entry + risk × R for long and entry − risk × R for short. R defaults to 2.3 and is adjustable.
* Frozen levels never trail or recalculate.
* While waiting, a trend mismatch, stop breach, or invalid geometry invalidates the setup. Stop breach takes precedence if a single waiting bar both touches the zone and breaches invalidation.
* The setup may touch during the next 24 bars by default. It expires once its age is greater than 24, so exactly 24 post-detection bars are eligible.
* Only a touched zone with supported trend, intact invalidation, unexpired lifetime, and sound geometry becomes active. Invalid and expired setups are not trades.

### FVG metadata

On the current confirmed third candle, bullish FVG means `low > high[2]`; bearish FVG means `high < low[2]`. An optional minimum size is measured in ticks. Direction-matching FVG status is frozen at setup creation. Detection and display controls change only metadata and visuals—never TS setup creation, revalidation, entry, stop, or target.

### Trade resolution

From the bar after activation, a sole TP or SL touch resolves at the corresponding frozen level in the internal R statistics. If both occur inside one OHLC bar, the internal result is **ambiguous**, not a win or loss. `use_bar_magnifier` is enabled to improve TradingView's broker-emulator fills where lower-timeframe data is available, but the explicit internal ambiguity rule remains conservative.

The implementation deliberately maintains two named models:

1. **SIGNAL / CONCEPTUAL RESEARCH MODEL.** The frozen projected entry center defines risk and the 2.3R target. A confirmed future bar must overlap the zone and pass revalidation. Conceptual outcomes and the dashboard then use the frozen entry, SL, and TP. Dashboard rows are explicitly prefixed `Conceptual`.
2. **TRADINGVIEW BROKER-EMULATOR EXECUTION MODEL.** Only after successful confirmed-bar revalidation does the strategy submit a market entry. With `process_orders_on_close = true`, the emulator can fill at the confirmed touch bar close. It does not—and must not—retroactively fill at the earlier projected entry. The frozen SL/TP bracket is submitted with that market order.

A post-revalidation limit order at the projected entry was rejected: it would either fill only on a later revisit (a different trade) or tempt a retroactive historical fill that did not exist before validation. `calc_on_order_fills` is disabled to avoid extra historical fill recalculations influencing the confirmed-bar conceptual state. Conceptual resolution no longer sends `strategy.close_all`, so it cannot race or overwrite the separate broker bracket.

Accordingly, TradingView Strategy Tester P&L is interpretable only as the broker-emulator market-entry model, subject to TradingView fill assumptions and gaps. It is **not** the P&L of the projected-entry 2.3R conceptual model. The Conceptual dashboard is the latter model, and the two must not be compared as if their entry prices were identical.

## State machine and alerts

The explicit states are `NO_SETUP`, long/short `SETUP_FORMING`, long/short `ENTRY_ACTIVE`, `INVALID`, `EXPIRED`, `COMPLETED_TP`, `COMPLETED_SL`, and `COMPLETED_AMBIGUOUS`. Only one setup exists at a time. Terminal status remains visible for one bar by default.

The yellow forming state displays direction, frozen zone, SL, TP, R, and FVG metadata without an actionable call to `alert()`. On successful revalidation, state changes once to green active, the per-setup alert flag is set, and one structured JSON alert is sent at bar close. Its payload labels the entry `projected_entry`, includes `touch_bar_close`, identifies `model: SIGNAL_CONCEPTUAL`, and warns that the projection is not the broker fill. State transition out of forming prevents repeated alerts while price remains in the zone. Invalid or expired paths never call the actionable alert.

Pine strategies do not expose usable `alertcondition()` triggers in the way indicators do. The prior inert declarations were removed. Optional lifecycle `alert()` messages now exist behind a default-OFF input; they are labeled non-actionable and cover forming, invalid, expired, conceptual TP/SL, and ambiguity. Leaving the option OFF preserves a VALID ENTRY-only `alert()` stream.

## Research output

Research mode shows bounded plot marks and dashboard segments for:

* all activated TS trades;
* TS + FVG;
* TS without FVG;
* wins, losses, resolved win rate, net R, and ambiguous count.

Ambiguous outcomes are excluded from wins, losses, and net R. No causal conclusion is inferred from subgroup results. The live projection uses one reusable box and three reusable lines rather than accumulating objects.

## Non-repainting audit

* All state changes are inside `barstate.isconfirmed`.
* Prior range explicitly uses `[1]`; FVG uses only the current and two preceding candles.
* There is no `request.security()`, pivot function, future offset, or lookahead setting.
* ATR, trend, entry, stop, target, direction, FVG tag, and setup bar are frozen at confirmed setup creation.
* No historical setup is moved or deleted based on its outcome.
* Setup events require the strategy to be idle, preventing duplicate setups during forming or active states.

Consequently, decisions are causal at confirmed-bar granularity. Realtime intrabar movement is intentionally ignored until confirmation, and alerts use `alert.freq_once_per_bar_close`.

## Automated checks

Run:

```bash
python -m unittest discover -s tests -v
```

The reference-model tests cover forming/no alert, long and short geometry, one-shot activation, invalidation at/before entry, expiration, FVG independence, large-candle precedence, and same-bar ambiguity. These tests verify the contract independently; they do **not** compile or execute Pine.

## Known limitations and manual TradingView verification

* This environment has no official TradingView Pine compiler. Paste the strategy into the current Pine Editor and confirm compilation under Pine v6.
* Confirm alert creation using **Any alert() function call**, inspect the JSON webhook payload, and verify exactly one notification for both FVG-tagged and untagged entries.
* Compare Strategy Tester order fills with the Conceptual dashboard without treating them as the same model. Confirm process-on-close and Bar Magnifier availability for the account/data range.
* Validate symbol tick formatting, chart timezone/session boundaries, gaps, tiny ATR, extreme volatility, insufficient warm-up data, and strategy behavior on live/replay bars.
* Pine scripts cannot share imported local signal code in a standalone paste-friendly file. v0.1 therefore provides the requested authoritative strategy first; an indicator companion should be derived only with synchronization tests to avoid divergent logic.

## Audit corrections (causal-execution pass)

The adversarial audit confirmed and corrected these implementation defects without changing baseline parameters:

* **High — model attribution:** projected-entry conceptual statistics and market-entry Strategy Tester results existed together without sufficiently explicit in-chart/payload attribution. Dashboard rows now say `Conceptual`; valid-entry JSON names `SIGNAL_CONCEPTUAL`, uses `projected_entry`, reports `touch_bar_close`, and states that the projection is not a broker fill.
* **High — competing exit mechanisms:** the conceptual OHLC resolver called `strategy.close_all()` while an independent frozen `strategy.exit()` bracket was already working. Those market-close calls could compete with or overwrite the broker-emulator result. Conceptual resolution now updates only conceptual state/statistics; the broker bracket alone controls broker exits.
* **Medium — fill recalculation risk:** `calc_on_order_fills` was enabled despite the confirmed-bar state model. It is now disabled so extra historical fill recalculations cannot cause the conceptual engine to consume broker-fill recalculation passes.
* **Medium — unusable strategy alert conditions:** `alertcondition()` declarations in a strategy were misleading as lifecycle facilities. They were replaced by explicit default-OFF lifecycle `alert()` calls labeled `actionable: false`; default behavior remains one valid-entry-only actionable stream.
* **Medium — ambiguous entry wording:** the alert field named `entry` could be mistaken for a broker fill. It is now `projected_entry`, alongside the observed touch-bar close and an execution warning.

The audit did **not** change EMA 50/200, structure 20, ATR 14, 50% retracement, 0.10 ATR zone, 1 ATR stop, 24-bar expiry, or default 2.3R. It found no FVG dependency in signal generation or revalidation, no future-series access, and no duplicate actionable-alert path.

## FTMO-style historical validation

The fixed-rule, conceptual-model validation runner is `validation/ftmo_validate.py`; it does not change Pine behavior. Run it with a vetted UTC XAUUSD 15-minute CSV:

```bash
python validation/ftmo_validate.py --data path/to/xauusd-15m.csv
```

The current environment contained no dataset and could not fetch the referenced GitHub repository, so the committed validation outputs explicitly report `NO_DATASET_AVAILABLE` rather than fabricating results. See `validation/FTMO_VALIDATION_REPORT.md` for assumptions and limitations.
