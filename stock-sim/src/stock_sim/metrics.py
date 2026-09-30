"""지표 계산. 순수 함수. 비율은 반올림하지 않은 소수로 돌려준다(docs/strategy.md 6~7절)."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from stock_sim.strategy import is_valid_bar, to_bars

CLOSED_COLUMNS = ["code", "entry_date", "exit_date", "qty", "buy_price", "sell_price",
                  "cost_basis", "pnl", "ret", "holding_days"]


def _iso_week(d: date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


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


def equal_weight_return(prices: dict[str, pd.DataFrame], days: list[date]) -> float | None:
    """유니버스 동일가중 buy&hold: 평균_i(C_i(dn) / O_i(d1)) − 1. d1에 유효 봉이 있는 종목만."""
    if not days:
        return None
    d1, dn = days[0], days[-1]
    ratios = []
    for df in prices.values():
        bars = to_bars(df)
        first = bars.get(d1)
        if not is_valid_bar(first):
            continue
        last = None
        for d in sorted(bars):
            if d > dn:
                break
            if bars[d][1] > 0:
                last = bars[d][1]
        if last:
            ratios.append(last / first[0])
    return sum(ratios) / len(ratios) - 1.0 if ratios else None


def closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """매수~매도 한 쌍 단위. (청산일, 종목코드) 오름차순."""
    open_buys: dict[str, dict] = {}
    rows = []
    for t in trades.sort_values("id").to_dict("records"):
        if t["side"] == "BUY":
            open_buys[t["code"]] = t
        elif t["code"] in open_buys:
            b = open_buys.pop(t["code"])
            basis = int(b["amount"]) + int(b["cost"])
            pnl = int(t["amount"]) - int(t["cost"]) - basis
            rows.append({"code": t["code"], "entry_date": b["date"], "exit_date": t["date"],
                         "qty": int(t["qty"]), "buy_price": int(b["price"]),
                         "sell_price": int(t["price"]), "cost_basis": basis, "pnl": pnl,
                         "ret": pnl / basis, "holding_days": t["holding_days"]})
    rows.sort(key=lambda r: (r["exit_date"], r["code"]))
    return pd.DataFrame(rows, columns=CLOSED_COLUMNS)


def _drawdown(equities: list[int], days: list[date], capital: int) -> dict:
    peak, peak_date = capital, None           # 고점 후보에 E0 포함(날짜 없음)
    mdd, mdd_peak, mdd_trough, series = 0.0, None, None, []
    for d, e in zip(days, equities):
        if e > peak:
            peak, peak_date = e, d
        dd = e / peak - 1.0
        series.append(dd)
        if dd < mdd:
            mdd, mdd_peak, mdd_trough = dd, peak_date, d
    return {"mdd": mdd, "mdd_peak_date": mdd_peak, "mdd_trough_date": mdd_trough, "drawdowns": series}


def summarize(trades: pd.DataFrame, snapshots: pd.DataFrame, positions: pd.DataFrame,
              bench: pd.DataFrame, capital: int) -> dict:
    """summary 원값. 비율은 소수(0.0186)."""
    days = list(snapshots["date"])
    equities = [int(x) for x in snapshots["equity"]]
    final_equity = equities[-1]
    closed = closed_trades(trades)
    pnls = [int(x) for x in closed["pnl"]]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    streak = best = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        best = max(best, streak)
    buys, sells = trades[trades["side"] == "BUY"], trades[trades["side"] == "SELL"]
    buy_value, sell_value = int(buys["amount"].sum()), int(sells["amount"].sum())
    total_return = final_equity / capital - 1.0
    bench_return = float(bench["ret"].iloc[-1])
    avg_equity = sum(equities) / len(equities)
    prev, daily = capital, []
    for e in equities:
        daily.append(e / prev - 1.0)
        prev = e
    cash = int(snapshots["cash"].iloc[-1])
    out = {
        "initial_capital": int(capital), "final_equity": final_equity,
        "total_pnl": final_equity - int(capital), "total_return": total_return,
        "benchmark_return": bench_return, "excess_return": total_return - bench_return,
        "trade_count": len(trades), "buy_count": len(buys), "sell_count": len(sells),
        "closed_count": len(pnls), "win_count": len(wins), "loss_count": len(losses),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "payoff_ratio": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
                         if wins and losses else None),
        "max_loss_streak": best,
        "realized_pnl": sum(pnls),
        "unrealized_pnl": int(positions["unrealized_pnl"].sum()) if len(positions) else 0,
        "total_cost": int(trades["cost"].sum()) if len(trades) else 0,
        "holding_count": len(positions), "cash": cash, "cash_weight": cash / final_equity,
        "total_trade_value": buy_value + sell_value, "buy_value": buy_value,
        "sell_value": sell_value,
        "total_trade_volume": int(trades["qty"].sum()) if len(trades) else 0,
        "avg_equity": avg_equity, "turnover": (buy_value + sell_value) / 2 / avg_equity,
        "daily_returns": daily,
        "cum_returns": [e / capital - 1.0 for e in equities],
    }
    out.update(_drawdown(equities, days, int(capital)))
    return out


def per_stock(trades: pd.DataFrame, positions: pd.DataFrame, universe: list[dict],
              capital: int) -> list[dict]:
    """유니버스 전 종목의 거래·손익 집계(config 순서). status: held / closed / no_trade."""
    closed = closed_trades(trades)
    held = {r["code"]: r for r in positions.to_dict("records")}
    out = []
    for item in universe:
        code = item["code"]
        mine = trades[trades["code"] == code]
        buys, sells = mine[mine["side"] == "BUY"], mine[mine["side"] == "SELL"]
        pnls = [int(x) for x in closed[closed["code"] == code]["pnl"]]
        realized = sum(pnls)
        unrealized = int(held[code]["unrealized_pnl"]) if code in held else 0
        invested = int(buys["amount"].sum() + buys["cost"].sum()) if len(buys) else 0
        total = realized + unrealized
        wins = len([p for p in pnls if p > 0])
        out.append({
            "code": code, "name": item["name"],
            "status": "held" if code in held else ("closed" if len(mine) else "no_trade"),
            "trade_count": len(mine), "buy_count": len(buys), "sell_count": len(sells),
            "closed_count": len(pnls), "win_count": wins,
            "win_rate": wins / len(pnls) if pnls else None,
            "realized_pnl": realized, "unrealized_pnl": unrealized, "total_pnl": total,
            "ret": total / invested if invested > 0 else None,
            "contribution": total / capital,
            "trade_value": int(mine["amount"].sum()) if len(mine) else 0,
            "trade_volume": int(mine["qty"].sum()) if len(mine) else 0,
        })
    return out


def weekly_flow(trades: pd.DataFrame, snapshots: pd.DataFrame) -> list[dict]:
    """ISO 주별 매수·매도 거래대금, 주 마지막 거래일의 보유 평가액·현금."""
    weeks: dict[tuple[int, int], dict] = {}
    for s in snapshots.to_dict("records"):
        w = weeks.setdefault(_iso_week(s["date"]), {
            "start": s["date"], "trading_days": 0, "buy_value": 0, "sell_value": 0,
            "buy_count": 0, "sell_count": 0})
        w["end"] = s["date"]
        w["trading_days"] += 1
        w["holdings_value"], w["cash"] = int(s["holdings_value"]), int(s["cash"])
    for t in trades.to_dict("records"):
        w = weeks.get(_iso_week(t["date"]))
        if w is None:
            continue
        key = "buy" if t["side"] == "BUY" else "sell"
        w[f"{key}_value"] += int(t["amount"])
        w[f"{key}_count"] += 1
    return list(weeks.values())
