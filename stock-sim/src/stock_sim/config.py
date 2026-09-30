"""설정 로드·검증, 경로 해석, .env 탐색, 자격 증명 읽기 (architecture.md 1.1절, 3절)."""
from __future__ import annotations

import copy
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from stock_sim import strategy

log = logging.getLogger(__name__)

ENV_FILE_VAR = "STOCK_SIM_ENV_FILE"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ConfigError(Exception):
    """설정 오류. 종료 코드 1."""


DEFAULTS: dict = {
    "kis": {"env": "DEV", "prod_approved_by_user": False, "min_interval_sec": 0.5,
            "max_retries": 3, "backoff_sec": 2.0, "timeout_sec": 10},
    "universe": [{"code": "005930", "name": "삼성전자"}, {"code": "000660", "name": "SK하이닉스"}],
    "benchmark": {"code": "0001", "name": "KOSPI"},
    "data": {"minute_time_label": "start", "minute_start_hour": "160000", "minute_max_pages": 6},
    "session": {"open": "09:00", "continuous_end": "15:20"},
    "backtest": {"end": "2026-09-29", "days": 30, "initial_cash": 100_000_000},
    "strategy": {
        "name": "intraday_breakout", "bar_minutes": 5, "entry_lookback": 6, "exit_lookback": 3,
        "vol_mult": 1.5, "min_range_pct": 0.005, "entry_cutoff": "14:50",
        "force_exit_time": "15:15", "cooldown_bars": 3, "max_entries_per_symbol_per_day": 4,
        "daily_loss_limit_pct": 0.01, "position_pct": 0.5, "min_bars_per_day": 60,
    },
    "costs": {"buy_rate": 0.00015, "sell_rate": 0.00215, "slippage_rate": 0.0},
    "target": {"monthly_return": 0.02},
    "output": {"result": "output/result.json", "dashboard": "output/dashboard.html",
               "template": "templates/dashboard.html.j2", "cache_dir": "data/cache"},
}

# v1 키: 있으면 옛 설정으로 돌린 줄 알게 되므로 조용히 무시하지 않고 거부한다(3.1절).
_V1_TOP = ("capital", "max_positions", "target_return")
_V1_STRATEGY = ("params", "lookback_days", "top_n", "rebalance")
_V1_BACKTEST = ("months", "warmup_days")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _reject_v1_keys(raw: dict) -> None:
    found = [k for k in _V1_TOP if k in raw]
    st, bt, costs = raw.get("strategy"), raw.get("backtest"), raw.get("costs")
    if isinstance(st, dict):
        found += [f"strategy.{k}" for k in _V1_STRATEGY if k in st]
    if isinstance(bt, dict):
        found += [f"backtest.{k}" for k in _V1_BACKTEST if k in bt]
    if isinstance(costs, dict):
        found += [f"costs.{k}" for k in costs if str(k).endswith("_pct")]
    if found:
        raise ConfigError("v1 설정 키는 v2에서 쓰지 않습니다: " + ", ".join(found)
                          + ". architecture.md 3절의 v2 스키마로 바꾸세요.")


def _validate(cfg: dict) -> None:
    kis = cfg["kis"]
    if kis.get("env") not in ("DEV", "PROD"):
        raise ConfigError(f"kis.env는 DEV 또는 PROD여야 합니다(현재: {kis.get('env')!r}).")
    if kis["env"] == "PROD" and kis.get("prod_approved_by_user") is not True:
        raise ConfigError(
            "kis.env가 PROD인데 kis.prod_approved_by_user가 true가 아닙니다. "
            "PROD 키는 사용자가 명시적으로 허용한 경우에만 시세 조회(read-only)에 씁니다(CLAUDE.md R3).")
    uni = cfg["universe"]
    if not isinstance(uni, list) or len(uni) < 1:
        raise ConfigError("universe에는 종목이 1개 이상 있어야 합니다.")
    seen: set[str] = set()
    for item in uni:
        code = item.get("code") if isinstance(item, dict) else None
        if not (isinstance(code, str) and len(code) == 6 and code.isalnum()):
            raise ConfigError(f"universe의 종목 코드는 따옴표로 감싼 6자리 문자열이어야 합니다: {code!r}")
        if code in seen:
            raise ConfigError(f"universe에 중복된 종목 코드가 있습니다: {code}")
        seen.add(code)
        if not item.get("name"):
            raise ConfigError(f"universe의 {code}에 name이 없습니다.")
    st = cfg["strategy"]
    if st.get("name") not in strategy.STRATEGIES:
        raise ConfigError(f"strategy.name이 등록된 전략이 아닙니다: {st.get('name')!r}")
    for key in ("bar_minutes", "entry_lookback", "exit_lookback"):
        if not _is_int(st.get(key)) or st[key] < 1:
            raise ConfigError(f"strategy.{key}는 1 이상의 정수여야 합니다.")
    for key in ("cooldown_bars", "max_entries_per_symbol_per_day", "min_bars_per_day"):
        if not _is_int(st.get(key)) or st[key] < 0:
            raise ConfigError(f"strategy.{key}는 0 이상의 정수여야 합니다.")
    for key in ("vol_mult", "min_range_pct", "daily_loss_limit_pct"):
        if not _is_number(st.get(key)) or st[key] < 0:
            raise ConfigError(f"strategy.{key}는 0 이상의 수여야 합니다.")
    pp = st.get("position_pct")
    if not _is_number(pp) or not 0 < pp <= 1:
        raise ConfigError("strategy.position_pct는 0보다 크고 1 이하여야 합니다.")
    if pp * len(uni) > 1 + 1e-12:
        raise ConfigError("strategy.position_pct × 종목 수가 1을 넘습니다(현금이 모자랄 수 있음).")
    times = {"session.open": cfg["session"].get("open"),
             "strategy.entry_cutoff": st.get("entry_cutoff"),
             "strategy.force_exit_time": st.get("force_exit_time"),
             "session.continuous_end": cfg["session"].get("continuous_end")}
    for key, value in times.items():
        if not (isinstance(value, str) and _HHMM.match(value)):
            raise ConfigError(f"{key}는 따옴표로 감싼 HH:MM 문자열이어야 합니다: {value!r}")
    order = [_minutes(v) for v in times.values()]
    if not order[0] < order[1] < order[2] < order[3]:
        raise ConfigError("시각 순서는 session.open < entry_cutoff < force_exit_time < "
                          "session.continuous_end 이어야 합니다.")
    bt = cfg["backtest"]
    if not _is_int(bt.get("days")) or bt["days"] < 1:
        raise ConfigError("backtest.days는 1 이상의 정수여야 합니다.")
    if not _is_number(bt.get("initial_cash")) or bt["initial_cash"] <= 0 \
            or int(bt["initial_cash"]) != bt["initial_cash"]:
        raise ConfigError("backtest.initial_cash는 0보다 큰 정수(원)여야 합니다.")
    for key in ("buy_rate", "sell_rate", "slippage_rate"):
        if not _is_number(cfg["costs"].get(key)) or cfg["costs"][key] < 0:
            raise ConfigError(f"costs.{key}는 0 이상의 수(비율)여야 합니다.")
    if not _is_number(cfg["target"].get("monthly_return")) or cfg["target"]["monthly_return"] <= 0:
        raise ConfigError("target.monthly_return은 0보다 큰 비율이어야 합니다.")
    dcfg = cfg["data"]
    if dcfg.get("minute_time_label") not in ("start", "end"):
        raise ConfigError("data.minute_time_label은 start 또는 end여야 합니다.")
    hour = dcfg.get("minute_start_hour")
    if not (isinstance(hour, str) and len(hour) == 6 and hour.isdigit()):
        raise ConfigError("data.minute_start_hour는 따옴표로 감싼 HHMMSS 문자열이어야 합니다.")
    if not _is_int(dcfg.get("minute_max_pages")) or dcfg["minute_max_pages"] < 1:
        raise ConfigError("data.minute_max_pages는 1 이상의 정수여야 합니다.")


def find_env_file(start: Path) -> Path | None:
    """① 환경변수 STOCK_SIM_ENV_FILE ② start부터 상위로 올라가며 첫 '.env' ③ None.

    경로만 돌려준다. 파일 내용은 읽지도 로그에 남기지도 않는다(R1).
    """
    override = os.environ.get(ENV_FILE_VAR, "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise ConfigError(f"환경변수 {ENV_FILE_VAR}가 가리키는 파일이 없습니다: {path}")
        return path.resolve()
    start = Path(start).resolve()
    for folder in [start, *start.parents]:
        cand = folder / ".env"
        if cand.is_file():
            return cand
    return None


def load_config(path: Path) -> dict:
    """YAML(UTF-8) 로드 → v1 키 거부 → 기본값 병합 → 검증. 상대 경로는 config 폴더 기준."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"설정 파일 YAML 형식 오류: {type(exc).__name__}") from None
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일의 최상위는 매핑이어야 합니다.")
    _reject_v1_keys(raw)
    for key in raw:
        if key not in DEFAULTS:
            log.warning("알 수 없는 설정 키를 무시합니다: %s", key)
    cfg = _merge(DEFAULTS, raw)
    if "universe" in raw:                  # 목록은 병합하지 않고 통째로 바꾼다
        cfg["universe"] = raw["universe"]
    _validate(cfg)
    cfg["backtest"]["initial_cash"] = int(cfg["backtest"]["initial_cash"])
    root = path.resolve().parent
    out = cfg["output"]
    cache_dir = (root / out["cache_dir"]).resolve()
    env_file = find_env_file(root)
    if env_file is not None:
        log.info(".env 경로: %s", env_file)
    cfg["paths"] = {
        "root": root,
        "cache_dir": cache_dir,
        "minute_cache_dir": cache_dir / "min",
        "result": (root / out["result"]).resolve(),
        "dashboard": (root / out["dashboard"]).resolve(),
        "template": (root / out["template"]).resolve(),
        "env_file": env_file,
    }
    return cfg


def load_credentials(env: str, env_file: Path | None) -> tuple[str, str]:
    """KIS_<env>_APP_KEY / KIS_<env>_APP_SECRET 반환. 값은 어디에도 출력하지 않는다(R1)."""
    key_name, secret_name = f"KIS_{env}_APP_KEY", f"KIS_{env}_APP_SECRET"
    if env_file is None:
        raise ConfigError(f".env 파일을 찾지 못했습니다. 환경변수 {ENV_FILE_VAR}로 경로를 지정하세요 "
                          f"(필요한 키 이름: {key_name}, {secret_name}).")
    load_dotenv(Path(env_file), override=False, encoding="utf-8")
    key, secret = os.environ.get(key_name, "").strip(), os.environ.get(secret_name, "").strip()
    missing = [n for n, v in ((key_name, key), (secret_name, secret)) if not v]
    if missing:
        raise ConfigError(f".env에 다음 키가 없습니다: {', '.join(missing)}")
    return key, secret


def mask(secret: str) -> str:
    """앞 4자리 + '****'. 4자 이하면 '****'."""
    if not secret or len(secret) <= 4:
        return "****"
    return secret[:4] + "****"


def resolve_period(cfg: dict, today: date) -> dict:
    """{'start', 'end', 'daily_fetch_start'} (architecture.md 3.2절)."""
    bt = cfg["backtest"]
    raw_end = bt.get("end", "auto")
    if isinstance(raw_end, datetime):
        end = raw_end.date()
    elif isinstance(raw_end, date):
        end = raw_end
    elif str(raw_end).strip().lower() == "auto":
        end = today - timedelta(days=1)
    else:
        try:
            end = datetime.strptime(str(raw_end).strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ConfigError(f"backtest.end는 auto 또는 YYYY-MM-DD여야 합니다: {raw_end!r}") from None
    start = end - timedelta(days=int(bt["days"]) - 1)
    return {"start": start, "end": end, "daily_fetch_start": start - timedelta(days=7)}


def cost_rates(cfg: dict) -> dict:
    """{'buy_rate', 'sell_rate', 'slippage_rate'} — cfg['costs'] 그대로(비율)."""
    c = cfg["costs"]
    return {"buy_rate": float(c["buy_rate"]), "sell_rate": float(c["sell_rate"]),
            "slippage_rate": float(c["slippage_rate"])}
