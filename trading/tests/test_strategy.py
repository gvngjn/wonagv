import unittest

from trendbot.models import Position
from trendbot.strategy import Action, TrendBreakoutStrategy

from .helpers import bars_from_closes, flat_then_rally


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.s = TrendBreakoutStrategy()

    def test_enters_on_breakout_in_uptrend(self):
        bars = bars_from_closes(flat_then_rally(rally_days=1, step=0.05))
        self.assertEqual(self.s.evaluate(bars, None).action, Action.ENTER)

    def test_no_entry_in_downtrend(self):
        closes = [20_000 * (1 - 0.002 * i) for i in range(300)]
        closes[-1] = closes[-2] * 1.05
        self.assertEqual(self.s.evaluate(bars_from_closes(closes), None).action, Action.HOLD)

    def test_no_signal_before_warmup(self):
        bars = bars_from_closes(flat_then_rally(flat_days=100))
        self.assertEqual(self.s.evaluate(bars, None).reason, "데이터 부족")

    def test_exit_on_stop(self):
        bars = bars_from_closes(flat_then_rally())
        pos = Position("X", 10, bars[-1].close, bars[-1].day, stop_price=bars[-1].close * 2)
        self.assertEqual(self.s.evaluate(bars, pos).action, Action.EXIT)

    def test_exit_on_channel_break(self):
        closes = flat_then_rally()
        closes.append(closes[-1] * 0.7)
        pos = Position("X", 10, closes[-2], None, stop_price=None)
        self.assertEqual(self.s.evaluate(bars_from_closes(closes), pos).action, Action.EXIT)


if __name__ == "__main__":
    unittest.main()
