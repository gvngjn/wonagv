"""스타1 노래 맞추기 메인 로직 (euddraft 플러그인).

songquiz.py build 가 만든 songquiz.edd 에서 [chatEvent] 다음에 불러온다.

동기화 방식:
  [chatEvent] 와 키보드 입력은 그 사람 PC 에서만 보인다(비동기).
  그래서 그 PC 가 자기 '신호 건물'(기본: 커맨드 센터)을 선택해
  랠리 포인트를 찍는 게임 명령을 보낸다. 게임 명령은 모든 PC 에서 똑같이
  처리되므로, 모든 PC 가 같은 프레임에 랠리 좌표를 보고 판정한다.
    (RALLY_X0 + 라운드번호, ANSWER_Y) : 정답
    (RALLY_X0 + 라운드번호, SKIP_Y)   : 스킵 투표
    (RALLY_X0 + 옵션코드, OPTION_Y)   : 방장 옵션 (대기실에서만)
  라운드 번호가 좌표에 들어가 있어서 지난 라운드 신호는 다시 인식되지 않는다.

기존 노래 맞추기 맵(갈대 오픈소스 계열)처럼:
  시작하면 방장이 옵션(곡 수, 목표 점수)을 정하고, 키를 눌러 스킵 투표를 하며,
  정해진 곡 수가 끝나거나 목표 점수에 먼저 닿은 사람이 우승한다.

중간에 끄기:
  스타에는 재생 중인 소리를 멈추는 기능이 없어서, 곡을 짧은 조각으로 잘라
  이어서 재생한다. 정답/스킵이 나오면 다음 조각을 틀지 않는다.
"""
import json

from eudplib import *

with open(settings["data"], encoding="utf-8") as f:
    DATA = json.load(f)

SONGS = DATA["songs"]
SONG_COUNT = len(SONGS)
CHAT_ADDR = int(DATA.get("chat_addr", "0x58D900"), 0)
SIGNAL_UNIT = DATA.get("signal_unit", "Terran Command Center")
CHUNK_FRAMES = DATA["chunk_frames"]
MAX_CHUNKS = max(len(s["chunks"]) for s in SONGS)

# 가장 빠름 속도 기준 1프레임 = 42ms
FPS = 1000 / 42
HINT_FRAMES = int(DATA["hint_seconds"] * FPS)
GAP_FRAMES = int(DATA["gap_seconds"] * FPS)
EXTRA_FRAMES = int(DATA.get("extra_seconds", 0) * FPS)  # 초성 힌트 후 추가 시간
LOBBY_FRAMES = int(DATA.get("lobby_seconds", 60) * FPS)  # 방장 옵션 대기 (자동 시작)
VICTORY_FRAMES = int(10 * FPS)

DEFAULT_TOTAL = min(DATA.get("default_songs") or SONG_COUNT, SONG_COUNT)
DEFAULT_TARGET = DATA.get("default_target", 0)
SKIP_PERCENT = DATA.get("skip_percent", 100)
SKIP_KEY = DATA.get("skip_key", "P").upper()
OPTION_BASE = DATA["option_base"]
OPTIONS = DATA["options"]  # [{"text", "code", "kind", "value"}]

RALLY_X0 = 64
ANSWER_Y = 64
SKIP_Y = 96
OPTION_Y = 128

# 키 상태 배열 0x596A18 (+가상 키 코드, A~Z 는 아스키와 같음), 채팅 입력 중 플래그 0x68C144
ep_assert(len(SKIP_KEY) == 1 and "A" <= SKIP_KEY <= "Z", "skip_key 는 A~Z 한 글자")
KEY_SKIP = 0x596A18 + ord(SKIP_KEY)
CHAT_TYPING = 0x68C144

CUNIT_OWNER = 0x4C
CUNIT_TYPE = 0x64
CUNIT_RALLY = 0xF8

ST_LOBBY = 0    # 방장 옵션 설정
ST_WAIT = 1     # 다음 곡 대기
ST_GUESS = 2    # 노래 재생 중, 정답 받는 중
ST_END = 3      # 결과 발표 후 승리 대기
ST_DONE = 4

state = EUDVariable(ST_LOBBY)
total = EUDVariable(DEFAULT_TOTAL)    # 이번 판 곡 수
target = EUDVariable(DEFAULT_TARGET)  # 목표 점수 (0 = 없음)
top_score = EUDVariable(0)
host = EUDVariable(8)                 # 방장 = 남아 있는 가장 앞 번호 플레이어
host_last_rally = EUDVariable(0)
cur = EUDVariable(0)          # 현재 곡 번호 (0부터)
chunk = EUDVariable(0)        # 다음에 틀 조각 번호
chunk_at = EUDVariable(0)     # 다음 조각을 틀 게임 틱
next_at = EUDVariable(0)
hint_at = EUDVariable(0)
hint_shown = EUDVariable(0)
overtime = EUDVariable(0)     # 1 = 노래 끝, 초성 힌트 보고 맞히는 추가 시간
signal_ptr = EUDArray(8)
scores = EUDArray(8)
skip_voted = EUDArray(8)
chunk_count = EUDArray([len(s["chunks"]) for s in SONGS])

# 아래는 자기 PC 에서만 쓰는 값 (게임 상태에 영향 X)
local_sent_round = EUDVariable(0xFFFFFFFF)
local_skip_round = EUDVariable(0xFFFFFFFF)
local_key_was_down = EUDVariable(0)
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

    for p in EUDLoopRange(8):
        f_setcurpl(p)
        DoActions(LeaderBoardScore(Custom, "점수"))
    f_setcurpl(P1)

    skip_rule = "전원" if SKIP_PERCENT >= 100 else f"{SKIP_PERCENT}% 이상"
    lines = [
        f"\x1f[노래 맞추기]\x04 총 {SONG_COUNT}곡 수록. 노래 제목을 채팅으로 치세요 (띄어쓰기 상관없음).",
        f"\x07{SKIP_KEY}\x04 = 스킵 투표 ({skip_rule} 동의 시 스킵)",
        "\x1c방장 옵션:\x04 " + " ".join(o["text"] for o in OPTIONS),
        f"\x04{int(LOBBY_FRAMES / FPS)}초 뒤 자동 시작",
    ]
    for line in lines:
        DoActions(DisplayTextAll(line))
    next_at << f_getgametick() + LOBBY_FRAMES


def add_sound_files():
    for song in SONGS:
        for c in song["chunks"]:
            with open(c["file"], "rb") as f:
                MPQAddFile(c["mpq_name"], f.read())


def play_chunk():
    """cur 곡의 chunk 번째 조각을 자기 PC 에서 재생 (소리만 나므로 디싱크 없음)."""
    oldcp = f_getcurpl()
    f_setcurpl(f_getuserplayerid())
    EUDSwitch(cur * MAX_CHUNKS + chunk)
    for i, song in enumerate(SONGS):
        for k, c in enumerate(song["chunks"]):
            if EUDSwitchCase()(i * MAX_CHUNKS + k):
                DoActions(PlayWAV(c["mpq_name"]))
                EUDBreak()
    EUDEndSwitch()
    f_setcurpl(oldcp)


def for_each_song(fn):
    """cur 값에 맞는 곡에 대해 fn(i) 실행."""
    EUDSwitch(cur)
    for i in range(SONG_COUNT):
        if EUDSwitchCase()(i):
            fn(i)
            EUDBreak()
    EUDEndSwitch()


def start_round(now):
    f_printAll("\x1f[{}/{}]\x04 노래 시작! 제목을 채팅으로 치세요.", cur + 1, total)
    chunk << 0
    chunk_at << now
    hint_at << now + HINT_FRAMES
    hint_shown << 0
    overtime << 0
    for p in range(8):
        skip_voted[p] = 0
    state << ST_GUESS


def show_hint(i):
    DoActions(DisplayTextAll(f"\x1c힌트:\x04 가수는 \x11{SONGS[i]['artist']}"))


def show_chosung(i):
    DoActions(DisplayTextAll(
        f"\x08노래 끝!\x04 {EXTRA_FRAMES * 42 // 1000}초 더! "
        f"\x1c초성 힌트:\x04 \x11{SONGS[i]['chosung']}"
    ))


def show_answer(i):
    s = SONGS[i]
    DoActions(DisplayTextAll(f"\x1f정답:\x04 {s['title']} - {s['artist']}"))


def send_rally(x, y):
    me = f_getuserplayerid()
    select_buf[0] = signal_ptr[me]
    QueueGameCommand_Select(1, select_buf)
    QueueGameCommand_RightClick(y * 65536 + RALLY_X0 + x)


def find_host():
    host << 8
    for p in EUDLoopRange(8):
        EUDContinueIf(signal_ptr[p] == 0)
        EUDContinueIf(f_playerexist(p) == 0)
        host << p
        EUDBreak()


def show_options():
    f_printAll("\x1f[옵션]\x04 곡 수 \x07{}\x04 / 목표 점수 \x07{}\x04 (0 = 끝까지)",
               total, target)


def lobby(now):
    """대기실: 방장 채팅 명령으로 옵션 설정. 시간이 지나거나 !시작 이면 시작."""
    old_host = EUDVariable()
    old_host << host
    find_host()
    if EUDIfNot()(host == old_host):
        if EUDIf()(host <= 7):
            f_printAll("\x1c방장:\x07 {}", PName(host))
            host_last_rally << f_dwread(signal_ptr[host] + CUNIT_RALLY)
        EUDEndIf()
    EUDEndIf()

    # 내가 방장이면 옵션 채팅을 신호로 보낸다 (로컬)
    if EUDIf()([host == f_getuserplayerid(), Memory(CHAT_ADDR, AtLeast, OPTION_BASE)]):
        send_rally(f_dwread(CHAT_ADDR) - OPTION_BASE, OPTION_Y)
    EUDEndIf()

    start = EUDVariable()
    start << 0
    if EUDIf()(host <= 7):
        rally = f_dwread(signal_ptr[host] + CUNIT_RALLY)
        if EUDIfNot()(rally == host_last_rally):
            host_last_rally << rally
            code = rally - (OPTION_Y * 65536 + RALLY_X0)
            EUDSwitch(code)
            for o in OPTIONS:
                if EUDSwitchCase()(o["code"]):
                    if o["kind"] == "songs":
                        total << min(o["value"] or SONG_COUNT, SONG_COUNT)
                    elif o["kind"] == "target":
                        target << o["value"]
                    elif o["kind"] == "start":
                        start << 1
                    EUDBreak()
            EUDEndSwitch()
            if EUDIf()(start == 0):
                show_options()
            EUDEndIf()
        EUDEndIf()
    EUDEndIf()

    if EUDIf()(now >= next_at):
        start << 1
    EUDEndIf()
    if EUDIf()(start == 1):
        show_options()
        DoActions(DisplayTextAll("\x1f게임 시작!"))
        next_at << now + GAP_FRAMES
        state << ST_WAIT
    EUDEndIf()


def local_input():
    """내 PC 에서만: 정답 채팅 / P 키를 감지해 신호를 보낸다."""
    me = f_getuserplayerid()
    if EUDIfNot()(signal_ptr[me] == 0):
        # 정답 채팅
        if EUDIf()([
            local_sent_round != cur,
            Memory(CHAT_ADDR, AtLeast, 2),
        ]):
            if EUDIf()(f_dwread(CHAT_ADDR) == cur + 2):
                local_sent_round << cur
                send_rally(cur, ANSWER_Y)
            EUDEndIf()
        EUDEndIf()

        # 스킵 키 (누르는 순간만, 채팅 입력 중이면 무시)
        key_down = EUDVariable()
        key_down << 0
        if EUDIf()([MemoryX(KEY_SKIP, Exactly, 1, 1), Memory(CHAT_TYPING, Exactly, 0)]):
            key_down << 1
        EUDEndIf()
        if EUDIf()([
            key_down == 1,
            local_key_was_down == 0,
            local_skip_round != cur,
            local_sent_round != cur,
        ]):
            local_skip_round << cur
            send_rally(cur, SKIP_Y)
        EUDEndIf()
        local_key_was_down << key_down
    EUDEndIf()


def end_round(now):
    """노래를 끊고 다음 곡 준비."""
    for_each_song(show_answer)
    cur << cur + 1
    game_over = EUDVariable()
    game_over << 0
    if EUDIf()(cur >= total):
        game_over << 1
    EUDEndIf()
    if EUDIf()([target >= 1, top_score >= target]):
        game_over << 1
    EUDEndIf()
    if EUDIf()(game_over == 1):
        state << ST_END
        next_at << now + VICTORY_FRAMES
        show_final()
    if EUDElse()():
        next_at << now + GAP_FRAMES
        state << ST_WAIT
    EUDEndIf()


def check_signals(now):
    """모든 PC 에서 같은 결과: 랠리 좌표로 정답자/스킵 투표 판정."""
    answer_xy = ANSWER_Y * 65536 + RALLY_X0 + cur
    skip_xy = SKIP_Y * 65536 + RALLY_X0 + cur
    winner = EUDVariable()
    active, votes = EUDCreateVariables(2)
    winner << 8
    active << 0
    votes << 0

    for p in EUDLoopRange(8):
        ptr = signal_ptr[p]
        EUDContinueIf(ptr == 0)
        EUDContinueIf(f_playerexist(p) == 0)
        active += 1
        rally = f_dwread(ptr + CUNIT_RALLY)
        if EUDIf()([rally == answer_xy, winner == 8]):
            winner << p
        EUDEndIf()
        if EUDIf()(rally == skip_xy):
            votes += 1
            if EUDIf()(skip_voted[p] == 0):
                skip_voted[p] = 1
                f_printAll("\x07{}\x04 님 스킵 투표", PName(p))
            EUDEndIf()
        EUDEndIf()

    if EUDIf()(winner <= 7):
        scores[winner] += 1
        if EUDIf()(scores[winner] > top_score):
            top_score << scores[winner]
        EUDEndIf()
        oldcp = f_getcurpl()
        f_setcurpl(winner)
        DoActions(SetScore(CurrentPlayer, Add, 1, Custom))
        f_setcurpl(oldcp)
        f_printAll("\x07{} \x04님 정답! (\x07{}점\x04)", PName(winner), scores[winner])
        end_round(now)
    if EUDElseIf()([active >= 1, votes * 100 >= active * SKIP_PERCENT]):
        DoActions(DisplayTextAll("\x08스킵!"))
        end_round(now)
    EUDEndIf()


def show_final():
    best = top_score
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
    add_sound_files()
    now = f_getgametick()

    if EUDIf()(state == ST_LOBBY):
        lobby(now)
    EUDEndIf()

    if EUDIf()([state == ST_END, now >= next_at]):
        state << ST_DONE
        oldcp = f_getcurpl()
        for p in EUDLoopRange(8):
            f_setcurpl(p)
            DoActions(Victory())
        f_setcurpl(oldcp)
    EUDEndIf()

    if EUDIf()(state == ST_WAIT):
        if EUDIf()(now >= next_at):
            start_round(now)
        EUDEndIf()
    EUDEndIf()

    if EUDIf()(state == ST_GUESS):
        local_input()
        check_signals(now)
    EUDEndIf()

    # check_signals 에서 라운드가 끝났을 수 있으니 다시 확인
    if EUDIf()(state == ST_GUESS):
        if EUDIf()([hint_shown == 0, now >= hint_at]):
            hint_shown << 1
            for_each_song(show_hint)
        EUDEndIf()
        if EUDIf()([overtime == 1, now >= next_at]):
            DoActions(DisplayTextAll("\x08시간 초과!"))
            end_round(now)
        if EUDElseIf()([overtime == 0, now >= chunk_at]):
            if EUDIf()(chunk >= chunk_count[cur]):
                if EXTRA_FRAMES > 0:
                    # 노래가 다 끝나면 초성을 보여 주고 조금 더 기다린다
                    for_each_song(show_chosung)
                    overtime << 1
                    next_at << now + EXTRA_FRAMES
                else:
                    DoActions(DisplayTextAll("\x08시간 초과!"))
                    end_round(now)
            if EUDElse()():
                play_chunk()
                chunk << chunk + 1
                chunk_at << chunk_at + CHUNK_FRAMES
            EUDEndIf()
        EUDEndIf()
    EUDEndIf()
