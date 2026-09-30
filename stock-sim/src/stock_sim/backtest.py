"""체결 시뮬레이션. 순수 함수(파일·네트워크·시계 접근 없음).

규칙은 docs/strategy.md 3~5절·8절: 신호일(T) 종가 → 체결일(T+1) 시가, 매도 먼저,
동일 비중, 1주 단위, 비용은 원 단위 half-up(정수 연산), 현금은 음수가 되지 않는다.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from stock_sim.strategy import is_valid_bar, to_bars

SCALE = 10 ** 8                 # 비율을 1억분율 정수로 바꿔 정수 연산한다
LIMIT_UP_PERMILLE = 1295        # 직전 유효 종가 대비 +29.5% 이상이면 매수 불가
LIMIT_DOWN_PERMILLE = 705       # −29.5% 이하면 매도 불가

TRADE_COLUMNS = ["id", "date", "signal_date", "code", "side", "qty", "price", "amount", "cost",
                 "net_cash", "realized_pnl", "realized_ret", "holding_days", "reason"]
SNAPSHOT_COLUMNS = ["date", "cash", "holdings_value", "equity", "position_count", "realized_pnl_cum"]
POSITION_COLUMNS = ["code", "qty", "entry_date", "entry_price", "buy_amount", "buy_cost",
                    "last_price", "market_value", "unrealized_pnl", "unrealized_ret", "holding_days"]


def rate_to_int(rate: float) -> int:
    """비율(0.00015) → 1억분율 정수(15000). 부동소수 오차를 피하려 Decimal을 거친다."""
    return int((Decimal(str(rate)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def calc_cost(amount: int, rate: float) -> int:
    """비용 = 거래대금 × 율, 원 단위 half-up."""
    return (int(amount) * rate_to_int(rate) + SCALE // 2) // SCALE


def fill_price(open_price: int, slippage_rate: float, side: str) -> int:
    """체결가 = 시가 × (1 ± 슬리피지), 원 단위 half-up."""
    slip = rate_to_int(slippage_rate)
    factor = SCALE + slip if side == "BUY" else SCALE - slip
    return (int(open_price) * factor + SCALE // 2) // SCALE


def calc_qty(alloc: int, price: int, buy_rate: float) -> int:
    """수량 = floor(alloc / (체결가 × (1 + buy_rate))). 비용 포함 금액이 alloc을 넘지 않게 정수로 검증."""
    if price <= 0 or alloc <= 0:
        return 0
    qty = (int(alloc) * SCALE) // (int(price) * (SCALE + rate_to_int(buy_rate)))
    while qty > 0 and qty * price + calc_cost(qty * price, buy_rate) > alloc:
        qty -= 1
    return int(qty)


def _event(code: str, stock: str, day: date, value=None, side: str | None = None,
           extra: dict | None = None) -> dict:
    return {"code": code, "stock": stock, "date": day, "value": value,
            "excluded": False, "side": side, "extra": extra or {}}


def _carried_closes(bars: dict[date, tuple], calendar: list[date]) -> dict[date, int | None]:
    """달력의 각 날짜에 대해 그 날까지의 마지막 유효 종가(> 0)."""
    out: dict[date, int | None] = {}
    last = None
    for d in calendar:
        bar = bars.get(d)
        if bar is not None and bar[1] > 0:
            last = bar[1]
        out[d] = last
    return out


def run_backtest(prices: dict[str, pd.DataFrame], calendar: list[date],
                 schedule: list[tuple[date, date]], targets: pd.DataFrame,
                 start: date, end: date, capital: int, max_positions: int,
                 costs: dict) -> dict:
    buy_rate, sell_rate = costs["buy_rate"], costs["sell_rate"]
    slippage = costs.get("slippage_rate", 0.0)
    bars = {code: to_bars(df) for code, df in prices.items()}
    closes = {code: _carried_closes(b, calendar) for code, b in bars.items()}
    index = {d: i for i, d in enumerate(calendar)}
    fills = {fill: sig for sig, fill in schedule}
    target_map: dict[date, list[tuple[str, int]]] = {}
    if targets is not None and len(targets):
        ordered = targets.sort_values(["fill_date", "rank"], kind="stable")
        for fill, code, rank in zip(ordered["fill_date"], ordered["code"], ordered["rank"]):
            target_map.setdefault(fill, []).append((str(code), int(rank)))

    cash = int(capital)
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    snapshots: list[dict] = []
    events: list[dict] = []
    realized_cum = 0

    def record(day, signal_day, code, side, qty, price, cost, reason, pnl=None, ret=None, hold=None):
        amount = qty * price
        net = -(amount + cost) if side == "BUY" else amount - cost
        trades.append({"id": len(trades) + 1, "date": day, "signal_date": signal_day, "code": code,
                       "side": side, "qty": qty, "price": price, "amount": amount, "cost": cost,
                       "net_cash": net, "realized_pnl": pnl, "realized_ret": ret,
                       "holding_days": hold, "reason": reason})
        return net

    for d in (x for x in calendar if start <= x <= end):
        if d in fills:
            p = fills[d]                                   # 신호일: d 직전 거래일
            prev_day = calendar[index[d] - 1]
            target = target_map.get(d, [])
            target_codes = [c for c, _ in target]
            # 신호일 종가 기준 평가액 (p까지의 정보만 사용)
            e_ref = cash + sum(pos["qty"] * (closes[c][p] or 0) for c, pos in positions.items())
            # 1) 매도 먼저: 목표에 없는 보유 종목, 종목코드 오름차순
            for code in sorted(set(positions) - set(target_codes)):
                bar = bars[code].get(d)
                prev_close = closes[code][prev_day]
                blocked = not is_valid_bar(bar) or (
                    prev_close and bar[0] * 1000 <= prev_close * LIMIT_DOWN_PERMILLE)
                if blocked:
                    events.append(_event("UNTRADABLE_SKIP", code, d, side="SELL"))
                    continue
                pos = positions.pop(code)
                price = fill_price(bar[0], slippage, "SELL")
                cost = calc_cost(pos["qty"] * price, sell_rate)
                basis = pos["buy_amount"] + pos["buy_cost"]
                pnl = pos["qty"] * price - cost - basis
                cash += record(d, p, code, "SELL", pos["qty"], price, cost, "목표 이탈", pnl,
                               pnl / basis, index[d] - index[pos["entry_date"]])
                realized_cum += pnl
            # 2) 매수: 목표 중 미보유 종목, 순위순. 막힌 자리는 대체하지 않는다
            slots = max(max_positions - len(positions), 0)
            candidates = [(c, r) for c, r in target if c not in positions][:slots]
            buyable: list[tuple[str, int, int]] = []
            for code, rank in candidates:
                bar = bars.get(code, {}).get(d)
                prev_close = closes.get(code, {}).get(prev_day)
                blocked = not is_valid_bar(bar) or (
                    prev_close and bar[0] * 1000 >= prev_close * LIMIT_UP_PERMILLE)
                if blocked:
                    events.append(_event("UNTRADABLE_SKIP", code, d, side="BUY"))
                    continue
                buyable.append((code, rank, bar[0]))
            if buyable:
                alloc = min(e_ref // max_positions, cash // len(buyable))   # 한 번만 계산
                for code, rank, open_price in buyable:
                    price = fill_price(open_price, slippage, "BUY")
                    qty = calc_qty(alloc, price, buy_rate)
                    if qty == 0:
                        events.append(_event("QTY_ZERO_SKIP", code, d, value=price, side="BUY",
                                             extra={"alloc": int(alloc)}))
                        continue
                    cost = calc_cost(qty * price, buy_rate)
                    cash += record(d, p, code, "BUY", qty, price, cost, f"목표 편입(순위 {rank})")
                    positions[code] = {"qty": qty, "entry_date": d, "entry_price": price,
                                       "buy_amount": qty * price, "buy_cost": cost}
            if cash < 0:
                raise AssertionError("현금이 음수가 되었습니다(사이징 규칙 위반).")
        # 3) 종가 평가 (매일). 종가 결측은 직전 유효 종가
        holdings = sum(pos["qty"] * (closes[c][d] or 0) for c, pos in positions.items())
        snapshots.append({"date": d, "cash": cash, "holdings_value": holdings,
                          "equity": cash + holdings, "position_count": len(positions),
                          "realized_pnl_cum": realized_cum})

    pos_rows: list[dict] = []
    if snapshots:
        last_day = snapshots[-1]["date"]
        for code, pos in positions.items():
            last_price = closes[code][last_day] or 0
            basis = pos["buy_amount"] + pos["buy_cost"]
            value = pos["qty"] * last_price
            pos_rows.append({"code": code, "qty": pos["qty"], "entry_date": pos["entry_date"],
                             "entry_price": pos["entry_price"], "buy_amount": pos["buy_amount"],
                             "buy_cost": pos["buy_cost"], "last_price": last_price,
                             "market_value": value, "unrealized_pnl": value - basis,
                             "unrealized_ret": (value - basis) / basis,
                             "holding_days": index[last_day] - index[pos["entry_date"]]})
    trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    for col in ("realized_pnl", "realized_ret", "holding_days"):   # None을 NaN으로 바꾸지 않는다
        trades_df[col] = pd.Series([t[col] for t in trades], dtype="object")
    return {
        "trades": trades_df,
        "snapshots": pd.DataFrame(snapshots, columns=SNAPSHOT_COLUMNS),
        "positions": pd.DataFrame(pos_rows, columns=POSITION_COLUMNS),
        "events": events,
    }
