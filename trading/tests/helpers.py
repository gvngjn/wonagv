from datetime import date, timedelta

from trendbot.models import Bar


def bars_from_closes(closes, start=date(2020, 1, 1), spread=0.01):
    out = []
    day = start
    prev = closes[0]
    for c in closes:
        out.append(Bar(day, prev, max(prev, c) * (1 + spread), min(prev, c) * (1 - spread), c, 1000))
        prev = c
        day += timedelta(days=1)
    return out


def flat_then_rally(flat_days=260, rally_days=60, base=10_000.0, step=0.01):
    # 완만히 오르다가(이평선 상승) 급등하는 모양
    closes = [base * (1 + 0.0005 * i) for i in range(flat_days)]
    last = closes[-1]
    closes += [last * (1 + step) ** (i + 1) for i in range(rally_days)]
    return closes
