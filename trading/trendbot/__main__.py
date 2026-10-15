"""명령줄 실행.

  python -m trendbot demo                  가상 데이터로 백테스트
  python -m trendbot backtest --data DIR   CSV 일봉으로 백테스트
"""

from __future__ import annotations

import argparse
import sys

from .broker import PaperBroker
from .costs import CostModel
from .data import load_directory, synthetic_bars
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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
