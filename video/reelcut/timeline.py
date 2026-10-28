"""클립 목록 → 렌더링할 조각(Segment) 목록 만들기.

- 일반 모드: 클립을 순서대로 이어붙인다.
- 비트 맞춤 모드: 음악 비트 위치에서 화면이 바뀌도록 클립을 잘라 이어붙인다.
"""
from __future__ import annotations

import random
from dataclasses import replace

from .project import Clip, Project, Segment


def concat_segments(clips: list[Clip]) -> list[Segment]:
    return [Segment(c.path, c.in_point, c.timeline_length, c.has_audio, c.speed, c.volume, c.motion)
            for c in clips if c.length > 0.05]


def cut_boundaries(beats: list[float], music_start: float, beats_per_cut: int,
                   end_time: float, fps: float) -> list[float]:
    """타임라인 기준 컷 경계(초). 프레임 단위로 맞춰 누적 오차를 없앤다.

    음악의 music_start 지점이 타임라인 0초. 첫 비트 전 구간도 하나의 컷이 된다.
    """
    beats_per_cut = max(1, int(beats_per_cut))
    rel = [b - music_start for b in beats if b - music_start > -1e-3]
    picked = rel[::beats_per_cut]
    bounds = [0.0]
    for t in picked:
        if t <= 1e-3:
            continue
        if t >= end_time:
            break
        bounds.append(t)
    if end_time - bounds[-1] > 1e-3:
        bounds.append(end_time)
    # 프레임 경계로 반올림하고, 1프레임 미만 조각은 합친다
    frames = []
    for t in bounds:
        f = int(t * fps + 0.5)
        if not frames or f > frames[-1]:
            frames.append(f)
    return [f / fps for f in frames]


def pick_cut_beats(beats: list[float], every: int, mode: str = "regular",
                   strengths: list[float] | None = None, energy: list[float] | None = None) -> list[float]:
    """컷을 넣을 비트를 고른다.

    regular: every 비트마다
    accent:  every 비트가 지난 뒤 처음 오는 센 비트(주변 최댓값의 70% 이상)에서 컷. 센 비트가 없으면 every의 2배에서 컷
    energy:  신나는 구간(음량 상위 35%)은 2배 자주, 조용한 구간(하위 25%)은 2배 드물게
    """
    every = max(1, int(every))
    n = len(beats)
    if mode == "accent" and strengths and len(strengths) == n:
        # 일정하게보다 자주 바꾸지 않는다: every 비트가 지난 뒤 처음 오는 센 비트에서 컷
        min_gap, max_gap = every, every * 2
        thresh = 0.7
        out, last = [], -10 ** 9
        for i, t in enumerate(beats):
            gap = i - last
            if (strengths[i] >= thresh and gap >= min_gap) or gap >= max_gap:
                out.append(t)
                last = i
        return out
    if mode == "energy" and energy and len(energy) == n:
        out, i = [], 0
        while i < n:
            out.append(beats[i])
            e = energy[i]
            step = max(1, every // 2) if e >= 0.65 else (every * 2 if e <= 0.25 else every)
            i += step
        return out
    return beats[::every]


def beat_sync_segments(clips: list[Clip], boundaries: list[float], order: str = "sequential",
                       seed: int = 7) -> list[Segment]:
    """클립 속도를 반영해서 컷을 고른다.

    속도가 다른 클립도 '완성 영상 기준 길이'로 바꾼 대리 클립으로 계산한 뒤 원본 위치로 되돌린다.
    """
    usable = [c for c in clips if c.length > 0.05]
    proxies = [Clip(f"\0{k}", c.timeline_length, has_audio=c.has_audio) for k, c in enumerate(usable)]
    out = []
    for s in _beat_sync_core(proxies, boundaries, order, seed):
        c = usable[int(s.path[1:])]
        out.append(Segment(c.path, c.in_point + s.src_start * c.speed, s.duration, c.has_audio,
                           c.speed, c.volume, c.motion))
    return out


def _beat_sync_core(clips: list[Clip], boundaries: list[float], order: str = "sequential",
                    seed: int = 7) -> list[Segment]:
    """컷 길이(boundaries 간격)에 맞게 클립에서 조각을 골라낸다.

    sequential: 컷마다 다음 파일로 (1→2→3→1…), 각 파일의 처음~끝을 고르게 사용
                ("spread"는 예전 이름, 같은 동작)
    grouped:    한 파일씩 몰아서 (1,1,1…→2,2…), 파일 안에서는 건너뛰며 사용
    continuous: 예전 방식. 파일을 처음부터 끊김 없이 이어서 자름 (원본 흐름 그대로)
    random:     무작위 파일의 무작위 위치, 같은 파일 연속 없음 (seed로 재현 가능)
    """
    usable = [c for c in clips if c.length > 0.05]
    if not usable or len(boundaries) < 2:
        return []
    durations = [b - a for a, b in zip(boundaries, boundaries[1:])]
    segs: list[Segment] = []

    if order == "continuous":
        # 예전 '차례대로': 클립을 처음부터 끊김 없이 이어서 자르고, 다 쓰면 다음 클립
        ci = 0
        pos = usable[0].in_point
        for d in durations:
            c = usable[ci]
            if pos + d > c.end + 1e-6:
                # 남은 부분이 컷 길이보다 짧으면 다음 클립으로 (모두 쓰면 처음부터 다시)
                for _ in range(len(usable)):
                    ci = (ci + 1) % len(usable)
                    c = usable[ci]
                    pos = c.in_point
                    if c.length >= d:
                        break
            segs.append(Segment(c.path, pos, d, c.has_audio))
            pos += d
        return segs

    if order == "random":
        rng = random.Random(seed)
        last = None
        for d in durations:
            choices = [c for c in usable if c is not last] or usable
            c = rng.choice(choices)
            last = c
            room = max(0.0, c.length - d)
            start = c.in_point + rng.uniform(0, room)
            segs.append(Segment(c.path, start, d, c.has_audio))
        return segs

    if order in ("sequential", "spread"):
        # 클립별로 몇 번 쓰일지 정하고, 그 횟수만큼 클립 구간을 등분해서 사용
        counts = [0] * len(usable)
        for i in range(len(durations)):
            counts[i % len(usable)] += 1
        used = [0] * len(usable)
        for i, d in enumerate(durations):
            k = i % len(usable)
            c = usable[k]
            n = counts[k]
            slot = c.length / n
            start = c.in_point + used[k] * slot + max(0.0, (slot - d) / 2)
            start = min(start, c.in_point + max(0.0, c.length - d))
            used[k] += 1
            segs.append(Segment(c.path, start, d, c.has_audio))
        return segs

    # grouped: 한 파일씩 몰아서. 클립마다 길이에 비례한 개수의 컷을 고르게 떨어진 위치에서 뽑는다.
    # (바로 이어지는 구간을 쓰면 컷이 바뀌어도 화면이 이어져 보여서 장면 전환이 안 느껴진다)
    counts = _allocate(durations, usable)
    order = [k for k, n in enumerate(counts) for _ in range(n)]
    used = [0] * len(usable)
    for d, k in zip(durations, order):
        c = usable[k]
        slot = c.length / counts[k]
        start = c.in_point + used[k] * slot + max(0.0, (slot - d) / 2)
        start = max(c.in_point, min(start, c.end - d))
        used[k] += 1
        segs.append(Segment(c.path, start, d, c.has_audio))
    return segs


def _allocate(durations: list[float], clips: list[Clip]) -> list[int]:
    """컷 개수를 클립 길이에 비례해서 나눈다 (최대 잉여 방식, 합계 = 컷 수)."""
    n = len(durations)
    lengths = [c.length for c in clips]
    total = sum(lengths) or 1.0
    exact = [n * l / total for l in lengths]
    counts = [int(x) for x in exact]
    rest = sorted(range(len(clips)), key=lambda i: exact[i] - counts[i], reverse=True)
    for i in rest[: n - sum(counts)]:
        counts[i] += 1
    return counts


def beat_sync_active(project: Project) -> bool:
    """비트(또는 일정 초)에 맞춰 자르는 모드가 실제로 동작하는지."""
    bs = project.beat_sync
    if not bs.enabled:
        return False
    if bs.cut_unit == "seconds":
        return bs.cut_seconds > 0
    return bool(project.music.path and project.music.beats)


def per_clip_segments(clips: list[Clip], boundaries: list[float], order: str, seed: int) -> list[Segment]:
    """클립마다 한 컷: k번째 컷 = k번째 클립의 시작 지점부터 (무작위면 순서만 섞음)."""
    usable = [c for c in clips if c.length > 0.05]
    if order == "random":
        usable = usable[:]
        random.Random(seed).shuffle(usable)
    durations = [b - a for a, b in zip(boundaries, boundaries[1:])]
    return [Segment(c.path, c.in_point, d, c.has_audio, c.speed, c.volume, c.motion) for c, d in zip(usable, durations)]


def build_segments(project: Project) -> list[Segment]:
    clips = project.clips
    bs = project.beat_sync
    music = project.music
    fps = project.export.fps
    if not beat_sync_active(project):
        segs = concat_segments(clips)
        if bs.max_duration > 0:
            segs = _limit(segs, bs.max_duration)
        return segs

    usable = [c for c in clips if c.length > 0.05]
    total_clips = sum(c.timeline_length for c in usable)
    has_music = bool(music.path) and music.duration > 0
    music_left = max(0.0, music.duration - music.start) if has_music else 0.0

    if bs.per_clip:
        # 영상 길이 = 클립 개수 × 컷 길이 (음악은 그 지점에서 끝남)
        end_time = 10 ** 6 if bs.cut_unit == "seconds" or not has_music else music_left
    elif bs.use_music_length and has_music:
        end_time = music_left
    elif has_music:
        # 비트는 음악이 있는 동안만 있으므로 음악보다 길게 만들지 않는다
        end_time = min(total_clips, music_left) if bs.cut_unit == "beats" else total_clips
    else:
        end_time = total_clips
    if bs.max_duration > 0:
        end_time = min(end_time, bs.max_duration)

    if bs.cut_unit == "seconds":
        step = max(1.0 / fps, bs.cut_seconds)
        count = len(usable) if bs.per_clip else int(end_time / step + 1e-9) + 1
        marks = [i * step for i in range(1, count + 1)]
        bounds = cut_boundaries(marks, 0.0, 1, min(end_time, count * step), fps)
    else:
        beats = [b + music.beat_offset for b in music.beats]
        # 음악 시작 위치 이후의 비트만 골라서 컷 위치 선택
        keep = [i for i, b in enumerate(beats) if b - music.start > -1e-3]
        sel = [beats[i] for i in keep]
        strengths = [music.beat_strengths[i] for i in keep] if len(music.beat_strengths) == len(beats) else None
        energy = [music.beat_energy[i] for i in keep] if len(music.beat_energy) == len(beats) else None
        picked = pick_cut_beats(sel, bs.beats_per_cut, bs.cut_mode, strengths, energy)
        bounds = cut_boundaries(picked, music.start, 1, end_time, fps)

    if bs.per_clip:
        bounds = bounds[:len(usable) + 1]
        return per_clip_segments(usable, bounds, bs.order, bs.seed)
    return beat_sync_segments(clips, bounds, bs.order, bs.seed)


def _limit(segs: list[Segment], max_duration: float) -> list[Segment]:
    out, t = [], 0.0
    for s in segs:
        if t >= max_duration:
            break
        d = min(s.duration, max_duration - t)
        out.append(replace(s, duration=d))
        t += d
    return out


def total_duration(segments: list[Segment]) -> float:
    return sum(s.duration for s in segments)


def segment_starts(segments: list[Segment]) -> list[float]:
    out, t = [], 0.0
    for s in segments:
        out.append(t)
        t += s.duration
    return out


MONTH_FORMATS = {
    "en": ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
           "OCTOBER", "NOVEMBER", "DECEMBER"),
    "en_short": ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    "ko": tuple(f"{m}월" for m in range(1, 13)),
    "num": tuple(f"{m:02d}" for m in range(1, 13)),
}


def month_titles(project, fmt: str = "en", show: float = 1.2) -> list:
    """완성 영상에서 달이 바뀌는 순간마다 월 이름 제목 (1년 recap 등).

    클립의 찍은 시각 기준. 다음 달이 금방 시작하면 그 전에 사라진다.
    """
    import time

    from .project import TitleEntry

    names = MONTH_FORMATS.get(fmt, MONTH_FORMATS["en"])
    shot = {}
    for c in project.clips:
        shot.setdefault(c.path, c.shot_at)
    segs = build_segments(project)
    starts = segment_starts(segs)
    marks: list[tuple[float, int]] = []
    last = None
    for seg, t in zip(segs, starts):
        when = shot.get(seg.path, 0.0)
        if not when:
            continue
        lt = time.localtime(when)
        month = (lt.tm_year, lt.tm_mon)
        if month != last:
            marks.append((t, lt.tm_mon))
            last = month
    total = total_duration(segs)
    out = []
    for i, (t, m) in enumerate(marks):
        end = min(t + show, marks[i + 1][0] if i + 1 < len(marks) else total, total)
        if end - t > 0.2:
            out.append(TitleEntry(round(t, 3), round(end, 3), names[m - 1]))
    return out
