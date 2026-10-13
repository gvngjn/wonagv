"""스타1 노래 맞추기 메인 로직 (euddraft 플러그인).

songquiz.py build 가 만든 songquiz.edd 에서 [chatEvent] 다음에 불러온다.

동기화 방식:
  [chatEvent] 는 채팅을 친 사람 PC 에서만 값을 바꾼다(비동기).
  그래서 정답을 친 플레이어의 PC 가 자기 '신호 건물'(기본: 커맨드 센터)을
  선택해 랠리 포인트를 (RALLY_X0 + 라운드번호, RALLY_Y) 로 찍는 게임 명령을
  보낸다. 게임 명령은 모든 PC 에서 똑같이 처리되므로, 모든 PC 가 같은 프레임에
  랠리 좌표를 보고 정답자를 판정한다. 라운드 번호가 좌표에 들어가 있어서
  지난 라운드 신호는 다시 인식되지 않는다.
"""
import json

from eudplib import *

with open(settings["data"], encoding="utf-8") as f:
    DATA = json.load(f)

SONGS = DATA["songs"]
SONG_COUNT = len(SONGS)
CHAT_ADDR = int(DATA.get("chat_addr", "0x58D900"), 0)
SIGNAL_UNIT = DATA.get("signal_unit", "Terran Command Center")

# 가장 빠름 속도 기준 1프레임 = 42ms
FPS = 1000 / 42
CLIP_FRAMES = int(DATA["clip_seconds"] * FPS)
HINT_FRAMES = int(DATA["hint_seconds"] * FPS)
GAP_FRAMES = int(DATA["gap_seconds"] * FPS)
START_DELAY_FRAMES = int(5 * FPS)

RALLY_X0 = 64
RALLY_Y = 64

CUNIT_OWNER = 0x4C
CUNIT_TYPE = 0x64
CUNIT_RALLY = 0xF8

ST_WAIT = 0     # 다음 곡 대기
ST_GUESS = 1    # 노래 재생 중, 정답 받는 중
ST_REVEAL = 2   # 정답 공개, 남은 노래 재생 중
ST_END = 3

state = EUDVariable(ST_WAIT)
cur = EUDVariable(0)          # 현재 곡 번호 (0부터)
next_at = EUDVariable(0)      # 다음 상태로 넘어갈 게임 틱
hint_at = EUDVariable(0)
hint_shown = EUDVariable(0)
signal_ptr = EUDArray(8)
scores = EUDArray(8)

# 아래 둘은 자기 PC 에서만 쓰는 값 (게임 상태에 영향 X)
local_sent_round = EUDVariable(0xFFFFFFFF)
select_buf = EUDArray(1)


def onPluginStart():
    signal_type = EncodeUnit(SIGNAL_UNIT)
    for ptr, epd in EUDLoopUnit2():
        if EUDIf()(f_wread(ptr + CUNIT_TYPE) == signal_type):
            owner = f_bread(ptr + CUNIT_OWNER)
            if EUDIf()([owner <= 7, signal_ptr[owner] == 0]):
                signal_ptr[owner] = ptr
            EUDEndIf()
        EUDEndIf()

    DoActions(DisplayTextAll(
        f"\x1f[노래 맞추기]\x04 총 {SONG_COUNT}곡! 노래 제목을 채팅으로 치세요."
    ))
    next_at << f_getgametick() + START_DELAY_FRAMES


def play_song(i):
    """곡 i 를 모든 플레이어에게 재생 (i 는 파이썬 상수)."""
    song = SONGS[i]
    with open(song["file"], "rb") as f:
        MPQAddFile(song["mpq_name"], f.read())
    oldcp = f_getcurpl()
    for p in EUDLoopRange(8):
        f_setcurpl(p)
        DoActions(PlayWAV(song["mpq_name"]))
    f_setcurpl(oldcp)


def for_each_song(fn):
    """cur 값에 맞는 곡에 대해 fn(i) 실행."""
    for i in range(SONG_COUNT):
        if EUDIf()(cur == i):
            fn(i)
        EUDEndIf()


def start_round():
    for_each_song(play_song)
    f_printAll("\x1f[{}/{}]\x04 노래 시작! 제목을 채팅으로 치세요.", cur + 1, SONG_COUNT)
    now = f_getgametick()
    next_at << now + CLIP_FRAMES
    hint_at << now + HINT_FRAMES
    hint_shown << 0
    state << ST_GUESS


def show_hint(i):
    DoActions(DisplayTextAll(f"\x1c힌트:\x04 가수는 \x11{SONGS[i]['artist']}"))


def show_answer(i):
    s = SONGS[i]
    DoActions(DisplayTextAll(f"\x1f정답:\x04 {s['title']} - {s['artist']}"))


def send_signal_if_correct():
    """내가 친 채팅이 현재 곡 정답이면 신호 건물 랠리 명령을 보낸다 (로컬)."""
    me = f_getuserplayerid()
    ptr = signal_ptr[me]
    if EUDIf()([
        ptr != 0,
        local_sent_round != cur,
        Memory(CHAT_ADDR, AtLeast, 2),
    ]):
        if EUDIf()(f_dwread(CHAT_ADDR) == cur + 2):
            local_sent_round << cur
            select_buf[0] = ptr
            QueueGameCommand_Select(1, select_buf)
            QueueGameCommand_RightClick(RALLY_Y * 65536 + RALLY_X0 + cur)
        EUDEndIf()
    EUDEndIf()


def check_signals():
    """모든 PC 에서 같은 결과: 랠리 좌표로 정답자 판정."""
    expected = RALLY_Y * 65536 + RALLY_X0 + cur
    for p in EUDLoopRange(8):
        ptr = signal_ptr[p]
        EUDContinueIf(ptr == 0)
        if EUDIf()(f_dwread(ptr + CUNIT_RALLY) == expected):
            scores[p] += 1
            oldcp = f_getcurpl()
            f_setcurpl(p)
            DoActions(SetScore(CurrentPlayer, Add, 1, Custom))
            f_setcurpl(oldcp)
            f_printAll("\x07{} \x04님 정답! (\x07{}점\x04)", PName(p), scores[p])
            for_each_song(show_answer)
            state << ST_REVEAL
            EUDBreak()
        EUDEndIf()


def finish_round():
    cur << cur + 1
    if EUDIf()(cur >= SONG_COUNT):
        state << ST_END
        show_final()
    if EUDElse()():
        next_at << f_getgametick() + GAP_FRAMES
        state << ST_WAIT
    EUDEndIf()


def show_final():
    best = EUDVariable(0)
    for p in EUDLoopRange(8):
        if EUDIf()(scores[p] > best):
            best << scores[p]
        EUDEndIf()
    DoActions(DisplayTextAll("\x1f[노래 맞추기] 게임 끝!"))
    if EUDIf()(best == 0):
        DoActions(DisplayTextAll("\x04아무도 못 맞췄어요..."))
    if EUDElse()():
        for p in EUDLoopRange(8):
            if EUDIf()([signal_ptr[p] != 0, scores[p] == best]):
                f_printAll("\x11우승: \x07{} \x04({}점)", PName(p), best)
            EUDEndIf()
        EUDEndIf()


def beforeTriggerExec():
    now = f_getgametick()

    if EUDIf()(state == ST_WAIT):
        if EUDIf()(now >= next_at):
            start_round()
        EUDEndIf()

    if EUDElseIf()(state == ST_GUESS):
        send_signal_if_correct()
        check_signals()
        if EUDIf()(state == ST_GUESS):
            if EUDIf()([hint_shown == 0, now >= hint_at]):
                hint_shown << 1
                for_each_song(show_hint)
            EUDEndIf()
            if EUDIf()(now >= next_at):
                DoActions(DisplayTextAll("\x08시간 초과!"))
                for_each_song(show_answer)
                finish_round()
            EUDEndIf()
        EUDEndIf()

    if EUDElseIf()(state == ST_REVEAL):
        # 노래를 중간에 끌 수 없으니 클립이 끝날 때까지 기다린 뒤 다음 곡
        if EUDIf()(now >= next_at):
            finish_round()
        EUDEndIf()
    EUDEndIf()
