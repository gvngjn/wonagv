"""일봉 데이터 읽기.

CSV 형식 (헤더 필수): date,open,high,low,close,volume
파일 이름(확장자 제외)이 종목 코드가 된다. 예: data/005930.csv
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .models import Bar


def load_csv(path: str | Path) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): v for k, v in row.items() if k}
            bars.append(
                Bar(
                    day=date.fromisoformat(row["date"].strip()[:10]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                )
            )
    bars.sort(key=lambda b: b.day)
    return bars


def load_directory(directory: str | Path) -> dict[str, list[Bar]]:
    feed = {p.stem: load_csv(p) for p in sorted(Path(directory).glob("*.csv"))}
    if not feed:
        raise FileNotFoundError(f"{directory} 에 CSV 파일이 없습니다")
    return feed


def write_csv(path: str | Path, bars: list[Bar]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.day.isoformat(), f"{b.open:.0f}", f"{b.high:.0f}", f"{b.low:.0f}", f"{b.close:.0f}", f"{b.volume:.0f}"])


def synthetic_bars(
    *,
    days: int = 1500,
    start_price: float = 50_000,
    seed: int = 0,
    start: date = date(2020, 1, 2),
) -> list[Bar]:
    """시험용 가상 일봉. 상승·하락·횡보 구간이 번갈아 나온다 (실제 시세 아님)."""
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = start_price
    day = start
    drift = 0.0
    regime_left = 0
    while len(bars) < days:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        if regime_left <= 0:
            drift = rng.choice([0.0015, -0.0012, 0.0, 0.0])
            regime_left = rng.randint(60, 250)
        regime_left -= 1
        ret = drift + rng.gauss(0, 0.015)
        open_ = price * (1 + rng.gauss(0, 0.004))
        close = price * math.exp(ret)
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.006)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.006)))
        bars.append(Bar(day, open_, high, low, close, rng.randint(100_000, 1_000_000)))
        price = close
        day += timedelta(days=1)
    return bars
