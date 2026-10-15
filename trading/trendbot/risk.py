"""비중·손절 계산과 '수수료 대비 작은 매매' 걸러내기."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .costs import CostModel


@dataclass(frozen=True)
class Sizing:
    quantity: int
    stop_price: float
    reason: str = ""


@dataclass(frozen=True)
class RiskManager:
    # 한 번 매매에서 손절 시 잃을 수 있는 돈 = 총자산 x risk_per_trade
    risk_per_trade: float = 0.01
    stop_atr: float = 2.0
    max_positions: int = 5
    max_position_weight: float = 0.25
    # 이보다 작은 주문은 하지 않음 (최소 수수료 비중이 커지는 것 방지)
    min_order_value: float = 1_000_000
    # 손절폭이 왕복 비용의 이 배수보다 작으면 진입하지 않음 → 움직임이 큰 종목만
    min_stop_to_cost: float = 10.0
    # 청산 후 같은 종목 재진입까지 쉬는 거래일 수 (잦은 왕복 방지)
    cooldown_days: int = 10

    def size_entry(
        self,
        *,
        equity: float,
        cash: float,
        price: float,
        atr: float,
        open_positions: int,
        costs: CostModel,
    ) -> Sizing:
        stop_distance = self.stop_atr * atr
        stop_price = price - stop_distance
        if open_positions >= self.max_positions:
            return Sizing(0, stop_price, "보유 종목 수 한도")
        if price <= 0 or stop_distance <= 0:
            return Sizing(0, stop_price, "가격 정보 이상")
        if stop_distance / price < self.min_stop_to_cost * costs.round_trip_rate():
            return Sizing(0, stop_price, "움직임이 수수료에 비해 작음")

        by_risk = equity * self.risk_per_trade / stop_distance
        by_weight = equity * self.max_position_weight / price
        unit_cost = costs.buy_price(price) * (1 + costs.commission_rate)
        by_cash = cash / unit_cost
        quantity = math.floor(min(by_risk, by_weight, by_cash))
        if quantity <= 0 or quantity * price < self.min_order_value:
            return Sizing(0, stop_price, "주문 금액이 최소 기준 미만")
        return Sizing(quantity, stop_price)
