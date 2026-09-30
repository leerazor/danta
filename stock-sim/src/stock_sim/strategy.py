"""신호(목표 종목) 계산. 순수 함수만 둔다(파일·네트워크·시계 접근 없음).

규칙은 docs/strategy.md 2.4절·3절. 신호는 signal_date 종가까지만 쓴다(R5).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

TARGET_COLUMNS = ["signal_date", "fill_date", "code", "rank", "score"]


def to_bars(df: pd.DataFrame) -> dict[date, tuple[int, int, int]]:
    """일봉 DataFrame → {날짜: (시가, 종가, 거래량)}."""
    if df is None or len(df) == 0:
        return {}
    dates = [ts.date() for ts in pd.to_datetime(df["date"])]
    return {
        d: (int(o), int(c), int(v))
        for d, o, c, v in zip(dates, df["open"], df["close"], df["volume"])
    }


def is_valid_bar(bar: tuple[int, int, int] | None) -> bool:
    """유효 봉: 행이 있고 시가 > 0, 종가 > 0, 거래량 > 0."""
    return bar is not None and bar[0] > 0 and bar[1] > 0 and bar[2] > 0


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def rebalance_schedule(calendar: list[date], start: date, end: date, params: dict
                       ) -> list[tuple[date, date]]:
    """[(signal_date, fill_date)]. fill_date는 [start, end] 안의 각 ISO 주 첫 거래일."""
    mode = params.get("rebalance", "weekly")
    if mode != "weekly":
        raise ValueError(f"지원하지 않는 rebalance 값: {mode}")
    out: list[tuple[date, date]] = []
    for i in range(1, len(calendar)):
        p, d = calendar[i - 1], calendar[i]
        if start <= d <= end and _iso_week(p) != _iso_week(d):
            out.append((p, d))
    return out


def signals(prices: dict[str, pd.DataFrame], calendar: list[date],
            schedule: list[tuple[date, date]], params: dict) -> pd.DataFrame:
    """신호일별 목표 종목 표(순위 포함). signal_date 이후 데이터는 읽지 않는다."""
    lookback = int(params["lookback_days"])
    top_n = int(params["top_n"])
    bars = {code: to_bars(df) for code, df in prices.items()}
    index = {d: i for i, d in enumerate(calendar)}
    rows: list[dict] = []
    for signal_date, fill_date in schedule:
        i = index.get(signal_date)
        if i is None or i - lookback < 0:
            continue
        base_date = calendar[i - lookback]
        scored: list[tuple[float, str]] = []
        for code, by_date in bars.items():
            now, base = by_date.get(signal_date), by_date.get(base_date)
            if not (is_valid_bar(now) and is_valid_bar(base)):
                continue
            scored.append((now[1] / base[1] - 1.0, code))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for rank, (score, code) in enumerate(scored[:top_n], start=1):
            rows.append({"signal_date": signal_date, "fill_date": fill_date,
                         "code": code, "rank": rank, "score": score})
    return pd.DataFrame(rows, columns=TARGET_COLUMNS)


def _momentum_label(params: dict) -> str:
    return f"{params['lookback_days']}일 수익률 상위 {params['top_n']}종목 · 주간 리밸런싱"


STRATEGIES: dict[str, dict] = {
    "momentum_topn": {
        "schedule": rebalance_schedule,
        "targets": signals,
        "min_warmup": lambda params: int(params["lookback_days"]) + 10,
        "label": _momentum_label,
    },
}


def min_warmup_days(name: str, params: dict) -> int:
    """백테스트 시작 전 필요한 거래일 수."""
    return STRATEGIES[name]["min_warmup"](params)
