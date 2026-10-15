"""장기 돌파 추세추종 전략.

- 진입: 종가가 직전 entry_lookback일 최고가를 넘고, trend_ma일 이동평균 위에 있으며
  그 이동평균이 올라가는 중일 때 (큰 상승 추세에만 올라탐)
- 청산: 종가가 직전 exit_lookback일 최저가 아래로 내려가거나 손절가를 깨면
- 일봉 종가 기준으로 판단하고 주문은 다음 날 시가에 낸다 → 하루 한 번만 확인
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from . import indicators as ind
from .models import Bar, Position


class Action(Enum):
    HOLD = "유지"
    ENTER = "진입"
    EXIT = "청산"


@dataclass(frozen=True)
class Signal:
    action: Action
    reason: str = ""
    atr: float | None = None


@dataclass(frozen=True)
class TrendBreakoutStrategy:
    entry_lookback: int = 55
    exit_lookback: int = 20
    trend_ma: int = 200
    trend_slope_days: int = 20
    atr_period: int = 20

    @property
    def warmup(self) -> int:
        return max(self.entry_lookback, self.trend_ma + self.trend_slope_days, self.atr_period) + 1

    def evaluate(self, bars: Sequence[Bar], position: Position | None) -> Signal:
        if len(bars) < self.warmup:
            return Signal(Action.HOLD, "데이터 부족")
        today = bars[-1]
        # 시세 오류로 0원이 들어오면 멀쩡한 보유 종목이 가짜 손절로 팔릴 수 있다
        if min(today.open, today.high, today.low, today.close) <= 0:
            return Signal(Action.HOLD, "가격 0원 데이터라 판단하지 않음")
        atr = ind.atr(bars, self.atr_period)

        if position is not None:
            if position.stop_price is not None and today.close < position.stop_price:
                return Signal(Action.EXIT, f"손절가 {position.stop_price:,.0f} 이탈", atr)
            low = ind.lowest_low(bars, self.exit_lookback)
            if low is not None and today.close < low:
                return Signal(Action.EXIT, f"{self.exit_lookback}일 최저가 {low:,.0f} 이탈", atr)
            return Signal(Action.HOLD, "추세 유지", atr)

        closes = [b.close for b in bars]
        ma_now = ind.sma(closes, self.trend_ma)
        ma_before = ind.sma(closes[: -self.trend_slope_days], self.trend_ma)
        high = ind.highest_high(bars, self.entry_lookback)
        if ma_now is None or ma_before is None or high is None or atr is None:
            return Signal(Action.HOLD, "데이터 부족")
        if today.close <= ma_now or ma_now <= ma_before:
            return Signal(Action.HOLD, "상승 추세 아님", atr)
        if today.close <= high:
            return Signal(Action.HOLD, "돌파 없음", atr)
        return Signal(Action.ENTER, f"{self.entry_lookback}일 최고가 {high:,.0f} 돌파", atr)
