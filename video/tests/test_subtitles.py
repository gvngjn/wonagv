import pytest

from reelcut import subtitles as subs
from reelcut.project import SubtitleEntry


def test_timestamp_roundtrip():
    assert subs.format_ts(3723.5) == "01:02:03,500"
    assert subs.parse_ts("01:02:03,500") == pytest.approx(3723.5)
    assert subs.parse_ts("02:03.25") == pytest.approx(123.25)
    with pytest.raises(ValueError):
        subs.parse_ts("abc")


def test_srt_roundtrip(tmp_path):
    entries = [SubtitleEntry(2.0, 3.5, "둘째"), SubtitleEntry(0.0, 1.25, "첫째\n두 줄")]
    path = tmp_path / "a.srt"
    subs.save_srt(path, entries)
    loaded = subs.load_srt(path)
    assert [(e.start, e.end, e.text) for e in loaded] == [(0.0, 1.25, "첫째\n두 줄"), (2.0, 3.5, "둘째")]


def test_parse_srt_tolerates_cp949_and_missing_numbers(tmp_path):
    path = tmp_path / "b.srt"
    path.write_bytes("00:00:01,000 --> 00:00:02,000\n안녕\n".encode("cp949"))
    assert subs.load_srt(path)[0].text == "안녕"


def test_wrap_line():
    assert subs.wrap_line("짧은 문장") == "짧은 문장"
    long = "오늘은 날씨가 정말 좋아서 공원에 산책을 나가 보기로 했어요"
    wrapped = subs.wrap_line(long)
    assert "\n" in wrapped and wrapped.replace("\n", " ") == long


def test_transcribe_uses_whisper_segments(monkeypatch):
    """실제 모델 대신 가짜 WhisperModel로 변환 흐름만 확인."""
    import sys
    import types

    import numpy as np

    class Seg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text = s, e, t

    class FakeModel:
        def __init__(self, name, **kw):
            self.name = name

        def transcribe(self, audio, language=None, **kw):
            assert language == "ko"
            return iter([Seg(0.0, 1.2, " 안녕하세요 "), Seg(1.5, 2.0, "  "), Seg(2.0, 3.0, "반가워요")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    progress = []
    out = subs.transcribe(np.zeros(16000 * 3, np.float32), "tiny", "ko", on_progress=progress.append)
    assert [(e.start, e.end, e.text) for e in out] == [(0.0, 1.2, "안녕하세요"), (2.0, 3.0, "반가워요")]
    assert progress[-1] == 1.0
