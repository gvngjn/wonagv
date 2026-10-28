"""조각 캐시: 같은 원본·같은 설정으로 만든 조각은 다시 인코딩하지 않는다."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .autosave import data_dir

DEFAULT_LIMIT = 3 * 1024 ** 3        # 3GB


def cache_dir() -> Path:
    return data_dir() / "cache" / "segments"


def segment_key(args: list[str], out_path: str, sources: list[str]) -> str:
    """ffmpeg 인자(출력 경로 제외) + 원본 파일 크기·수정 시각으로 만든 키."""
    parts = [a for a in args if a != out_path]
    stats = []
    for src in sources:
        try:
            st = os.stat(src)
            stats.append([src, st.st_size, int(st.st_mtime)])
        except OSError:
            stats.append([src, None, None])
    raw = json.dumps([parts, stats, 2], ensure_ascii=False)      # 2 = 캐시 형식 버전
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def lookup(key: str) -> Path | None:
    p = cache_dir() / f"{key}.mkv"
    if p.exists() and p.stat().st_size > 0:
        try:
            os.utime(p)              # 최근 사용 표시 (오래된 것부터 지우기 위해)
        except OSError:
            pass
        return p
    return None


def store(key: str, produced: Path) -> Path:
    """만든 조각을 캐시로 옮기고 캐시 경로를 돌려준다 (실패하면 원래 경로)."""
    d = cache_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        target = d / f"{key}.mkv"
        try:
            os.replace(produced, target)
        except OSError:                      # 다른 드라이브면 복사
            shutil.copy2(produced, target)
        return target
    except OSError:
        return produced


def size() -> int:
    d = cache_dir()
    return sum(f.stat().st_size for f in d.glob("*.mkv")) if d.exists() else 0


def prune(limit: int = DEFAULT_LIMIT, keep: set[Path] | None = None) -> None:
    """캐시가 limit을 넘으면 오래 안 쓴 것부터 지운다."""
    d = cache_dir()
    if not d.exists():
        return
    files = sorted(d.glob("*.mkv"), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    keep = keep or set()
    for f in files:
        if total <= limit:
            break
        if f in keep:
            continue
        try:
            sz = f.stat().st_size
            f.unlink()
            total -= sz
        except OSError:
            pass


def clear() -> None:
    shutil.rmtree(cache_dir(), ignore_errors=True)
