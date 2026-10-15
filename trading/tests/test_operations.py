import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

from trendbot.cache import BarCache
from trendbot.config import EXAMPLE_PATH, ConfigError, Schedule, load_settings, resolve_config
from trendbot.engine import limit_fill_price
from trendbot.models import Bar, Order, Position, Side
from trendbot.orders import OrderSettings, round_down_to_tick, round_up_to_tick, tick_size
from trendbot.schedule import KST, check_run_window, last_completed_session
from trendbot.strategy import Action, TrendBreakoutStrategy

from .helpers import bars_from_closes, flat_then_rally


class OrderPriceTests(unittest.TestCase):
    def test_tick_sizes(self):
        self.assertEqual([tick_size(p) for p in (1_999, 4_999, 19_990, 49_950, 199_900, 499_500, 500_000)],
                         [1, 5, 10, 50, 100, 500, 1_000])

    def test_rounding(self):
        self.assertEqual(round_up_to_tick(70_620), 70_700)
        self.assertEqual(round_down_to_tick(70_620), 70_600)
        self.assertEqual(round_up_to_tick(19_995), 20_000)
        self.assertEqual(round_up_to_tick(49_990), 50_000)

    def test_limit_prices(self):
        o = OrderSettings(buy_limit_buffer=0.01, sell_limit_buffer=0.02)
        self.assertEqual(o.limit_price(Side.BUY, 70_000), 70_700)
        self.assertEqual(o.limit_price(Side.SELL, 70_000), 68_600)
        with self.assertRaises(ValueError):
            o.limit_price(Side.BUY, 0)


class LimitFillTests(unittest.TestCase):
    bar = Bar(date(2024, 1, 2), open=100, high=110, low=95, close=105)

    def test_buy(self):
        self.assertEqual(limit_fill_price(Order("A", Side.BUY, 1, limit_price=101), self.bar), 100)
        self.assertEqual(limit_fill_price(Order("A", Side.BUY, 1, limit_price=97), self.bar), 97)
        self.assertIsNone(limit_fill_price(Order("A", Side.BUY, 1, limit_price=90), self.bar))

    def test_sell(self):
        self.assertEqual(limit_fill_price(Order("A", Side.SELL, 1, limit_price=98), self.bar), 100)
        self.assertEqual(limit_fill_price(Order("A", Side.SELL, 1, limit_price=108), self.bar), 108)
        self.assertIsNone(limit_fill_price(Order("A", Side.SELL, 1, limit_price=120), self.bar))


class ZeroPriceGuardTests(unittest.TestCase):
    def test_zero_close_never_exits(self):
        bars = bars_from_closes(flat_then_rally())
        bars[-1] = replace(bars[-1], open=0, high=0, low=0, close=0)
        pos = Position("X", 10, 10_000, date(2020, 1, 1), stop_price=9_000)
        self.assertEqual(TrendBreakoutStrategy().evaluate(bars, pos).action, Action.HOLD)


class ConfigTests(unittest.TestCase):
    def write(self, tmp, text):
        p = Path(tmp) / "t.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_example_file_loads(self):
        s = load_settings(EXAMPLE_PATH)
        self.assertEqual(s.costs.commission_rate, 0.00015)
        self.assertEqual(s.risk.max_positions, 5)
        self.assertEqual(s.schedule.run_start, time(8, 30))
        self.assertIn(date(2026, 12, 25), s.schedule.holidays)

    def test_costs_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_settings(self.write(tmp, "[risk]\nmax_positions = 3\n"))
            with self.assertRaisesRegex(ConfigError, "sell_tax_rate"):
                load_settings(self.write(tmp, "[costs]\ncommission_rate = 0.0001\nmin_commission = 0\nslippage_rate = 0\n"))

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "comission"):
                load_settings(self.write(tmp, "[costs]\ncomission_rate = 0.1\n"))

    def test_live_run_refuses_example_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                self.assertEqual(resolve_config(None, allow_example=True), EXAMPLE_PATH)
                if not (Path.home() / ".trendbot" / "config.toml").exists():
                    with self.assertRaises(ConfigError):
                        resolve_config(None, allow_example=False)
            finally:
                os.chdir(cwd)


class ScheduleTests(unittest.TestCase):
    sched = Schedule(holidays=frozenset({date(2026, 12, 25)}))

    def at(self, *args):
        return datetime(*args, tzinfo=KST)

    def test_window(self):
        self.assertIsNone(check_run_window(self.at(2026, 10, 15, 8, 40), self.sched))
        self.assertIn("시간", check_run_window(self.at(2026, 10, 15, 10, 0), self.sched))
        self.assertIn("시간", check_run_window(self.at(2026, 10, 15, 8, 29), self.sched))
        self.assertIn("주말", check_run_window(self.at(2026, 10, 17, 8, 40), self.sched))
        self.assertIn("휴장", check_run_window(self.at(2026, 12, 25, 8, 40), self.sched))

    def test_last_completed_session(self):
        self.assertEqual(last_completed_session(self.at(2026, 10, 15, 8, 40), self.sched), date(2026, 10, 14))
        self.assertEqual(last_completed_session(self.at(2026, 10, 15, 16, 0), self.sched), date(2026, 10, 15))
        self.assertEqual(last_completed_session(self.at(2026, 10, 19, 8, 40), self.sched), date(2026, 10, 16))
        self.assertEqual(last_completed_session(self.at(2026, 12, 28, 8, 40), self.sched), date(2026, 12, 24))


class CacheTests(unittest.TestCase):
    def test_incremental_and_split_refetch(self):
        all_bars = bars_from_closes([1000.0 + i for i in range(60)], start=date(2026, 1, 1))
        calls = []
        source = {"bars": all_bars}

        def fetch(sym, start, end):
            calls.append((start, end))
            return [b for b in source["bars"] if start <= b.day <= end]

        with tempfile.TemporaryDirectory() as tmp:
            cache = BarCache(Path(tmp))
            start = date(2026, 1, 1)
            got = cache.get("A", start, all_bars[49].day, fetch)
            self.assertEqual(len(got), 50)
            # 같은 날 다시: 호출 없음
            cache.get("A", start, all_bars[49].day, fetch)
            self.assertEqual(len(calls), 1)
            # 다음 날: 겹치는 구간부터만 받음
            got = cache.get("A", start, all_bars[50].day, fetch)
            self.assertEqual(len(got), 51)
            self.assertGreater(calls[-1][0], start)
            # 액면분할로 과거 가격이 바뀌면 전체를 다시 받음
            source["bars"] = [replace(b, open=b.open / 5, high=b.high / 5, low=b.low / 5, close=b.close / 5) for b in all_bars]
            got = cache.get("A", start, all_bars[52].day, fetch)
            self.assertEqual(calls[-1][0], start)
            self.assertAlmostEqual(got[0].close, all_bars[0].close / 5, delta=1)


if __name__ == "__main__":
    unittest.main()
