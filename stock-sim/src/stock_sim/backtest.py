"""장중 체결 엔진. 순수 함수(파일·네트워크·시계 접근 없음).

규칙은 docs/strategy.md 4.5·4.6절(하루 루프), 5절(체결·비용), 6절(사이징), 8절(엣지 케이스):
봉 시가에 대기 주문 체결(매도 먼저 → 매수, 각각 종목코드 오름차순) → 봉 종가에 신호 판정.
금액은 정수 원, 비용·슬리피지는 half-up 정수 연산, 현금은 음수가 되지 않는다.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pandas as pd

from stock_sim.strategy import slot_count, to_minutes

SCALE = 10 ** 8                 # 비율을 1억분율 정수로 바꿔 정수 연산한다
LIMIT_UP_PERMILLE = 1295        # 전일 종가 대비 +29.5% 이상 시가면 매수 취소
LIMIT_DOWN_PERMILLE = 705       # −29.5% 이하 시가 매도는 체결하되 PRICE_LIMIT_FILL
ANOMALY_PERMILLE = 100          # 5분봉 종가 ±10% 초과 등락이면 PRICE_ANOMALY(표시용)
FALLBACK_TIME = "15:30"
BLOCK_KEYS = ["halt", "max_entries", "cooldown", "cutoff", "range", "volume", "vwap"]
DEFAULT_SESSION = {"open": "09:00", "continuous_end": "15:20"}

FILL_COLUMNS = ["id", "date", "time", "signal_time", "code", "side", "qty", "price", "amount",
                "cost", "net_cash", "reason", "closed_id", "realized_pnl", "realized_ret",
                "hold_minutes"]
CLOSED_COLUMNS = ["id", "code", "date", "entry_time", "exit_time", "hold_minutes", "qty",
                  "entry_price", "exit_price", "gross_pnl", "cost", "pnl", "ret", "exit_reason",
                  "buy_fill_id", "sell_fill_id"]
DAY_COLUMNS = ["date", "e_start", "e_end", "halted", "skipped_codes"]


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
    """data.make_issue와 같은 모양(architecture.md 4.8절)."""
    return {"code": code, "stock": stock, "date": day, "value": value,
            "excluded": False, "side": side, "extra": extra or {}}


def _daily_lookup(daily: dict[str, pd.DataFrame]) -> dict[str, list[tuple[date, int, int]]]:
    """{code: [(date, open, close), …]} 오름차순."""
    out = {}
    for code, df in (daily or {}).items():
        if df is None or len(df) == 0:
            out[code] = []
            continue
        rows = sorted((ts.date(), int(o), int(c)) for ts, o, c in
                      zip(pd.to_datetime(df["date"]), df["open"], df["close"]))
        out[code] = rows
    return out


def _prev_close(rows: list[tuple[date, int, int]], d: date) -> int | None:
    last = None
    for day, _, close in rows:
        if day >= d:
            break
        if close > 0:
            last = close
    return last


def _day_close(rows: list[tuple[date, int, int]], d: date) -> int | None:
    for day, _, close in rows:
        if day == d and close > 0:
            return close
    return None


def _group_bars(bars: dict[str, pd.DataFrame]) -> dict[str, dict[date, list[dict]]]:
    out: dict[str, dict[date, list[dict]]] = {}
    for code, df in bars.items():
        per_day: dict[date, list[dict]] = {}
        if df is not None and len(df):
            for rec in df.sort_values(["date", "slot"], kind="stable").to_dict("records"):
                d = rec["date"].date() if isinstance(rec["date"], pd.Timestamp) else rec["date"]
                rec["date"] = d
                per_day.setdefault(d, []).append(rec)
        out[code] = per_day
    return out


def run_backtest(bars: dict[str, pd.DataFrame], daily: dict[str, pd.DataFrame],
                 auction: dict[str, dict[date, int]], params: dict, costs: dict,
                 initial_cash: int, session: dict | None = None) -> dict:
    """장중 백테스트. 반환 {"fills", "closed", "days", "blocks", "events"} (architecture.md 1.5절).

    session({"open", "continuous_end"})은 BAR_MISSING의 슬롯 수 계산에만 쓴다(기본 09:00~15:20).
    """
    session = session or DEFAULT_SESSION
    buy_rate, sell_rate = costs["buy_rate"], costs["sell_rate"]
    slippage = costs.get("slippage_rate", 0.0)
    bar_min = int(params.get("bar_minutes", 5))
    n_slots = slot_count(session["open"], session["continuous_end"], bar_min)
    force_exit = to_minutes(params["force_exit_time"])
    cooldown = int(params["cooldown_bars"])
    max_entries = int(params["max_entries_per_symbol_per_day"])
    min_bars = int(params["min_bars_per_day"])
    pos_pct = Fraction(str(params["position_pct"]))
    loss_pct = Fraction(str(params["daily_loss_limit_pct"]))

    grouped = _group_bars(bars)
    dailies = _daily_lookup(daily)
    codes = sorted(grouped)
    all_days = sorted({d for per_day in grouped.values() for d in per_day})

    cash = int(initial_cash)
    fills: list[dict] = []
    closed: list[dict] = []
    days: list[dict] = []
    events: list[dict] = []
    blocks = {"breakout": 0, **{k: 0 for k in BLOCK_KEYS}}

    for d in all_days:
        e_start = cash
        budget = int(e_start * pos_pct.numerator // pos_pct.denominator)
        halted, realized_today = False, 0
        day_bars = {c: grouped[c].get(d, []) for c in codes}
        active, skipped = [], []
        for c in codes:
            count = len(day_bars[c])
            if count >= min_bars and count > 0:
                active.append(c)
                missing = n_slots - count
                if missing > 0:
                    events.append(_event("BAR_MISSING", c, d, value=missing))
            else:
                skipped.append(c)
                events.append(_event("DAY_SKIPPED", c, d, value=count))
        for c in codes:                                   # 같은 날 안의 직전 유효 봉 대비(8절 7번)
            prev = None
            for b in day_bars[c]:
                if prev is not None and abs(b["close"] - prev) * 1000 > prev * ANOMALY_PERMILLE:
                    events.append(_event("PRICE_ANOMALY", c, d, value=b["close"] / prev - 1.0,
                                         extra={"time": b["time"]}))
                prev = b["close"]
        by_time = {c: {b["time"]: b for b in day_bars[c]} for c in active}
        slots = sorted({t for c in active for t in by_time[c]}, key=to_minutes)
        prev_close = {c: _prev_close(dailies.get(c, []), d) for c in active}
        state = {c: {"pos": None, "sell": None, "buy": None, "entries": 0, "exit_k": None,
                     "last_close": None} for c in active}

        def sell(c: str, t: str, raw_price: int, reason: str, signal_time: str | None) -> None:
            nonlocal cash, realized_today, halted
            st = state[c]
            pos = st["pos"]
            price = fill_price(raw_price, slippage, "SELL")
            pc = prev_close.get(c)
            if pc and raw_price * 1000 <= pc * LIMIT_DOWN_PERMILLE:
                events.append(_event("PRICE_LIMIT_FILL", c, d, value=price, side="SELL"))
            amount = pos["qty"] * price
            cost = calc_cost(amount, sell_rate)
            basis = pos["amount"] + pos["cost"]
            pnl = amount - cost - basis
            hold = to_minutes(t) - to_minutes(pos["time"])
            cash += amount - cost
            fill_id, closed_id = len(fills) + 1, len(closed) + 1
            fills.append({"id": fill_id, "date": d, "time": t, "signal_time": signal_time,
                          "code": c, "side": "SELL", "qty": pos["qty"], "price": price,
                          "amount": amount, "cost": cost, "net_cash": amount - cost,
                          "reason": reason, "closed_id": closed_id, "realized_pnl": pnl,
                          "realized_ret": pnl / basis, "hold_minutes": hold})
            fills[pos["fill_id"] - 1]["closed_id"] = closed_id
            closed.append({"id": closed_id, "code": c, "date": d, "entry_time": pos["time"],
                           "exit_time": t, "hold_minutes": hold, "qty": pos["qty"],
                           "entry_price": pos["price"], "exit_price": price,
                           "gross_pnl": pos["qty"] * (price - pos["price"]),
                           "cost": pos["cost"] + cost, "pnl": pnl, "ret": pnl / basis,
                           "exit_reason": reason, "buy_fill_id": pos["fill_id"],
                           "sell_fill_id": fill_id})
            st["pos"], st["sell"] = None, None
            realized_today += pnl
            if realized_today * loss_pct.denominator <= -loss_pct.numerator * e_start:
                halted = True

        for t in slots:
            here = [c for c in active if t in by_time[c]]
            # (1) 봉 시가: 매도 먼저(코드순)
            for c in here:
                st, bar = state[c], by_time[c][t]
                if st["pos"] is not None and (st["sell"] is not None or to_minutes(t) >= force_exit):
                    if st["sell"] is not None:
                        sell(c, t, bar["open"], "EXIT_BREAKDOWN", st["sell"])
                    else:
                        sell(c, t, bar["open"], "EXIT_EOD", None)
                    st["exit_k"] = bar["k"]
            # (1') 그다음 매수(코드순)
            for c in here:
                st, bar = state[c], by_time[c][t]
                if st["buy"] is None:
                    continue
                signal_time, signal_slot = st["buy"]
                st["buy"] = None
                if halted or bar["slot"] != signal_slot + 1:
                    continue
                pc = prev_close.get(c)
                if pc and bar["open"] * 1000 >= pc * LIMIT_UP_PERMILLE:
                    events.append(_event("UNTRADABLE_SKIP", c, d, value=bar["open"], side="BUY",
                                         extra={"time": t}))
                    continue
                price = fill_price(bar["open"], slippage, "BUY")
                alloc = min(budget, cash)
                qty = calc_qty(alloc, price, buy_rate)
                if qty == 0:
                    events.append(_event("QTY_ZERO_SKIP", c, d, value=price, side="BUY",
                                         extra={"alloc": int(alloc), "time": t}))
                    continue
                amount = qty * price
                cost = calc_cost(amount, buy_rate)
                cash -= amount + cost
                if cash < 0:
                    raise AssertionError("현금이 음수가 되었습니다(사이징 규칙 위반).")
                fill_id = len(fills) + 1
                fills.append({"id": fill_id, "date": d, "time": t, "signal_time": signal_time,
                              "code": c, "side": "BUY", "qty": qty, "price": price,
                              "amount": amount, "cost": cost, "net_cash": -(amount + cost),
                              "reason": "ENTRY_BREAKOUT", "closed_id": None, "realized_pnl": None,
                              "realized_ret": None, "hold_minutes": None})
                st["pos"] = {"qty": qty, "price": price, "amount": amount, "cost": cost,
                             "time": t, "fill_id": fill_id}
                st["entries"] += 1
            # (2) 봉 종가: 신호 판정(봉 t까지의 정보만). force_exit_time 이후 봉은 판정하지 않는다
            for c in here:
                st, bar = state[c], by_time[c][t]
                st["last_close"] = bar["close"]
                if to_minutes(t) >= force_exit:
                    continue
                if st["pos"] is not None:
                    if st["sell"] is None and bar["exit_signal"]:
                        st["sell"] = t
                    continue
                if st["buy"] is not None or not bar["breakout"]:
                    continue
                blocks["breakout"] += 1
                checks = [("halt", not halted), ("max_entries", st["entries"] < max_entries),
                          ("cooldown", st["exit_k"] is None or bar["k"] >= st["exit_k"] + cooldown),
                          ("cutoff", bool(bar["cutoff_ok"])), ("range", bool(bar["range_ok"])),
                          ("volume", bool(bar["volume_ok"])), ("vwap", bool(bar["vwap_ok"]))]
                failed = next((key for key, ok in checks if not ok), None)
                if failed is None:
                    st["buy"] = (t, bar["slot"])
                else:
                    blocks[failed] += 1
        # 장 마감: 남은 포지션은 대체가 청산(8절 5번, 사유 EXIT_EOD), 대기 매수는 버린다
        for c in active:
            st = state[c]
            if st["pos"] is None:
                continue
            price = (auction.get(c, {}).get(d) or _day_close(dailies.get(c, []), d)
                     or st["last_close"])
            sell(c, FALLBACK_TIME, price, "EXIT_EOD", None)
            events.append(_event("EOD_FALLBACK", c, d, value=fills[-1]["price"], side="SELL"))
        if any(state[c]["pos"] is not None for c in active):
            raise AssertionError("장 마감에 포지션이 남았습니다.")
        days.append({"date": d, "e_start": e_start, "e_end": cash, "halted": halted,
                     "skipped_codes": skipped})

    fills_df = pd.DataFrame(fills, columns=FILL_COLUMNS)
    for col in ("signal_time", "closed_id", "realized_pnl", "realized_ret", "hold_minutes"):
        fills_df[col] = pd.Series([f[col] for f in fills], dtype="object")   # None을 NaN으로 바꾸지 않는다
    return {
        "fills": fills_df,
        "closed": pd.DataFrame(closed, columns=CLOSED_COLUMNS),
        "days": pd.DataFrame(days, columns=DAY_COLUMNS),
        "blocks": blocks,
        "events": events,
    }
