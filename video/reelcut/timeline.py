"""클립 목록 → 렌더링할 조각(Segment) 목록 만들기.

- 일반 모드: 클립을 순서대로 이어붙인다.
- 비트 맞춤 모드: 음악 비트 위치에서 화면이 바뀌도록 클립을 잘라 이어붙인다.
"""
from __future__ import annotations

import random

from .project import Clip, Project, Segment


def concat_segments(clips: list[Clip]) -> list[Segment]:
    return [Segment(c.path, c.in_point, c.length, c.has_audio) for c in clips if c.length > 0.05]


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


def beat_sync_segments(clips: list[Clip], boundaries: list[float], order: str = "sequential",
                       seed: int = 7) -> list[Segment]:
    """컷 길이(boundaries 간격)에 맞게 클립에서 조각을 골라낸다.

    sequential: 클립을 앞에서부터 차례로 잘라 쓰고, 다 쓰면 다음 클립 (모두 쓰면 처음부터 다시)
    spread:     클립을 번갈아 가며, 각 클립의 처음~끝을 고르게 사용
    random:     무작위 클립의 무작위 위치 (seed로 재현 가능)
    """
    usable = [c for c in clips if c.length > 0.05]
    if not usable or len(boundaries) < 2:
        return []
    durations = [b - a for a, b in zip(boundaries, boundaries[1:])]
    segs: list[Segment] = []

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

    if order == "spread":
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

    # sequential
    ci = 0
    pos = usable[0].in_point
    for d in durations:
        c = usable[ci]
        if pos + d > c.end + 1e-6:
            # 남은 부분이 컷 길이보다 짧으면 다음 클립으로
            for _ in range(len(usable)):
                ci = (ci + 1) % len(usable)
                c = usable[ci]
                pos = c.in_point
                if c.length >= d:
                    break
        segs.append(Segment(c.path, pos, d, c.has_audio))
        pos += d
    return segs


def build_segments(project: Project) -> list[Segment]:
    clips = project.clips
    bs = project.beat_sync
    music = project.music
    if not (bs.enabled and music.path and music.beats):
        segs = concat_segments(clips)
        if bs.max_duration > 0:
            segs = _limit(segs, bs.max_duration)
        return segs

    total_clips = sum(c.length for c in clips)
    if bs.use_music_length and music.duration > 0:
        end_time = max(0.0, music.duration - music.start)
    else:
        end_time = total_clips
    if bs.max_duration > 0:
        end_time = min(end_time, bs.max_duration)
    beats = [b + music.beat_offset for b in music.beats]
    bounds = cut_boundaries(beats, music.start, bs.beats_per_cut, end_time, project.export.fps)
    return beat_sync_segments(clips, bounds, bs.order, bs.seed)


def _limit(segs: list[Segment], max_duration: float) -> list[Segment]:
    out, t = [], 0.0
    for s in segs:
        if t >= max_duration:
            break
        d = min(s.duration, max_duration - t)
        out.append(Segment(s.path, s.src_start, d, s.has_audio))
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
