"""backtest.py: strategy.md 10.4~10.7절 기대값, 8절 엣지 케이스, 9.2절 항등식 1~6."""
from datetime import date

import pandas as pd
import pytest

from helpers import (CAPITAL, COSTS, DEFAULT_SESSION, DEFAULT_TIME_PARAMS, HAND_PARAMS, HAND_SESSION,
                     as_bars, hand_bars5, run_hand)
from stock_sim import backtest, strategy

D = date(2026, 9, 21)


def _fills(bt):
    return bt["fills"].to_dict("records")


# ---- 10.4~10.6절 --------------------------------------------------------------------
def test_hand_example_fills_and_ledger():
    bt = run_hand()
    buy, sell = _fills(bt)
    assert (buy["side"], buy["time"], buy["signal_time"], buy["qty"], buy["price"]) == \
        ("BUY", "09:25", "09:20", 496, 100_700)
    assert (buy["amount"], buy["cost"], buy["net_cash"], buy["reason"]) == \
        (49_947_200, 7_492, -49_954_692, "ENTRY_BREAKOUT")
    assert (sell["side"], sell["time"], sell["signal_time"], sell["qty"], sell["price"]) == \
        ("SELL", "09:50", "09:45", 496, 100_500)
    assert (sell["amount"], sell["cost"], sell["realized_pnl"], sell["hold_minutes"]) == \
        (49_848_000, 107_173, -213_865, 25)
    assert sell["reason"] == "EXIT_BREAKDOWN"
    assert sell["realized_ret"] == pytest.approx(-0.00428118, abs=1e-8)
    assert buy["closed_id"] == sell["closed_id"] == 1
    day = bt["days"].iloc[0]
    assert (day["e_start"], day["e_end"], bool(day["halted"])) == (CAPITAL, 99_786_135, False)
    closed = bt["closed"].iloc[0]
    assert (closed["gross_pnl"], closed["cost"], closed["pnl"]) == (-99_200, 114_665, -213_865)
    assert (closed["entry_time"], closed["exit_time"], closed["buy_fill_id"], closed["sell_fill_id"]) == \
        ("09:25", "09:50", 1, 2)
    assert bt["blocks"] == {"breakout": 2, "halt": 0, "max_entries": 0, "cooldown": 1, "cutoff": 0,
                            "range": 0, "volume": 0, "vwap": 0}
    assert [e["code"] for e in bt["events"]] == []          # 10.1절 시각 설정: 무효 슬롯 0 → BAR_MISSING 없음


# ---- 10.7절 보조 케이스 -----------------------------------------------------------------
@pytest.mark.parametrize("sell_price,cost,pnl", [
    (100_500, 107_173, -213_865), (100_700, 107_386, -114_878),
    (100_900, 107_600, -15_892), (101_000, 107_706, 33_602)])
def test_case2_breakeven_table(sell_price, cost, pnl):
    amount = 496 * sell_price
    assert backtest.calc_cost(amount, 0.00215) == cost
    assert amount - cost - (49_947_200 + 7_492) == pnl


def test_case4_cooldown_release_signal_without_next_bar():
    params = {**DEFAULT_TIME_PARAMS, "cooldown_bars": 2}
    bt = run_hand(params=params, session=DEFAULT_SESSION)
    assert len(bt["fills"]) == 2                              # 봉 12 신호는 다음 봉이 없어 체결되지 않는다
    assert bt["blocks"]["breakout"] == 2
    assert sum(v for k, v in bt["blocks"].items() if k != "breakout") == 0


def _case5_bars(with_1515: bool) -> pd.DataFrame:
    df5 = hand_bars5().iloc[:9].copy()
    if with_1515:
        df5 = pd.concat([df5, pd.DataFrame([{"date": D, "time": "15:15", "open": 101_000, "high": 101_100,
                                             "low": 100_900, "close": 101_000, "volume": 500}])],
                        ignore_index=True)
    return df5


def test_case5_force_exit_at_1515_open():
    bt = run_hand(params=DEFAULT_TIME_PARAMS, session=DEFAULT_SESSION, df5=_case5_bars(True))
    sell = _fills(bt)[-1]
    assert (sell["time"], sell["reason"], sell["signal_time"], sell["price"]) == ("15:15", "EXIT_EOD", None, 101_000)
    assert (sell["amount"], sell["cost"], sell["realized_pnl"], sell["hold_minutes"]) == \
        (50_096_000, 107_706, 33_602, 350)
    assert bt["days"].iloc[0]["e_end"] == 100_033_602
    assert not [e for e in bt["events"] if e["code"] == "EOD_FALLBACK"]


def test_case5_fallback_to_1530_auction_close():
    bt = run_hand(params=DEFAULT_TIME_PARAMS, session=DEFAULT_SESSION, df5=_case5_bars(False),
                  auction={"AAA": {D: 101_000}})
    sell = _fills(bt)[-1]
    assert (sell["time"], sell["reason"], sell["signal_time"], sell["price"]) == ("15:30", "EXIT_EOD", None, 101_000)
    assert (sell["realized_pnl"], sell["hold_minutes"]) == (33_602, 365)
    fb = [e for e in bt["events"] if e["code"] == "EOD_FALLBACK"]
    assert len(fb) == 1 and fb[0]["value"] == 101_000 and fb[0]["date"] == D


def test_fallback_price_order_and_reason_even_with_pending_breakdown():
    # 15:10 봉 종가에 매도 신호가 났는데 15:15 봉이 없다 → 대체가 청산, 사유 EXIT_EOD, signal_time None
    df5 = hand_bars5().iloc[:9].copy()
    df5.loc[len(df5)] = [D, "15:10", 101_000, 101_000, 99_000, 99_000, 500]
    daily = {"AAA": pd.DataFrame({"date": pd.to_datetime([D]), "open": [100_000], "high": [1],
                                  "low": [1], "close": [100_900], "volume": [1], "value": [1]})}
    bt = run_hand(params=DEFAULT_TIME_PARAMS, session=DEFAULT_SESSION, df5=df5, daily=daily)
    sell = _fills(bt)[-1]
    assert (sell["time"], sell["reason"], sell["signal_time"], sell["price"]) == ("15:30", "EXIT_EOD", None, 100_900)
    bt2 = run_hand(params=DEFAULT_TIME_PARAMS, session=DEFAULT_SESSION, df5=df5)
    assert _fills(bt2)[-1]["price"] == 99_000                  # 일봉도 없으면 마지막 유효 5분봉 종가


def test_case6_daily_loss_halt():
    bt = run_hand(params={**HAND_PARAMS, "daily_loss_limit_pct": 0.002})
    assert bool(bt["days"].iloc[0]["halted"]) is True
    assert bt["blocks"]["halt"] == 1 and bt["blocks"]["cooldown"] == 0


def test_case7_rounding_half_up():
    assert backtest.calc_cost(30_000, 0.00015) == 5
    assert backtest.calc_cost(10_000, 0.00215) == 22
    assert backtest.fill_price(100_000, 0.001, "BUY") == 100_100
    assert backtest.fill_price(100_000, 0.001, "SELL") == 99_900
    assert backtest.calc_qty(50_000_000, 100_700, 0.00015) == 496


# ---- 8절 엣지 케이스 -------------------------------------------------------------------
def test_buy_cancelled_when_next_slot_is_invalid():
    df5 = hand_bars5().drop(index=5).reset_index(drop=True)   # 09:25 슬롯이 무효
    bt = run_hand(df5=df5)
    assert len(bt["fills"]) == 0


def test_pending_sell_carries_over_an_invalid_slot():
    df5 = hand_bars5().drop(index=10).reset_index(drop=True)  # 매도 대기 뒤 09:50 슬롯이 무효
    bt = run_hand(df5=df5)
    sell = _fills(bt)[-1]
    assert (sell["time"], sell["price"], sell["reason"]) == ("09:55", 100_400, "EXIT_BREAKDOWN")


def test_limit_up_open_cancels_buy():
    daily = {"AAA": pd.DataFrame({"date": pd.to_datetime(["2026-09-18"]), "open": [77_000], "high": [1],
                                  "low": [1], "close": [77_000], "volume": [1], "value": [1]})}
    bt = run_hand(daily=daily)                                  # 100,700 ≥ 77,000 × 1.295 = 99,715
    assert len(bt["fills"]) == 0
    assert [e["code"] for e in bt["events"]] == ["UNTRADABLE_SKIP"]


def test_limit_down_sell_is_filled_with_alert():
    daily = {"AAA": pd.DataFrame({"date": pd.to_datetime(["2026-09-18"]), "open": [143_000], "high": [1],
                                  "low": [1], "close": [143_000], "volume": [1], "value": [1]})}
    bt = run_hand(daily=daily)                                  # 100,500 ≤ 143,000 × 0.705 = 100,815
    assert len(bt["fills"]) == 2
    assert [e["code"] for e in bt["events"]] == ["PRICE_LIMIT_FILL"]


def test_day_skipped_bar_missing_and_price_anomaly():
    params = {**HAND_PARAMS, "min_bars_per_day": 14}
    bt = run_hand(params=params)
    assert len(bt["fills"]) == 0
    ev = bt["events"]
    assert [(e["code"], e["value"]) for e in ev] == [("DAY_SKIPPED", 13)]
    assert bt["days"].iloc[0]["skipped_codes"] == ["AAA"]
    bt2 = run_hand(session=DEFAULT_SESSION)                     # 76 − 13 = 63 무효 슬롯
    assert [(e["code"], e["value"]) for e in bt2["events"]] == [("BAR_MISSING", 63)]
    df5 = hand_bars5()
    df5.loc[7, "close"] = 112_000                               # 101,400 → 112,000: +10.45%
    bt3 = run_hand(df5=df5)
    anomalies = [e for e in bt3["events"] if e["code"] == "PRICE_ANOMALY"]
    assert anomalies[0]["extra"]["time"] == "09:35" and anomalies[0]["value"] > 0.10


def test_qty_zero_skip():
    bt = backtest.run_backtest({"AAA": strategy.signals(as_bars(hand_bars5()), HAND_PARAMS)}, {}, {},
                               HAND_PARAMS, COSTS, 150_000, session=HAND_SESSION)
    assert len(bt["fills"]) == 0
    ev = [e for e in bt["events"] if e["code"] == "QTY_ZERO_SKIP"]
    assert ev[0]["value"] == 100_700 and ev[0]["extra"]["alloc"] == 75_000


def _two_code_bars():
    a = hand_bars5()
    b = hand_bars5()
    return {"AAA": strategy.signals(as_bars(a), HAND_PARAMS),
            "BBB": strategy.signals(as_bars(b), HAND_PARAMS)}


def test_same_bar_orders_by_code_and_budget_per_code():
    bt = backtest.run_backtest(_two_code_bars(), {}, {}, HAND_PARAMS, COSTS, CAPITAL, session=HAND_SESSION)
    f = _fills(bt)
    assert [(x["time"], x["code"], x["side"]) for x in f] == [
        ("09:25", "AAA", "BUY"), ("09:25", "BBB", "BUY"), ("09:50", "AAA", "SELL"), ("09:50", "BBB", "SELL")]
    assert f[0]["qty"] == f[1]["qty"] == 496
    assert [c for c in bt["closed"]["code"]] == ["AAA", "BBB"]
    assert list(bt["closed"]["id"]) == [1, 2]


def _shifted_pair_run(limit):
    """AAA = 손계산 봉, BBB = 같은 봉을 +25분 옮긴 입력. BBB 매수 체결 봉 = AAA 매도 체결 봉(09:50)."""
    a = hand_bars5()
    b = a.copy()
    b["time"] = [f"{m // 60:02d}:{m % 60:02d}" for m in (strategy.to_minutes(t) + 25 for t in b["time"])]
    params = {**HAND_PARAMS, "daily_loss_limit_pct": limit}
    bars = {"AAA": strategy.signals(as_bars(a), params), "BBB": strategy.signals(as_bars(b), params)}
    return backtest.run_backtest(bars, {}, {}, params, COSTS, CAPITAL, session=HAND_SESSION)


def test_halt_by_sell_cancels_same_bar_pending_buy():
    """strategy.md 4.6절 5번: 매도 체결로 halted가 되면 같은 봉의 대기 매수를 취소한다."""
    bt = _shifted_pair_run(0.002)                             # AAA 손실 213,865 > 한도 200,000
    assert [(x["time"], x["code"], x["side"]) for x in _fills(bt)] == [
        ("09:25", "AAA", "BUY"), ("09:50", "AAA", "SELL")]   # 09:50 BBB 대기 매수(09:45 신호) 취소
    assert _fills(bt)[1]["realized_pnl"] == -213_865
    assert bool(bt["days"].iloc[0]["halted"]) is True
    assert bt["blocks"]["halt"] >= 1

    # 대조: 한도 1%(1,000,000)면 halted가 아니므로 같은 봉에서 AAA 매도 뒤 BBB 매수가 체결된다
    bt2 = _shifted_pair_run(0.01)
    f2 = _fills(bt2)
    assert [(x["time"], x["code"], x["side"]) for x in f2[:3]] == [
        ("09:25", "AAA", "BUY"), ("09:50", "AAA", "SELL"), ("09:50", "BBB", "BUY")]
    assert (f2[2]["signal_time"], f2[2]["qty"], f2[2]["price"]) == ("09:45", 496, 100_700)
    assert bool(bt2["days"].iloc[0]["halted"]) is False
    assert bt2["blocks"]["halt"] == 0


def test_max_entries_per_day():
    params = {**HAND_PARAMS, "cooldown_bars": 0, "max_entries_per_symbol_per_day": 1}
    bt = run_hand(params=params)
    assert bt["blocks"]["max_entries"] == 1 and len(bt["fills"]) == 2


# ---- 9.2절 항등식 ----------------------------------------------------------------------
def _check_identities(bt, params, initial=CAPITAL):
    fills, closed, days = bt["fills"], bt["closed"], bt["days"]
    final = int(days.iloc[-1]["e_end"])
    assert final - initial == int(closed["pnl"].sum()) == int(closed["gross_pnl"].sum()) - int(closed["cost"].sum())
    buys, sells = fills[fills["side"] == "BUY"], fills[fills["side"] == "SELL"]
    cash = initial - int((buys["amount"] + buys["cost"]).sum()) + int((sells["amount"] - sells["cost"]).sum())
    assert cash == final
    assert len(buys) == len(sells) == len(closed)
    running = initial
    for f in fills.to_dict("records"):
        running += int(f["net_cash"])
        assert running >= 0 and f["qty"] > 0
    per_day = buys.groupby(["date", "code"]).size()
    assert (per_day <= params["max_entries_per_symbol_per_day"]).all()
    cutoff = strategy.to_minutes(params["entry_cutoff"])
    for f in buys.to_dict("records"):
        assert strategy.to_minutes(f["time"]) <= cutoff
    for f in fills.to_dict("records"):
        if f["signal_time"] is not None:
            assert strategy.to_minutes(f["time"]) > strategy.to_minutes(f["signal_time"])
    for i in range(1, len(days)):
        assert days.iloc[i]["e_start"] == days.iloc[i - 1]["e_end"]


def test_identities_on_hand_example_and_two_codes():
    _check_identities(run_hand(), HAND_PARAMS)
    _check_identities(backtest.run_backtest(_two_code_bars(), {}, {}, HAND_PARAMS, COSTS, CAPITAL,
                                            session=HAND_SESSION), HAND_PARAMS)


def test_lookahead_changing_bars_after_k_keeps_fills_up_to_k_plus_1_open():
    base = _fills(run_hand())
    for k in range(12):
        df5 = hand_bars5()
        later = df5.index > k
        for col, delta in (("high", 3_000), ("low", -2_500), ("close", 900)):
            df5.loc[later, col] = df5.loc[later, col] + delta
        df5.loc[later, "volume"] = df5.loc[later, "volume"] * 5 + 1    # 유효 봉 수는 유지(0 금지)
        df5.loc[df5.index > k + 1, "open"] = df5.loc[df5.index > k + 1, "open"] + 400
        got = _fills(run_hand(df5=df5))
        cut = strategy.to_minutes(hand_bars5().iloc[k + 1]["time"])
        keep = [f for f in base if strategy.to_minutes(f["time"]) <= cut]
        assert [f for f in got if strategy.to_minutes(f["time"]) <= cut] == keep, k


def test_lookahead_previous_day_change_keeps_today():
    prev = hand_bars5().assign(date=date(2026, 9, 18))
    today = hand_bars5()
    both = pd.concat([prev, today], ignore_index=True)
    params = {**HAND_PARAMS, "daily_loss_limit_pct": 1.0}
    bt1 = backtest.run_backtest({"AAA": strategy.signals(as_bars(both), params)}, {}, {}, params, COSTS,
                                CAPITAL, session=HAND_SESSION)
    prev2 = prev.copy()
    prev2["close"] = prev2["close"] + 50_000
    prev2["high"] = prev2["high"] + 60_000
    both2 = pd.concat([prev2, today], ignore_index=True)
    bt2 = backtest.run_backtest({"AAA": strategy.signals(as_bars(both2), params)}, {}, {}, params, COSTS,
                                CAPITAL, session=HAND_SESSION)
    # 전일 종료 현금이 다르면 수량이 달라질 수 있으므로 신호·시각·가격만 비교한다
    def sig(bt):
        f = bt["fills"]
        return [(x["time"], x["side"], x["price"], x["signal_time"]) for x in f[f["date"] == date(2026, 9, 21)].to_dict("records")]
    assert sig(bt1) == sig(bt2)


def test_zero_trades_day():
    df5 = hand_bars5()
    df5["volume"] = 1                                           # 거래량 필터가 막는다
    bt = run_hand(df5=df5)
    assert len(bt["fills"]) == 0 and bt["days"].iloc[0]["e_end"] == CAPITAL
    assert bt["blocks"]["breakout"] >= 1
