"""지정가 주문 가격 계산.

시장가 매수는 상한가 기준으로 증거금을 잡아 소액 계좌에서 주문이 막히므로 쓰지 않는다.
대신 기준가(어제 종가)에서 조금 유리하지 않은 쪽으로 여유를 둔 지정가를 낸다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Side

# 2023년 1월부터 코스피·코스닥 공통 호가 단위
_TICKS = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
)


def tick_size(price: float) -> int:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return 1_000


def round_up_to_tick(price: float) -> int:
    tick = tick_size(price)
    rounded = math.ceil(price / tick - 1e-9) * tick
    # 올림으로 다음 가격대에 넘어가면 그 가격대 호가 단위에 다시 맞춘다
    t2 = tick_size(rounded)
    return math.ceil(rounded / t2 - 1e-9) * t2


def round_down_to_tick(price: float) -> int:
    return math.floor(price / tick_size(price) + 1e-9) * tick_size(price)


@dataclass(frozen=True)
class OrderSettings:
    # 매수 지정가 = 기준가 x (1 + buy_limit_buffer), 호가 단위로 올림
    buy_limit_buffer: float = 0.01
    # 매도 지정가 = 기준가 x (1 - sell_limit_buffer), 호가 단위로 내림
    sell_limit_buffer: float = 0.02

    def limit_price(self, side: Side, reference: float) -> int:
        if reference <= 0:
            raise ValueError("기준가가 0 이하라 지정가를 정할 수 없습니다")
        if side is Side.BUY:
            return round_up_to_tick(reference * (1 + self.buy_limit_buffer))
        return max(1, round_down_to_tick(reference * (1 - self.sell_limit_buffer)))
