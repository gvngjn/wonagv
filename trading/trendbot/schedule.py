"""장 운영 시간 확인. 장외 시간에는 API를 한 번도 부르지 않고 끝낸다."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .config import Schedule

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어 고정 시차로 충분
MARKET_CLOSE_SETTLED = (15, 40)  # 이 시각 이후면 오늘 일봉이 확정된 것으로 본다


def now_kst() -> datetime:
    return datetime.now(KST)


def is_session_day(day: date, schedule: Schedule) -> bool:
    return day.weekday() < 5 and day not in schedule.holidays


def check_run_window(now: datetime, schedule: Schedule) -> str | None:
    """실행해도 되면 None, 아니면 이유."""
    if now.weekday() >= 5:
        return "주말이라 실행하지 않습니다"
    if now.date() in schedule.holidays:
        return "휴장일이라 실행하지 않습니다"
    t = now.time().replace(tzinfo=None)
    if not (schedule.run_start <= t <= schedule.run_end):
        return (
            f"실행 시간({schedule.run_start:%H:%M}~{schedule.run_end:%H:%M})이 아니라 실행하지 않습니다"
        )
    return None


def last_completed_session(now: datetime, schedule: Schedule) -> date:
    """지금 시점에 일봉이 확정된 가장 최근 거래일."""
    day = now.date()
    if (now.hour, now.minute) < MARKET_CLOSE_SETTLED or not is_session_day(day, schedule):
        day -= timedelta(days=1)
    while not is_session_day(day, schedule):
        day -= timedelta(days=1)
    return day
