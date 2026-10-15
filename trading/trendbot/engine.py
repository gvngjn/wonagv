"""하루 단위로 돌아가는 매매 엔진.

매일 장 마감 후: 종가로 신호 판단 → 주문 예약
다음 날 장 시작: 예약 주문을 시가에 체결
같은 흐름을 백테스트(과거 데이터)와 모의매매(매일 실행)에 함께 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .broker import Broker, BrokerError
from .costs import CostModel
from .models import Bar, Fill, Order, Side, Trade
from .orders import OrderSettings
from .risk import RiskManager
from .planner import plan_orders
from .strategy import TrendBreakoutStrategy


@dataclass
class EngineResult:
    initial_cash: float
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    skipped: list[tuple[date, str, str]] = field(default_factory=list)


def limit_fill_price(order: Order, bar: Bar) -> float | None:
    """지정가 주문이 이 일봉에서 체결되는 가격. 체결 안 되면 None."""
    if order.limit_price is None:
        return bar.open
    limit = order.limit_price
    if order.side is Side.BUY:
        if bar.open <= limit:
            return bar.open
        return limit if bar.low <= limit else None
    if bar.open >= limit:
        return bar.open
    return limit if bar.high >= limit else None


class Engine:
    def __init__(
        self,
        broker: Broker,
        strategy: TrendBreakoutStrategy | None = None,
        risk: RiskManager | None = None,
        costs: CostModel | None = None,
        order: OrderSettings | None = None,
    ) -> None:
        self.broker = broker
        self.strategy = strategy or TrendBreakoutStrategy()
        self.risk = risk or RiskManager()
        self.costs = costs or getattr(broker, "costs", None) or CostModel()
        self.order = order or OrderSettings()

    def run(self, feed: dict[str, list[Bar]], initial_cash: float | None = None) -> EngineResult:
        result = EngineResult(initial_cash if initial_cash is not None else self.broker.cash())
        by_day: dict[date, dict[str, int]] = {}
        for symbol, bars in feed.items():
            for i, bar in enumerate(bars):
                by_day.setdefault(bar.day, {})[symbol] = i

        pending: list[Order] = []
        last_close: dict[str, float] = {}
        last_exit: dict[str, date] = {}
        open_entries: dict[str, Fill] = {}
        entry_costs: dict[str, float] = {}

        for day in sorted(by_day):
            today = by_day[day]

            # 1) 어제 낸 지정가 주문을 오늘 체결 (시가가 더 유리하면 시가, 장중에 닿으면 지정가)
            still_pending: list[Order] = []
            for order in pending:
                idx = today.get(order.symbol)
                if idx is None:  # 거래정지 등으로 오늘 시세가 없으면 다음 날로
                    still_pending.append(order)
                    continue
                price = limit_fill_price(order, feed[order.symbol][idx])
                if price is None:  # 미체결 주문은 당일로 취소되고 다음 판단에서 다시 낸다
                    result.skipped.append((day, order.symbol, f"{order.side.value} 지정가 미체결"))
                    continue
                try:
                    fill = self.broker.execute(order, price, day)
                except BrokerError as e:
                    result.skipped.append((day, order.symbol, str(e)))
                    continue
                result.fills.append(fill)
                if fill.side is Side.BUY:
                    open_entries[fill.symbol] = fill
                    entry_costs[fill.symbol] = fill.costs
                else:
                    entry = open_entries.pop(fill.symbol)
                    result.trades.append(
                        Trade(
                            fill.symbol, entry.day, fill.day, fill.quantity, entry.price, fill.price,
                            entry_costs.pop(fill.symbol) + fill.costs, fill.reason,
                        )
                    )
                    last_exit[fill.symbol] = day
            pending = still_pending

            # 2) 종가로 평가
            for symbol, idx in today.items():
                last_close[symbol] = feed[symbol][idx].close
            positions = self.broker.positions()
            equity = self.broker.cash() + sum(p.quantity * last_close.get(s, p.avg_price) for s, p in positions.items())
            result.equity_curve.append((day, equity))

            # 3) 신호 판단 → 내일 주문 예약
            plan = plan_orders(
                history={sym: feed[sym][: idx + 1] for sym, idx in today.items()},
                positions=positions,
                cash=self.broker.cash(),
                equity=equity,
                strategy=self.strategy,
                risk=self.risk,
                costs=self.costs,
                last_exit=last_exit,
                busy={o.symbol for o in pending},
                order=self.order,
            )
            pending.extend(plan.orders)
            result.skipped.extend((day, sym, reason) for sym, reason in plan.skipped)

        return result
