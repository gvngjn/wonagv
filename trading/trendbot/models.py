from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


@dataclass(frozen=True)
class Bar:
    """일봉 한 개."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Side(Enum):
    BUY = "매수"
    SELL = "매도"


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    quantity: int
    reason: str = ""
    # 매수 주문일 때 함께 정해 두는 손절 가격
    stop_price: float | None = None


@dataclass(frozen=True)
class Fill:
    day: date
    symbol: str
    side: Side
    quantity: int
    price: float
    commission: float
    tax: float
    reason: str = ""

    @property
    def gross(self) -> float:
        return self.price * self.quantity

    @property
    def costs(self) -> float:
        return self.commission + self.tax


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_price: float
    entry_day: date
    stop_price: float | None = None


@dataclass(frozen=True)
class Trade:
    """진입부터 청산까지 한 번의 왕복 매매."""

    symbol: str
    entry_day: date
    exit_day: date
    quantity: int
    entry_price: float
    exit_price: float
    costs: float
    exit_reason: str

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.quantity - self.costs

    @property
    def return_pct(self) -> float:
        return self.pnl / (self.entry_price * self.quantity)

    @property
    def holding_days(self) -> int:
        return (self.exit_day - self.entry_day).days
