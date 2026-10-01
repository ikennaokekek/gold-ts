from pathlib import Path
import re
import unittest

SRC = Path(__file__).parents[1].joinpath("gold_ts_strategy.pine").read_text()
CODE = "\n".join(line for line in SRC.splitlines() if not line.lstrip().startswith("//"))


class SourceContract(unittest.TestCase):
    def test_no_lookahead_or_security(self):
        self.assertNotIn("request.security", CODE)
        self.assertNotIn("lookahead_on", CODE)
        self.assertIn("barstate.isconfirmed", SRC)

    def test_locked_baseline_defaults(self):
        for fragment in (
            'input.float(2.3, "Risk/Reward"', 'input.int(50, "Fast EMA"',
            'input.int(200, "Slow EMA"', 'input.int(20, "Prior-range structure bars"',
            'input.float(50.0, "Entry retracement (%)"', 'input.float(0.10, "Entry zone half-width (ATR)"',
            'input.int(14, "ATR length"', 'input.float(1.0, "Stop distance (ATR)"',
            'input.int(24, "Maximum bars waiting for entry"',
        ):
            self.assertIn(fragment, SRC)

    def test_fvg_does_not_participate_in_signal_or_revalidation(self):
        signal = re.search(r"int newDirection = (.*)", SRC).group(1)
        forming = SRC[SRC.index("if isForming"):SRC.index("else if zoneTouched")]
        for block in (signal, forming):
            self.assertNotRegex(block, r"(?i)fvg")

    def test_only_valid_revalidation_emits_default_actionable_alert(self):
        default_alert = 'alert(payload, alert.freq_once_per_bar_close)'
        self.assertEqual(SRC.count(default_alert), 1)
        branch = SRC[SRC.index("else if zoneTouched"):SRC.index("else if isActive")]
        self.assertIn(default_alert, branch)
        self.assertIn("entryAlertSent := true", branch)
        self.assertIn('input.bool(false, "Enable non-entry lifecycle alerts"', SRC)

    def test_projected_entry_not_mislabeled_as_broker_fill(self):
        self.assertIn('"model":"SIGNAL_CONCEPTUAL"', SRC)
        self.assertIn('"projected_entry":', SRC)
        self.assertIn('"touch_bar_close":', SRC)
        self.assertIn('"execution_note":"PROJECTED ENTRY IS NOT BROKER FILL"', SRC)
        self.assertIn('"Conceptual All TS"', SRC)

    def test_broker_order_is_causal_market_order_after_revalidation(self):
        branch = SRC[SRC.index("else if zoneTouched"):SRC.index("else if isActive")]
        entry_call = re.search(r"strategy\.entry\([^\n]+", branch).group(0)
        self.assertNotIn("limit =", entry_call)
        self.assertNotIn("stop =", entry_call)
        self.assertIn("process_orders_on_close = true", SRC)
        self.assertIn("calc_on_order_fills = false", SRC)

    def test_conceptual_resolution_does_not_conflict_with_broker_exit(self):
        self.assertNotIn("strategy.close_all", CODE)
        self.assertEqual(CODE.count('strategy.exit("TS Exit"'), 1)
        self.assertIn("if stopHit and tpHit", SRC)

    def test_explicit_states_and_reset_clear_geometry(self):
        for state in (
            "NO_SETUP", "SETUP_FORMING_LONG", "SETUP_FORMING_SHORT", "ENTRY_ACTIVE_LONG",
            "ENTRY_ACTIVE_SHORT", "INVALID", "EXPIRED", "COMPLETED_TP", "COMPLETED_SL",
            "COMPLETED_AMBIGUOUS",
        ):
            self.assertIn(state, SRC)
        reset = SRC[SRC.index("if state >= INVALID"):SRC.index("isForming :=", SRC.index("if state >= INVALID"))]
        for variable in ("direction", "entry", "entryLower", "entryUpper", "stop", "target", "frozenRisk", "setupFvg", "entryAlertSent"):
            self.assertRegex(reset, rf"{variable} := (?:na|0|false)")


if __name__ == "__main__":
    unittest.main()
