from pathlib import Path
import re
import unittest

SRC = Path(__file__).parents[1].joinpath("gold_ts_strategy.pine").read_text()

class SourceContract(unittest.TestCase):
    def test_no_lookahead_or_security(self):
        code = "\n".join(line for line in SRC.splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("request.security", code)
        self.assertNotIn("lookahead_on", code)
        self.assertIn("barstate.isconfirmed", SRC)
    def test_default_rr_and_fvg_not_signal_filter(self):
        self.assertRegex(SRC, r'input\.float\(2\.3, "Risk/Reward"')
        signal = re.search(r"int newDirection = (.*)", SRC).group(1)
        self.assertNotIn("Fvg", signal)
        self.assertNotIn("fvg", signal)
    def test_actionable_alert_only_in_revalidation_branch(self):
        self.assertEqual(SRC.count("alert(payload, alert.freq_once_per_bar_close)"), 1)
        self.assertIn("else if zoneTouched", SRC)
        self.assertIn("entryAlertSent := true", SRC)
    def test_explicit_states_and_conservative_ambiguity(self):
        for state in ("NO_SETUP", "SETUP_FORMING_LONG", "SETUP_FORMING_SHORT", "ENTRY_ACTIVE_LONG", "ENTRY_ACTIVE_SHORT", "INVALID", "EXPIRED", "COMPLETED_TP", "COMPLETED_SL", "COMPLETED_AMBIGUOUS"):
            self.assertIn(state, SRC)
        self.assertIn("if stopHit and tpHit", SRC)

if __name__ == "__main__": unittest.main()
