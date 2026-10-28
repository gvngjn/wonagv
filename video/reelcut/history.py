"""실행 취소 / 다시 실행 기록 (프로젝트 상태를 통째로 저장)."""
from __future__ import annotations

import json


class History:
    def __init__(self, limit: int = 100) -> None:
        self.limit = limit
        self._states: list[str] = []
        self._index = -1

    def reset(self, state: dict) -> None:
        self._states = [json.dumps(state, ensure_ascii=False, sort_keys=True)]
        self._index = 0

    def push(self, state: dict) -> bool:
        """현재 상태를 기록. 바로 전과 같으면 무시하고 False."""
        s = json.dumps(state, ensure_ascii=False, sort_keys=True)
        if self._index >= 0 and self._states[self._index] == s:
            return False
        del self._states[self._index + 1:]          # 되돌린 뒤 새로 편집하면 '다시 실행' 기록은 버림
        self._states.append(s)
        if len(self._states) > self.limit:
            del self._states[0]
        self._index = len(self._states) - 1
        return True

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    def undo(self) -> dict | None:
        if not self.can_undo:
            return None
        self._index -= 1
        return json.loads(self._states[self._index])

    def redo(self) -> dict | None:
        if not self.can_redo:
            return None
        self._index += 1
        return json.loads(self._states[self._index])
