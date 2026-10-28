"""그래픽카드 인코더(NVIDIA·Intel·AMD) 찾기와 인코딩 옵션.

최종 영상 인코딩(2단계)만 그래픽카드로 한다. 조각(1단계)은 캐시와 정확한 프레임 수를 위해
항상 libx264를 쓴다. 그래픽카드 인코딩이 실패하면 렌더러가 libx264로 다시 만든다.
"""
from __future__ import annotations

import subprocess
import threading

from . import logs
from .ffmpeg import _NO_WINDOW, ffmpeg_path

SOFTWARE = "libx264"
# 찾는 순서와 화면에 보일 이름
HW_ENCODERS = (("h264_nvenc", "NVIDIA"), ("h264_qsv", "Intel"), ("h264_amf", "AMD"))
NAMES = dict(HW_ENCODERS) | {SOFTWARE: "CPU"}

_lock = threading.Lock()
_detected: str | None = None       # 찾은 인코더 ("" = 없음, None = 아직 안 찾음)
_broken: set[str] = set()          # 실제 내보내기에서 실패한 인코더


def _works(encoder: str) -> bool:
    """작은 영상을 실제로 인코딩해 본다 (드라이버가 없으면 목록에 있어도 실패한다)."""
    cmd = [ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:r=30:d=0.2",
           "-pix_fmt", "yuv420p", "-c:v", encoder, "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20, creationflags=_NO_WINDOW).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect() -> str:
    """쓸 수 있는 그래픽카드 인코더 이름, 없으면 ""(한 번만 찾고 기억한다)."""
    global _detected
    with _lock:
        if _detected is None:
            _detected = next((e for e, _ in HW_ENCODERS if _works(e)), "")
            logs.log.info("그래픽카드 인코더: %s", _detected or "없음")
        return "" if _detected in _broken else _detected


def mark_broken(encoder: str) -> None:
    """내보내기 중 실패한 인코더는 이번 실행 동안 다시 쓰지 않는다."""
    with _lock:
        _broken.add(encoder)


def codec_args(encoder: str, crf: int, preset: str) -> list[str]:
    """CRF(화질 숫자)를 각 인코더의 비슷한 화질 설정으로 바꾼다."""
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-tune", "hq", "-rc", "vbr",
                "-cq", str(crf + 2), "-b:v", "0", "-spatial-aq", "1"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-preset", "medium", "-global_quality", str(crf + 2)]
    if encoder == "h264_amf":
        return ["-c:v", encoder, "-quality", "balanced", "-rc", "cqp",
                "-qp_i", str(crf), "-qp_p", str(crf + 2), "-qp_b", str(crf + 4)]
    return ["-c:v", SOFTWARE, "-preset", preset, "-crf", str(crf)]
