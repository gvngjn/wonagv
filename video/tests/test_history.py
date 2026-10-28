from reelcut.history import History


def test_undo_redo_flow():
    h = History(limit=5)
    h.reset({"v": 0})
    assert not h.can_undo and not h.can_redo
    assert h.push({"v": 1}) and h.push({"v": 2})
    assert not h.push({"v": 2})                     # 같은 상태는 무시
    assert h.undo() == {"v": 1} and h.undo() == {"v": 0} and h.undo() is None
    assert h.redo() == {"v": 1}
    h.push({"v": 9})                                # 되돌린 뒤 새 편집 → redo 기록 삭제
    assert not h.can_redo and h.undo() == {"v": 1}


def test_history_limit():
    h = History(limit=3)
    h.reset({"v": 0})
    for i in range(1, 6):
        h.push({"v": i})
    assert h.undo() == {"v": 4} and h.undo() == {"v": 3} and h.undo() is None
