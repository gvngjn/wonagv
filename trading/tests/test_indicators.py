import unittest

from trendbot import indicators as ind

from .helpers import bars_from_closes


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(ind.sma([1, 2], 3))

    def test_channel_excludes_today(self):
        bars = bars_from_closes([10, 11, 12, 100], spread=0)
        self.assertEqual(ind.highest_high(bars, 3), 12)
        self.assertEqual(ind.lowest_low(bars, 3), 10)

    def test_atr_constant_range(self):
        bars = bars_from_closes([100.0] * 30, spread=0.01)
        self.assertAlmostEqual(ind.atr(bars, 14), 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
