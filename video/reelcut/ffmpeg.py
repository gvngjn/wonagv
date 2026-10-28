"""FFmpeg / FFprobe 찾기, 미디어 정보 조회, 진행률을 읽으며 실행하기."""
from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

# Windows에서 ffmpeg 콘솔 창이 뜨지 않게 한다.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


_FRIENDLY = [
    ("No space left on device", "디스크 공간이 부족해요. 저장할 드라이브의 공간을 비워 주세요."),
    ("Permission denied", "파일에 쓸 권한이 없거나 다른 프로그램이 파일을 쓰고 있어요. 플레이어를 닫거나 다른 폴더를 골라 주세요."),
    ("Invalid data found when processing input", "파일이 손상됐거나 지원하지 않는 형식이에요."),
    ("moov atom not found", "파일이 끝까지 저장되지 않은(손상된) 영상이에요."),
    ("No such file or directory", "파일을 찾을 수 없어요. 옮기거나 지웠는지 확인해 주세요."),
    ("Cannot allocate memory", "메모리가 부족해요. 다른 프로그램을 닫거나 해상도를 낮춰 보세요."),
]


def friendly_message(stderr: str) -> str:
    """ffmpeg 오류 출력에서 흔한 원인을 찾아 쉬운 설명을 돌려준다 (없으면 빈 문자열)."""
    for needle, msg in _FRIENDLY:
        if needle in stderr:
            return msg
    return ""


class Cancelled(Exception):
    """사용자가 작업을 취소했을 때."""


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        dirs += [exe_dir, exe_dir / "ffmpeg"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs += [Path(meipass), Path(meipass) / "ffmpeg"]
    here = Path(__file__).resolve().parent.parent
    dirs += [here / "ffmpeg", here]
    return dirs


def find_tool(name: str) -> str:
    """ffmpeg/ffprobe 실행 파일 경로. 앱 폴더 → 환경변수 → PATH 순으로 찾는다."""
    env = os.environ.get(f"REELCUT_{name.upper()}")
    if env and Path(env).exists():
        return env
    exe = name + (".exe" if os.name == "nt" else "")
    for d in _candidate_dirs():
        p = d / exe
        if p.exists():
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise FFmpegError(
        f"{name}을(를) 찾을 수 없어요. 앱 폴더의 ffmpeg 폴더에 {exe}를 넣거나 PATH에 추가해 주세요."
    )


def ffmpeg_path() -> str:
    return find_tool("ffmpeg")


def ffprobe_path() -> str:
    return find_tool("ffprobe")


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    created: float = 0.0           # 찍은 시각 (유닉스 시간, 모르면 0)

    @property
    def is_audio_only(self) -> bool:
        return self.has_audio and not self.has_video


def parse_time(text: str) -> float:
    """'2025-03-14T09:12:30.000000Z', '2025-03-14T18:12:30+0900' 같은 시각 → 유닉스 시간 (모르면 0)."""
    from datetime import datetime, timezone

    text = (text or "").strip()
    if not text:
        return 0.0
    text = text.replace("Z", "+00:00")
    # +0900 → +09:00 (파이썬 3.10 호환)
    if len(text) > 5 and text[-5] in "+-" and text[-4:].isdigit():
        text = text[:-2] + ":" + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    t = dt.timestamp()
    return t if t > 86400 * 365 else 0.0     # 1970년 같은 빈 값은 무시


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 0.0
    if "/" in rate:
        n, d = rate.split("/", 1)
        try:
            return float(n) / float(d) if float(d) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def parse_probe_json(path: str, data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    # 앨범 커버(attached_pic)는 영상으로 치지 않는다.
    video = next(
        (s for s in streams if s.get("codec_type") == "video"
         and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = 0.0
    for src in (fmt, video or {}, audio or {}):
        try:
            duration = float(src.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break
    info = MediaInfo(path=path, duration=duration, has_video=video is not None,
                     has_audio=audio is not None)
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    if video:
        tags = {**{k.lower(): v for k, v in (video.get("tags") or {}).items()}, **tags}
    # 아이폰은 현지 시간대가 붙은 creationdate를 따로 남긴다 (creation_time은 UTC)
    info.created = parse_time(tags.get("com.apple.quicktime.creationdate", "")) or parse_time(
        tags.get("creation_time", ""))
    if video:
        info.width = int(video.get("width") or 0)
        info.height = int(video.get("height") or 0)
        # 세로 촬영(회전 메타데이터)이면 가로세로를 바꾼다.
        rotation = 0
        for side in video.get("side_data_list", []) or []:
            if "rotation" in side:
                rotation = int(side["rotation"])
        rotation = int(video.get("tags", {}).get("rotate", rotation) or rotation)
        if abs(rotation) % 180 == 90:
            info.width, info.height = info.height, info.width
        info.fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    return info


def probe(path: str) -> MediaInfo:
    cmd = [ffprobe_path(), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, creationflags=_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise FFmpegError(f"파일을 읽을 수 없어요: {path}\n{e.stderr.decode('utf-8', 'replace')}") from e
    return parse_probe_json(str(path), json.loads(out.stdout.decode("utf-8", "replace")))


HDR_TRANSFERS = ("arib-std-b67", "smpte2084")   # HLG(아이폰·갤럭시 HDR), PQ(HDR10)


@functools.lru_cache(maxsize=512)
def _hdr_transfer_cached(path: str, mtime: float) -> str:
    cmd = [ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=color_transfer", "-of", "default=nw=1:nk=1", path]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    trc = out.decode("utf-8", "replace").strip()
    return trc if trc in HDR_TRANSFERS else ""


def hdr_transfer(path: str) -> str:
    """HDR 영상이면 전달 특성 이름(arib-std-b67 / smpte2084), 아니면 ""."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    return _hdr_transfer_cached(str(path), mtime)


def decode_audio(path: str, sample_rate: int, start: float = 0.0,
                 duration: float | None = None):
    """오디오를 모노 float32 numpy 배열로 디코딩한다. 소리가 없으면 빈 배열."""
    import numpy as np

    cmd = [ffmpeg_path(), "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        if "does not contain any stream" in err or "matches no streams" in err:
            return np.zeros(0, dtype=np.float32)
        raise FFmpegError(f"오디오를 읽을 수 없어요: {path}\n{err}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


class ProcessRunner:
    """ffmpeg를 실행하고 -progress 출력을 읽어 진행률(초)을 알려준다. 취소 가능."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._proc and self._proc.poll() is None:
                self._proc.kill()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self, args: Sequence[str], on_time: Callable[[float], None] | None = None,
            cwd: str | None = None) -> None:
        if self._cancelled:
            raise Cancelled()
        cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y",
               "-progress", "pipe:1", "-nostats", *args]
        stderr_lines: list[str] = []
        with self._lock:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                creationflags=_NO_WINDOW,
            )
        proc = self._proc

        def read_err() -> None:
            assert proc.stderr
            for raw in proc.stderr:
                stderr_lines.append(raw.decode("utf-8", "replace"))
                del stderr_lines[:-60]

        t = threading.Thread(target=read_err, daemon=True)
        t.start()
        assert proc.stdout
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if on_time and line.startswith("out_time_us="):
                try:
                    on_time(max(0.0, int(line.split("=", 1)[1]) / 1_000_000))
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=2)
        if self._cancelled:
            raise Cancelled()
        if proc.returncode != 0:
            detail = "".join(stderr_lines[-25:])
            logging.getLogger("reelcut").error("ffmpeg 실패 (코드 %s)\n명령: %s\n%s", proc.returncode,
                                               " ".join(str(a) for a in cmd), "".join(stderr_lines[-60:]))
            hint = friendly_message(detail)
            raise FFmpegError((hint + "\n\n[자세한 내용]\n" if hint else "ffmpeg 실행 실패:\n") + detail)


def thumbnail_png(path: str, at: float = 0.0, width: int = 160) -> bytes:
    """영상의 at초 장면을 PNG로 (실패하면 빈 bytes)."""
    cmd = [ffmpeg_path(), "-v", "error", "-nostdin"]
    if at > 0:
        cmd += ["-ss", f"{at:.3f}"]
    cmd += ["-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2",
            "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError):
        return b""
    return proc.stdout if proc.returncode == 0 else b""
