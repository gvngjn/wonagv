"""ffmpeg로 실제 렌더링해 보는 통합 테스트."""
import subprocess

import pytest
from conftest import needs_ffmpeg

from reelcut import beats
from reelcut.ffmpeg import probe
from reelcut.project import BeatSyncSettings, Clip, MusicSettings, PipOverlay, Project, SubtitleEntry
from reelcut.render import Renderer
from reelcut.subtitles import timeline_audio
from reelcut.timeline import build_segments


def base_project(media):
    a, b = probe(str(media / "a.mp4")), probe(str(media / "b_silent.mp4"))
    p = Project(clips=[
        Clip(a.path, a.duration, 0.5, 3.5, a.has_audio, a.width, a.height),
        Clip(b.path, b.duration, has_audio=b.has_audio),
        Clip(str(media / "logo.png"), 0.0, 0.0, 1.0, has_audio=False),
    ])
    p.export.width, p.export.height, p.export.fps, p.export.preset = 320, 180, 25, "ultrafast"
    return p


@needs_ffmpeg
def test_concat_render(media, tmp_path):
    p = base_project(media)
    out = tmp_path / "concat.mp4"
    progress = []
    total = Renderer().render(p, str(out), on_progress=lambda f, m: progress.append(f))
    info = probe(str(out))
    assert total == pytest.approx(7.0)
    assert info.duration == pytest.approx(7.0, abs=0.1)
    assert (info.width, info.height) == (320, 180) and info.has_audio
    assert progress[-1] == 1.0


@needs_ffmpeg
def test_beat_sync_with_pip_and_subtitles(media, tmp_path):
    p = base_project(media)
    m = probe(str(media / "music.wav"))
    r = beats.analyze_file(m.path)
    assert r.bpm == pytest.approx(120, rel=0.03)
    p.music = MusicSettings(m.path, m.duration, beats=r.beats, bpm=r.bpm)
    p.beat_sync = BeatSyncSettings(enabled=True, beats_per_cut=2, order="random")
    pi = probe(str(media / "pip.mp4"))
    p.pips = [PipOverlay(pi.path, start=1.0, src_duration=pi.duration, has_audio=True, volume=0.5),
              PipOverlay(str(media / "logo.png"), start=0, duration=2, position="top-left", border=0)]
    p.subtitles.entries = [SubtitleEntry(0.2, 1.5, "자막 '테스트', 쉼표")]
    out = tmp_path / "beat.mp4"
    Renderer().render(p, str(out))
    info = probe(str(out))
    assert info.duration == pytest.approx(8.0, abs=0.1)

    # 소프트 자막 트랙
    p.subtitles.burn_in = False
    out2 = tmp_path / "soft.mp4"
    Renderer().render(p, str(out2), preview=True)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", str(out2)], capture_output=True, text=True).stdout
    assert "subtitle" in streams


@needs_ffmpeg
def test_timeline_audio_length_matches_segments(media):
    p = base_project(media)
    audio = timeline_audio(build_segments(p))
    assert len(audio) == pytest.approx(7.0 * 16000, abs=2)
