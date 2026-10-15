"""설정 파일(TOML) 읽기.

수수료·세금처럼 바뀌는 값은 코드에 박지 않고 설정 파일에서만 관리한다.
[costs] 항목은 하나라도 빠지면 오류를 낸다 (조용히 기본값으로 돌지 않게).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from datetime import date, time
from pathlib import Path
from typing import Any

from .costs import CostModel
from .orders import OrderSettings
from .risk import RiskManager
from .strategy import TrendBreakoutStrategy

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "trendbot.example.toml"
HOME_DIR = Path.home() / ".trendbot"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Schedule:
    run_start: time = time(8, 30)
    run_end: time = time(8, 59)
    holidays: frozenset[date] = frozenset()


@dataclass(frozen=True)
class Settings:
    costs: CostModel
    risk: RiskManager = field(default_factory=RiskManager)
    strategy: TrendBreakoutStrategy = field(default_factory=TrendBreakoutStrategy)
    order: OrderSettings = field(default_factory=OrderSettings)
    schedule: Schedule = field(default_factory=Schedule)
    symbols: tuple[str, ...] = ()
    cache_dir: Path = HOME_DIR / "cache"
    state_path: Path = HOME_DIR / "state.json"
    source: Path | None = None


def _build(cls, section: dict[str, Any], name: str, *, required: bool = False):
    known = {f.name: f for f in fields(cls)}
    unknown = set(section) - set(known)
    if unknown:
        raise ConfigError(f"[{name}] 에 모르는 항목: {', '.join(sorted(unknown))}")
    if required:
        missing = [n for n in known if n not in section]
        if missing:
            raise ConfigError(f"[{name}] 에 빠진 항목: {', '.join(missing)}")
    kwargs = {}
    for key, value in section.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"[{name}] {key} 는 숫자여야 합니다")
        expected = known[key].type
        kwargs[key] = int(value) if expected in ("int", int) else float(value)
    return cls(**kwargs)


def _parse_time(value: Any, key: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError as e:
        raise ConfigError(f"[schedule] {key} 는 '08:30' 형식이어야 합니다") from e


def load_settings(path: str | Path) -> Settings:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"설정 파일이 없습니다: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"설정 파일 형식 오류 ({path}): {e}") from e

    if "costs" not in raw:
        raise ConfigError("[costs] 항목이 없습니다. 수수료·세금은 설정 파일에 꼭 적어야 합니다")
    sched = raw.get("schedule", {})
    try:
        holidays = frozenset(date.fromisoformat(str(d)) for d in sched.get("holidays", []))
    except ValueError as e:
        raise ConfigError("[schedule] holidays 는 '2026-12-25' 형식의 목록이어야 합니다") from e
    paths = raw.get("paths", {})
    return Settings(
        costs=_build(CostModel, raw["costs"], "costs", required=True),
        risk=_build(RiskManager, raw.get("risk", {}), "risk"),
        strategy=_build(TrendBreakoutStrategy, raw.get("strategy", {}), "strategy"),
        order=_build(OrderSettings, raw.get("order", {}), "order"),
        schedule=Schedule(
            run_start=_parse_time(sched.get("run_start", "08:30"), "run_start"),
            run_end=_parse_time(sched.get("run_end", "08:59"), "run_end"),
            holidays=holidays,
        ),
        symbols=tuple(str(s) for s in raw.get("universe", {}).get("symbols", [])),
        cache_dir=Path(paths.get("cache_dir", HOME_DIR / "cache")).expanduser(),
        state_path=Path(paths.get("state_path", HOME_DIR / "state.json")).expanduser(),
        source=path,
    )


def resolve_config(arg: str | None, *, allow_example: bool) -> Path:
    """--config 가 없으면 ./trendbot.toml → ~/.trendbot/config.toml → (허용 시) 예시 파일 순서로 찾는다."""
    if arg:
        return Path(arg)
    for candidate in (Path("trendbot.toml"), HOME_DIR / "config.toml"):
        if candidate.exists():
            return candidate
    if allow_example:
        return EXAMPLE_PATH
    raise ConfigError(
        "설정 파일이 없습니다. trendbot.example.toml 을 trendbot.toml 로 복사하고 "
        "수수료·세금을 내 계좌 기준으로 고친 뒤 다시 실행하세요"
    )
