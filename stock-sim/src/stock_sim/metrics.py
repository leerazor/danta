"""지표 계산. 순수 함수. 비율은 반올림하지 않은 소수로 돌려준다(docs/strategy.md 7·9절).

% 변환과 자리수 맞춤은 report.py만 한다.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

DAILY_COLUMNS = ["date", "e_start", "e_end", "halted", "skipped_codes", "pnl", "ret", "cum_ret",
                 "drawdown", "buy_count", "sell_count", "closed_count", "trade_value", "cost"]


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


# ---- 벤치마크 (일봉, v1과 같음) ------------------------------------------------
def benchmark_curve(benchmark: pd.DataFrame, days: list[date], capital: int
                    ) -> tuple[pd.DataFrame, dict]:
    """BM(t) = E0 × 종가(t) / 기준가. 기준가는 d1 시가, 없으면 직전 거래일 종가(prev_close)."""
    if not days:
        raise ValueError("백테스트 거래일이 없습니다.")
    rows = {ts.date(): (_num(o), _num(c)) for ts, o, c in
            zip(pd.to_datetime(benchmark["date"]), benchmark["open"], benchmark["close"])}
    d1 = days[0]
    prev_close = None
    for d in sorted(rows):
        if d >= d1:
            break
        if rows[d][1] and rows[d][1] > 0:
            prev_close = rows[d][1]
    base = rows.get(d1, (None, None))[0]
    kind = "d1_open"
    if not base or base <= 0:
        base, kind = prev_close, "prev_close"
    if not base or base <= 0:
        raise ValueError("벤치마크 기준가를 정할 수 없습니다(지수 시가·직전 종가 없음).")
    out, last = [], prev_close
    for d in days:
        close = rows.get(d, (None, None))[1]
        if close and close > 0:
            last = close
        value = last if last else base            # 결측일은 직전 값
        out.append({"date": d, "close": float(value),
                    "value": int(math.floor(capital * value / base + 0.5)),
                    "ret": value / base - 1.0})
    return (pd.DataFrame(out, columns=["date", "close", "value", "ret"]),
            {"base_price": float(base), "base_kind": kind})


def _equal_weight_ratios(prices: dict[str, pd.DataFrame], days: list[date]) -> list[float]:
    """종목별 C_i(dn) / O_i(d1). d1 일봉이 유효(시가·종가 > 0)한 종목만. 종가 결측은 직전 유효 종가."""
    if not days:
        return []
    d1, dn = days[0], days[-1]
    ratios = []
    for df in (prices or {}).values():
        if df is None or len(df) == 0:
            continue
        bars = {ts.date(): (int(o), int(c)) for ts, o, c in
                zip(pd.to_datetime(df["date"]), df["open"], df["close"])}
        first = bars.get(d1)
        if not first or first[0] <= 0 or first[1] <= 0:
            continue
        last = None
        for d in sorted(bars):
            if d > dn:
                break
            if bars[d][1] > 0:
                last = bars[d][1]
        if last:
            ratios.append(last / first[0])
    return ratios


def equal_weight_return(prices: dict[str, pd.DataFrame], days: list[date]) -> float | None:
    """유니버스 동일가중 buy&hold: 평균_i(C_i(dn) / O_i(d1)) − 1."""
    ratios = _equal_weight_ratios(prices, days)
    return sum(ratios) / len(ratios) - 1.0 if ratios else None


def equal_weight_count(prices: dict[str, pd.DataFrame], days: list[date]) -> int:
    return len(_equal_weight_ratios(prices, days))


# ---- 일별 집계 ------------------------------------------------------------------
def daily_table(days: pd.DataFrame, fills: pd.DataFrame, closed: pd.DataFrame,
                initial_cash: int) -> pd.DataFrame:
    """거래일마다 1행(architecture.md 4.6절). drawdown의 고점 후보에 E0를 넣는다."""
    rows, peak = [], int(initial_cash)
    fill_recs = fills.to_dict("records") if len(fills) else []
    closed_recs = closed.to_dict("records") if len(closed) else []
    for rec in days.to_dict("records"):
        d = rec["date"]
        e_start, e_end = int(rec["e_start"]), int(rec["e_end"])
        mine = [f for f in fill_recs if f["date"] == d]
        peak = max(peak, e_end)
        rows.append({
            "date": d, "e_start": e_start, "e_end": e_end, "halted": bool(rec["halted"]),
            "skipped_codes": list(rec.get("skipped_codes") or []),
            "pnl": e_end - e_start, "ret": e_end / e_start - 1.0,
            "cum_ret": e_end / initial_cash - 1.0, "drawdown": e_end / peak - 1.0,
            "buy_count": sum(1 for f in mine if f["side"] == "BUY"),
            "sell_count": sum(1 for f in mine if f["side"] == "SELL"),
            "closed_count": sum(1 for c in closed_recs if c["date"] == d),
            "trade_value": sum(int(f["amount"]) for f in mine),
            "cost": sum(int(f["cost"]) for f in mine),
        })
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _drawdown(equities: list[int], days: list[date], capital: int) -> dict:
    # 고점 후보에 E0 포함(날짜 없음). 저점일은 같은 낙폭 중 가장 이른 날(<),
    # 고점일은 같은 평가액 중 저점일에 가장 가까운 날(>=)이다(strategy.md 11.1절 ③).
    peak, peak_date = capital, None
    mdd, mdd_peak, mdd_trough, series = 0.0, None, None, []
    for d, e in zip(days, equities):
        if e >= peak:
            peak, peak_date = e, d
        dd = e / peak - 1.0
        series.append(dd)
        if dd < mdd:
            mdd, mdd_peak, mdd_trough = dd, peak_date, d
    return {"mdd": mdd, "mdd_peak_date": mdd_peak, "mdd_trough_date": mdd_trough, "drawdowns": series}


def summarize(fills: pd.DataFrame, closed: pd.DataFrame, daily: pd.DataFrame, bench: pd.DataFrame,
              initial_cash: int) -> dict:
    """summary 원값(architecture.md 5.3절). 비율은 반올림 없는 소수."""
    capital = int(initial_cash)
    days = list(daily["date"])
    n = len(days)
    equities = [int(x) for x in daily["e_end"]]
    final_equity = equities[-1]
    pnls = [int(x) for x in closed["pnl"]] if len(closed) else []
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    streak = best = 0
    for p in pnls:                                    # closed는 (매도 일시, 종목코드) 순
        streak = streak + 1 if p < 0 else 0
        best = max(best, streak)
    has = len(fills) > 0
    buys = fills[fills["side"] == "BUY"] if has else fills
    sells = fills[fills["side"] == "SELL"] if has else fills
    buy_value = int(buys["amount"].sum()) if has else 0
    sell_value = int(sells["amount"].sum()) if has else 0
    buy_cost = int(buys["cost"].sum()) if has else 0
    sell_cost = int(sells["cost"].sum()) if has else 0
    total_cost = buy_cost + sell_cost
    gross = int(closed["gross_pnl"].sum()) if len(closed) else 0
    total_return = final_equity / capital - 1.0
    bench_return = float(bench["ret"].iloc[-1])
    holds = [int(x) for x in closed["hold_minutes"]] if len(closed) else []
    reasons = list(closed["exit_reason"]) if len(closed) else []
    avg_equity = sum(equities) / n
    out = {
        "initial_capital": capital, "final_equity": final_equity,
        "total_pnl": final_equity - capital, "total_return": total_return,
        "benchmark_return": bench_return, "excess_return": total_return - bench_return,
        "trade_count": len(fills), "buy_count": len(buys), "sell_count": len(sells),
        "closed_count": len(pnls), "win_count": len(wins), "loss_count": len(losses),
        "even_count": len(pnls) - len(wins) - len(losses),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "payoff_ratio": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
                         if wins and losses else None),
        "max_loss_streak": best,
        "realized_pnl": sum(pnls), "gross_pnl": gross, "total_cost": total_cost,
        "buy_cost": buy_cost, "sell_cost": sell_cost, "cost_to_capital": total_cost / capital,
        "avg_hold_minutes": sum(holds) / len(holds) if holds else None,
        "avg_closed_per_day": len(pnls) / n, "avg_fills_per_day": len(fills) / n,
        "halt_days": int(sum(1 for h in daily["halted"] if bool(h))),
        "exit_reasons": {"breakdown": reasons.count("EXIT_BREAKDOWN"),
                         "eod": reasons.count("EXIT_EOD")},
        "total_trade_value": buy_value + sell_value, "buy_value": buy_value,
        "sell_value": sell_value,
        "total_trade_volume": int(fills["qty"].sum()) if has else 0,
        "avg_equity": avg_equity, "turnover": (buy_value + sell_value) / 2 / avg_equity,
        "trading_days": n,
        "cum_returns": [e / capital - 1.0 for e in equities],
    }
    out.update(_drawdown(equities, days, capital))
    return out


def per_stock(fills: pd.DataFrame, closed: pd.DataFrame, universe: list[dict],
              initial_cash: int) -> list[dict]:
    """유니버스 전 종목(config 순서). status: traded / no_trade (excluded는 report가 정한다)."""
    out = []
    for item in universe:
        code = item["code"]
        mine = fills[fills["code"] == code] if len(fills) else fills
        buys = mine[mine["side"] == "BUY"] if len(mine) else mine
        sells = mine[mine["side"] == "SELL"] if len(mine) else mine
        cl = closed[closed["code"] == code] if len(closed) else closed
        pnls = [int(x) for x in cl["pnl"]] if len(cl) else []
        holds = [int(x) for x in cl["hold_minutes"]] if len(cl) else []
        realized = sum(pnls)
        invested = int(buys["amount"].sum() + buys["cost"].sum()) if len(buys) else 0
        wins = sum(1 for p in pnls if p > 0)
        out.append({
            "code": code, "name": item.get("name") or code,
            "status": "traded" if len(mine) else "no_trade",
            "trade_count": len(mine), "buy_count": len(buys), "sell_count": len(sells),
            "closed_count": len(pnls), "win_count": wins,
            "loss_count": sum(1 for p in pnls if p < 0),
            "win_rate": wins / len(pnls) if pnls else None,
            "gross_pnl": int(cl["gross_pnl"].sum()) if len(cl) else 0,
            "cost": int(mine["cost"].sum()) if len(mine) else 0,
            "realized_pnl": realized,
            "ret": realized / invested if invested > 0 else None,
            "contribution": realized / initial_cash,
            "trade_value": int(mine["amount"].sum()) if len(mine) else 0,
            "trade_volume": int(mine["qty"].sum()) if len(mine) else 0,
            "avg_hold_minutes": sum(holds) / len(holds) if holds else None,
        })
    return out


def weekly_trade_value(fills: pd.DataFrame, days: list[date] | None = None) -> list[dict]:
    """ISO 주별 거래대금(매수 + 매도). days를 주면 거래 없는 주도 0으로 넣고 주 첫 거래일을 start로 쓴다."""
    weeks: dict[tuple[int, int], dict] = {}
    for d in sorted(days or []):
        weeks.setdefault(_iso_week(d), {"start": d, "buy_value": 0, "sell_value": 0})
    for f in (fills.to_dict("records") if len(fills) else []):
        w = weeks.setdefault(_iso_week(f["date"]), {"start": f["date"], "buy_value": 0, "sell_value": 0})
        w["start"] = min(w["start"], f["date"])
        w["buy_value" if f["side"] == "BUY" else "sell_value"] += int(f["amount"])
    out = []
    for key in sorted(weeks):
        w = weeks[key]
        out.append({"start": w["start"], "buy_value": w["buy_value"], "sell_value": w["sell_value"],
                    "value": w["buy_value"] + w["sell_value"]})
    return out
