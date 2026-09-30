"""테스트 공용 도우미. 네트워크를 쓰지 않는다."""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pandas as pd

from stock_sim import backtest, config, metrics, strategy

FIXTURES = Path(__file__).parent / "fixtures"
FIX_CACHE = FIXTURES / "cache"
DOCS = Path(__file__).resolve().parents[1] / "docs"
SRC = Path(__file__).resolve().parents[1] / "src" / "stock_sim"

HAND_DAY = date(2026, 9, 21)
COSTS = {"buy_rate": 0.00015, "sell_rate": 0.00215, "slippage_rate": 0.0}
CAPITAL = 100_000_000

# strategy.md 10.1절: 축소 파라미터 + 테스트용 시각 설정
HAND_PARAMS = {**copy.deepcopy(config.DEFAULTS["strategy"]), "entry_lookback": 3, "exit_lookback": 2,
               "min_bars_per_day": 1, "entry_cutoff": "10:00", "force_exit_time": "10:04"}
HAND_SESSION = {"open": "09:00", "continuous_end": "10:05"}
# 10.7절 케이스 4·5: 기본 시각 설정
DEFAULT_TIME_PARAMS = {**HAND_PARAMS, "entry_cutoff": "14:50", "force_exit_time": "15:15"}
DEFAULT_SESSION = {"open": "09:00", "continuous_end": "15:20"}


def hand_bars5() -> pd.DataFrame:
    """10.2절 5분봉 13개(date, time, open, high, low, close, volume)."""
    df = pd.read_csv(FIXTURES / "bars5_AAA_20260921.csv", encoding="utf-8", dtype={"time": str})
    df["date"] = [d.date() for d in pd.to_datetime(df["date"])]
    return df


def as_bars(df5: pd.DataFrame, session_open: str = "09:00", bar_minutes: int = 5) -> pd.DataFrame:
    """5분봉 입력에 slot·k를 붙인다(직접 입력 fixture용)."""
    out = df5.copy().sort_values(["date", "time"]).reset_index(drop=True)
    open_m = strategy.to_minutes(session_open)
    out["slot"] = [(strategy.to_minutes(t) - open_m) // bar_minutes for t in out["time"]]
    out["k"] = out.groupby("date").cumcount()
    return out[strategy.BAR_COLUMNS]


def hand_signals(params: dict | None = None, df5: pd.DataFrame | None = None) -> pd.DataFrame:
    params = params or HAND_PARAMS
    return strategy.signals(as_bars(df5 if df5 is not None else hand_bars5()), params)


def hand_daily() -> dict[str, pd.DataFrame]:
    """11.6절 추가 입력: AAA 일봉 09-21 시가 100,000, 종가 100,800."""
    return {"AAA": pd.DataFrame({"date": pd.to_datetime(["2026-09-21"]), "open": [100_000],
                                 "high": [101_300], "low": [99_700], "close": [100_800],
                                 "volume": [13_000], "value": [0]})}


def hand_index() -> pd.DataFrame:
    """11.6절: KOSPI 09-21 시가 4,000.00, 종가 4,020.00."""
    return pd.DataFrame({"date": pd.to_datetime(["2026-09-21"]), "open": [4000.0], "high": [4030.0],
                         "low": [3990.0], "close": [4020.0], "volume": [1], "value": [1]})


def run_hand(params: dict | None = None, session: dict | None = None, df5: pd.DataFrame | None = None,
             auction: dict | None = None, daily: dict | None = None, costs: dict | None = None) -> dict:
    params = params or HAND_PARAMS
    bars = {"AAA": hand_signals(params, df5)}
    return backtest.run_backtest(bars, daily if daily is not None else {}, auction or {}, params,
                                 costs or COSTS, CAPITAL, session=session or HAND_SESSION)


def hand_cfg() -> dict:
    """10절 손계산용 cfg(build_result 입력). 시각 설정은 10.1절."""
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["universe"] = [{"code": "AAA", "name": ""}]
    cfg["strategy"] = copy.deepcopy(HAND_PARAMS)
    cfg["session"] = dict(HAND_SESSION)
    cfg["backtest"] = {"end": "2026-09-21", "days": 30, "initial_cash": CAPITAL}
    return cfg


def hand_result() -> dict:
    """10절 fixture로 result.json(dict)을 만든다."""
    from stock_sim import report
    cfg = hand_cfg()
    bt = run_hand()
    days = list(bt["days"]["date"])
    daily_tab = metrics.daily_table(bt["days"], bt["fills"], bt["closed"], CAPITAL)
    bench, info = metrics.benchmark_curve(hand_index(), days, CAPITAL)
    info["equal_weight_return"] = metrics.equal_weight_return(hand_daily(), days)
    info["equal_weight_count"] = metrics.equal_weight_count(hand_daily(), days)
    period = {"start": HAND_DAY, "end": HAND_DAY, "daily_fetch_start": date(2026, 9, 14)}
    source = {"api_calls": 0, "cache_hits": 0, "minute_files": 1, "minute_rows": 13, "empty_days": []}
    return report.build_result(cfg, period, bt, daily_tab, bench, info, [], source,
                               "2026-09-30T09:00:00+09:00")
