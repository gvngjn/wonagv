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


@needs_ffmpeg
def test_burn_in_with_font_file(media, tmp_path):
    import glob
    fonts = sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))
    if not fonts:
        pytest.skip("테스트할 글꼴 파일 없음")
    p = base_project(media)
    p.subtitles.entries = [SubtitleEntry(0.0, 2.0, "Font test")]
    p.subtitles.font_file = fonts[0]
    p.subtitles.font_name = "Whatever"
    p.subtitles.box = True
    p.subtitles.position = "top"
    out = tmp_path / "font.mp4"
    Renderer().render(p, str(out), preview=True)
    assert probe(str(out)).duration == pytest.approx(7.0, abs=0.1)


@needs_ffmpeg
@pytest.mark.parametrize("fit", ["blur", "crop", "pad"])
def test_vertical_reels_render(media, tmp_path, fit):
    p = base_project(media)
    p.export.width, p.export.height, p.export.fit = 180, 320, fit
    out = tmp_path / f"reels_{fit}.mp4"
    Renderer().render(p, str(out))
    info = probe(str(out))
    assert (info.width, info.height) == (180, 320)
    assert info.duration == pytest.approx(7.0, abs=0.1)


@needs_ffmpeg
def test_cancel_stops_parallel_render(media, tmp_path):
    import threading
    import time

    from reelcut.ffmpeg import Cancelled

    p = base_project(media)
    p.clips = p.clips * 6                      # 조각 18개
    r = Renderer(workers=2)
    err = []

    def run():
        try:
            r.render(p, str(tmp_path / "x.mp4"))
        except Exception as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.8)
    r.cancel()
    t.join(30)
    assert not t.is_alive()
    assert err and isinstance(err[0], Cancelled)
    assert not (tmp_path / "x.mp4").exists()


@needs_ffmpeg
def test_cancel_during_final_stage_keeps_existing_output(media, tmp_path):
    from reelcut.ffmpeg import Cancelled
    from reelcut.render import temp_output_path

    out = tmp_path / "완성 영상.mp4"
    out.write_bytes(b"old good video")
    p = base_project(media)
    r = Renderer(workers=2)

    def progress(f, m):
        if f > 0.55:
            r.cancel()

    with pytest.raises(Cancelled):
        r.render(p, str(out), on_progress=progress)
    assert out.read_bytes() == b"old good video"          # 기존 파일 그대로
    assert not temp_output_path(str(out)).exists()       # 임시 파일 정리


@needs_ffmpeg
def test_missing_file_is_reported_before_rendering(media, tmp_path):
    from reelcut.render import MissingFilesError

    p = base_project(media)
    p.clips.append(Clip(str(tmp_path / "사라진 영상.mp4"), 3.0))
    p.music.path = str(tmp_path / "없는 노래.mp3")
    with pytest.raises(MissingFilesError) as e:
        Renderer().render(p, str(tmp_path / "o.mp4"))
    assert "사라진 영상.mp4" in str(e.value) and "없는 노래.mp3" in str(e.value)


@needs_ffmpeg
def test_thumbnail_png(media, tmp_path):
    from reelcut.ffmpeg import thumbnail_png

    data = thumbnail_png(str(media / "a.mp4"), 1.0, 96)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert thumbnail_png(str(tmp_path / "없음.mp4")) == b""


@needs_ffmpeg
@pytest.mark.parametrize("transition", ["flash", "zoom", "dip"])
def test_beat_transitions_keep_exact_length(media, tmp_path, transition):
    """전환 효과가 있어도 영상·소리 길이가 정확해야 한다 (조각 경계 필터 재시작 버그 회귀 방지)."""
    import subprocess

    p = base_project(media)
    m = probe(str(media / "music.wav"))
    r = beats.analyze_file(m.path)
    p.music = MusicSettings(m.path, m.duration, beats=r.beats, bpm=r.bpm)
    p.beat_sync = BeatSyncSettings(enabled=True, beats_per_cut=2, transition=transition)
    out = tmp_path / f"{transition}.mp4"
    total = Renderer().render(p, str(out), preview=True)
    lines = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time,duration",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    for line in lines:
        kind, start, dur = line.split(",")
        assert float(start) == pytest.approx(0, abs=0.01), line
        assert float(dur) == pytest.approx(total, abs=0.05), line


@needs_ffmpeg
def test_render_with_title(media, tmp_path):
    from reelcut.project import TitleEntry

    p = base_project(media)
    p.titles.entries = [TitleEntry(0.0, 2.0, "제목 테스트\n두 줄")]
    out = tmp_path / "title.mp4"
    Renderer().render(p, str(out), preview=True)
    assert probe(str(out)).duration == pytest.approx(7.0, abs=0.1)


def test_free_space_check(tmp_path, monkeypatch):
    import shutil as sh
    from collections import namedtuple

    from reelcut.render import NotEnoughSpaceError, RenderOptions, check_free_space, estimate_space

    opt = RenderOptions(1080, 1920, 30)
    temp, final = estimate_space(240, opt)
    assert 300e6 < temp < 1500e6 and final < temp            # 4분 세로 1080p: 수백 MB
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(sh, "disk_usage", lambda p: Usage(1, 1, 10 * 1024 ** 2))   # 10MB 남음
    with pytest.raises(NotEnoughSpaceError) as e:
        check_free_space(240, opt, tmp_path, tmp_path)
    assert "디스크 공간" in str(e.value)
    monkeypatch.setattr(sh, "disk_usage", lambda p: Usage(1, 1, 100 * 1024 ** 3))
    check_free_space(240, opt, tmp_path, tmp_path)           # 100GB면 통과


@needs_ffmpeg
def test_verify_output_detects_problems(media):
    from reelcut.render import RenderOptions, verify_output

    a = media / "a.mp4"                                        # 320x240, 4초, 소리 있음
    assert verify_output(a, RenderOptions(320, 240, 30), 4.0) == []
    probs = verify_output(media / "b_silent.mp4", RenderOptions(320, 240, 30), 10.0)
    assert any("크기" in p for p in probs) and any("소리" in p for p in probs) and any("길이" in p for p in probs)


@needs_ffmpeg
def test_segment_cache_reuse_and_invalidation(media, tmp_path, monkeypatch):
    import shutil as sh

    monkeypatch.setenv("REELCUT_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "클립.mp4"
    sh.copy(media / "a.mp4", src)
    i = probe(str(src))
    p = Project(clips=[Clip(str(src), i.duration, 0, 3, True, i.width, i.height)])
    p.export.width, p.export.height = 160, 90
    r1 = Renderer()
    r1.render(p, str(tmp_path / "1.mp4"))
    assert r1.cache_hits == 0
    p.subtitles.entries = [SubtitleEntry(0, 1, "자막만 바뀜")]
    r2 = Renderer()
    r2.render(p, str(tmp_path / "2.mp4"))
    assert r2.cache_hits == 1                                 # 조각 재사용
    import os, time
    os.utime(src, (time.time() + 100, time.time() + 100))     # 원본이 바뀌면 다시 만든다
    r3 = Renderer()
    r3.render(p, str(tmp_path / "3.mp4"))
    assert r3.cache_hits == 0
    p.clips[0].in_point = 0.5                                 # 자르기를 바꿔도 다시 만든다
    r4 = Renderer()
    r4.render(p, str(tmp_path / "4.mp4"))
    assert r4.cache_hits == 0
    assert probe(str(tmp_path / "4.mp4")).duration == pytest.approx(2.5, abs=0.1)


def test_cache_prune(tmp_path, monkeypatch):
    import os
    import time

    from reelcut import cache

    monkeypatch.setenv("REELCUT_DATA_DIR", str(tmp_path))
    d = cache.cache_dir()
    d.mkdir(parents=True)
    for k in range(5):
        f = d / f"{k}.mkv"
        f.write_bytes(b"x" * 1000)
        os.utime(f, (time.time() + k, time.time() + k))       # 0이 가장 오래됨
    cache.prune(limit=2500)
    assert sorted(f.name for f in d.glob("*.mkv")) == ["3.mkv", "4.mkv"]
    cache.clear()
    assert cache.size() == 0


@needs_ffmpeg
def test_music_ducks_under_speech(tmp_path):
    """원본 소리가 나는 동안만 음악(220Hz)이 줄어드는지 실제로 렌더링해서 잰다."""
    import numpy as np

    ff = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    talk, music = tmp_path / "talk.mp4", tmp_path / "music.wav"
    ff("-f", "lavfi", "-i", "color=c=gray:s=160x90:d=6", "-f", "lavfi",
       "-i", "sine=f=1000:d=6,volume='if(gte(t,3),1.13,0)':eval=frame",
       "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(talk))
    ff("-f", "lavfi", "-i", "sine=f=220:d=8", str(music))
    levels = {}
    for duck in ("off", "strong"):
        p = Project(clips=[Clip(str(talk), probe(str(talk)).duration)])
        p.music = MusicSettings(str(music), 8.0, fade_out=0, duck=duck)
        p.export.width, p.export.height, p.export.fps, p.export.preset, p.export.loudness = 160, 90, 25, "ultrafast", 0
        out = tmp_path / f"{duck}.mp4"
        Renderer().render(p, str(out))
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-af", "lowpass=f=400,lowpass=f=400",
                              "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
        y = np.frombuffer(raw, np.int16).astype(float)
        db = lambda a, b: 20 * np.log10(np.sqrt(np.mean(y[int(a * 8000):int(b * 8000)] ** 2)) + 1e-9)
        levels[duck] = (db(0.5, 2.5), db(3.8, 5.5))
    assert abs(levels["off"][0] - levels["off"][1]) < 1
    assert abs(levels["strong"][0] - levels["off"][0]) < 1       # 조용할 때는 그대로
    assert levels["strong"][0] - levels["strong"][1] > 12        # 말할 때는 크게 줄어듦


@needs_ffmpeg
def test_every_color_filter_renders(media, tmp_path):
    from reelcut.render import COLOR_FILTERS

    for color in COLOR_FILTERS:
        p = base_project(media)
        p.clips = p.clips[:1]
        p.export.color = color
        out = tmp_path / f"{color}.mp4"
        Renderer().render(p, str(out), preview=True)
        assert probe(str(out)).duration > 2.5, color


@needs_ffmpeg
def test_gpu_encoder_failure_falls_back_to_cpu(media, tmp_path, monkeypatch):
    """그래픽카드 인코더가 있다고 나왔는데 실제로 실패하면 CPU로 다시 만들어야 한다."""
    from reelcut import hwenc

    monkeypatch.setattr(hwenc, "_detected", "h264_nvenc")
    monkeypatch.setattr(hwenc, "_broken", set())
    monkeypatch.setattr(hwenc, "codec_args", lambda enc, crf, preset: (
        ["-c:v", "this_encoder_does_not_exist"] if enc != hwenc.SOFTWARE else ["-c:v", "libx264", "-preset", "ultrafast"]))
    p = base_project(media)
    out = tmp_path / "gpu.mp4"
    r = Renderer()
    r.render(p, str(out))
    assert probe(str(out)).duration == pytest.approx(7.0, abs=0.1)
    assert r.encoder_used == hwenc.SOFTWARE and hwenc.detect() == ""   # 다음부터는 바로 CPU
    p.export.gpu = False
    assert Renderer().render(p, str(tmp_path / "cpu.mp4")) == pytest.approx(7.0)
