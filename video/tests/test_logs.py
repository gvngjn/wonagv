import logging


def test_logs_written(tmp_path, monkeypatch):
    import reelcut.logs as logs

    monkeypatch.setenv("REELCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(logs, "_installed", False)
    logger = logging.getLogger("reelcut")
    before = list(logger.handlers)
    try:
        logs.setup("test")
        try:
            raise ValueError("일부러 낸 오류")
        except ValueError as e:
            logs.exception("테스트", e)
        shown = []
        logs.install_crash_handler(shown.append)
        import sys
        try:
            raise RuntimeError("잡히지 않은 오류")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        for h in logger.handlers:
            h.flush()
        text = logs.log_file().read_text(encoding="utf-8")
        assert "ReelCut test 시작" in text and "일부러 낸 오류" in text and "잡히지 않은 오류" in text
        assert shown == ["RuntimeError: 잡히지 않은 오류"]
    finally:
        import sys
        import threading
        sys.excepthook = sys.__excepthook__
        threading.excepthook = threading.__excepthook__
        for h in list(logger.handlers):
            if h not in before:
                logger.removeHandler(h)
                h.close()
