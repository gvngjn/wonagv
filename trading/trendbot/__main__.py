"""명령줄 실행.

  python -m trendbot demo                  가상 데이터로 백테스트
  python -m trendbot backtest --data DIR   CSV 일봉으로 백테스트
  python -m trendbot fetch --symbols 005930,000660 --out DIR
                                           한국투자증권에서 일봉을 받아 CSV로 저장
  python -m trendbot kis-run --symbols 005930,000660 [--submit]
                                           모의투자 계좌로 오늘 주문 판단 (기본은 미리보기)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from .broker import PaperBroker
from .costs import CostModel
from .data import load_directory, synthetic_bars, write_csv
from .engine import Engine
from .report import format_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendbot", description="큰 추세만 잡는 저빈도 자동매매 (모의매매 전용)")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="가상 데이터로 백테스트")
    demo.add_argument("--symbols", type=int, default=5)
    demo.add_argument("--cash", type=float, default=100_000_000)
    bt = sub.add_parser("backtest", help="CSV 일봉 데이터로 백테스트")
    bt.add_argument("--data", required=True, help="종목코드.csv 파일이 들어 있는 폴더")
    bt.add_argument("--cash", type=float, default=100_000_000)
    fetch = sub.add_parser("fetch", help="한국투자증권에서 일봉을 받아 CSV로 저장")
    fetch.add_argument("--symbols", required=True, help="쉼표로 구분한 종목코드")
    fetch.add_argument("--years", type=float, default=6)
    fetch.add_argument("--out", default="data")
    run = sub.add_parser("kis-run", help="모의투자 계좌로 오늘 주문 판단 (장 시작 전 실행)")
    run.add_argument("--symbols", required=True, help="감시할 종목코드 (보유 종목은 자동 포함)")
    run.add_argument("--state", default=str(Path.home() / ".trendbot" / "state.json"))
    run.add_argument("--submit", action="store_true", help="모의투자 계좌로 실제 주문 전송")
    args = parser.parse_args(argv)

    if args.command in ("fetch", "kis-run"):
        return _kis_command(args)

    if args.command == "demo":
        feed = {f"SAMPLE{i}": synthetic_bars(seed=i) for i in range(args.symbols)}
        print("※ 가상 데이터입니다 (실제 시세 아님)\n")
    else:
        feed = load_directory(args.data)

    costs = CostModel()
    broker = PaperBroker(args.cash, costs)
    result = Engine(broker, costs=costs).run(feed)
    print(format_summary(result))
    return 0


def _parse_symbols(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


def _kis_command(args: argparse.Namespace) -> int:
    from .kis import KisConfig, KisError, KisMockClient
    from .live import run_once

    try:
        client = KisMockClient(KisConfig.from_env())
        if args.command == "fetch":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            start = date.today() - timedelta(days=int(args.years * 365.25))
            for sym in _parse_symbols(args.symbols):
                bars = client.daily_bars(sym, start, date.today())
                write_csv(out / f"{sym}.csv", bars)
                print(f"{sym}: {len(bars)}일 저장")
            return 0
        report = run_once(client, _parse_symbols(args.symbols), Path(args.state), submit=args.submit)
        print("[한국투자증권 모의투자]")
        print(report.format(args.submit))
        return 1 if report.errors else 0
    except KisError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
