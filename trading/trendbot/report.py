from __future__ import annotations

from .engine import EngineResult


def max_drawdown(curve: list[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def summarize(result: EngineResult) -> dict[str, float]:
    values = [v for _, v in result.equity_curve]
    final = values[-1] if values else result.initial_cash
    days = (result.equity_curve[-1][0] - result.equity_curve[0][0]).days if len(values) > 1 else 0
    years = days / 365.25
    total_return = final / result.initial_cash - 1
    cagr = (final / result.initial_cash) ** (1 / years) - 1 if years > 0 and final > 0 else 0.0
    trades = result.trades
    wins = [t for t in trades if t.pnl > 0]
    return {
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown(values),
        "trades": len(trades),
        "trades_per_year": len(trades) / years if years > 0 else 0.0,
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_holding_days": sum(t.holding_days for t in trades) / len(trades) if trades else 0.0,
        "total_costs": sum(f.costs for f in result.fills),
    }


def format_summary(result: EngineResult) -> str:
    s = summarize(result)
    lines = [
        f"최종 자산      {s['final_equity']:>16,.0f} 원",
        f"총 수익률      {s['total_return']:>15.1%}",
        f"연 환산 수익률 {s['cagr']:>15.1%}",
        f"최대 낙폭      {s['max_drawdown']:>15.1%}",
        f"왕복 매매 수   {s['trades']:>13.0f} 회 (연 {s['trades_per_year']:.1f}회)",
        f"승률           {s['win_rate']:>15.1%}",
        f"평균 보유 기간 {s['avg_holding_days']:>13.0f} 일",
        f"총 수수료+세금 {s['total_costs']:>16,.0f} 원",
    ]
    if result.trades:
        lines.append("")
        lines.append("최근 매매")
        for t in result.trades[-10:]:
            lines.append(
                f"  {t.symbol:<8} {t.entry_day} → {t.exit_day}  {t.quantity:>6}주  "
                f"{t.return_pct:>7.1%}  ({t.exit_reason})"
            )
    return "\n".join(lines)
