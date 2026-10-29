"""Google 테이크아웃 YouTube 시청 기록에서 '그해 들은 노래' 뽑기.

파일(시청 기록.json / watch-history.json, 또는 테이크아웃 zip)은 이 컴퓨터에서만 읽는다.
"""
from __future__ import annotations

import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ffmpeg import parse_time


class TakeoutError(ValueError):
    pass


@dataclass
class Song:
    video_id: str
    title: str
    artist: str
    url: str
    plays: int = 0
    first: float = 0.0             # 그 기간에 처음 들은 시각
    last: float = 0.0              # 마지막으로 들은 시각
    from_music: bool = True        # YouTube Music에서 들었는지 (아니면 YouTube 영상)


@dataclass
class History:
    entries: list[dict] = field(default_factory=list)   # 정리한 기록 (시간순 아님)

    def years(self) -> list[int]:
        return sorted({time.localtime(e["time"]).tm_year for e in self.entries}, reverse=True)

    def top_songs(self, year: int | None = None, include_youtube: bool = False) -> list[Song]:
        """많이 들은 순 (같으면 최근에 들은 순). include_youtube: 음악으로 보이는 YouTube 영상도."""
        songs: dict[str, Song] = {}
        for e in self.entries:
            if year and time.localtime(e["time"]).tm_year != year:
                continue
            if not e["music"] and not (include_youtube and e["musicish"]):
                continue
            s = songs.get(e["id"])
            if s is None:
                s = songs[e["id"]] = Song(e["id"], e["title"], e["artist"], e["url"], first=e["time"],
                                          from_music=e["music"])
            s.plays += 1
            s.first = min(s.first, e["time"])
            s.last = max(s.last, e["time"])
            s.from_music = s.from_music or e["music"]
        return sorted(songs.values(), key=lambda s: (-s.plays, -s.last))


# "Watched ○○" / "○○ 을(를) 시청했습니다." / "○○ を視聴しました" 같은 앞뒤 문구 떼기
_TITLE_PATTERNS = [
    re.compile(r"^Watched\s+(.*)$", re.S),
    re.compile(r"^(.*?)\s*을\(를\)\s*시청했습니다\.?$", re.S),
    re.compile(r"^(.*?)\s*시청함$", re.S),
    re.compile(r"^(.*?)\s*を視聴しました$", re.S),
]
_ARTIST_SUFFIX = re.compile(r"\s*-\s*(Topic|주제|トピック)\s*$")
_MUSICISH = re.compile(r"(\s-\s(Topic|주제|トピック)$|VEVO$|Official\s*(Music\s*)?(Video|Audio|MV)|"
                       r"\bM/?V\b|뮤직비디오|Lyrics?|가사|\bAudio\b)", re.I)


def clean_title(text: str) -> str:
    text = (text or "").strip()
    for p in _TITLE_PATTERNS:
        m = p.match(text)
        if m:
            return m.group(1).strip()
    return text


def video_id(url: str) -> str:
    try:
        u = urlparse(url)
    except ValueError:
        return ""
    if u.hostname and u.hostname.endswith("youtu.be"):
        return u.path.lstrip("/")
    return (parse_qs(u.query).get("v") or [""])[0]


def parse_entries(raw: list) -> History:
    """테이크아웃 JSON 목록 → 정리한 기록. 광고·삭제된 영상·영상 아닌 활동은 뺀다."""
    if not isinstance(raw, list):
        raise TakeoutError("시청 기록 파일 형식이 아니에요.")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("titleUrl") or ""
        vid = video_id(url)
        if not vid:
            continue                                     # 삭제된 영상, 검색 기록 등
        if any("Google Ads" in (d.get("name") or "") or "광고" in (d.get("name") or "")
               for d in item.get("details") or []):
            continue                                     # 광고로 본 영상
        t = parse_time(item.get("time", ""))
        if not t:
            continue
        subs = item.get("subtitles") or []
        channel = (subs[0].get("name") or "") if subs else ""
        title = clean_title(item.get("title", ""))
        music = item.get("header") == "YouTube Music" or "music.youtube.com" in url
        out.append({
            "id": vid, "time": t, "title": title, "artist": _ARTIST_SUFFIX.sub("", channel),
            "url": f"https://music.youtube.com/watch?v={vid}" if music else f"https://www.youtube.com/watch?v={vid}",
            "music": music,
            "musicish": music or bool(_MUSICISH.search(channel) or _MUSICISH.search(title)),
        })
    if not out:
        raise TakeoutError("시청 기록이 비어 있어요. YouTube 기록 저장이 꺼져 있었는지 확인해 주세요.")
    return History(out)


def _is_history_name(name: str) -> bool:
    n = Path(name).name.lower()
    return n.endswith(".json") and ("watch-history" in n or "시청 기록" in n or "視聴履歴" in n)


def load_history(path: str | Path) -> History:
    """시청 기록 JSON 또는 테이크아웃 zip을 읽는다."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if _is_history_name(n)]
            if not names:
                if any(Path(n).name.lower().endswith((".html", ".htm")) and ("기록" in n or "history" in n.lower())
                       for n in z.namelist()):
                    raise TakeoutError(_HTML_HELP)
                raise TakeoutError("zip 안에 시청 기록 파일이 없어요. 테이크아웃에서 'YouTube 및 YouTube Music → 기록'을 "
                                   "골랐는지 확인해 주세요.")
            with z.open(names[0]) as f:
                return parse_entries(json.load(f))
    if path.suffix.lower() in (".html", ".htm"):
        raise TakeoutError(_HTML_HELP)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise TakeoutError(f"JSON 파일을 읽을 수 없어요: {e}") from e
    return parse_entries(raw)


_HTML_HELP = ("기록이 HTML 형식이에요. 테이크아웃에서 'YouTube 및 YouTube Music' → '여러 형식' → "
              "기록을 JSON으로 바꿔서 다시 내보내 주세요.")


def songs_csv(songs: list[Song]) -> str:
    """순위·제목·아티스트·재생 수·처음/마지막으로 들은 날·링크 (엑셀에서 열리게 BOM 포함)."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["순위", "제목", "아티스트", "재생 수", "처음 들은 날", "마지막으로 들은 날", "링크"])
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t))
    for i, s in enumerate(songs, 1):
        w.writerow([i, s.title, s.artist, s.plays, day(s.first), day(s.last), s.url])
    return "﻿" + buf.getvalue()
