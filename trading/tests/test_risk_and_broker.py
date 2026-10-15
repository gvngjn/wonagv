import unittest
from datetime import date

from trendbot.broker import BrokerError, PaperBroker
from trendbot.costs import CostModel
from trendbot.models import Order, Side
from trendbot.risk import RiskManager


class RiskTests(unittest.TestCase):
    costs = CostModel()

    def size(self, **kw):
        args = dict(equity=100_000_000, cash=100_000_000, price=50_000, atr=2_000, open_positions=0, costs=self.costs)
        args.update(kw)
        return RiskManager().size_entry(**args)

    def test_risk_based_quantity(self):
        # 1억 x 1% / (2 x 2,000) = 250주
        s = self.size()
        self.assertEqual(s.quantity, 250)
        self.assertEqual(s.stop_price, 46_000)

    def test_weight_cap(self):
        # 손절폭이 아주 작아도 한 종목 25%를 넘지 않음
        s = self.size(atr=2_000, price=10_000)
        self.assertLessEqual(s.quantity * 10_000, 25_000_000)

    def test_small_move_rejected(self):
        # 손절폭 0.4% < 왕복비용(약 0.33%) x 10
        s = self.size(atr=100)
        self.assertEqual(s.quantity, 0)
        self.assertIn("수수료", s.reason)

    def test_min_order_value(self):
        self.assertEqual(self.size(equity=5_000_000, cash=5_000_000).quantity, 0)

    def test_max_positions(self):
        self.assertEqual(self.size(open_positions=5).quantity, 0)


class PaperBrokerTests(unittest.TestCase):
    def test_round_trip_costs(self):
        costs = CostModel(commission_rate=0.001, sell_tax_rate=0.002, slippage_rate=0.0)
        b = PaperBroker(1_000_000, costs)
        d = date(2024, 1, 2)
        b.execute(Order("A", Side.BUY, 10, stop_price=9_000), 10_000, d)
        self.assertAlmostEqual(b.cash(), 1_000_000 - 100_000 - 100)
        self.assertEqual(b.positions()["A"].stop_price, 9_000)
        b.execute(Order("A", Side.SELL, 10), 11_000, d)
        self.assertAlmostEqual(b.cash(), 1_000_000 - 100_100 + 110_000 - 110 - 220)
        self.assertEqual(b.positions(), {})

    def test_cannot_oversell_or_overspend(self):
        b = PaperBroker(10_000)
        with self.assertRaises(BrokerError):
            b.execute(Order("A", Side.SELL, 1), 100, date(2024, 1, 2))
        with self.assertRaises(BrokerError):
            b.execute(Order("A", Side.BUY, 1), 20_000, date(2024, 1, 2))


if __name__ == "__main__":
    unittest.main()
