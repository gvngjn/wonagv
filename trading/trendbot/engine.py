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
from .risk import RiskManager
from .strategy import Action, TrendBreakoutStrategy


@dataclass
class EngineResult:
    initial_cash: float
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    skipped: list[tuple[date, str, str]] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        broker: Broker,
        strategy: TrendBreakoutStrategy | None = None,
        risk: RiskManager | None = None,
        costs: CostModel | None = None,
    ) -> None:
        self.broker = broker
        self.strategy = strategy or TrendBreakoutStrategy()
        self.risk = risk or RiskManager()
        self.costs = costs or getattr(broker, "costs", None) or CostModel()

    def run(self, feed: dict[str, list[Bar]], initial_cash: float | None = None) -> EngineResult:
        result = EngineResult(initial_cash if initial_cash is not None else self.broker.cash())
        by_day: dict[date, dict[str, int]] = {}
        for symbol, bars in feed.items():
            for i, bar in enumerate(bars):
                by_day.setdefault(bar.day, {})[symbol] = i

        pending: list[Order] = []
        last_close: dict[str, float] = {}
        last_exit_index: dict[str, int] = {}
        open_entries: dict[str, Fill] = {}
        entry_costs: dict[str, float] = {}

        for day in sorted(by_day):
            today = by_day[day]

            # 1) 어제 예약한 주문을 오늘 시가에 체결
            still_pending: list[Order] = []
            for order in pending:
                idx = today.get(order.symbol)
                if idx is None:  # 거래정지 등으로 오늘 시세가 없으면 다음 날로
                    still_pending.append(order)
                    continue
                price = feed[order.symbol][idx].open
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
                    last_exit_index[fill.symbol] = idx
            pending = still_pending

            # 2) 종가로 평가
            for symbol, idx in today.items():
                last_close[symbol] = feed[symbol][idx].close
            positions = self.broker.positions()
            equity = self.broker.cash() + sum(p.quantity * last_close.get(s, p.avg_price) for s, p in positions.items())
            result.equity_curve.append((day, equity))

            # 3) 신호 판단 → 내일 주문 예약 (청산 먼저)
            pending_symbols = {o.symbol for o in pending}
            open_count = len(positions)
            for symbol, idx in sorted(today.items()):
                if symbol in pending_symbols:
                    continue
                pos = positions.get(symbol)
                if pos is None:
                    continue
                signal = self.strategy.evaluate(feed[symbol][: idx + 1], pos)
                if signal.action is Action.EXIT:
                    pending.append(Order(symbol, Side.SELL, pos.quantity, signal.reason))
                    pending_symbols.add(symbol)

            cash = self.broker.cash()
            for symbol, idx in sorted(today.items()):
                if symbol in pending_symbols or symbol in positions:
                    continue
                exit_idx = last_exit_index.get(symbol)
                if exit_idx is not None and idx - exit_idx < self.risk.cooldown_days:
                    continue
                signal = self.strategy.evaluate(feed[symbol][: idx + 1], None)
                if signal.action is not Action.ENTER or signal.atr is None:
                    continue
                price = feed[symbol][idx].close
                sizing = self.risk.size_entry(
                    equity=equity, cash=cash, price=price, atr=signal.atr,
                    open_positions=open_count, costs=self.costs,
                )
                if sizing.quantity <= 0:
                    result.skipped.append((day, symbol, sizing.reason))
                    continue
                pending.append(Order(symbol, Side.BUY, sizing.quantity, signal.reason, sizing.stop_price))
                pending_symbols.add(symbol)
                open_count += 1
                # 내일 시가가 조금 올라도 현금이 모자라지 않게 여유를 둔다
                cash -= sizing.quantity * self.costs.buy_price(price) * 1.05

        return result
