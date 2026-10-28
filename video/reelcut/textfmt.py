"""화면에 보여줄 문구 만들기."""
from __future__ import annotations


def eta_text(elapsed: float, frac: float) -> str:
    """경과 시간과 진행률로 남은 시간 문구. 초반(정확하지 않을 때)에는 빈 문자열."""
    if frac < 0.03 or frac >= 1.0 or elapsed < 3:
        return ""
    left = elapsed * (1 - frac) / frac
    if left < 60:
        return f"남은 시간 약 {max(1, int(round(left / 5) * 5))}초"
    m, sec = divmod(int(left), 60)
    if m < 60:
        return f"남은 시간 약 {m}분 {sec // 10 * 10}초" if m < 10 else f"남은 시간 약 {m}분"
    return f"남은 시간 약 {m // 60}시간 {m % 60}분"
