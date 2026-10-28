"""오류 기록: 문제가 생겼을 때 원인을 찾을 수 있게 파일로 남긴다."""
from __future__ import annotations

import logging
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from .autosave import data_dir

log = logging.getLogger("reelcut")
_installed = False


def log_dir() -> Path:
    return data_dir() / "logs"


def log_file() -> Path:
    return log_dir() / "reelcut.log"


def setup(version: str = "") -> None:
    """파일 기록 시작 (최대 1MB × 3개 보관). 여러 번 불러도 한 번만 설정."""
    global _installed
    if _installed:
        return
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    _installed = True
    log.info("ReelCut %s 시작 · %s · Python %s", version, platform.platform(), platform.python_version())


def install_crash_handler(show: Callable[[str], None] | None = None) -> None:
    """예상 못한 오류를 기록하고, show가 있으면 사용자에게 알린다."""

    def handle(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("예상 못한 오류\n%s", text)
        if show:
            try:
                show(f"{exc_type.__name__}: {exc}")
            except Exception:  # noqa: BLE001 - 알림 실패가 또 오류를 만들지 않게
                pass

    sys.excepthook = handle
    threading.excepthook = lambda a: handle(a.exc_type, a.exc_value, a.exc_traceback)


def exception(msg: str, exc: BaseException) -> None:
    log.error("%s\n%s", msg, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
