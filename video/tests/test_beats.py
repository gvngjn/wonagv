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
