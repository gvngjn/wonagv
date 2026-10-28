import numpy as np
import pytest
from helpers import click_track

from reelcut import beats


@pytest.mark.parametrize("bpm", [90, 110, 128, 150, 174])
def test_detects_tempo_and_beat_positions(bpm):
    offset = 0.37
    y = click_track(bpm, 40.0, offset=offset, hihat=0.2)
    r = beats.analyze_samples(y)
    assert r.bpm == pytest.approx(bpm, rel=0.02)
    truth = np.arange(offset, 40.0, 60 / bpm)
    err = np.array([np.min(np.abs(truth - b)) for b in r.beats])
    assert np.median(err) < 0.03          # 30ms 이내
    assert len(r.beats) >= 0.9 * len(truth)


def test_silence_has_no_beats():
    r = beats.analyze_samples(np.zeros(22050 * 5, dtype=np.float32))
    assert r.beats == []


def test_grid_beats():
    g = beats.grid_beats(120, 0.25, 2.0)
    assert g == [0.25, 0.75, 1.25, 1.75]
    assert beats.grid_beats(0, 0, 10) == []


def _verse_chorus(sr=22050, bpm=120, dur=40):
    rng = np.random.default_rng(0)
    y = 0.005 * rng.standard_normal(sr * dur)
    step = 60 / bpm
    for i, t in enumerate(np.arange(0.25, dur, step)):
        n = int(t * sr)
        tt = np.arange(int(0.12 * sr)) / sr
        amp = (0.25 if t < dur / 2 else 1.0) * (1.0 if i % 4 == 0 else 0.35)   # 4박 중 첫 박이 강박
        k = np.sin(2 * np.pi * (60 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 18) * amp
        y[n:n + len(k)] += k[:len(y[n:n + len(k)])]
    return y.astype(np.float32), step


def test_beat_strength_and_energy_modes():
    from reelcut.timeline import pick_cut_beats

    y, step = _verse_chorus()
    r = beats.analyze_samples(y)
    assert len(r.strengths) == len(r.beats) == len(r.energy)
    acc = pick_cut_beats(r.beats, 2, "accent", r.strengths, r.energy)
    downbeats = [int(round((b - 0.25) / step)) % 4 == 0 for b in acc]
    assert sum(downbeats) / len(downbeats) > 0.9                 # 조용한 부분·후렴 모두 강박에서 컷
    en = pick_cut_beats(r.beats, 2, "energy", r.strengths, r.energy)
    first = sum(1 for b in en if b < 20)
    second = sum(1 for b in en if b >= 20)
    assert second > first * 1.5                                  # 큰 구간에서 더 자주
    assert pick_cut_beats(r.beats, 2) == r.beats[::2]
    # 세기 정보가 없으면(예전 프로젝트) 일정하게로 대체
    assert pick_cut_beats(r.beats, 2, "accent", [], []) == r.beats[::2]


def test_accent_never_cuts_more_often_than_regular():
    from reelcut.timeline import pick_cut_beats

    beats_ = [i * 0.5 for i in range(40)]
    flat = [1.0] * 40                                   # 모든 비트가 똑같이 셈
    assert len(pick_cut_beats(beats_, 2, "accent", flat, flat)) <= len(beats_[::2])
