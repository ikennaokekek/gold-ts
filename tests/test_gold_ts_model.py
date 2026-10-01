"""Deterministic executable checks for Gold TS's state/geometry contract.

This is a small reference model, not a Pine runtime replacement. It makes the
locked state transitions independently testable in CI.
"""
from dataclasses import dataclass
from enum import Enum, auto
import unittest

class State(Enum):
    NONE=auto(); FORMING=auto(); ACTIVE=auto(); INVALID=auto(); EXPIRED=auto(); TP=auto(); SL=auto(); AMBIGUOUS=auto()

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
    alerts: int = 0

    @property
    def target(self):
        risk=abs(self.entry-self.stop)
        return self.entry + self.direction*risk*self.rr

    def bar(self, low, high, trend_ok=True):
        if self.state == State.FORMING:
            self.age += 1
            stop_breached = low <= self.stop if self.direction == 1 else high >= self.stop
            touched = high >= self.entry-self.half_width and low <= self.entry+self.half_width
            if stop_breached or not trend_ok:
                self.state=State.INVALID
            elif self.age > self.max_wait:
                self.state=State.EXPIRED
            elif touched:
                self.state=State.ACTIVE; self.alerts += 1
        elif self.state == State.ACTIVE:
            stop_hit = low <= self.stop if self.direction == 1 else high >= self.stop
            tp_hit = high >= self.target if self.direction == 1 else low <= self.target
            if stop_hit and tp_hit: self.state=State.AMBIGUOUS
            elif stop_hit: self.state=State.SL
            elif tp_hit: self.state=State.TP

class GoldTsContract(unittest.TestCase):
    def long(self, **kw): return Model(1, 100, 1, 90, **kw)
    def short(self, **kw): return Model(-1, 100, 1, 110, **kw)
    def test_forming_has_geometry_and_no_alert(self):
        m=self.long(); self.assertAlmostEqual((m.target-m.entry)/(m.entry-m.stop),2.3); self.assertEqual(m.alerts,0)
    def test_valid_long_alerts_once(self):
        m=self.long(); m.bar(99,101); m.bar(99,101); self.assertEqual((m.state,m.alerts),(State.ACTIVE,1))
    def test_valid_short_alerts_once(self):
        m=self.short(); m.bar(99,101); m.bar(99,101); self.assertEqual((m.state,m.alerts),(State.ACTIVE,1)); self.assertAlmostEqual((m.entry-m.target)/(m.stop-m.entry),2.3)
    def test_invalid_at_entry_has_no_alert(self):
        m=self.long(); m.bar(89,101); self.assertEqual((m.state,m.alerts),(State.INVALID,0))
    def test_trend_invalid_before_entry(self):
        m=self.long(); m.bar(102,104,False); self.assertEqual((m.state,m.alerts),(State.INVALID,0))
    def test_expired_has_no_alert(self):
        m=self.long(max_wait=2); [m.bar(102,104) for _ in range(3)]; self.assertEqual((m.state,m.alerts),(State.EXPIRED,0))
    def test_fvg_does_not_control_entry(self):
        tagged=self.long(fvg=True); plain=self.long(fvg=False)
        tagged.bar(99,101); plain.bar(99,101)
        self.assertEqual((tagged.state,tagged.alerts),(plain.state,plain.alerts))
    def test_same_bar_is_ambiguous(self):
        m=self.long(); m.bar(99,101); m.bar(89,124); self.assertEqual(m.state,State.AMBIGUOUS)
    def test_large_candle_invalidation_precedes_touch(self):
        m=self.short(); m.bar(99,111); self.assertEqual((m.state,m.alerts),(State.INVALID,0))

if __name__ == '__main__': unittest.main()
