import tempfile
import unittest
from pathlib import Path

from trendbot.broker import PaperBroker
from trendbot.costs import CostModel
from trendbot.data import load_directory, synthetic_bars, write_csv
from trendbot.engine import Engine
from trendbot.models import Side
from trendbot.report import summarize

from .helpers import bars_from_closes, flat_then_rally


class EngineTests(unittest.TestCase):
    def test_orders_fill_at_next_open(self):
        bars = bars_from_closes(flat_then_rally(rally_days=10))
        costs = CostModel(slippage_rate=0.0)
        result = Engine(PaperBroker(100_000_000, costs), costs=costs).run({"X": bars})
        buy = next(f for f in result.fills if f.side is Side.BUY)
        signal_idx = next(i for i, b in enumerate(bars) if b.day == buy.day) - 1
        self.assertEqual(buy.price, bars[signal_idx + 1].open)

    def test_low_frequency_on_synthetic_market(self):
        feed = {f"S{i}": synthetic_bars(seed=i) for i in range(5)}
        result = Engine(PaperBroker(100_000_000)).run(feed)
        s = summarize(result)
        self.assertGreater(s["trades"], 0)
        # 종목당 연 2~3회 이하: 저빈도 확인
        self.assertLess(s["trades_per_year"], 5 * 3)
        self.assertGreater(s["avg_holding_days"], 15)
        self.assertLess(s["total_costs"] / 100_000_000, 0.05)

    def test_never_holds_more_cash_than_it_has(self):
        feed = {f"S{i}": synthetic_bars(seed=i) for i in range(8)}
        result = Engine(PaperBroker(30_000_000)).run(feed)
        self.assertTrue(all(v > 0 for _, v in result.equity_curve))

    def test_csv_round_trip(self):
        bars = synthetic_bars(days=50)
        with tempfile.TemporaryDirectory() as d:
            write_csv(Path(d) / "005930.csv", bars)
            feed = load_directory(d)
        self.assertEqual(list(feed), ["005930"])
        self.assertEqual(len(feed["005930"]), 50)
        self.assertEqual(feed["005930"][0].day, bars[0].day)


if __name__ == "__main__":
    unittest.main()
