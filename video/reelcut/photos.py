"""사진 파일 준비: 아이폰 HEIC 사진은 ffmpeg가 못 읽는 경우가 많아서 JPG로 바꿔 둔다.

프로젝트에는 원본 경로를 그대로 두고, 렌더링·썸네일 때만 바꾼 파일을 쓴다
(같은 사진은 한 번만 바꾸고 다시 쓴다).
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from .autosave import data_dir

HEIC_EXTS = {".heic", ".heif"}
_lock = threading.Lock()


def is_heic(path: str) -> bool:
    return Path(path).suffix.lower() in HEIC_EXTS


def converted_dir() -> Path:
    return data_dir() / "photos"


def readable_image(path: str) -> str:
    """ffmpeg·Qt가 읽을 수 있는 사진 경로 (HEIC면 바꾼 JPG, 아니면 원본 그대로)."""
    if not is_heic(path):
        return path
    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    out = converted_dir() / f"{Path(path).stem}_{key}.jpg"
    with _lock:
        if out.exists() and out.stat().st_size > 0:
            return str(out)
        try:
            import pillow_heif
            from PIL import Image, ImageOps
        except ImportError as e:  # 설치본에는 항상 들어 있다
            raise RuntimeError("HEIC 사진을 읽으려면 pillow-heif가 필요해요 (pip install pillow-heif).") from e
        pillow_heif.register_heif_opener()
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")   # 세로로 찍은 사진은 세로로
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".part.jpg")
                im.save(tmp, "JPEG", quality=95)
                os.replace(tmp, out)
        except Exception as e:  # noqa: BLE001 - 사용자에게 알기 쉬운 메시지로
            raise RuntimeError(f"HEIC 사진을 읽지 못했어요: {Path(path).name} ({e})") from e
    return str(out)


def photo_taken_time(path: str) -> float:
    """사진 EXIF의 찍은 시각 (유닉스 시간, 모르면 0)."""
    import time

    try:
        from PIL import Image
        if is_heic(path):
            import pillow_heif
            pillow_heif.register_heif_opener()
        with Image.open(path) as im:
            exif = im.getexif()
            sub = exif.get_ifd(0x8769)          # Exif IFD
            text = sub.get(0x9003) or exif.get(0x0132)   # DateTimeOriginal, 없으면 DateTime
            offset = sub.get(0x9011)            # OffsetTimeOriginal (예: +09:00)
    except Exception:  # noqa: BLE001 - 날짜를 못 읽으면 파일 시각을 쓴다
        return 0.0
    if not text:
        return 0.0
    try:
        st = time.strptime(str(text).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return 0.0
    if offset:
        from .ffmpeg import parse_time
        return parse_time(time.strftime("%Y-%m-%dT%H:%M:%S", st) + str(offset).strip())
    return time.mktime(st)      # 시간대가 없으면 이 컴퓨터 시간대로


def shot_time(path: str, created: float = 0.0) -> float:
    """찍은 시각: 영상 메타데이터 → 사진 EXIF → 파일 수정 시각 순으로."""
    from .render import is_image

    t = created or (photo_taken_time(path) if is_image(path) else 0.0)
    if not t:
        try:
            t = os.path.getmtime(path)
        except OSError:
            t = 0.0
    return t
