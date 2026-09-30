"""설정 로드·검증, 경로 해석, 자격 증명 읽기 (architecture.md 1.1절, 3절)."""
from __future__ import annotations

import copy
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from stock_sim import strategy

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """설정 오류. 종료 코드 1."""


DEFAULTS: dict = {
    "kis": {"env": "DEV", "prod_approved_by_user": False, "min_interval_sec": 1.0,
            "max_retries": 3, "backoff_sec": 2.0, "timeout_sec": 10},
    "universe": [
        {"code": "005930", "name": "삼성전자"}, {"code": "000660", "name": "SK하이닉스"},
        {"code": "373220", "name": "LG에너지솔루션"}, {"code": "207940", "name": "삼성바이오로직스"},
        {"code": "005380", "name": "현대차"}, {"code": "000270", "name": "기아"},
        {"code": "068270", "name": "셀트리온"}, {"code": "035420", "name": "NAVER"},
        {"code": "105560", "name": "KB금융"}, {"code": "005490", "name": "POSCO홀딩스"},
    ],
    "benchmark": {"code": "0001", "name": "KOSPI"},
    "backtest": {"end": "auto", "months": 1, "warmup_days": 90},
    "strategy": {"name": "momentum_topn",
                 "params": {"lookback_days": 20, "top_n": 5, "rebalance": "weekly"}},
    "capital": 100_000_000,
    "max_positions": 5,
    "costs": {"buy_fee_pct": 0.015, "sell_fee_pct": 0.015, "sell_tax_pct": 0.20,
              "slippage_pct": 0.0},
    "target_return": 2.0,
    "output": {"result": "output/result.json", "dashboard": "output/dashboard.html",
               "template": "templates/dashboard.html.j2", "cache_dir": "data/cache"},
}


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
    if not _is_number(cfg["capital"]) or cfg["capital"] <= 0 or int(cfg["capital"]) != cfg["capital"]:
        raise ConfigError("capital은 0보다 큰 정수(원)여야 합니다.")
    if not isinstance(cfg["max_positions"], int) or cfg["max_positions"] < 1:
        raise ConfigError("max_positions는 1 이상의 정수여야 합니다.")
    for key in ("buy_fee_pct", "sell_fee_pct", "sell_tax_pct", "slippage_pct"):
        if not _is_number(cfg["costs"].get(key)) or cfg["costs"][key] < 0:
            raise ConfigError(f"costs.{key}는 0 이상의 수여야 합니다.")
    name = cfg["strategy"].get("name")
    if name not in strategy.STRATEGIES:
        raise ConfigError(f"strategy.name이 등록된 전략이 아닙니다: {name!r}")
    params = cfg["strategy"].get("params") or {}
    if not isinstance(params.get("lookback_days"), int) or params["lookback_days"] < 1:
        raise ConfigError("strategy.params.lookback_days는 1 이상의 정수여야 합니다.")
    if params.get("top_n") != cfg["max_positions"]:
        raise ConfigError("strategy.params.top_n은 max_positions와 같아야 합니다.")
    if params.get("rebalance", "weekly") != "weekly":
        raise ConfigError("strategy.params.rebalance는 weekly만 지원합니다.")
    bt = cfg["backtest"]
    if not isinstance(bt.get("months"), int) or bt["months"] < 1:
        raise ConfigError("backtest.months는 1 이상의 정수여야 합니다.")
    if not isinstance(bt.get("warmup_days"), int) or bt["warmup_days"] < 0:
        raise ConfigError("backtest.warmup_days는 0 이상의 정수여야 합니다.")
    if not _is_number(cfg["target_return"]) or cfg["target_return"] <= 0:
        raise ConfigError("target_return은 0보다 큰 수(%)여야 합니다.")


def load_config(path: Path) -> dict:
    """YAML(UTF-8) 로드 → 기본값 병합 → 검증. 상대 경로는 config 폴더 기준."""
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
    for key in raw:
        if key not in DEFAULTS:
            log.warning("알 수 없는 설정 키를 무시합니다: %s", key)
    cfg = _merge(DEFAULTS, raw)
    cfg["capital"] = int(cfg["capital"]) if _is_number(cfg["capital"]) else cfg["capital"]
    _validate(cfg)
    root = path.resolve().parent
    out = cfg["output"]
    cfg["paths"] = {
        "root": root,
        "cache_dir": (root / out["cache_dir"]).resolve(),
        "result": (root / out["result"]).resolve(),
        "dashboard": (root / out["dashboard"]).resolve(),
        "template": (root / out["template"]).resolve(),
        "env_file": (root.parent / ".env").resolve(),
    }
    return cfg


def load_credentials(env: str, env_file: Path) -> tuple[str, str]:
    """KIS_<env>_APP_KEY / KIS_<env>_APP_SECRET 반환. 값은 어디에도 출력하지 않는다(R1)."""
    load_dotenv(Path(env_file), override=False, encoding="utf-8")
    key_name, secret_name = f"KIS_{env}_APP_KEY", f"KIS_{env}_APP_SECRET"
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
    """{'fetch_start', 'requested_start', 'end'} (architecture.md 3.2절)."""
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
    requested_start = (pd.Timestamp(end) - pd.DateOffset(months=int(bt["months"]))).date()
    fetch_start = requested_start - timedelta(days=int(bt["warmup_days"]))
    return {"fetch_start": fetch_start, "requested_start": requested_start, "end": end}


def cost_rates(cfg: dict) -> dict:
    """% 단위 설정 → 비율(architecture.md 3.1절)."""
    c = cfg["costs"]
    return {
        "buy_rate": c["buy_fee_pct"] / 100,
        "sell_rate": (c["sell_fee_pct"] + c["sell_tax_pct"]) / 100,
        "slippage_rate": c["slippage_pct"] / 100,
    }
