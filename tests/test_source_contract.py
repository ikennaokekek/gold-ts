from pathlib import Path
import re
import unittest
import json

SRC = Path(__file__).parents[1].joinpath("gold_ts_strategy.pine").read_text()
CODE = "\n".join(line for line in SRC.splitlines() if not line.lstrip().startswith("//"))


class SourceContract(unittest.TestCase):
    def test_no_lookahead_or_security(self):
        self.assertNotIn("request.security", CODE)
        self.assertNotIn("lookahead_on", CODE)
        self.assertIn("barstate.isconfirmed", SRC)

    def test_locked_baseline_defaults(self):
        for fragment in (
            'const float rr = 2.3', 'const int fastLen = 50',
            'const int slowLen = 200', 'const int structureLen = 20',
            'const float retracement = 0.50', 'const float zoneAtrWidth = 0.10',
            'const int atrLen = 14', 'const float stopAtr = 1.0',
            'const int maxWait = 24',
        ):
            self.assertIn(fragment, SRC)
        self.assertNotIn("G_STRATEGY", CODE)

    def test_forward_defaults_and_emulator_settings(self):
        for fragment in ('input.bool(false, "Backtesting / Research Mode"',
                         "pyramiding = 0", "use_bar_magnifier = false",
                         "calc_on_order_fills = false", "process_orders_on_close = true"):
            self.assertIn(fragment, CODE)
        self.assertNotIn("alertcondition(", CODE)
        self.assertNotRegex(CODE, r"lookahead|ta\.pivot|\[(?:-\d+)\]")

    def test_geometry_only_changes_at_creation_or_reset(self):
        # No waiting/active-bar recalculation of frozen prices or metadata.
        engine = SRC[SRC.index("if barstate.isconfirmed"):SRC.index("// ── Bounded chart")]
        waiting_active = engine[engine.index("if isForming"):engine.index("// Create only")]
        for name in ("entry", "entryLower", "entryUpper", "stop", "target",
                     "frozenRisk", "direction", "setupBar", "setupFvg"):
            self.assertNotRegex(waiting_active, rf"\b{name}\s*:=")
        self.assertIn("float target = direction == 1 ? center + risk * rr : center - risk * rr", CODE)
        self.assertIn("age > 0 and not entryAlertSent", waiting_active)
        self.assertIn("else if isActive and bar_index > activeBar", waiting_active)
        self.assertLess(waiting_active.index("if stopBreached"), waiting_active.index("else if expired"))
        self.assertLess(waiting_active.index("else if expired"), waiting_active.index("else if zoneTouched"))

    def test_risk_planning_never_changes_orders_or_geometry(self):
        for fragment in ("const float referenceAccount = 200000.0",
                         "const float plannedRiskPct = 0.25",
                         "referenceAccount * plannedRiskPct / 100.0",
                         "const float internalDailyLossPct = 2.0",
                         "referenceAccount * internalDailyLossPct / 100.0",
                         "0.25% / $500 MAX", "2% / $4,000",
                         "EXTERNAL PORTFOLIO CONTROL"):
            self.assertIn(fragment, SRC)
        geometry = SRC[SRC.index("f_geometry("):SRC.index("f_status_text(")]
        orders = "\n".join(line for line in CODE.splitlines() if "strategy.entry(" in line or "strategy.exit(" in line)
        for block in (geometry, orders):
            self.assertNotRegex(block, r"referenceAccount|plannedRisk|referenceRisk|internalDaily")
        self.assertNotIn("qty", orders)
        docs = Path(__file__).parents[1].joinpath("README.md").read_text()
        self.assertIn("not an FTMO rule", docs)
        self.assertIn("realized daily losses + current open-position planned downside + proposed new-trade risk <= $4,000", docs)
        self.assertIn("Never move the SL to force $500 risk", docs)
        self.assertIn("$1,150", docs)
        self.assertIn("CONCEPTUAL ", SRC)

    def test_actionable_json_composes_for_both_directions_and_fvg_tags(self):
        # Evaluate literal concatenation with fixture values, not a substitute Pine compiler.
        expression = SRC[SRC.index("string payload = ") + len("string payload = "):SRC.index("            alert(payload")]
        values = {
            "str.tostring(entry, format.mintick)": "100",
            "str.tostring(entryLower, format.mintick)": "99",
            "str.tostring(entryUpper, format.mintick)": "101",
            "str.tostring(rr)": "2.3",
            "str.tostring(close, format.mintick)": "102",
            "str.tostring(frozenRisk, format.mintick)": "10",
            "str.tostring(math.abs(close - stop), format.mintick)": "12",
            "str.tostring(referenceAccount)": "200000",
            "str.tostring(plannedRiskPct)": "0.25",
            "str.tostring(referenceRisk)": "500",
            "str.tostring(internalDailyLossPct)": "2",
            "str.tostring(internalDailyLossLimit)": "4000",
            "syminfo.tickerid": "BROKER:XAUUSD", "timeframe.period": "15",
        }
        for long in (True, False):
            for fvg in (True, False):
                rendered = expression
                replacements = dict(values)
                replacements.update({
                    '(direction == 1 ? "LONG" : "SHORT")': "LONG" if long else "SHORT",
                    '(direction == 1 ? "BUY" : "SELL")': "BUY" if long else "SELL",
                    '(setupFvg ? "YES" : "NO")': "YES" if fvg else "NO",
                    "str.tostring(stop, format.mintick)": "90" if long else "110",
                    "str.tostring(target, format.mintick)": "123" if long else "77",
                })
                for key, value in replacements.items():
                    rendered = rendered.replace(key, "'" + value + "'")
                literals = re.findall(r"'([^']*)'", rendered)
                self.assertRegex(re.sub(r"'[^']*'", "", rendered), r"^[\s+]*$")
                payload = json.loads("".join(literals))
                self.assertEqual(payload["action"], "BUY" if long else "SELL")
                self.assertEqual(payload["fvg"], "YES" if fvg else "NO")
                self.assertEqual(payload["planned_max_normal_loss_usd"], 500)
                self.assertEqual(payload["planned_risk_pct"], 0.25)
                self.assertEqual(payload["reference_account_usd"], 200000)
                self.assertEqual(payload["internal_daily_loss_limit_usd"], 4000)
                self.assertEqual(payload["internal_daily_loss_pct"], 2)
                self.assertEqual(payload["rr"], 2.3)
                self.assertEqual(payload["touch_bar_close"], payload["market_revalidation_price"])
                self.assertEqual(payload["model"], "SIGNAL_CONCEPTUAL")
                self.assertEqual(payload["status"], "VALID ENTRY")
                self.assertFalse(payload["automatic_position_sizing"])
                self.assertEqual(payload["risk_control"], "EXTERNAL_MANUAL_PORTFOLIO")

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
