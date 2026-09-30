"""실험 공통: 데이터 적재(stock_sim.data 로더, 캐시 우선), 구간 정의, 백테스트 실행 헬퍼.

체결·비용·지표는 stock_sim.backtest / stock_sim.metrics를 그대로 쓴다(재구현 없음).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from stock_sim import backtest, config, data, metrics  # noqa: E402

# 구간 (PLAN.md 2절)
V1_START, V1_END = date(2026, 5, 31), date(2026, 9, 29)      # v1 캐시(기존)
EXT_START, EXT_END = date(2025, 5, 6), date(2026, 5, 30)     # IS용 추가 수집(390일 = 종목 3조각, 지수 7조각)
IS_START, IS_END = date(2025, 8, 29), date(2026, 8, 28)
OOS_START, OOS_END = date(2026, 8, 29), date(2026, 9, 29)


def load_cfg() -> dict:
    return config.load_config(ROOT / "config.yaml")


def load_prices(cfg: dict, client=None) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[str]]:
    """(prices, kospi, notes). 두 캐시 구간(EXT + V1)을 로더로 읽어 이어 붙인다.

    client가 None이면 캐시만 읽는다. EXT 캐시가 없으면 V1 구간만 돌려주고 notes에 적는다.
    """
    cache = cfg["paths"]["cache_dir"]
    notes: list[str] = []

    def both(loader, code):
        parts = []
        for a, b in ((EXT_START, EXT_END), (V1_START, V1_END)):
            try:
                df = loader(code, a, b, cache, client)
            except FileNotFoundError:
                notes.append(f"캐시 없음: {code} {a}~{b}")
                continue
            if df.attrs.get("truncation"):
                notes.append(f"잘림 의심: {code} {a}~{b}")
            parts.append(df)
        df = pd.concat(parts, ignore_index=True)
        return df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    prices = {u["code"]: both(data.load_daily, u["code"]) for u in cfg["universe"]}
    kospi = both(data.load_index, cfg["benchmark"]["code"])
    return prices, kospi, notes


def run(prices, kospi, calendar, strat: dict, params: dict, start: date, end: date, cfg: dict) -> dict:
    """후보 하나를 [start, end]에서 돌려 요약 지표를 돌려준다. 엔진은 v1과 동일."""
    days = [d for d in calendar if start <= d <= end]
    schedule = strat["schedule"](calendar, days[0], days[-1], params)
    targets = strat["targets"](prices, calendar, schedule, params, kospi)
    max_pos = int(params["top_n"])
    bt = backtest.run_backtest(prices, calendar, schedule, targets, days[0], days[-1],
                               cfg["capital"], max_pos, config.cost_rates(cfg))
    bench, _ = metrics.benchmark_curve(kospi, days, cfg["capital"])
    s = metrics.summarize(bt["trades"], bt["snapshots"], bt["positions"], bench, cfg["capital"])
    return {"ret": s["total_return"], "mdd": s["mdd"], "trades": s["trade_count"],
            "closed": s["closed_count"], "win": s["win_rate"], "turnover": s["turnover"],
            "cost": s["total_cost"], "kospi": s["benchmark_return"],
            "ew": metrics.equal_weight_return(prices, days), "days": len(days),
            "rebalances": len(schedule),
            "avg_pos": float(bt["snapshots"]["position_count"].mean()),
            "equity": list(bt["snapshots"]["equity"]), "dates": days}
