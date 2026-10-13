"""유튜브(등) 링크에서 음악을 mp3로 내려받기 — yt-dlp 사용."""
from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ffmpeg import Cancelled, ffmpeg_path

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_YOUTUBE_RE = re.compile(
    r"^https?://(www\.|m\.|music\.)?(youtube\.com/(watch\?|shorts/|live/|embed/)|youtu\.be/)", re.IGNORECASE)


@dataclass
class DownloadResult:
    path: str
    title: str
    duration: float


def default_music_dir() -> Path:
    return Path.home() / "Music" / "ReelCut"


def is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


def is_youtube_url(text: str) -> bool:
    return bool(_YOUTUBE_RE.match(text.strip()))


def clean_url(text: str) -> str:
    """재생목록·시작 시간 등 붙은 값을 정리하고 영상 하나만 받도록."""
    url = text.strip()
    if is_youtube_url(url) and "watch?" in url:
        m = re.search(r"[?&]v=([\w-]{6,})", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def find_deno() -> str | None:
    """유튜브 해독에 쓰는 JavaScript 런타임(Deno). 앱 폴더 → PATH 순."""
    names = ["deno.exe", "deno"] if os.name == "nt" else ["deno"]
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        dirs += [exe_dir / "deno", exe_dir]
    here = Path(__file__).resolve().parent.parent
    dirs += [here / "deno"]
    for d in dirs:
        for n in names:
            if (d / n).exists():
                return str(d / n)
    return shutil.which("deno")


def build_options(out_dir: Path, hook: Callable[[dict], None]) -> dict:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title).80B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": str(Path(ffmpeg_path()).parent),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "progress_hooks": [hook],
    }
    deno = find_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    return opts


def download_audio(url: str, out_dir: str | Path | None = None,
                   on_progress: Callable[[float, str], None] | None = None,
                   should_stop: Callable[[], bool] | None = None) -> DownloadResult:
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover - 설치 환경 문제
        raise RuntimeError("링크로 받기에는 yt-dlp가 필요해요: pip install yt-dlp") from e

    url = clean_url(url)
    if not is_url(url):
        raise ValueError("올바른 링크가 아니에요. https:// 로 시작하는 주소를 넣어 주세요.")
    out = Path(out_dir) if out_dir else default_music_dir()
    out.mkdir(parents=True, exist_ok=True)
    report = on_progress or (lambda f, m: None)

    def hook(d: dict) -> None:
        if should_stop and should_stop():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = done / total if total else 0.0
            report(0.9 * frac, f"내려받는 중… {int(frac * 100)}%")
        elif d.get("status") == "finished":
            report(0.92, "mp3로 바꾸는 중…")

    report(0.0, "링크 확인 중…")
    try:
        with yt_dlp.YoutubeDL(build_options(out, hook)) as ydl:
            info = ydl.extract_info(url, download=True)
    except Cancelled:
        raise
    except Exception as e:
        if should_stop and should_stop():
            raise Cancelled() from e
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
        raise RuntimeError(f"음악을 받지 못했어요.\n{msg}") from e
    if info and info.get("entries"):
        info = next((x for x in info["entries"] if x), info)
    path = ""
    for d in (info or {}).get("requested_downloads") or []:
        path = d.get("filepath") or d.get("filename") or path
    if not path or not Path(path).exists():
        # 후처리 후 확장자가 mp3로 바뀐 경우
        guess = Path(path).with_suffix(".mp3") if path else None
        if guess and guess.exists():
            path = str(guess)
        else:
            raise RuntimeError("내려받은 파일을 찾지 못했어요.")
    report(1.0, "완료")
    return DownloadResult(path=str(path), title=(info or {}).get("title") or Path(path).stem,
                          duration=float((info or {}).get("duration") or 0))
