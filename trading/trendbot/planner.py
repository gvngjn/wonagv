"""하루치 판단: 오늘 종가까지 보고 '내일 시가에 낼 주문'을 정한다.

백테스트 엔진과 증권사 연결 실행(live.py)이 같은 함수를 써서
과거 검증 결과와 실제 동작이 어긋나지 않게 한다.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .costs import CostModel
from .models import Bar, Order, Position, Side
from .orders import OrderSettings
from .risk import RiskManager
from .strategy import Action, TrendBreakoutStrategy


@dataclass
class Plan:
    orders: list[Order] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def trading_days_since(bars: Sequence[Bar], day: date) -> int:
    return sum(1 for b in bars if b.day > day)


def plan_orders(
    *,
    history: Mapping[str, Sequence[Bar]],
    positions: Mapping[str, Position],
    cash: float,
    equity: float,
    strategy: TrendBreakoutStrategy,
    risk: RiskManager,
    costs: CostModel,
    last_exit: Mapping[str, date] | None = None,
    busy: Collection[str] = (),
    order: OrderSettings | None = None,
) -> Plan:
    """history: 종목별로 오늘(마지막 봉)까지의 일봉. busy: 이미 주문이 걸려 있어 건너뛸 종목.

    모든 주문은 마지막 종가 기준 지정가(order 설정)로 만든다.
    """
    order = order or OrderSettings()
    plan = Plan()
    last_exit = last_exit or {}
    taken = set(busy)

    # 청산 먼저
    for symbol in sorted(history):
        pos = positions.get(symbol)
        if pos is None or symbol in taken:
            continue
        signal = strategy.evaluate(history[symbol], pos)
        if signal.action is Action.EXIT:
            limit = order.limit_price(Side.SELL, history[symbol][-1].close)
            plan.orders.append(Order(symbol, Side.SELL, pos.quantity, signal.reason, limit_price=limit))
            taken.add(symbol)

    open_count = len(positions)
    for symbol in sorted(history):
        if symbol in taken or symbol in positions:
            continue
        bars = history[symbol]
        exit_day = last_exit.get(symbol)
        if exit_day is not None and trading_days_since(bars, exit_day) < risk.cooldown_days:
            continue
        signal = strategy.evaluate(bars, None)
        if signal.action is not Action.ENTER or signal.atr is None:
            continue
        price = bars[-1].close
        limit = order.limit_price(Side.BUY, price)
        sizing = risk.size_entry(
            equity=equity, cash=cash, price=price, atr=signal.atr,
            open_positions=open_count, costs=costs, fill_price=limit,
        )
        if sizing.quantity <= 0:
            plan.skipped.append((symbol, sizing.reason))
            continue
        plan.orders.append(Order(symbol, Side.BUY, sizing.quantity, signal.reason, sizing.stop_price, limit))
        taken.add(symbol)
        open_count += 1
        # 지정가 전액 + 수수료만큼 현금을 묶어 둔다
        cash -= sizing.quantity * costs.buy_price(limit) * (1 + costs.commission_rate)
    return plan
