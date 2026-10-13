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


@pytest.mark.parametrize("order", ["sequential", "spread", "random"])
def test_beat_sync_fills_every_cut_within_clip_ranges(order):
    bounds = [i * 0.5 for i in range(41)]          # 20초, 컷 40개
    segs = beat_sync_segments(clips(), bounds, order, seed=3)
    assert len(segs) == 40
    assert total_duration(segs) == pytest.approx(20.0)
    for s in segs:
        c = next(c for c in clips() if c.path == s.path)
        assert s.src_start >= c.in_point - 1e-9
        assert s.src_start + s.duration <= c.end + 1e-9


def test_sequential_walks_through_clips_in_order():
    segs = beat_sync_segments(clips(), [0, 4, 8, 12, 14], "sequential")
    assert [(s.path, s.src_start) for s in segs] == [
        ("a.mp4", 0.0), ("a.mp4", 4.0), ("b.mp4", 1.0), ("c.mp4", 0.0)]


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
