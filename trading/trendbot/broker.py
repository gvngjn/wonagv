"""브로커 어댑터.

엔진은 Broker 인터페이스만 알고, 실제 증권사 연결은 이 인터페이스를 구현해 붙인다.
지금은 PaperBroker(모의매매)만 있고 실제 주문을 내는 코드는 없다.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .costs import CostModel
from .models import Fill, Order, Position, Side


class BrokerError(Exception):
    pass


class Broker(Protocol):
    def cash(self) -> float: ...

    def positions(self) -> dict[str, Position]: ...

    def execute(self, order: Order, price: float, day: date) -> Fill: ...


class PaperBroker:
    """주문을 받은 가격(+슬리피지)에 그대로 체결시키는 모의 계좌."""

    def __init__(self, initial_cash: float, costs: CostModel | None = None) -> None:
        self._cash = float(initial_cash)
        self._positions: dict[str, Position] = {}
        self.costs = costs or CostModel()
        self.fills: list[Fill] = []

    def cash(self) -> float:
        return self._cash

    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def execute(self, order: Order, price: float, day: date) -> Fill:
        if order.quantity <= 0:
            raise BrokerError("주문 수량은 1주 이상이어야 합니다")
        if order.side is Side.BUY:
            fill = self._buy(order, price, day)
        else:
            fill = self._sell(order, price, day)
        self.fills.append(fill)
        return fill

    def _buy(self, order: Order, price: float, day: date) -> Fill:
        exec_price = self.costs.buy_price(price)
        gross = exec_price * order.quantity
        commission = self.costs.commission(gross)
        if gross + commission > self._cash:
            raise BrokerError(f"{order.symbol}: 현금 부족")
        self._cash -= gross + commission
        pos = self._positions.get(order.symbol)
        if pos is None:
            self._positions[order.symbol] = Position(
                order.symbol, order.quantity, exec_price, day, order.stop_price
            )
        else:
            total = pos.quantity + order.quantity
            pos.avg_price = (pos.avg_price * pos.quantity + gross) / total
            pos.quantity = total
            if order.stop_price is not None:
                pos.stop_price = order.stop_price
        return Fill(day, order.symbol, Side.BUY, order.quantity, exec_price, commission, 0.0, order.reason)

    def _sell(self, order: Order, price: float, day: date) -> Fill:
        pos = self._positions.get(order.symbol)
        if pos is None or pos.quantity < order.quantity:
            raise BrokerError(f"{order.symbol}: 보유 수량보다 많이 팔 수 없습니다")
        exec_price = self.costs.sell_price(price)
        gross = exec_price * order.quantity
        commission = self.costs.commission(gross)
        tax = self.costs.tax(gross)
        self._cash += gross - commission - tax
        pos.quantity -= order.quantity
        if pos.quantity == 0:
            del self._positions[order.symbol]
        return Fill(day, order.symbol, Side.SELL, order.quantity, exec_price, commission, tax, order.reason)
