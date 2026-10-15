"""한국투자증권 모의투자 계좌로 하루 한 번 돌리는 실행기.

장 시작 전 동시호가 시간(기본 08:30~08:59)에만 실행한다:
어제 종가까지의 일봉으로 판단하고 지정가 주문을 낸다 → 백테스트와 같은 규칙.
손절가·청산일처럼 증권사가 모르는 정보는 상태 파일(JSON)에 따로 저장한다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .cache import BarCache
from .config import Settings
from .kis import KisError, KisMockClient
from .models import Order, Position, Side
from .planner import plan_orders
from .schedule import last_completed_session

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
            lines.append(f"  {o.side.value} {o.symbol} {o.quantity}주 지정가 {o.limit_price:,.0f} ({o.reason}{stop})")
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


def run_once(
    client: KisMockClient,
    settings: Settings,
    symbols: list[str],
    *,
    submit: bool,
    now: datetime,
) -> RunReport:
    """now 는 한국 시간. 실행 시간대 확인은 부르는 쪽(schedule.check_run_window)에서 먼저 한다."""
    state = State.load(settings.state_path)
    cache = BarCache(settings.cache_dir)

    balance = client.balance()
    # 어제 낸 매수가 체결되지 않았으면 기록해 둔 손절가는 버린다
    for sym in list(state.stops):
        if sym not in balance.holdings:
            state.stops.pop(sym)
            state.entry_days.pop(sym, None)

    last_session = last_completed_session(now, settings.schedule)
    start = last_session - timedelta(days=HISTORY_CALENDAR_DAYS)
    history = {}
    skipped: list[tuple[str, str]] = []
    for sym in sorted(set(symbols) | set(balance.holdings)):
        bars = cache.get(sym, start, last_session, client.daily_bars)
        if not bars:
            skipped.append((sym, "일봉 없음"))
        elif bars[-1].day < last_session:
            # 거래정지 등으로 최신 봉이 없으면 오래된 가격으로 판단하지 않는다
            skipped.append((sym, f"최근 일봉이 {bars[-1].day} 라 판단하지 않음"))
        else:
            history[sym] = bars

    positions = {
        sym: Position(sym, h.quantity, h.avg_price, state.entry_days.get(sym, now.date()), state.stops.get(sym))
        for sym, h in balance.holdings.items()
    }
    equity = balance.cash
    for sym, p in positions.items():
        h = balance.holdings[sym]
        if sym in history:
            price = history[sym][-1].close
        else:  # 현재가 0원은 믿지 않는다
            price = h.price if h.price > 0 else h.avg_price
        equity += p.quantity * price

    plan = plan_orders(
        history=history, positions=positions, cash=balance.cash, equity=equity,
        strategy=settings.strategy, risk=settings.risk, costs=settings.costs,
        last_exit=state.last_exit, order=settings.order,
    )
    orders, dropped = _fit_buys_to_cash(
        plan.orders, balance.cash, settings.costs.commission_rate, settings.risk.min_order_value
    )
    report = RunReport(balance.cash, equity, orders, skipped + plan.skipped + dropped)
    if not submit:
        return report

    today = now.date()
    for order in orders:
        try:
            odno = client.limit_order(order.symbol, order.side, order.quantity, int(order.limit_price))
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
    state.save(settings.state_path)
    return report


def _fit_buys_to_cash(
    orders: list[Order], cash: float, commission_rate: float, min_order_value: float
) -> tuple[list[Order], list[tuple[str, str]]]:
    """지정가 x 수량 + 수수료가 예수금을 넘지 않게 마지막으로 확인한다."""
    out: list[Order] = []
    dropped: list[tuple[str, str]] = []
    left = cash
    for o in orders:
        if o.side is Side.SELL:
            out.append(o)
            continue
        unit = o.limit_price * (1 + commission_rate)
        qty = min(o.quantity, math.floor(left / unit))
        if qty <= 0 or qty * o.limit_price < min_order_value:
            dropped.append((o.symbol, "예수금 부족"))
            continue
        out.append(Order(o.symbol, o.side, qty, o.reason, o.stop_price, o.limit_price))
        left -= qty * unit
    return out, dropped
