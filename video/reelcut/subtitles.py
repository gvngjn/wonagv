"""자막: SRT 읽기/쓰기와 Whisper(faster-whisper) 자동 자막 생성."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .project import Segment, SubtitleEntry

WHISPER_SR = 16000
MODELS = ("tiny", "base", "small", "medium", "large-v3")
LANGUAGES = {"": "자동 감지", "ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어"}


def format_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_ts(text: str) -> float:
    m = re.match(r"\s*(?:(\d+):)?(\d+):(\d+)(?:[,.](\d{1,3}))?\s*$", text)
    if not m:
        raise ValueError(f"시간 형식이 잘못됐어요: {text!r} (예: 00:01:02,500)")
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int((ms or "0").ljust(3, "0")) / 1000


def to_srt(entries: list[SubtitleEntry]) -> str:
    blocks = []
    for e in sorted(entries, key=lambda x: x.start):
        text = e.text.strip()
        if not text:
            continue
        blocks.append(f"{len(blocks) + 1}\n{format_ts(e.start)} --> {format_ts(e.end)}\n{text}\n")
    return "\n".join(blocks)


def parse_srt(text: str) -> list[SubtitleEntry]:
    entries = []
    text = text.replace("\r\n", "\n").replace("﻿", "")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        a, b = lines[0].split("-->", 1)
        b = b.strip().split(" ")[0]
        entries.append(SubtitleEntry(parse_ts(a), parse_ts(b), "\n".join(lines[1:])))
    return entries


def save_srt(path: str | Path, entries: list[SubtitleEntry]) -> None:
    Path(path).write_text(to_srt(entries), encoding="utf-8")


def load_srt(path: str | Path) -> list[SubtitleEntry]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949", "latin-1"):
        try:
            return parse_srt(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return []


def wrap_line(text: str, max_chars: int = 28) -> str:
    """한 줄이 너무 길면 가운데 근처 공백에서 두 줄로 나눈다."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    mid = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    cut = min(spaces, key=lambda i: abs(i - mid))
    return text[:cut] + "\n" + text[cut + 1:]


def shift(entries: list[SubtitleEntry], offset: float) -> list[SubtitleEntry]:
    return [SubtitleEntry(max(0.0, e.start + offset), max(0.0, e.end + offset), e.text) for e in entries]


# ---------- 자동 자막 ----------

def timeline_audio(segments: list[Segment], sample_rate: int = WHISPER_SR):
    """타임라인 순서대로 각 조각의 소리를 이어붙인 numpy 배열 (조각 길이에 정확히 맞춤)."""
    import numpy as np

    from .ffmpeg import decode_audio

    parts = []
    for s in segments:
        n = int(round(s.duration * sample_rate))
        y = decode_audio(s.path, sample_rate, s.src_start, s.duration) if s.has_audio else np.zeros(0, np.float32)
        if len(y) < n:
            y = np.pad(y, (0, n - len(y)))
        parts.append(y[:n])
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


def music_audio(path: str, start: float, duration: float, sample_rate: int = WHISPER_SR):
    from .ffmpeg import decode_audio

    return decode_audio(path, sample_rate, start, duration)


def transcribe(audio, model_name: str = "small", language: str = "",
               on_progress: Callable[[float], None] | None = None,
               should_stop: Callable[[], bool] | None = None,
               on_status: Callable[[str], None] | None = None) -> list[SubtitleEntry]:
    """faster-whisper로 음성을 자막으로. 모델은 처음 한 번 인터넷에서 내려받는다."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover - 설치 환경 문제
        raise RuntimeError("자동 자막에는 faster-whisper가 필요해요: pip install faster-whisper") from e

    if len(audio) == 0:
        return []
    total = len(audio) / WHISPER_SR
    if on_status:
        on_status(f"'{model_name}' 모델 준비 중… (처음에는 내려받느라 시간이 걸려요)")
    # GPU 드라이버 상태에 따라 실패하는 일이 없도록 CPU(int8)로 실행
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    if on_status:
        on_status("음성을 글자로 바꾸는 중…")
    segments, _info = model.transcribe(
        audio, language=language or None, vad_filter=True, beam_size=5,
        vad_parameters={"min_silence_duration_ms": 400},
    )
    out: list[SubtitleEntry] = []
    for seg in segments:
        if should_stop and should_stop():
            break
        text = seg.text.strip()
        if text:
            out.append(SubtitleEntry(round(seg.start, 3), round(seg.end, 3), wrap_line(text)))
        if on_progress and total > 0:
            on_progress(min(1.0, seg.end / total))
    return out
