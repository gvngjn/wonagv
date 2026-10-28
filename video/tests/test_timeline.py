import pytest

from reelcut.project import BeatSyncSettings, Clip, MusicSettings, Project
from reelcut.timeline import (beat_sync_segments, build_segments, concat_segments, cut_boundaries,
                              total_duration)


def clips():
    return [Clip("a.mp4", 10.0), Clip("b.mp4", 6.0, in_point=1.0, out_point=5.0), Clip("c.mp4", 3.0)]


def test_concat_uses_trim_points():
    segs = concat_segments(clips())
    assert [(s.path, s.src_start, s.duration) for s in segs] == [
        ("a.mp4", 0.0, 10.0), ("b.mp4", 1.0, 4.0), ("c.mp4", 0.0, 3.0)]


def test_cut_boundaries_every_n_beats_and_frame_aligned():
    beats = [0.5 * i + 0.26 for i in range(40)]
    b = cut_boundaries(beats, music_start=0.0, beats_per_cut=2, end_time=6.0, fps=30)
    assert b[0] == 0.0 and b[-1] == 6.0
    for t in b:
        assert abs(t * 30 - round(t * 30)) < 1e-9     # 프레임 경계
    # 첫 비트(0.26)와 이후 2비트마다(1.26, 2.26, ...) 근처에서 컷
    for expected, got in zip([0.26, 1.26, 2.26, 3.26], b[1:]):
        assert abs(expected - got) <= 1 / 60 + 1e-9


def test_cut_boundaries_respects_music_start():
    beats = [1.0, 2.0, 3.0, 4.0]
    b = cut_boundaries(beats, music_start=1.5, beats_per_cut=1, end_time=3.0, fps=20)
    assert b == [0.0, 0.5, 1.5, 2.5, 3.0]


@pytest.mark.parametrize("order", ["sequential", "spread", "grouped", "random", "continuous"])
def test_beat_sync_fills_every_cut_within_clip_ranges(order):
    bounds = [i * 0.5 for i in range(41)]          # 20초, 컷 40개
    segs = beat_sync_segments(clips(), bounds, order, seed=3)
    assert len(segs) == 40
    assert total_duration(segs) == pytest.approx(20.0)
    for s in segs:
        c = next(c for c in clips() if c.path == s.path)
        assert s.src_start >= c.in_point - 1e-9
        assert s.src_start + s.duration <= c.end + 1e-9


def test_sequential_alternates_files_every_cut():
    segs = beat_sync_segments(clips(), [i * 0.5 for i in range(13)], "sequential")
    assert [s.path for s in segs] == ["a.mp4", "b.mp4", "c.mp4"] * 4
    # 같은 파일 안에서는 앞에서 뒤로 고르게 진행
    a_starts = [s.src_start for s in segs if s.path == "a.mp4"]
    assert a_starts == sorted(a_starts) and a_starts[-1] > 5


def test_grouped_uses_one_file_at_a_time():
    segs = beat_sync_segments(clips(), [0, 4, 8, 12, 14], "grouped")
    assert [s.path for s in segs] == ["a.mp4", "a.mp4", "b.mp4", "c.mp4"]
    assert segs[0].src_start < segs[1].src_start


def test_sequential_cuts_jump_instead_of_continuing():
    """같은 클립에서 연달아 뽑아도 바로 이어지는 구간이 아니라 건너뛰어야 장면 전환이 보인다."""
    long_clip = [Clip("concert.mp4", 850.0)]
    bounds = [i * 0.857 for i in range(281)]          # 140BPM 2비트마다, 4분
    segs = beat_sync_segments(long_clip, bounds, "sequential")
    assert segs == beat_sync_segments(long_clip, bounds, "grouped")
    assert len(segs) == 280
    gaps = [b.src_start - (a.src_start + a.duration) for a, b in zip(segs, segs[1:])]
    assert min(gaps) > 1.0                             # 매 컷마다 1초 넘게 건너뜀
    assert segs[-1].src_start + segs[-1].duration <= 850.0
    assert segs[-1].src_start > 800                    # 클립 전체를 고르게 사용


def test_random_never_repeats_same_clip_twice_in_a_row():
    segs = beat_sync_segments(clips(), [i * 0.5 for i in range(30)], "random", seed=1)
    assert all(a.path != b.path for a, b in zip(segs, segs[1:]))


def test_build_segments_beat_sync_uses_music_length():
    p = Project(clips=clips())
    p.music = MusicSettings(path="m.mp3", duration=12.0, start=2.0, beats=[0.5 * i for i in range(30)])
    p.beat_sync = BeatSyncSettings(enabled=True, beats_per_cut=4)
    segs = build_segments(p)
    assert total_duration(segs) == pytest.approx(10.0)
    assert all(s.duration == pytest.approx(2.0) for s in segs)


def test_build_segments_without_beats_falls_back_to_concat():
    p = Project(clips=clips())
    p.beat_sync.enabled = True
    assert total_duration(build_segments(p)) == pytest.approx(17.0)


def test_clip_length_mode_never_exceeds_music():
    p = Project(clips=[Clip("long.mp4", 850.0)])
    p.music = MusicSettings(path="m.mp3", duration=240.0, beats=[0.43 * i for i in range(560)])
    p.beat_sync = BeatSyncSettings(enabled=True, beats_per_cut=2, use_music_length=False)
    segs = build_segments(p)
    assert total_duration(segs) == pytest.approx(240.0, abs=0.05)
    assert max(s.duration for s in segs) < 1.0         # 음악 끝난 뒤 긴 덩어리가 없어야 함


def test_continuous_keeps_original_flow():
    segs = beat_sync_segments(clips(), [0, 4, 8, 12, 14], "continuous")
    assert [(s.path, s.src_start) for s in segs] == [
        ("a.mp4", 0.0), ("a.mp4", 4.0), ("b.mp4", 1.0), ("c.mp4", 0.0)]


def test_speed_changes_timeline_length_and_source_range():
    fast = Clip("fast.mp4", 20.0, 0.0, 10.0, speed=2.0, volume=0.5)
    slow = Clip("slow.mp4", 20.0, 2.0, 4.0, speed=0.5)
    assert fast.timeline_length == 5.0 and slow.timeline_length == 4.0
    segs = concat_segments([fast, slow])
    assert [(s.duration, s.speed, s.volume) for s in segs] == [(5.0, 2.0, 0.5), (4.0, 0.5, 1.0)]
    # 비트 맞춤: 컷 길이는 완성 영상 기준, 원본에서는 속도만큼 더(덜) 사용하고 범위를 넘지 않음
    bounds = [i * 0.5 for i in range(19)]
    out = beat_sync_segments([fast, slow], bounds, "sequential")
    for s in out:
        c = fast if s.path == "fast.mp4" else slow
        assert s.speed == c.speed
        assert c.in_point - 1e-9 <= s.src_start
        assert s.src_start + s.duration * s.speed <= c.end + 1e-9


def _eight_clips():
    lengths = [3.0, 12.5, 7.0, 25.0, 4.2, 9.9, 60.0, 5.5]          # 무작위 길이 8개
    return [Clip(f"c{i}.mp4", L) for i, L in enumerate(lengths)]


def test_per_clip_seconds_total_is_count_times_n():
    """사용자 요청: 8개 영상을 N초씩 이으면 8×N초에 끝남, 클립마다 한 번씩, 시작 지점부터."""
    p = Project(clips=_eight_clips())
    p.music = MusicSettings(path="song.mp3", duration=200.0)
    p.beat_sync = BeatSyncSettings(enabled=True, cut_unit="seconds", cut_seconds=2.5, per_clip=True)
    segs = build_segments(p)
    assert len(segs) == 8
    assert total_duration(segs) == pytest.approx(20.0)
    assert [s.path for s in segs] == [f"c{i}.mp4" for i in range(8)]
    assert all(s.src_start == 0.0 and s.duration == pytest.approx(2.5) for s in segs)
    p.beat_sync.order = "random"
    shuffled = build_segments(p)
    assert sorted(s.path for s in shuffled) == sorted(s.path for s in segs)   # 각 클립 정확히 한 번


def test_per_clip_with_beats_and_seconds_without_music():
    p = Project(clips=_eight_clips())
    p.music = MusicSettings(path="song.mp3", duration=60.0, beats=[0.5 * i for i in range(120)])
    p.beat_sync = BeatSyncSettings(enabled=True, beats_per_cut=4, per_clip=True)
    segs = build_segments(p)
    assert len(segs) == 8 and total_duration(segs) == pytest.approx(16.0)      # 8 × (4비트 = 2초)
    # 음악 없이 초 단위도 동작
    q = Project(clips=_eight_clips())
    q.beat_sync = BeatSyncSettings(enabled=True, cut_unit="seconds", cut_seconds=1.0)
    assert total_duration(build_segments(q)) == pytest.approx(sum(c.length for c in q.clips), abs=1.0)


def test_month_titles_follow_shot_dates():
    import time

    from reelcut.project import Clip, Project
    from reelcut.timeline import month_titles

    day = lambda m, d: time.mktime((2026, m, d, 12, 0, 0, 0, 0, -1))
    p = Project(clips=[Clip("a.mp4", 10, 0, 2, shot_at=day(1, 3)), Clip("b.mp4", 10, 0, 3, shot_at=day(1, 20)),
                       Clip("c.mp4", 10, 0, 0.5, shot_at=day(3, 1)), Clip("d.mp4", 10, 0, 2, shot_at=day(4, 9)),
                       Clip("e.mp4", 10, 0, 2)])
    got = [(e.start, e.end, e.text) for e in month_titles(p)]
    # 1월은 0초, 3월은 5초(다음 달이 0.5초 뒤라 거기서 끝), 4월은 5.5초, 날짜 없는 클립은 무시
    assert got == [(0.0, 1.2, "JANUARY"), (5.0, 5.5, "MARCH"), (5.5, 6.7, "APRIL")]
    assert [e.text for e in month_titles(p, "ko")] == ["1월", "3월", "4월"]
