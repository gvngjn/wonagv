"""한국투자증권 모의투자 계좌로 하루 한 번 돌리는 실행기.

장 시작 전(08:30~08:55)에 실행하는 것을 전제로 한다:
어제 종가까지의 일봉으로 판단하고 시장가 주문을 내면 시초가에 체결된다 → 백테스트와 같은 규칙.
손절가·청산일처럼 증권사가 모르는 정보는 상태 파일(JSON)에 따로 저장한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .costs import CostModel
from .kis import KisError, KisMockClient
from .models import Bar, Order, Position, Side
from .planner import plan_orders
from .risk import RiskManager
from .strategy import TrendBreakoutStrategy

# 판단에 필요한 일봉(약 280거래일)을 넉넉히 받기 위한 달력 일수
HISTORY_CALENDAR_DAYS = 450


@dataclass
class State:
    stops: dict[str, float] = field(default_factory=dict)
    entry_days: dict[str, date] = field(default_factory=dict)
    last_exit: dict[str, date] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        return cls(
            stops={k: float(v) for k, v in raw.get("stops", {}).items()},
            entry_days={k: date.fromisoformat(v) for k, v in raw.get("entry_days", {}).items()},
            last_exit={k: date.fromisoformat(v) for k, v in raw.get("last_exit", {}).items()},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "stops": self.stops,
            "entry_days": {k: v.isoformat() for k, v in self.entry_days.items()},
            "last_exit": {k: v.isoformat() for k, v in self.last_exit.items()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class RunReport:
    cash: float
    equity: float
    orders: list[Order]
    skipped: list[tuple[str, str]]
    submitted: list[tuple[Order, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def format(self, submit: bool) -> str:
        lines = [f"예수금 {self.cash:,.0f} 원 · 평가 총액 {self.equity:,.0f} 원"]
        if not self.orders:
            lines.append("오늘 낼 주문 없음")
        for o in self.orders:
            stop = f" · 손절가 {o.stop_price:,.0f}" if o.stop_price else ""
            lines.append(f"  {o.side.value} {o.symbol} {o.quantity}주 ({o.reason}{stop})")
        for sym, reason in self.skipped:
            lines.append(f"  건너뜀 {sym}: {reason}")
        if submit:
            for o, odno in self.submitted:
                lines.append(f"  모의투자 주문 접수 {o.symbol} 주문번호 {odno}")
            for sym, err in self.errors:
                lines.append(f"  주문 실패 {sym}: {err}")
        else:
            lines.append("(미리보기만 했습니다. 모의투자 계좌로 주문하려면 --submit)")
        return "\n".join(lines)


def completed_bars(bars: list[Bar], now: datetime) -> list[Bar]:
    """장중에 실행하면 오늘 봉은 아직 완성되지 않았으므로 뺀다."""
    if bars and bars[-1].day == now.date() and now.hour * 60 + now.minute < 15 * 60 + 40:
        return bars[:-1]
    return bars


def run_once(
    client: KisMockClient,
    symbols: list[str],
    state_path: Path,
    *,
    submit: bool,
    now: datetime | None = None,
    strategy: TrendBreakoutStrategy | None = None,
    risk: RiskManager | None = None,
    costs: CostModel | None = None,
) -> RunReport:
    now = now or datetime.now()
    strategy = strategy or TrendBreakoutStrategy()
    risk = risk or RiskManager()
    costs = costs or CostModel()
    state = State.load(state_path)

    balance = client.balance()
    # 어제 낸 매수가 체결되지 않았으면 기록해 둔 손절가는 버린다
    for sym in list(state.stops):
        if sym not in balance.holdings:
            state.stops.pop(sym)
            state.entry_days.pop(sym, None)
    universe = sorted(set(symbols) | set(balance.holdings))
    start = now.date() - timedelta(days=HISTORY_CALENDAR_DAYS)
    history = {}
    for sym in universe:
        bars = completed_bars(client.daily_bars(sym, start, now.date()), now)
        if bars:
            history[sym] = bars

    positions = {
        sym: Position(sym, h.quantity, h.avg_price, state.entry_days.get(sym, now.date()), state.stops.get(sym))
        for sym, h in balance.holdings.items()
    }
    equity = balance.cash + sum(
        p.quantity * (history[s][-1].close if s in history else p.avg_price) for s, p in positions.items()
    )
    plan = plan_orders(
        history=history, positions=positions, cash=balance.cash, equity=equity,
        strategy=strategy, risk=risk, costs=costs, last_exit=state.last_exit,
    )
    report = RunReport(balance.cash, equity, plan.orders, plan.skipped)
    if not submit:
        return report

    today = now.date()
    for order in plan.orders:
        try:
            odno = client.market_order(order.symbol, order.side, order.quantity)
        except KisError as e:
            report.errors.append((order.symbol, str(e)))
            continue
        report.submitted.append((order, odno))
        if order.side is Side.BUY:
            if order.stop_price is not None:
                state.stops[order.symbol] = order.stop_price
            state.entry_days[order.symbol] = today
        else:
            state.stops.pop(order.symbol, None)
            state.entry_days.pop(order.symbol, None)
            state.last_exit[order.symbol] = today
    state.save(state_path)
    return report
