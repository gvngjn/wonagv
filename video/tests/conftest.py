import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg가 설치되어 있지 않음")


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """테스트용 짧은 영상·사진·음악 파일."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg 필요")
    d = tmp_path_factory.mktemp("media")
    ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4",
       "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest",
       "-c:v", "libx264", "-c:a", "aac", str(d / "a.mp4"))
    ff("-f", "lavfi", "-i", "smptebars=size=240x320:rate=25:duration=3",
       "-c:v", "libx264", str(d / "b_silent.mp4"))
    ff("-f", "lavfi", "-i", "testsrc=size=160x120:rate=24:duration=3",
       "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-shortest",
       "-c:v", "libx264", "-c:a", "aac", str(d / "pip.mp4"))
    ff("-f", "lavfi", "-i", "color=c=red:size=200x100", "-frames:v", "1", str(d / "logo.png"))
    from helpers import click_track, write_wav
    write_wav(d / "music.wav", click_track(120, 8.0, offset=0.25), 22050)
    return d
