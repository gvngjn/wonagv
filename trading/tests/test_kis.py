import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from trendbot import kis
from trendbot.kis import KisConfig, KisError, KisMockClient
from trendbot.config import Settings
from trendbot.costs import CostModel
from trendbot.live import State, run_once
from trendbot.models import Side
from trendbot.schedule import KST

from .helpers import bars_from_closes, flat_then_rally


class FakeKis:
    """한국투자증권 모의투자 서버 흉내."""

    def __init__(self, bars_by_symbol, cash=100_000_000, holdings=None):
        self.bars = bars_by_symbol
        self.cash = cash
        self.holdings = holdings or {}
        self.calls = []
        self.orders = []

    def __call__(self, method, url, headers, body):
        parsed = urlparse(url)
        self.calls.append((method, parsed, headers))
        assert parsed.netloc == "openapivts.koreainvestment.com:29443", url
        if parsed.path == "/oauth2/tokenP":
            return 200, {}, {"access_token": "TOKEN", "access_token_token_expired": "2099-01-01 00:00:00"}
        assert headers["authorization"] == "Bearer TOKEN"
        q = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        if parsed.path.endswith("inquire-daily-itemchartprice"):
            lo = datetime.strptime(q["FID_INPUT_DATE_1"], "%Y%m%d").date()
            hi = datetime.strptime(q["FID_INPUT_DATE_2"], "%Y%m%d").date()
            rows = [
                {"stck_bsop_date": b.day.strftime("%Y%m%d"), "stck_oprc": str(b.open), "stck_hgpr": str(b.high),
                 "stck_lwpr": str(b.low), "stck_clpr": str(b.close), "acml_vol": "1000"}
                for b in reversed(self.bars.get(q["FID_INPUT_ISCD"], [])) if lo <= b.day <= hi
            ][:100]
            return 200, {}, {"rt_cd": "0", "output1": {}, "output2": rows}
        if parsed.path.endswith("inquire-balance"):
            out1 = [{"pdno": s, "prdt_name": s, "hldg_qty": str(q_), "pchs_avg_pric": "10000", "prpr": "10000"}
                    for s, q_ in self.holdings.items()]
            return 200, {"tr_cont": "D"}, {"rt_cd": "0", "output1": out1,
                                           "output2": [{"dnca_tot_amt": str(self.cash), "prvs_rcdl_excc_amt": str(self.cash)}]}
        if parsed.path.endswith("order-cash"):
            self.orders.append((headers["tr_id"], json.loads(body)))
            return 200, {}, {"rt_cd": "0", "msg1": "모의투자 주문 완료", "output": {"ODNO": "0000123"}}
        return 404, {}, {"rt_cd": "1", "msg1": "unknown"}


def make_client(fake, tmp):
    cfg = KisConfig("KEY", "SECRET", "50012345", "01", token_path=Path(tmp) / "token.json")
    return KisMockClient(cfg, transport=fake, sleep=lambda s: None, now=lambda: datetime(2026, 10, 15, 8, 40))


def dated(closes, end):
    bars = bars_from_closes(closes)
    shift = end - bars[-1].day
    from dataclasses import replace
    return [replace(b, day=b.day + shift) for b in bars]


class KisClientTests(unittest.TestCase):
    def test_only_mock_server_and_mock_tr_ids(self):
        self.assertIn("openapivts", kis.MOCK_BASE_URL)
        for tr in (kis.TR_BUY, kis.TR_SELL, kis.TR_BALANCE):
            self.assertTrue(tr.startswith("V"), tr)
        source = Path(kis.__file__).read_text(encoding="utf-8")
        self.assertNotIn("openapi.koreainvestment.com:9443", source)
        self.assertNotIn('"TTTC', source)

    def test_daily_bars_paginates_and_sorts(self):
        end = date(2026, 10, 14)
        bars = dated([10_000 + i for i in range(300)], end)
        fake = FakeKis({"005930": bars})
        with tempfile.TemporaryDirectory() as tmp:
            got = make_client(fake, tmp).daily_bars("005930", bars[0].day, end)
        self.assertEqual([b.day for b in got], [b.day for b in bars])
        self.assertEqual(got[-1].close, bars[-1].close)

    def test_token_is_cached_on_disk(self):
        fake = FakeKis({})
        with tempfile.TemporaryDirectory() as tmp:
            make_client(fake, tmp).balance()
            make_client(fake, tmp).balance()
        token_calls = [c for c in fake.calls if c[1].path == "/oauth2/tokenP"]
        self.assertEqual(len(token_calls), 1)

    def test_limit_order_body(self):
        fake = FakeKis({})
        with tempfile.TemporaryDirectory() as tmp:
            odno = make_client(fake, tmp).limit_order("005930", Side.BUY, 3, 70_100)
        self.assertEqual(odno, "0000123")
        tr_id, body = fake.orders[0]
        self.assertEqual(tr_id, "VTTC0012U")
        self.assertEqual((body["PDNO"], body["ORD_DVSN"], body["ORD_QTY"], body["ORD_UNPR"]), ("005930", "00", "3", "70100"))

    def test_no_market_order_in_client(self):
        self.assertFalse(hasattr(KisMockClient, "market_order"))
        source = Path(kis.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"ORD_DVSN": "01"', source)

    def test_zero_price_bars_are_dropped(self):
        end = date(2026, 10, 14)
        bars = dated([10_000.0] * 5, end)
        fake = FakeKis({"005930": bars})
        real = fake.__call__

        def with_zero(method, url, headers, body):
            status, h, data = real(method, url, headers, body)
            for row in data.get("output2") or []:
                if row.get("stck_bsop_date") == end.strftime("%Y%m%d"):
                    row["stck_clpr"] = "0"
            return status, h, data

        with tempfile.TemporaryDirectory() as tmp:
            got = make_client(with_zero, tmp).daily_bars("005930", bars[0].day, end)
        self.assertEqual(len(got), 4)
        self.assertNotIn(end, [b.day for b in got])

    def test_error_response_raises(self):
        def failing(method, url, headers, body):
            if url.endswith("tokenP"):
                return 200, {}, {"access_token": "T", "access_token_token_expired": "2099-01-01 00:00:00"}
            return 200, {}, {"rt_cd": "1", "msg_cd": "40310000", "msg1": "모의투자 미신청계좌입니다."}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(KisError):
                make_client(failing, tmp).balance()

    def test_config_from_env_validates_account(self):
        import os
        old = dict(os.environ)
        try:
            os.environ.update(KIS_APP_KEY="k", KIS_APP_SECRET="s", KIS_ACCOUNT="50012345-01")
            cfg = KisConfig.from_env()
            self.assertEqual((cfg.account_no, cfg.account_product), ("50012345", "01"))
            os.environ["KIS_ACCOUNT"] = "123"
            with self.assertRaises(KisError):
                KisConfig.from_env()
        finally:
            os.environ.clear()
            os.environ.update(old)


def make_settings(tmp):
    return Settings(costs=CostModel(), cache_dir=Path(tmp) / "cache", state_path=Path(tmp) / "state.json")


class LiveRunTests(unittest.TestCase):
    now = datetime(2026, 10, 15, 8, 40, tzinfo=KST)  # 목요일 장 시작 전
    yesterday = date(2026, 10, 14)

    def run_live(self, fake, tmp, symbols, submit, settings=None):
        settings = settings or make_settings(tmp)
        return run_once(make_client(fake, tmp), settings, symbols, submit=submit, now=self.now)

    def test_preview_does_not_order(self):
        bars = dated(flat_then_rally(rally_days=1, step=0.05), self.yesterday)
        fake = FakeKis({"005930": bars})
        with tempfile.TemporaryDirectory() as tmp:
            report = self.run_live(fake, tmp, ["005930"], submit=False)
            self.assertFalse((Path(tmp) / "state.json").exists())
        self.assertEqual([(o.side, o.symbol) for o in report.orders], [(Side.BUY, "005930")])
        self.assertEqual(fake.orders, [])

    def test_submit_buys_with_limit_and_records_stop(self):
        bars = dated(flat_then_rally(rally_days=1, step=0.05), self.yesterday)
        fake = FakeKis({"005930": bars})
        with tempfile.TemporaryDirectory() as tmp:
            report = self.run_live(fake, tmp, ["005930"], submit=True)
            state = State.load(Path(tmp) / "state.json")
        tr_id, body = fake.orders[0]
        self.assertEqual((tr_id, body["ORD_DVSN"]), ("VTTC0012U", "00"))
        limit = int(body["ORD_UNPR"])
        self.assertGreater(limit, bars[-1].close)
        self.assertLess(limit, bars[-1].close * 1.02)
        self.assertLessEqual(limit * int(body["ORD_QTY"]), fake.cash)
        self.assertAlmostEqual(state.stops["005930"], report.orders[0].stop_price)

    def test_held_position_exits_on_stop_and_starts_cooldown(self):
        bars = dated(flat_then_rally(rally_days=5), self.yesterday)
        fake = FakeKis({"005930": bars}, holdings={"005930": 100})
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(tmp)
            State(stops={"005930": bars[-1].close * 2}, entry_days={"005930": date(2026, 9, 1)}).save(settings.state_path)
            self.run_live(fake, tmp, [], submit=True, settings=settings)
            state = State.load(settings.state_path)
        tr_id, body = fake.orders[0]
        self.assertEqual((tr_id, body["ORD_QTY"], body["ORD_DVSN"]), ("VTTC0011U", "100", "00"))
        self.assertLess(int(body["ORD_UNPR"]), bars[-1].close)
        self.assertEqual(state.last_exit["005930"], self.now.date())
        self.assertNotIn("005930", state.stops)

    def test_zero_price_does_not_trigger_fake_stop(self):
        bars = dated(flat_then_rally(rally_days=5), self.yesterday)
        fake = FakeKis({"005930": bars}, holdings={"005930": 100})
        real = fake.__call__

        def zero_last(method, url, headers, body):
            status, h, data = real(method, url, headers, body)
            for row in data.get("output2") or []:
                if row.get("stck_bsop_date") == self.yesterday.strftime("%Y%m%d"):
                    row.update(stck_oprc="0", stck_hgpr="0", stck_lwpr="0", stck_clpr="0")
            return status, h, data

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(tmp)
            State(stops={"005930": bars[-2].close * 0.9}).save(settings.state_path)
            report = run_once(make_client(zero_last, tmp), settings, [], submit=True, now=self.now)
        self.assertEqual(fake.orders, [])
        self.assertTrue(any("최근 일봉" in r for _, r in report.skipped))

    def test_stale_stop_dropped_when_buy_never_filled(self):
        fake = FakeKis({})
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(tmp)
            State(stops={"000660": 1.0}, entry_days={"000660": date(2026, 10, 14)}).save(settings.state_path)
            self.run_live(fake, tmp, [], submit=True, settings=settings)
            self.assertEqual(State.load(settings.state_path).stops, {})

    def test_second_run_uses_cache(self):
        bars = dated(flat_then_rally(), self.yesterday)
        fake = FakeKis({"005930": bars})
        with tempfile.TemporaryDirectory() as tmp:
            self.run_live(fake, tmp, ["005930"], submit=False)
            first = sum(1 for c in fake.calls if c[1].path.endswith("itemchartprice"))
            self.run_live(fake, tmp, ["005930"], submit=False)
            second = sum(1 for c in fake.calls if c[1].path.endswith("itemchartprice")) - first
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)


if __name__ == "__main__":
    unittest.main()
