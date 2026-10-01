"""Executable contract model for the causal Gold TS signal/conceptual engine.

It intentionally does not simulate TradingView fills. Broker-emulator execution is
a distinct model because a confirmed historical touch cannot be filled retroactively.
"""
from dataclasses import dataclass
from enum import Enum, auto
import unittest


class State(Enum):
    NONE = auto()
    FORMING = auto()
    ACTIVE = auto()
    INVALID = auto()
    EXPIRED = auto()
    TP = auto()
    SL = auto()
    AMBIGUOUS = auto()


@dataclass
class Model:
    direction: int
    entry: float
    half_width: float
    stop: float
    rr: float = 2.3
    max_wait: int = 24
    fvg: bool = False
    state: State = State.FORMING
    age: int = 0
    actionable_alerts: int = 0
    conceptual_trades: int = 0

    @property
    def target(self):
        risk = abs(self.entry - self.stop)
        return self.entry + self.direction * risk * self.rr

    def waiting_bar(self, low, high, trend_ok=True):
        if self.state != State.FORMING:
            return
        self.age += 1
        stop_breached = low <= self.stop if self.direction == 1 else high >= self.stop
        touched = high >= self.entry - self.half_width and low <= self.entry + self.half_width
        geometry_ok = self.stop < self.entry < self.target if self.direction == 1 else self.target < self.entry < self.stop
        # Matches Pine precedence: invalidation, expiry, then eligible touch.
        if stop_breached or not trend_ok or not geometry_ok:
            self.state = State.INVALID
        elif self.age > self.max_wait:
            self.state = State.EXPIRED
        elif touched:
            self.state = State.ACTIVE
            self.actionable_alerts += 1
            self.conceptual_trades += 1

    def active_bar(self, low, high):
        if self.state != State.ACTIVE:
            return
        stop_hit = low <= self.stop if self.direction == 1 else high >= self.stop
        tp_hit = high >= self.target if self.direction == 1 else low <= self.target
        if stop_hit and tp_hit:
            self.state = State.AMBIGUOUS
        elif stop_hit:
            self.state = State.SL
        elif tp_hit:
            self.state = State.TP

    def terminal_reset(self):
        if self.state in {State.INVALID, State.EXPIRED, State.TP, State.SL, State.AMBIGUOUS}:
            self.state = State.NONE
            self.direction = 0
            self.entry = self.half_width = self.stop = 0.0
            self.age = 0


class GoldTsContract(unittest.TestCase):
    def long(self, **kw):
        return Model(1, 100, 1, 90, **kw)

    def short(self, **kw):
        return Model(-1, 100, 1, 110, **kw)

    def test_forming_setup_sends_zero_actionable_alerts(self):
        model = self.long()
        model.waiting_bar(102, 104)
        self.assertEqual((model.state, model.actionable_alerts), (State.FORMING, 0))

    def test_valid_long_sends_exactly_one(self):
        model = self.long()
        model.waiting_bar(99, 101)
        self.assertEqual((model.state, model.actionable_alerts), (State.ACTIVE, 1))

    def test_valid_short_sends_exactly_one(self):
        model = self.short()
        model.waiting_bar(99, 101)
        self.assertEqual((model.state, model.actionable_alerts), (State.ACTIVE, 1))

    def test_invalid_at_entry_sends_zero(self):
        model = self.long()
        model.waiting_bar(89, 101)
        self.assertEqual((model.state, model.actionable_alerts), (State.INVALID, 0))

    def test_invalid_before_entry_sends_zero(self):
        model = self.long()
        model.waiting_bar(102, 104, trend_ok=False)
        self.assertEqual((model.state, model.actionable_alerts), (State.INVALID, 0))

    def test_expired_setup_sends_zero(self):
        model = self.long(max_wait=2)
        for _ in range(3):
            model.waiting_bar(102, 104)
        self.assertEqual((model.state, model.actionable_alerts), (State.EXPIRED, 0))

    def test_repeated_zone_interaction_cannot_duplicate_alert(self):
        model = self.long()
        model.waiting_bar(99, 101)
        model.waiting_bar(99, 101)
        model.waiting_bar(99, 101)
        self.assertEqual(model.actionable_alerts, 1)

    def test_fvg_yes_and_no_both_activate(self):
        tagged, plain = self.long(fvg=True), self.long(fvg=False)
        tagged.waiting_bar(99, 101)
        plain.waiting_bar(99, 101)
        self.assertEqual((tagged.state, tagged.actionable_alerts), (State.ACTIVE, 1))
        self.assertEqual((plain.state, plain.actionable_alerts), (State.ACTIVE, 1))

    def test_2_3r_long_mathematics(self):
        model = self.long()
        self.assertAlmostEqual((model.target - model.entry) / (model.entry - model.stop), 2.3)

    def test_2_3r_short_mathematics(self):
        model = self.short()
        self.assertAlmostEqual((model.entry - model.target) / (model.stop - model.entry), 2.3)

    def test_entry_and_invalidation_same_waiting_bar_is_invalid(self):
        model = self.long()
        model.waiting_bar(89, 101)
        self.assertEqual((model.state, model.actionable_alerts, model.conceptual_trades), (State.INVALID, 0, 0))

    def test_same_post_entry_bar_is_ambiguous_not_favorable(self):
        model = self.long()
        model.waiting_bar(99, 101)
        model.active_bar(89, 124)
        self.assertEqual(model.state, State.AMBIGUOUS)

    def test_terminal_reset_clears_stale_geometry(self):
        model = self.long()
        model.waiting_bar(89, 101)
        model.terminal_reset()
        self.assertEqual((model.state, model.direction, model.entry, model.stop), (State.NONE, 0, 0.0, 0.0))
        model.waiting_bar(99, 101)
        self.assertEqual((model.state, model.actionable_alerts), (State.NONE, 0))

    def test_24_post_detection_bars_are_eligible_then_expire(self):
        model = self.long(max_wait=24)
        for _ in range(24):
            model.waiting_bar(102, 104)
        self.assertEqual(model.state, State.FORMING)
        model.waiting_bar(102, 104)
        self.assertEqual(model.state, State.EXPIRED)


if __name__ == "__main__":
    unittest.main()
