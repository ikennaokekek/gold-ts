#!/usr/bin/env python3
"""Fixed-rule Gold TS conceptual backtest and FTMO-style path simulator.

No parameter search exists in this module. TradingView broker fills are deliberately
out of scope: all trades use Gold TS's frozen projected entry/SL/TP geometry.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Iterable

RISKS = (0.0025, 0.0050, 0.0075, 0.0100)
RR = 2.3
FAST_EMA = 50
SLOW_EMA = 200
STRUCTURE = 20
ATR_LENGTH = 14
RETRACEMENT = 0.50
ZONE_ATR = 0.10
STOP_ATR = 1.0
MAX_WAIT = 24
MIN_TRADING_DAYS = 4


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass
class Trade:
    setup_time: datetime
    entry_time: datetime
    exit_time: datetime
    direction: str
    projected_entry: float
    stop: float
    target: float
    result: str
    result_r: float
    fvg: bool
    volatility: str
    adverse_r_by_day: dict[str, float] = field(default_factory=dict)


@dataclass
class ChallengeResult:
    risk_pct: float
    phase: int
    start_date: str
    end_date: str
    status: str
    reason: str
    trading_days: int
    trades: int
    ending_balance_pct: float
    max_drawdown_pct: float


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.isdigit():
        raw = int(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_csv(path: Path) -> list[Bar]:
    aliases = {
        "time": ("time", "timestamp", "datetime", "date"),
        "open": ("open", "o"), "high": ("high", "h"),
        "low": ("low", "l"), "close": ("close", "c"),
        "volume": ("volume", "vol", "v"),
    }
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        lookup = {name.lower().strip(): name for name in reader.fieldnames}
        cols = {}
        for required, names in aliases.items():
            actual = next((lookup[n] for n in names if n in lookup), None)
            if required != "volume" and actual is None:
                raise ValueError(f"missing {required} column; found {reader.fieldnames}")
            cols[required] = actual
        bars = []
        for row in reader:
            if not row.get(cols["time"]):
                continue
            bars.append(Bar(
                parse_time(row[cols["time"]]),
                float(row[cols["open"]]), float(row[cols["high"]]),
                float(row[cols["low"]]), float(row[cols["close"]]),
                float(row[cols["volume"]]) if cols["volume"] and row.get(cols["volume"]) else None,
            ))
    bars.sort(key=lambda bar: bar.time)
    if any(a.time >= b.time for a, b in zip(bars, bars[1:])):
        raise ValueError("timestamps must be unique and strictly increasing")
    if any(bar.low > min(bar.open, bar.close, bar.high) or bar.high < max(bar.open, bar.close, bar.low) for bar in bars):
        raise ValueError("invalid OHLC geometry")
    return bars


def ema(values: list[float], length: int) -> list[float | None]:
    # Pine ta.ema recurrence: first non-na source seeds the series.
    if not values:
        return []
    out: list[float | None] = [None] * len(values)
    out[0] = values[0]
    alpha = 2.0 / (length + 1)
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]  # type: ignore[operator]
    return out


def atr_rma(bars: list[Bar], length: int) -> list[float | None]:
    tr = []
    for i, bar in enumerate(bars):
        prev = bars[i - 1].close if i else bar.close
        tr.append(max(bar.high - bar.low, abs(bar.high - prev), abs(bar.low - prev)))
    out: list[float | None] = [None] * len(bars)
    if len(bars) < length:
        return out
    out[length - 1] = mean(tr[:length])
    for i in range(length, len(bars)):
        out[i] = (out[i - 1] * (length - 1) + tr[i]) / length  # type: ignore[operator]
    return out


def backtest(bars: list[Bar]) -> list[Trade]:
    """Reproduce the fixed Pine conceptual state machine on confirmed OHLC bars."""
    closes = [b.close for b in bars]
    fast, slow, atr = ema(closes, FAST_EMA), ema(closes, SLOW_EMA), atr_rma(bars, ATR_LENGTH)
    atr_pct_history: list[float] = []
    state = "NONE"
    setup = {}
    trades: list[Trade] = []
    active_trade: Trade | None = None

    for i, bar in enumerate(bars):
        atr_i = atr[i]
        atr_pct = atr_i / bar.close if atr_i is not None and bar.close else None
        trailing_vol = median(atr_pct_history[-200:]) if len(atr_pct_history) >= 20 else None
        vol_regime = "HIGH" if trailing_vol is not None and atr_pct is not None and atr_pct > trailing_vol else "LOW" if trailing_vol is not None else "UNCLASSIFIED"

        terminal_this_bar = False
        if state == "FORMING":
            age = i - setup["index"]
            direction = setup["direction"]
            trend_ok = (direction == 1 and fast[i] is not None and slow[i] is not None and fast[i] > slow[i] and bar.close > fast[i]) or (direction == -1 and fast[i] is not None and slow[i] is not None and fast[i] < slow[i] and bar.close < fast[i])
            stop_breached = bar.low <= setup["stop"] if direction == 1 else bar.high >= setup["stop"]
            touched = age > 0 and bar.high >= setup["lower"] and bar.low <= setup["upper"]
            geometry_ok = setup["risk"] > 0 and (setup["stop"] < setup["entry"] < setup["target"] if direction == 1 else setup["target"] < setup["entry"] < setup["stop"])
            if stop_breached or not trend_ok or not geometry_ok:
                state, setup, terminal_this_bar = "NONE", {}, True
            elif age > MAX_WAIT:
                state, setup, terminal_this_bar = "NONE", {}, True
            elif touched:
                active_trade = Trade(
                    setup_time=setup["time"], entry_time=bar.time, exit_time=bar.time,
                    direction="LONG" if direction == 1 else "SHORT",
                    projected_entry=setup["entry"], stop=setup["stop"], target=setup["target"],
                    result="OPEN", result_r=0.0, fvg=setup["fvg"], volatility=setup["volatility"],
                )
                state = "ACTIVE"

        elif state == "ACTIVE" and active_trade is not None:
            direction = 1 if active_trade.direction == "LONG" else -1
            risk = abs(active_trade.projected_entry - active_trade.stop)
            adverse = (bar.low - active_trade.projected_entry) / risk if direction == 1 else (active_trade.projected_entry - bar.high) / risk
            day = bar.time.date().isoformat()
            active_trade.adverse_r_by_day[day] = min(active_trade.adverse_r_by_day.get(day, 0.0), max(-1.0, adverse))
            stop_hit = bar.low <= active_trade.stop if direction == 1 else bar.high >= active_trade.stop
            tp_hit = bar.high >= active_trade.target if direction == 1 else bar.low <= active_trade.target
            if stop_hit and tp_hit:
                active_trade.result, active_trade.result_r = "AMBIGUOUS", -1.0
            elif stop_hit:
                active_trade.result, active_trade.result_r = "LOSS", -1.0
            elif tp_hit:
                active_trade.result, active_trade.result_r = "WIN", RR
            if stop_hit or tp_hit:
                active_trade.exit_time = bar.time
                trades.append(active_trade)
                active_trade, state, terminal_this_bar = None, "NONE", True

        # Pine retains a terminal state through its event bar. It may create a new
        # setup on the following reset bar, never from stale same-bar geometry.
        if state == "NONE" and not terminal_this_bar and i >= STRUCTURE and atr_i is not None and fast[i] is not None and slow[i] is not None:
            prior_high = max(b.high for b in bars[i - STRUCTURE:i])
            prior_low = min(b.low for b in bars[i - STRUCTURE:i])
            bull_break = bar.close > prior_high and bars[i - 1].close <= prior_high
            bear_break = bar.close < prior_low and bars[i - 1].close >= prior_low
            direction = 1 if fast[i] > slow[i] and bar.close > fast[i] and bull_break else -1 if fast[i] < slow[i] and bar.close < fast[i] and bear_break else 0
            if direction:
                broken = prior_high if direction == 1 else prior_low
                impulse = abs(bar.close - broken)
                entry = bar.close - impulse * RETRACEMENT if direction == 1 else bar.close + impulse * RETRACEMENT
                half_width = atr_i * ZONE_ATR
                stop = entry - atr_i * STOP_ATR if direction == 1 else entry + atr_i * STOP_ATR
                risk = abs(entry - stop)
                target = entry + risk * RR if direction == 1 else entry - risk * RR
                bull_fvg = i >= 2 and bar.low > bars[i - 2].high
                bear_fvg = i >= 2 and bar.high < bars[i - 2].low
                if risk > 0:
                    setup = {"index": i, "time": bar.time, "direction": direction, "entry": entry,
                             "lower": entry - half_width, "upper": entry + half_width, "stop": stop,
                             "risk": risk, "target": target, "fvg": bull_fvg if direction == 1 else bear_fvg,
                             "volatility": vol_regime}
                    state = "FORMING"
        if atr_pct is not None:
            atr_pct_history.append(atr_pct)
    return trades


def simulate_phase(trades: list[Trade], start_date: str, risk: float, phase: int) -> tuple[ChallengeResult, int]:
    target = 0.10 if phase == 1 else 0.05
    initial = balance = peak = 1.0
    max_dd = 0.0
    trading_days: set[str] = set()
    day_start_balance: dict[str, float] = {}
    used = 0
    end_date = start_date
    for idx, trade in enumerate(trades):
        trade_day = trade.entry_time.date().isoformat()
        if trade_day < start_date:
            continue
        used += 1
        trading_days.add(trade_day)
        risk_cash = balance * risk
        for day, adverse_r in sorted(trade.adverse_r_by_day.items()):
            if day < start_date:
                continue
            day_start_balance.setdefault(day, balance)
            worst_equity = balance + risk_cash * adverse_r
            max_dd = max(max_dd, (peak - worst_equity) / initial)
            if day_start_balance[day] - worst_equity >= 0.05 * initial:
                return ChallengeResult(risk * 100, phase, start_date, day, "FAIL", "DAILY_LOSS", len(trading_days), used, balance * 100, max_dd * 100), idx
            if worst_equity <= 0.90 * initial:
                return ChallengeResult(risk * 100, phase, start_date, day, "FAIL", "MAX_LOSS", len(trading_days), used, balance * 100, max_dd * 100), idx
        exit_day = trade.exit_time.date().isoformat()
        day_start_balance.setdefault(exit_day, balance)
        balance += risk_cash * trade.result_r  # ambiguity is conservatively -1R
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / initial)
        end_date = exit_day
        if day_start_balance[exit_day] - balance >= 0.05 * initial:
            return ChallengeResult(risk * 100, phase, start_date, end_date, "FAIL", "DAILY_LOSS", len(trading_days), used, balance * 100, max_dd * 100), idx
        if balance <= 0.90 * initial:
            return ChallengeResult(risk * 100, phase, start_date, end_date, "FAIL", "MAX_LOSS", len(trading_days), used, balance * 100, max_dd * 100), idx
        if balance >= initial * (1 + target) and len(trading_days) >= MIN_TRADING_DAYS:
            return ChallengeResult(risk * 100, phase, start_date, end_date, "PASS", "TARGET", len(trading_days), used, balance * 100, max_dd * 100), idx
    return ChallengeResult(risk * 100, phase, start_date, end_date, "INCOMPLETE", "DATA_END", len(trading_days), used, balance * 100, max_dd * 100), len(trades)


def rolling_challenges(bars: list[Bar], trades: list[Trade]) -> list[dict]:
    rows = []
    dates = sorted({bar.time.date().isoformat() for bar in bars})
    for risk in RISKS:
        for start in dates:
            phase1, p1_index = simulate_phase(trades, start, risk, 1)
            row = {f"phase1_{k}": v for k, v in asdict(phase1).items()}
            row.update({"risk_pct": risk * 100, "rolling_start": start, "phase2_status": "NOT_ELIGIBLE",
                        "phase2_reason": "PHASE1_NOT_PASSED", "full_completion": False})
            if phase1.status == "PASS":
                remaining = trades[p1_index + 1:]
                if remaining:
                    phase2_start = remaining[0].entry_time.date().isoformat()
                    phase2, _ = simulate_phase(remaining, phase2_start, risk, 2)
                    row.update({"phase2_status": phase2.status, "phase2_reason": phase2.reason,
                                "phase2_start": phase2.start_date, "phase2_end": phase2.end_date,
                                "phase2_trading_days": phase2.trading_days,
                                "full_completion": phase2.status == "PASS"})
                else:
                    row.update({"phase2_status": "INCOMPLETE", "phase2_reason": "DATA_END"})
            rows.append(row)
    return rows


def max_streak(results: Iterable[str], wanted: str) -> int:
    best = current = 0
    for result in results:
        current = current + 1 if result == wanted else 0
        best = max(best, current)
    return best


def performance(trades: list[Trade]) -> dict:
    wins = [t for t in trades if t.result == "WIN"]
    losses = [t for t in trades if t.result == "LOSS"]
    ambiguous = [t for t in trades if t.result == "AMBIGUOUS"]
    resolved = len(wins) + len(losses)
    rs = [t.result_r for t in trades]
    equity = peak = max_dd = 0.0
    for value in rs:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    gross_win = sum(t.result_r for t in wins)
    gross_loss = abs(sum(t.result_r for t in losses + ambiguous))
    by_month = defaultdict(float)
    by_year = defaultdict(float)
    for t in trades:
        by_month[t.exit_time.strftime("%Y-%m")] += t.result_r
        by_year[str(t.exit_time.year)] += t.result_r
    return {"trades": len(trades), "wins": len(wins), "losses": len(losses), "ambiguous": len(ambiguous),
            "win_rate_resolved_pct": 100 * len(wins) / resolved if resolved else None,
            "expectancy_r_including_ambiguous_as_loss": mean(rs) if rs else None,
            "profit_factor_including_ambiguous_as_loss": gross_win / gross_loss if gross_loss else None,
            "max_consecutive_wins": max_streak((t.result for t in trades), "WIN"),
            "max_consecutive_losses": max_streak(("LOSS" if t.result == "AMBIGUOUS" else t.result for t in trades), "LOSS"),
            "max_drawdown_r": max_dd, "monthly_r": dict(sorted(by_month.items())), "yearly_r": dict(sorted(by_year.items()))}


def group_performance(trades: list[Trade], key) -> dict:
    groups = defaultdict(list)
    for trade in trades:
        groups[str(key(trade))].append(trade)
    return {name: performance(items) for name, items in sorted(groups.items())}


def risk_metrics(trades: list[Trade], risk: float) -> dict:
    if not trades:
        return {"risk_pct": risk * 100, "status": "NOT_RUN_NO_DATA", "ending_balance_pct": None,
                "max_drawdown_pct_compounded_close_to_close": None, "worst_trading_day_pct": None,
                "best_trading_day_pct": None, "average_trades_per_trading_day": None,
                "average_trades_per_active_week": None}
    balance = peak = 1.0
    max_dd = 0.0
    daily = defaultdict(float)
    for trade in trades:
        pnl = balance * risk * trade.result_r
        balance += pnl
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) * 100)
        daily[trade.exit_time.date().isoformat()] += pnl * 100
    weeks = {t.entry_time.strftime("%G-%V") for t in trades}
    days = {t.entry_time.date().isoformat() for t in trades}
    return {"risk_pct": risk * 100, "ending_balance_pct": balance * 100,
            "max_drawdown_pct_compounded_close_to_close": max_dd,
            "worst_trading_day_pct": min(daily.values()) if daily else None,
            "best_trading_day_pct": max(daily.values()) if daily else None,
            "average_trades_per_trading_day": len(trades) / len(days) if days else None,
            "average_trades_per_active_week": len(trades) / len(weeks) if weeks else None}


def rolling_summary(rows: list[dict], risk: float) -> dict:
    selected = [r for r in rows if math.isclose(r["risk_pct"], risk * 100)]
    statuses = [r["phase1_status"] for r in selected]
    decided = statuses.count("PASS") + statuses.count("FAIL")
    pass_days = [r["phase1_trading_days"] for r in selected if r["phase1_status"] == "PASS"]
    eligible = [r for r in selected if r["phase1_status"] == "PASS"]
    full = sum(bool(r["full_completion"]) for r in selected)
    return {"risk_pct": risk * 100, "phase1_simulations": len(selected),
            "phase1_passes": statuses.count("PASS"), "phase1_failures": statuses.count("FAIL"),
            "phase1_incomplete": statuses.count("INCOMPLETE"),
            "phase1_pass_rate_excluding_incomplete_pct": 100 * statuses.count("PASS") / decided if decided else None,
            "median_trading_days_to_phase1_pass": median(pass_days) if pass_days else None,
            "phase2_passes_among_eligible": sum(r["phase2_status"] == "PASS" for r in eligible),
            "full_two_phase_completions": full,
            "full_completion_rate_pct": 100 * full / len(selected) if selected else None,
            "daily_loss_failures": sum(r["phase1_reason"] == "DAILY_LOSS" or r.get("phase2_reason") == "DAILY_LOSS" for r in selected),
            "maximum_loss_failures": sum(r["phase1_reason"] == "MAX_LOSS" or r.get("phase2_reason") == "MAX_LOSS" for r in selected),
            "worst_observed_drawdown_pct": max((r["phase1_max_drawdown_pct"] for r in selected), default=None)}


def walk_forward_summary(trades: list[Trade]) -> dict:
    years = sorted({trade.entry_time.year for trade in trades})
    if len(years) < 2:
        return {"status": "NOT_RUN_INSUFFICIENT_YEARS", "required_years": 2,
                "available_years": years, "note": "fixed rules; no fitting or selection"}
    return {"status": "RUN", "definition": "first calendar year is context; each later calendar year is an untouched fixed-rule evaluation slice",
            "context_year": years[0], "evaluation_slices": {str(year): performance([t for t in trades if t.entry_time.year == year]) for year in years[1:]},
            "note": "walk-forward here is temporal robustness slicing, not parameter optimization"}


def monte_carlo(trades: list[Trade], risk: float, iterations: int = 1000) -> dict:
    if not trades:
        return {"iterations": 0, "note": "not run: no trades"}
    rng = random.Random(20261001)
    results = [t.result_r for t in trades]
    drawdowns = []
    endings = []
    for _ in range(iterations):
        shuffled = results[:]
        rng.shuffle(shuffled)
        balance = peak = 1.0
        max_dd = 0.0
        for result in shuffled:
            balance *= 1 + risk * result
            peak = max(peak, balance)
            max_dd = max(max_dd, (peak - balance) * 100)
        endings.append(balance * 100); drawdowns.append(max_dd)
    return {"iterations": iterations, "seed": 20261001,
            "median_ending_balance_pct": median(endings),
            "p95_max_drawdown_pct": sorted(drawdowns)[int(0.95 * (iterations - 1))],
            "note": "trade-order risk stress only; shuffling destroys temporal market structure"}


def write_outputs(out: Path, dataset: Path | None, bars: list[Bar], trades: list[Trade], rolling: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"status": "AVAILABLE" if bars else "NO_DATASET_AVAILABLE", "source": str(dataset) if dataset else None,
                "bars": len(bars), "start": bars[0].time.isoformat() if bars else None,
                "end": bars[-1].time.isoformat() if bars else None, "timeframe": "15m expected; timestamp spacing must be verified"}
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    split = int(len(trades) * 0.70)
    summary = {"fixed_parameters": {"ema": [50, 200], "structure": 20, "atr": 14, "retracement": 0.5,
                "zone_atr": 0.1, "stop_atr": 1.0, "expiry_bars": 24, "rr": 2.3},
               "ftmo_assumptions": {"phase1_target_pct": 10, "phase2_target_pct": 5,
                "daily_loss_pct": 5, "maximum_loss_pct": 10, "minimum_trading_days": 4,
                "period": "unlimited but right-censored by dataset end", "risk_basis": "current balance at entry"},
               "costs": {"spread": 0, "commission": 0, "slippage": 0, "note": "zero-cost baseline; no reliable cost data supplied"},
               "ambiguity_policy": "counted as -1R conservatively for capital and FTMO paths",
               "performance": performance(trades),
               "by_direction": group_performance(trades, lambda t: t.direction),
               "by_fvg": group_performance(trades, lambda t: "FVG" if t.fvg else "NO_FVG"),
               "by_volatility": group_performance(trades, lambda t: t.volatility),
               "chronological_split": {"definition": "first 70% trades / final 30% trades; no fitting",
                                        "in_sample": performance(trades[:split]), "out_of_sample": performance(trades[split:])},
               "walk_forward": walk_forward_summary(trades),
               "risk_scenarios": [risk_metrics(trades, r) for r in RISKS],
               "rolling_challenges": [rolling_summary(rolling, r) for r in RISKS],
               "monte_carlo": {str(r * 100): monte_carlo(trades, r) for r in RISKS}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    fields = sorted({key for row in rolling for key in row}) or ["risk_pct", "rolling_start", "phase1_status", "phase2_status", "full_completion"]
    with (out / "rolling_challenges.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rolling)
    trade_fields = list(Trade.__dataclass_fields__)
    with (out / "conceptual_trades.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=trade_fields, lineterminator="\n"); writer.writeheader()
        for trade in trades:
            row = asdict(trade); row["adverse_r_by_day"] = json.dumps(row["adverse_r_by_day"], sort_keys=True)
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path)
    parser.add_argument("--output", type=Path, default=Path("validation/outputs"))
    args = parser.parse_args()
    candidates = [args.data] if args.data else sorted(Path("data").glob("*.csv")) if Path("data").exists() else []
    dataset = next((p for p in candidates if p and p.exists()), None)
    bars = load_csv(dataset) if dataset else []
    trades = backtest(bars) if bars else []
    rolling = rolling_challenges(bars, trades) if bars else []
    write_outputs(args.output, dataset, bars, trades, rolling)
    print(json.dumps({"dataset": str(dataset) if dataset else None, "bars": len(bars), "trades": len(trades), "rolling": len(rolling)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
