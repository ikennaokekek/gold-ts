import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from validation.ftmo_validate import (
    ATR_LENGTH, FAST_EMA, MAX_WAIT, RETRACEMENT, RR, SLOW_EMA, STOP_ATR,
    STRUCTURE, ZONE_ATR, Bar, ChallengeResult, Trade, ema, performance,
    simulate_phase, write_outputs,
)

UTC = timezone.utc


def trade(day, result="WIN", result_r=2.3, direction="LONG", fvg=False, adverse=-0.4):
    when = datetime(2025, 1, day, 12, tzinfo=UTC)
    return Trade(
        setup_time=when - timedelta(minutes=15), entry_time=when,
        exit_time=when + timedelta(minutes=30), direction=direction,
        projected_entry=100, stop=99 if direction == "LONG" else 101,
        target=102.3 if direction == "LONG" else 97.7,
        result=result, result_r=result_r, fvg=fvg, volatility="LOW",
        adverse_r_by_day={when.date().isoformat(): adverse},
    )


class FtmoValidationTests(unittest.TestCase):
    def test_validator_constants_match_locked_pine_defaults(self):
        pine = Path("gold_ts_strategy.pine").read_text()
        self.assertEqual((FAST_EMA, SLOW_EMA, STRUCTURE, ATR_LENGTH, RETRACEMENT, ZONE_ATR, STOP_ATR, MAX_WAIT, RR),
                         (50, 200, 20, 14, 0.5, 0.1, 1.0, 24, 2.3))
        for fragment in ('input.float(2.3, "Risk/Reward"', 'input.int(50, "Fast EMA"',
                         'input.int(200, "Slow EMA"', 'input.int(20, "Prior-range structure bars"',
                         'input.int(14, "ATR length"', 'input.int(24, "Maximum bars waiting for entry"'):
            self.assertIn(fragment, pine)

    def test_pine_style_ema_seeds_first_value(self):
        values = ema([10, 11, 12], 2)
        self.assertEqual(values[0], 10)
        self.assertAlmostEqual(values[1], 10 + (2 / 3) * 1)

    def test_phase_one_pass_requires_target_and_four_days(self):
        trades = [trade(day) for day in range(1, 6)]
        result, _ = simulate_phase(trades, "2025-01-01", 0.01, 1)
        self.assertEqual((result.status, result.reason), ("PASS", "TARGET"))
        self.assertGreaterEqual(result.trading_days, 4)

    def test_phase_two_uses_five_percent_target(self):
        trades = [trade(day) for day in range(1, 5)]
        result, _ = simulate_phase(trades, "2025-01-01", 0.01, 2)
        self.assertEqual(result.status, "PASS")

    def test_daily_loss_includes_cumulative_realized_losses(self):
        trades = [trade(1, "LOSS", -1, adverse=-1) for _ in range(6)]
        result, _ = simulate_phase(trades, "2025-01-01", 0.01, 1)
        self.assertEqual((result.status, result.reason), ("FAIL", "DAILY_LOSS"))

    def test_floating_adverse_excursion_can_fail_daily_rule(self):
        t = trade(1, "WIN", 2.3, adverse=-6)
        result, _ = simulate_phase([t], "2025-01-01", 0.01, 1)
        self.assertEqual((result.status, result.reason), ("FAIL", "DAILY_LOSS"))

    def test_maximum_loss_across_separate_days(self):
        trades = [trade(day, "LOSS", -1, adverse=-1) for day in range(1, 13)]
        result, _ = simulate_phase(trades, "2025-01-01", 0.01, 1)
        self.assertEqual((result.status, result.reason), ("FAIL", "MAX_LOSS"))

    def test_ambiguous_is_conservative_loss_in_statistics(self):
        stats = performance([trade(1, "AMBIGUOUS", -1)])
        self.assertEqual(stats["ambiguous"], 1)
        self.assertEqual(stats["expectancy_r_including_ambiguous_as_loss"], -1)

    def test_zero_data_outputs_are_explicit_not_fabricated(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            write_outputs(out, None, [], [], [])
            manifest = json.loads((out / "dataset_manifest.json").read_text())
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(manifest["status"], "NO_DATASET_AVAILABLE")
            self.assertEqual(summary["performance"]["trades"], 0)
            self.assertEqual(summary["rolling_challenges"][0]["phase1_simulations"], 0)


if __name__ == "__main__":
    unittest.main()
