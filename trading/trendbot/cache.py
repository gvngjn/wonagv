"""일봉 디스크 캐시. 이미 받은 날짜는 다시 요청하지 않는다.

수정주가는 액면분할·증자 때 과거 값이 바뀌므로, 새로 받은 겹치는 구간이
캐시와 다르면 그 종목은 처음부터 다시 받는다.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from datetime import date, timedelta
from pathlib import Path

from .data import load_csv, write_csv
from .models import Bar

OVERLAP_DAYS = 10
MISMATCH_TOLERANCE = 0.001

Fetcher = Callable[[str, date, date], list[Bar]]


class BarCache:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, symbol: str) -> Path:
        return self.directory / f"{symbol}.csv"

    def load(self, symbol: str) -> list[Bar]:
        try:
            return load_csv(self._path(symbol))
        except FileNotFoundError:
            return []

    def _meta_path(self, symbol: str) -> Path:
        return self.directory / f"{symbol}.meta.json"

    def _covered_from(self, symbol: str) -> date | None:
        """이 캐시가 어느 날짜부터 요청해서 받은 것인지 (상장일이 늦은 종목도 다시 받지 않게)."""
        try:
            return date.fromisoformat(json.loads(self._meta_path(symbol).read_text())["requested_from"])
        except (OSError, ValueError, KeyError):
            return None

    def get(self, symbol: str, start: date, last_session: date, fetch: Fetcher) -> list[Bar]:
        """start ~ last_session 일봉. last_session 이후(아직 확정 안 된) 봉은 저장하지 않는다."""
        cached = self.load(symbol)
        covered_from = self._covered_from(symbol)
        covers_start = bool(cached) and covered_from is not None and covered_from <= start
        if covers_start and cached[-1].day >= last_session:
            return [b for b in cached if start <= b.day <= last_session]

        requested_from = start
        if covers_start:
            fresh = fetch(symbol, cached[-1].day - timedelta(days=OVERLAP_DAYS), last_session)
            if self._consistent(cached, fresh):
                merged = {b.day: b for b in cached}
                merged.update({b.day: b for b in fresh})
                bars = [merged[d] for d in sorted(merged)]
                requested_from = covered_from
            else:
                bars = fetch(symbol, start, last_session)
        else:
            bars = fetch(symbol, start, last_session)

        bars = [b for b in bars if b.day <= last_session]
        if bars:
            self.directory.mkdir(parents=True, exist_ok=True)
            write_csv(self._path(symbol), bars)
            self._meta_path(symbol).write_text(json.dumps({"requested_from": requested_from.isoformat()}))
        return [b for b in bars if b.day >= start]

    @staticmethod
    def _consistent(cached: list[Bar], fresh: list[Bar]) -> bool:
        old = {b.day: b.close for b in cached}
        for b in fresh:
            prev = old.get(b.day)
            if prev and abs(b.close / prev - 1) > MISMATCH_TOLERANCE:
                return False
        return True
