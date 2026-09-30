"""후보 전략. strategy.STRATEGIES와 같은 모양(schedule, targets)이고 입력은 일봉 OHLCV·거래대금과 KOSPI 일봉뿐이다.

look-ahead 규칙: targets는 신호일 인덱스 i 이하의 배열 원소만 읽는다(모든 조회가 _win(i, n) 또는 [i]를 거친다).
보유 상태(추적 손절·돌파 보유)는 "직전 목표 = 보유"로 보고 함수 안에서 순차적으로 추적한다.
엔진에서 매수가 막힌 경우(수량 0·거래 불가)와는 어긋날 수 있으나 그 경우는 실험 로그의 events로 확인한다.

params (없으면 기준 전략과 같음):
  lookback_days, top_n           기준 전략과 동일
  rebalance                      "weekly" | "daily"
  every_weeks                    주간 리밸런싱을 k주마다(기본 1)
  score                          "mom" | "mom_x_value"(모멘텀 × 거래대금 증가율)
  value_short, value_long        거래대금 증가율 = 평균(value, short) / 평균(value, long)
  value_ratio_min                거래대금 증가율이 이 값 미만이면 순위에서 제외
  stock_sma                      종가 > SMA(n)인 종목만
  abs_mom                        True면 모멘텀 > 0인 종목만
  kospi_sma                      KOSPI 종가 > SMA(n)일 때만 보유(아니면 목표 없음 = 전량 현금)
  trail_stop                     보유 중 종가 고점 대비 −x(0.10 = 10%) 이하면 청산. 매일 점검
  vol_exit                       평균(volume,5) / 평균(volume,20) < k면 청산. 매일 점검
  mode = "breakout"              breakout_days, breakout_vol_k, exit_sma (아래 _breakout_targets)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stock_sim.strategy import TARGET_COLUMNS


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _daily_check(params: dict) -> bool:
    return (params.get("rebalance", "weekly") == "daily" or params.get("mode") == "breakout"
            or params.get("trail_stop") is not None or params.get("vol_exit") is not None)


def _rebalance_fills(calendar: list[date], start: date, end: date, params: dict) -> set[date]:
    """순위를 다시 매기는 체결일 집합."""
    if params.get("rebalance", "weekly") == "daily" or params.get("mode") == "breakout":
        return {calendar[i] for i in range(1, len(calendar)) if start <= calendar[i] <= end}
    every = int(params.get("every_weeks", 1))
    offset = int(params.get("week_offset", 0))     # 위상 점검용: 첫 리밸런싱을 offset주 늦춘다
    out, n = set(), 0
    for i in range(1, len(calendar)):
        p, d = calendar[i - 1], calendar[i]
        if start <= d <= end and _iso_week(p) != _iso_week(d):
            if n >= offset and (n - offset) % every == 0:
                out.add(d)
            n += 1
    return out


def schedule(calendar: list[date], start: date, end: date, params: dict) -> list[tuple[date, date]]:
    """[(signal_date, fill_date)]. 매일 점검이 필요한 규칙이면 모든 거래일, 아니면 리밸런싱 체결일만."""
    reb = _rebalance_fills(calendar, start, end, params)
    daily = _daily_check(params)
    return [(calendar[i - 1], calendar[i]) for i in range(1, len(calendar))
            if start <= calendar[i] <= end and (daily or calendar[i] in reb)]


class _Arr:
    """달력에 정렬한 배열. 결측·무효 봉은 NaN."""

    def __init__(self, prices: dict[str, pd.DataFrame], calendar: list[date], kospi: pd.DataFrame | None):
        cal = pd.DatetimeIndex(pd.to_datetime(calendar))
        self.close, self.volume, self.value = {}, {}, {}
        for code, df in prices.items():
            d = df.set_index(pd.to_datetime(df["date"])).reindex(cal)
            ok = (d["open"] > 0) & (d["close"] > 0) & (d["volume"] > 0)     # 유효 봉(strategy.md 2.4)
            self.close[code] = d["close"].where(ok).to_numpy(dtype="float64")
            self.volume[code] = d["volume"].where(ok).to_numpy(dtype="float64")
            self.value[code] = d["value"].where(ok).to_numpy(dtype="float64")
        self.kospi = None
        if kospi is not None:
            k = kospi.set_index(pd.to_datetime(kospi["date"]))["close"].reindex(cal)
            self.kospi = k.to_numpy(dtype="float64")


def _win(a: np.ndarray, i: int, n: int) -> np.ndarray | None:
    """a[i-n+1 .. i]. i 이후는 절대 읽지 않는다. 길이 부족·NaN 포함이면 None."""
    if i - n + 1 < 0:
        return None
    w = a[i - n + 1: i + 1]
    return None if np.isnan(w).any() else w


def _market_on(arr: _Arr, i: int, params: dict) -> bool:
    n = params.get("kospi_sma")
    if not n:
        return True
    w = _win(arr.kospi, i, int(n))
    return w is not None and w[-1] > w.mean()


def _value_ratio(arr: _Arr, code: str, i: int, params: dict) -> float | None:
    s, l = int(params.get("value_short", 5)), int(params.get("value_long", 20))
    ws, wl = _win(arr.value[code], i, s), _win(arr.value[code], i, l)
    if ws is None or wl is None or wl.mean() <= 0:
        return None
    return float(ws.mean() / wl.mean())


def _rank(arr: _Arr, i: int, params: dict) -> list[tuple[float, str]]:
    L = int(params["lookback_days"])
    out = []
    for code, c in arr.close.items():
        if i - L < 0 or np.isnan(c[i]) or np.isnan(c[i - L]):
            continue
        mom = c[i] / c[i - L] - 1.0
        if params.get("abs_mom") and mom <= 0:
            continue
        n = params.get("stock_sma")
        if n:
            w = _win(c, i, int(n))
            if w is None or not w[-1] > w.mean():
                continue
        score = mom
        if params.get("score") == "mom_x_value" or params.get("value_ratio_min") is not None:
            vr = _value_ratio(arr, code, i, params)
            if vr is None:
                continue
            if params.get("value_ratio_min") is not None and vr < params["value_ratio_min"]:
                continue
            if params.get("score") == "mom_x_value":
                score = mom * vr if mom >= 0 else mom / vr   # 거래대금이 붙은 하락은 더 나쁘게
        out.append((float(score), code))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def _exits(arr: _Arr, i: int, held: dict[str, float], params: dict) -> set[str]:
    """매일 점검 청산. held[code] = 보유 중 종가 고점(이 함수가 i일 종가로 갱신)."""
    out = set()
    for code in list(held):
        c = arr.close[code][i]
        if np.isnan(c):
            continue
        held[code] = max(held[code], c)
        x = params.get("trail_stop")
        if x is not None and c <= held[code] * (1.0 - x):
            out.add(code)
        k = params.get("vol_exit")
        if k is not None:
            a, b = _win(arr.volume[code], i, 5), _win(arr.volume[code], i, 20)
            if a is not None and b is not None and a.mean() < k * b.mean():
                out.add(code)
        n = params.get("exit_sma")
        if n:
            w = _win(arr.close[code], i, int(n))
            if w is not None and w[-1] < w.mean():
                out.add(code)
    return out


def _breakout_new(arr: _Arr, i: int, params: dict) -> list[tuple[float, str]]:
    """i일 종가가 직전 N일 종가 최고 이상이고, i일 거래량이 직전 20일 평균의 k배 이상. 거래량 배수 내림차순."""
    N, k = int(params["breakout_days"]), float(params["breakout_vol_k"])
    out = []
    for code, c in arr.close.items():
        if i < 1:
            continue
        prev_c, prev_v = _win(c, i - 1, N), _win(arr.volume[code], i - 1, 20)
        if prev_c is None or prev_v is None or np.isnan(c[i]) or np.isnan(arr.volume[code][i]):
            continue
        ratio = arr.volume[code][i] / prev_v.mean()
        if c[i] >= prev_c.max() and ratio >= k:
            out.append((float(ratio), code))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def targets(prices: dict[str, pd.DataFrame], calendar: list[date],
            schedule_: list[tuple[date, date]], params: dict, kospi: pd.DataFrame | None = None
            ) -> pd.DataFrame:
    arr = _Arr(prices, calendar, kospi)
    index = {d: i for i, d in enumerate(calendar)}
    top_n = int(params["top_n"])
    breakout = params.get("mode") == "breakout"
    if not schedule_:
        reb = set()
    elif _daily_check(params):     # 매일 점검 일정: 첫 체결일이 구간 첫 거래일이라 같은 기준으로 다시 센다
        reb = _rebalance_fills(calendar, schedule_[0][1], schedule_[-1][1], params)
    else:                          # 리밸런싱 체결일만 담긴 일정
        reb = {fill for _, fill in schedule_}
    held: dict[str, float] = {}        # code -> 보유 중 종가 고점
    rows: list[dict] = []
    for sig, fill in schedule_:
        i = index[sig]
        out = _exits(arr, i, held, params)
        if breakout:
            keep = [(None, c) for c in held if c not in out]
            fresh = [(s, c) for s, c in _breakout_new(arr, i, params) if c not in held]
            chosen = (keep + fresh)[:top_n] if _market_on(arr, i, params) else []
        elif fill in reb:
            ranked = _rank(arr, i, params) if _market_on(arr, i, params) else []
            chosen = [(s, c) for s, c in ranked if c not in out][:top_n]
        else:
            chosen = [(None, c) for c in held if c not in out]
        held = {c: held.get(c, arr.close[c][i]) for _, c in chosen}
        for rank, (score, code) in enumerate(chosen, start=1):
            rows.append({"signal_date": sig, "fill_date": fill, "code": code, "rank": rank,
                         "score": score})
    return pd.DataFrame(rows, columns=TARGET_COLUMNS)


STRAT = {"schedule": schedule, "targets": targets}
BASE = {"lookback_days": 20, "top_n": 5, "rebalance": "weekly"}


def warmup_needed(params: dict) -> int:
    """첫 신호일 이전에 필요한 거래일 수(신호일 포함 창 길이 기준)."""
    need = [int(params["lookback_days"]) + 1]
    for key in ("stock_sma", "kospi_sma", "exit_sma", "value_long"):
        if params.get(key):
            need.append(int(params[key]))
    if params.get("mode") == "breakout":
        need.append(max(int(params["breakout_days"]), 20) + 1)
    if params.get("vol_exit") is not None:
        need.append(20)
    return max(need)
