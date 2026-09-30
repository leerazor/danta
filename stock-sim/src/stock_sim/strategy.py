"""5분봉 채널 돌파(intraday_breakout). 순수 함수(파일·네트워크·시계 접근 없음).

규칙은 docs/strategy.md 3.4·3.5절(리샘플), 4.1절(지표), 4.2·4.3절(신호 플래그).
신호 플래그는 봉 k의 종가까지 정보만 쓴다(R5). 포지션·쿨다운·횟수·중단 같은 상태 조건은
넣지 않는다(backtest가 본다). 비교는 정수·유리수(Fraction)로 해 부동소수 오차를 피한다.
"""
from __future__ import annotations

from datetime import date
from fractions import Fraction

import pandas as pd

BAR_COLUMNS = ["date", "time", "slot", "k", "open", "high", "low", "close", "volume"]
INDICATOR_COLUMNS = ["hh", "ll", "sv", "xl", "pv", "cv"]
FLAG_COLUMNS = ["breakout", "cutoff_ok", "range_ok", "volume_ok", "vwap_ok", "exit_signal"]


def to_minutes(hhmm: str) -> int:
    """'HH:MM' → 자정부터 분."""
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def slot_count(session_open: str, continuous_end: str, bar_minutes: int) -> int:
    """접속매매 구간의 슬롯 수(5분봉 09:00~15:20이면 76)."""
    span = to_minutes(continuous_end) - to_minutes(session_open)
    return max(0, -(-span // bar_minutes))


def _as_date(x) -> date:
    """Timestamp·datetime → date. date는 그대로."""
    return x.date() if isinstance(x, pd.Timestamp) else x


def resample_bars(minutes: pd.DataFrame, bar_minutes: int = 5,
                  session_open: str = "09:00", continuous_end: str = "15:20") -> pd.DataFrame:
    """1분봉(4.2절, 여러 날) → 유효 5분봉(4.3절 앞 9개 컬럼).

    슬롯 s는 1분봉 s ~ s + bar_minutes − 1분을 묶는다. continuous_end 이후 1분봉은 버린다.
    유효 봉 = 1분봉이 하나 이상 있고 open > 0, close > 0, volume > 0. 무효 슬롯은 행이 없다.
    """
    if minutes is None or len(minutes) == 0:
        return pd.DataFrame(columns=BAR_COLUMNS)
    open_m, end_m = to_minutes(session_open), to_minutes(continuous_end)
    df = minutes[["date", "time", "open", "high", "low", "close", "volume"]].copy()
    df["d"] = [_as_date(x) for x in pd.to_datetime(pd.Series(df["date"]))]
    df["m"] = [to_minutes(str(t)) for t in df["time"]]
    df = df[(df["m"] >= open_m) & (df["m"] < end_m)]
    df = df.sort_values(["d", "m"], kind="stable")
    df["slot"] = (df["m"] - open_m) // bar_minutes
    rows = []
    for (d, slot), g in df.groupby(["d", "slot"], sort=True):
        o, c, v = int(g["open"].iloc[0]), int(g["close"].iloc[-1]), int(g["volume"].sum())
        if o <= 0 or c <= 0 or v <= 0:
            continue
        rows.append({"date": d, "time": hhmm(open_m + int(slot) * bar_minutes), "slot": int(slot),
                     "open": o, "high": int(g["high"].max()), "low": int(g["low"].min()),
                     "close": c, "volume": v})
    out = pd.DataFrame(rows, columns=[c for c in BAR_COLUMNS if c != "k"])
    out["k"] = out.groupby("date").cumcount() if len(out) else pd.Series(dtype="int64")
    return out[BAR_COLUMNS].reset_index(drop=True)


def add_indicators(bars: pd.DataFrame, entry_lookback: int, exit_lookback: int) -> pd.DataFrame:
    """날짜별로 초기화한 당일 지표(4.1절). hh·ll·sv·xl은 직전 봉(자기 제외), pv·cv는 자기 포함 누적."""
    out = bars.copy().reset_index(drop=True)
    if len(out) == 0:
        for col in INDICATOR_COLUMNS:
            out[col] = pd.Series(dtype="Int64")
        return out
    n, m = int(entry_lookback), int(exit_lookback)
    g = out.groupby("date", sort=False)
    prev_h, prev_l, prev_v = g["high"].shift(1), g["low"].shift(1), g["volume"].shift(1)
    key = out["date"]
    out["hh"] = prev_h.groupby(key).rolling(n, min_periods=n).max().reset_index(level=0, drop=True)
    out["ll"] = prev_l.groupby(key).rolling(n, min_periods=n).min().reset_index(level=0, drop=True)
    out["sv"] = prev_v.groupby(key).rolling(n, min_periods=n).sum().reset_index(level=0, drop=True)
    out["xl"] = prev_l.groupby(key).rolling(m, min_periods=m).min().reset_index(level=0, drop=True)
    for col in ("hh", "ll", "sv", "xl"):
        out[col] = out[col].round().astype("Int64")
    tp_v = (out["high"] + out["low"] + out["close"]).astype("int64") * out["volume"].astype("int64")
    out["pv"] = tp_v.groupby(key).cumsum().astype("int64")
    out["cv"] = out["volume"].astype("int64").groupby(key).cumsum().astype("int64")
    return out


def _frac(x) -> Fraction:
    return Fraction(str(x))


def signals(bars: pd.DataFrame, params: dict) -> pd.DataFrame:
    """지표(없으면 계산) + 봉별 bool 플래그 6개(architecture.md 1.4절).

    breakout: k ≥ N 이고 close > hh / cutoff_ok: 봉 종료 시각 ≤ entry_cutoff /
    range_ok: (hh − ll) ≥ min_range_pct × close / volume_ok: volume × N ≥ vol_mult × sv /
    vwap_ok: 3 × close × cv > pv / exit_signal: k ≥ M 이고 close < xl.
    """
    n, m = int(params["entry_lookback"]), int(params["exit_lookback"])
    out = bars if "hh" in bars.columns else add_indicators(bars, n, m)
    out = out.copy()
    bar_min = int(params.get("bar_minutes", 5))
    cutoff = to_minutes(params["entry_cutoff"])
    rng, vol = _frac(params["min_range_pct"]), _frac(params["vol_mult"])
    flags = {c: [] for c in FLAG_COLUMNS}
    for r in out.itertuples(index=False):
        k, c, v = int(r.k), int(r.close), int(r.volume)
        defined_n = k >= n and not pd.isna(r.hh)
        defined_m = k >= m and not pd.isna(r.xl)
        hh = int(r.hh) if defined_n else None
        flags["breakout"].append(bool(defined_n and c > hh))
        flags["cutoff_ok"].append(to_minutes(r.time) + bar_min <= cutoff)
        if defined_n:
            span, sv = int(r.hh) - int(r.ll), int(r.sv)
            flags["range_ok"].append(span * rng.denominator >= rng.numerator * c)
            flags["volume_ok"].append(v * n * vol.denominator >= vol.numerator * sv)
        else:
            flags["range_ok"].append(False)
            flags["volume_ok"].append(False)
        flags["vwap_ok"].append(3 * c * int(r.cv) > int(r.pv))
        flags["exit_signal"].append(bool(defined_m and c < int(r.xl)))
    for col, vals in flags.items():
        out[col] = pd.Series(vals, index=out.index, dtype="bool")
    return out


def auction_closes(minutes: pd.DataFrame, at: str = "15:30") -> dict[date, int]:
    """날짜별 at 시각 1분봉의 종가(strategy.md 8절 5번 대체 체결가용). 없는 날은 키 없음."""
    if minutes is None or len(minutes) == 0:
        return {}
    sub = minutes[minutes["time"].astype(str) == at]
    out: dict[date, int] = {}
    for d, c in zip(pd.to_datetime(sub["date"]), sub["close"]):
        if int(c) > 0:
            out[d.date()] = int(c)
    return out


def label(params: dict) -> str:
    """meta.strategy.label. 예 '5분봉 채널 돌파 · 당일 청산'."""
    return f"{int(params.get('bar_minutes', 5))}분봉 채널 돌파 · 당일 청산"


STRATEGIES: dict[str, dict] = {"intraday_breakout": {"signals": signals, "label": label}}
