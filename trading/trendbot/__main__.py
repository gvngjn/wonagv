"""명령줄 실행.

  python -m trendbot demo                  가상 데이터로 백테스트
  python -m trendbot backtest --data DIR   CSV 일봉으로 백테스트
  python -m trendbot fetch --out DIR       한국투자증권에서 일봉을 받아 CSV로 저장
  python -m trendbot kis-run [--submit]    모의투자 계좌로 오늘 주문 판단 (기본은 미리보기)

설정(수수료·세금·전략값·종목)은 trendbot.toml 에서 읽는다. --config 로 다른 파일 지정 가능.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from .broker import PaperBroker
from .config import ConfigError, Settings, load_settings, resolve_config
from .data import load_directory, synthetic_bars, write_csv
from .engine import Engine
from .report import format_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendbot", description="큰 추세만 잡는 저빈도 자동매매 (모의투자 전용)")
    parser.add_argument("--config", help="설정 파일 (기본: ./trendbot.toml 또는 ~/.trendbot/config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="가상 데이터로 백테스트")
    demo.add_argument("--symbols", type=int, default=5)
    demo.add_argument("--cash", type=float, default=100_000_000)
    bt = sub.add_parser("backtest", help="CSV 일봉 데이터로 백테스트")
    bt.add_argument("--data", required=True, help="종목코드.csv 파일이 들어 있는 폴더")
    bt.add_argument("--cash", type=float, default=100_000_000)
    fetch = sub.add_parser("fetch", help="한국투자증권에서 일봉을 받아 CSV로 저장")
    fetch.add_argument("--symbols", help="쉼표로 구분한 종목코드 (없으면 설정 파일의 종목)")
    fetch.add_argument("--years", type=float, default=6)
    fetch.add_argument("--out", default="data")
    run = sub.add_parser("kis-run", help="모의투자 계좌로 오늘 주문 판단 (장 시작 전 실행)")
    run.add_argument("--symbols", help="감시할 종목코드 (없으면 설정 파일의 종목, 보유 종목은 자동 포함)")
    run.add_argument("--submit", action="store_true", help="모의투자 계좌로 지정가 주문 전송")
    run.add_argument("--ignore-hours", action="store_true", help="실행 시간이 아니어도 미리보기 (--submit 과 함께 못 씀)")
    args = parser.parse_args(argv)

    try:
        live = args.command in ("fetch", "kis-run")
        path = resolve_config(args.config, allow_example=not live)
        settings = load_settings(path)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
    if not live and settings.source is not None and settings.source.name == "trendbot.example.toml":
        print("※ trendbot.toml 이 없어 예시 설정(trendbot.example.toml)으로 실행합니다\n")

    if live:
        return _kis_command(args, settings)

    if args.command == "demo":
        feed = {f"SAMPLE{i}": synthetic_bars(seed=i) for i in range(args.symbols)}
        print("※ 가상 데이터입니다 (실제 시세 아님)\n")
    else:
        feed = load_directory(args.data)

    broker = PaperBroker(args.cash, settings.costs)
    engine = Engine(broker, settings.strategy, settings.risk, settings.costs, settings.order)
    print(format_summary(engine.run(feed)))
    return 0


def _parse_symbols(text: str | None, settings: Settings) -> list[str]:
    if text:
        return [s.strip() for s in text.split(",") if s.strip()]
    return list(settings.symbols)


def _kis_command(args: argparse.Namespace, settings: Settings) -> int:
    from .kis import KisConfig, KisError, KisMockClient
    from .live import run_once
    from .schedule import check_run_window, last_completed_session, now_kst

    now = now_kst()
    symbols = _parse_symbols(args.symbols, settings)
    if not symbols and args.command == "fetch":
        print("종목이 없습니다. --symbols 또는 설정 파일 [universe] symbols 를 채워 주세요", file=sys.stderr)
        return 2

    if args.command == "kis-run":
        if args.ignore_hours and args.submit:
            print("--ignore-hours 는 미리보기에만 쓸 수 있습니다", file=sys.stderr)
            return 2
        reason = check_run_window(now, settings.schedule)
        if reason and not args.ignore_hours:
            # 장외 시간에는 토큰 발급을 포함해 API를 한 번도 부르지 않는다
            print(f"{now:%Y-%m-%d %H:%M} {reason}")
            return 0

    try:
        client = KisMockClient(KisConfig.from_env())
        if args.command == "fetch":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            end = last_completed_session(now, settings.schedule)
            start = end - timedelta(days=int(args.years * 365.25))
            for sym in symbols:
                bars = client.daily_bars(sym, start, end)
                write_csv(out / f"{sym}.csv", bars)
                print(f"{sym}: {len(bars)}일 저장")
            return 0
        report = run_once(client, settings, symbols, submit=args.submit, now=now)
        print(f"[한국투자증권 모의투자 · 설정 {settings.source}]")
        print(report.format(args.submit))
        return 1 if report.errors else 0
    except KisError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
