"""지표 계산. 모두 '오늘까지의 데이터'만 쓰고 미래 값은 보지 않는다."""

from __future__ import annotations

from collections.abc import Sequence

from .models import Bar


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(bar.high - bar.low)
            continue
        prev_close = bars[i - 1].close
        out.append(max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close)))
    return out


def atr(bars: Sequence[Bar], period: int) -> float | None:
    """Wilder 방식 ATR."""
    if len(bars) < period + 1:
        return None
    trs = true_ranges(bars)[1:]
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def highest_high(bars: Sequence[Bar], lookback: int) -> float | None:
    """오늘을 뺀 직전 lookback일 최고가."""
    if len(bars) < lookback + 1:
        return None
    return max(b.high for b in bars[-lookback - 1 : -1])


def lowest_low(bars: Sequence[Bar], lookback: int) -> float | None:
    """오늘을 뺀 직전 lookback일 최저가."""
    if len(bars) < lookback + 1:
        return None
    return min(b.low for b in bars[-lookback - 1 : -1])
