import functools
import http.server
import threading

import numpy as np
import pytest
from conftest import needs_ffmpeg

from reelcut import download
from reelcut.beats import waveform_peaks


def test_url_helpers():
    assert download.is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert download.is_youtube_url("https://www.youtube.com/shorts/abc123")
    assert download.is_youtube_url("https://music.youtube.com/watch?v=abc123")
    assert not download.is_youtube_url("https://example.com/watch?v=1")
    assert download.clean_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&t=30s") == \
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert download.is_url(" https://youtu.be/x ") and not download.is_url("노래 제목")


def test_rejects_non_url(tmp_path):
    pytest.importorskip("yt_dlp")
    with pytest.raises(ValueError):
        download.download_audio("그냥 글자", tmp_path)


def test_waveform_peaks():
    y = np.concatenate([np.zeros(1000), np.ones(1000) * 0.5]).astype(np.float32)
    p = waveform_peaks(y, 10)
    assert len(p) == 10 and p[:5].max() == 0 and p[5:].min() == pytest.approx(1.0)
    assert len(waveform_peaks(np.zeros(0, np.float32))) == 0


@needs_ffmpeg
def test_download_extracts_mp3_from_link(media, tmp_path):
    """yt-dlp 실제 흐름: 링크 → 내려받기 → mp3 변환 (인터넷 대신 로컬 서버 사용)."""
    pytest.importorskip("yt_dlp")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(media))
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/a.mp4"
        progress = []
        r = download.download_audio(url, tmp_path / "music", on_progress=lambda f, m: progress.append(f))
    finally:
        server.shutdown()
    from reelcut.ffmpeg import probe
    assert r.path.endswith(".mp3")
    info = probe(r.path)
    assert info.has_audio and info.duration == pytest.approx(4.0, abs=0.2)
    assert progress[-1] == 1.0
