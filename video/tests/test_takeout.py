import json
import zipfile

import pytest

from reelcut.takeout import TakeoutError, clean_title, load_history, parse_entries, songs_csv, video_id


def entry(title, vid, when, music=True, channel="IU", ad=False, url=None):
    e = {"header": "YouTube Music" if music else "YouTube", "title": title,
         "titleUrl": url or (f"https://music.youtube.com/watch?v={vid}" if music
                             else f"https://www.youtube.com/watch?v={vid}"),
         "subtitles": [{"name": channel, "url": "https://www.youtube.com/channel/x"}],
         "time": when, "products": ["YouTube"]}
    if ad:
        e["details"] = [{"name": "From Google Ads"}]
    return e


RAW = [
    entry("Love wins all 을(를) 시청했습니다.", "aaa", "2026-03-01T10:00:00.000Z", channel="IU - 주제"),
    entry("Love wins all 을(를) 시청했습니다.", "aaa", "2026-05-01T10:00:00.000Z", channel="IU - 주제"),
    entry("Watched Supernova", "bbb", "2026-06-01T10:00:00Z", channel="aespa - Topic"),
    entry("Watched Supernova", "bbb", "2026-06-02T10:00:00Z", channel="aespa - Topic"),
    entry("Watched Supernova", "bbb", "2026-06-03T10:00:00Z", channel="aespa - Topic"),
    entry("Watched Old song", "ccc", "2025-12-31T10:00:00Z"),
    entry("Watched 요리 브이로그", "ddd", "2026-02-01T10:00:00Z", music=False, channel="쿡방"),
    entry("Watched NewJeans (뉴진스) 'How Sweet' Official MV", "eee", "2026-07-01T10:00:00Z", music=False,
          channel="HYBE LABELS"),
    entry("Watched 광고", "fff", "2026-07-01T10:00:00Z", ad=True),
    {"header": "YouTube", "title": "Watched a video that has been removed", "time": "2026-01-01T00:00:00Z"},
    {"header": "YouTube", "title": "Searched for iu", "titleUrl": "https://www.youtube.com/results?search_query=iu",
     "time": "2026-01-01T00:00:00Z"},
]


def test_titles_and_ids():
    assert clean_title("Love wins all 을(를) 시청했습니다.") == "Love wins all"
    assert clean_title("Watched Supernova") == "Supernova"
    assert clean_title("夜に駆ける を視聴しました") == "夜に駆ける"
    assert video_id("https://music.youtube.com/watch?v=abc&list=x") == "abc"
    assert video_id("https://youtu.be/xyz") == "xyz" and video_id("https://www.youtube.com/results?q=1") == ""


def test_top_songs_of_a_year():
    h = parse_entries(RAW)
    assert h.years() == [2026, 2025]
    top = h.top_songs(2026)
    assert [(s.title, s.artist, s.plays) for s in top] == [("Supernova", "aespa", 3), ("Love wins all", "IU", 2)]
    assert top[0].url == "https://music.youtube.com/watch?v=bbb"
    # 음악으로 보이는 YouTube 영상(뮤직비디오)도 포함, 요리 브이로그·광고는 제외
    titles = [s.title for s in h.top_songs(2026, include_youtube=True)]
    assert "NewJeans (뉴진스) 'How Sweet' Official MV" in titles and "요리 브이로그" not in titles
    assert "광고" not in titles
    assert [s.title for s in h.top_songs(2025)] == ["Old song"]
    csv = songs_csv(top)
    assert csv.startswith("﻿순위,제목") and "1,Supernova,aespa,3,2026-06-01,2026-06-03" in csv


def test_load_json_zip_and_errors(tmp_path):
    js = tmp_path / "시청 기록.json"
    js.write_text(json.dumps(RAW, ensure_ascii=False), encoding="utf-8")
    assert load_history(js).top_songs(2026)[0].title == "Supernova"
    z = tmp_path / "takeout.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Takeout/YouTube 및 YouTube Music/기록/시청 기록.json", json.dumps(RAW))
    assert len(load_history(z).top_songs(2026)) == 2
    html = tmp_path / "html.zip"
    with zipfile.ZipFile(html, "w") as f:
        f.writestr("Takeout/YouTube and YouTube Music/history/watch-history.html", "<html></html>")
    with pytest.raises(TakeoutError, match="JSON"):
        load_history(html)
    with pytest.raises(TakeoutError):
        parse_entries([])
