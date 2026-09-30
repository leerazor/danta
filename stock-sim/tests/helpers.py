"""테스트 공용 도우미. 네트워크를 쓰지 않는다."""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stock_sim import backtest, data, metrics, strategy

FIXTURES = Path(__file__).parent / "fixtures"
DOCS = Path(__file__).resolve().parents[1] / "docs"
SRC = Path(__file__).resolve().parents[1] / "src" / "stock_sim"

HAND_START, HAND_END = date(2026, 9, 17), date(2026, 9, 29)
BT_START = date(2026, 9, 21)
COSTS = {"buy_rate": 0.00015, "sell_rate": 0.00215, "slippage_rate": 0.0}
CAPITAL = 100_000_000


def hand_prices() -> dict[str, pd.DataFrame]:
    """strategy.md 9.2절 가격표(AAA, BBB)."""
    return {code: data.read_cache(data.cache_path(FIXTURES, code, HAND_START, HAND_END), True)
            for code in ("AAA", "BBB")}


def hand_index() -> pd.DataFrame:
    return data.read_cache(data.cache_path(FIXTURES, "IDX0001", HAND_START, HAND_END), False)


def run_hand(top_n: int = 1, end: date = HAND_END, prices: dict | None = None,
             costs: dict | None = None) -> dict:
    """9절 설정(lookback 1, weekly)으로 백테스트를 돌리고 중간 산출물까지 돌려준다."""
    prices = prices or hand_prices()
    params = {"lookback_days": 1, "top_n": top_n, "rebalance": "weekly"}
    calendar = data.build_calendar(prices)
    schedule = strategy.rebalance_schedule(calendar, BT_START, end, params)
    targets = strategy.signals(prices, calendar, schedule, params)
    bt = backtest.run_backtest(prices, calendar, schedule, targets, BT_START, end,
                               CAPITAL, top_n, costs or COSTS)
    days = [d for d in calendar if BT_START <= d <= end]
    bench, bench_info = metrics.benchmark_curve(hand_index(), days, CAPITAL)
    return {"prices": prices, "calendar": calendar, "schedule": schedule, "targets": targets,
            "bt": bt, "days": days, "bench": bench, "bench_info": bench_info, "params": params}


def make_df(rows: list[tuple]) -> pd.DataFrame:
    """[(date, open, close, volume)] → 4.1절 규격 DataFrame."""
    return pd.DataFrame({
        "date": pd.to_datetime([r[0] for r in rows]),
        "open": [int(r[1]) for r in rows], "high": [int(max(r[1], r[2])) for r in rows],
        "low": [int(min(r[1], r[2])) for r in rows], "close": [int(r[2]) for r in rows],
        "volume": [int(r[3]) for r in rows], "value": [int(r[2] * r[3]) for r in rows],
    })


# ---- e2e·계약 테스트용 합성 데이터 (6자리 코드, 워밍업 충분) ------------------
SYN_UNIVERSE = [{"code": "000001", "name": "가상전자"}, {"code": "000002", "name": "가상화학"},
                {"code": "000003", "name": "가상금융"}, {"code": "000004", "name": "가상바이오"}]
SYN_FETCH_START, SYN_REQ_START, SYN_END = date(2026, 5, 31), date(2026, 8, 29), date(2026, 9, 29)
SYN_HOLIDAYS = {date(2026, 9, 24), date(2026, 9, 25)}


def syn_days() -> list[date]:
    out, d = [], SYN_FETCH_START
    while d <= SYN_END:
        if d.weekday() < 5 and d not in SYN_HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


def syn_prices() -> dict[str, pd.DataFrame]:
    """위상이 다른 사인파 가격. 20일 모멘텀 순위가 주마다 바뀌어 매수·매도가 모두 생긴다."""
    days, out = syn_days(), {}
    for j, item in enumerate(SYN_UNIVERSE):
        base, rows, prev = 50_000 * (j + 1), [], None
        for k, d in enumerate(days):
            close = int(base * (1 + 0.12 * math.sin(k / 9.0 + j * 1.7)))
            rows.append((d, prev if prev else close, close, 10_000 + 100 * j))
            prev = close
        out[item["code"]] = make_df(rows)
    return out


def syn_index() -> pd.DataFrame:
    days = syn_days()
    closes = [4000.0 + 60 * math.sin(k / 11.0) for k in range(len(days))]
    opens = [closes[0]] + closes[:-1]
    return pd.DataFrame({"date": pd.to_datetime(days), "open": opens,
                         "high": [max(o, c) for o, c in zip(opens, closes)],
                         "low": [min(o, c) for o, c in zip(opens, closes)], "close": closes,
                         "volume": [500_000] * len(days), "value": [9_000_000] * len(days)})


def write_syn_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for code, df in syn_prices().items():
        df.to_csv(data.cache_path(cache_dir, code, SYN_FETCH_START, SYN_END), index=False,
                  encoding="utf-8", date_format="%Y-%m-%d")
    syn_index().to_csv(data.cache_path(cache_dir, "IDX0001", SYN_FETCH_START, SYN_END),
                       index=False, encoding="utf-8", date_format="%Y-%m-%d")


def syn_cfg(extra_universe: list[dict] | None = None) -> dict:
    return {
        "kis": {"env": "DEV"},
        "universe": SYN_UNIVERSE + (extra_universe or []),
        "benchmark": {"code": "0001", "name": "KOSPI"},
        "backtest": {"end": SYN_END.isoformat(), "months": 1, "warmup_days": 90},
        "strategy": {"name": "momentum_topn",
                     "params": {"lookback_days": 20, "top_n": 2, "rebalance": "weekly"}},
        "capital": CAPITAL, "max_positions": 2,
        "costs": {"buy_fee_pct": 0.015, "sell_fee_pct": 0.015, "sell_tax_pct": 0.20,
                  "slippage_pct": 0.0},
        "target_return": 2.0,
    }


def syn_run(prices: dict | None = None) -> dict:
    """합성 데이터로 스케줄 → 신호 → 백테스트 → 벤치마크까지."""
    cfg = syn_cfg()
    prices = prices if prices is not None else syn_prices()
    params = cfg["strategy"]["params"]
    calendar = data.build_calendar(prices) if prices else syn_days()
    days = [d for d in calendar if SYN_REQ_START <= d <= SYN_END]
    schedule = strategy.rebalance_schedule(calendar, days[0], days[-1], params)
    targets = strategy.signals(prices, calendar, schedule, params)
    bt = backtest.run_backtest(prices, calendar, schedule, targets, days[0], days[-1],
                               CAPITAL, 2, COSTS)
    bench, bench_info = metrics.benchmark_curve(syn_index(), days, CAPITAL)
    bench_info["equal_weight_return"] = metrics.equal_weight_return(prices, days)
    period = {"fetch_start": SYN_FETCH_START, "requested_start": SYN_REQ_START, "end": SYN_END,
              "rebalances": len(schedule)}
    return {"cfg": cfg, "prices": prices, "calendar": calendar, "days": days,
            "schedule": schedule, "targets": targets, "bt": bt, "bench": bench,
            "bench_info": bench_info, "period": period}
