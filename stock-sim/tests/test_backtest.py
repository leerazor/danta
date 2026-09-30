"""체결 시뮬레이션 테스트. 기대값은 strategy.md 9.4~9.7절 손계산 그대로다."""
from datetime import date

import pandas as pd
import pytest

from helpers import BT_START, CAPITAL, COSTS, HAND_END, hand_prices, make_df, run_hand, syn_run
from stock_sim import backtest, data

D1, D4 = date(2026, 9, 21), date(2026, 9, 28)


def _trades(run):
    return run["bt"]["trades"].to_dict("records")


def test_9_4_fills_match_hand_calc():
    t = _trades(run_hand())
    assert [(x["id"], x["date"], x["code"], x["side"]) for x in t] == [
        (1, D1, "AAA", "BUY"), (2, D4, "AAA", "SELL"), (3, D4, "BBB", "BUY")]
    buy1, sell, buy2 = t
    assert (buy1["qty"], buy1["price"], buy1["amount"], buy1["cost"]) == (1941, 51_500, 99_961_500, 14_994)
    assert buy1["net_cash"] == -(99_961_500 + 14_994)
    assert (sell["qty"], sell["price"], sell["amount"], sell["cost"]) == (1941, 52_000, 100_932_000, 217_004)
    assert sell["net_cash"] == 100_932_000 - 217_004
    assert sell["realized_pnl"] == 738_502
    assert sell["realized_ret"] == pytest.approx(0.00738676, abs=1e-7)
    assert sell["holding_days"] == 3
    assert (buy2["qty"], buy2["price"], buy2["amount"], buy2["cost"]) == (941, 107_000, 100_687_000, 15_103)
    assert buy1["realized_pnl"] is None and buy1["holding_days"] is None
    assert buy1["reason"] == "목표 편입(순위 1)" and sell["reason"] == "목표 이탈"


def test_9_5_daily_ledger():
    snaps = run_hand()["bt"]["snapshots"]
    assert list(snaps["date"]) == [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
                                   date(2026, 9, 28), date(2026, 9, 29)]
    assert list(snaps["cash"]) == [23_506, 23_506, 23_506, 36_399, 36_399]
    assert list(snaps["holdings_value"]) == [100_932_000, 102_873_000, 101_902_500,
                                             101_628_000, 103_510_000]
    assert list(snaps["equity"]) == [100_955_506, 102_896_506, 101_926_006, 101_664_399, 103_546_399]
    assert list(snaps["position_count"]) == [1, 1, 1, 1, 1]
    assert list(snaps["realized_pnl_cum"]) == [0, 0, 0, 738_502, 738_502]


def test_period_end_position_is_marked_not_liquidated():
    bt = run_hand()["bt"]
    pos = bt["positions"].to_dict("records")
    assert len(pos) == 1
    p = pos[0]
    assert (p["code"], p["qty"], p["entry_date"], p["entry_price"]) == ("BBB", 941, D4, 107_000)
    assert (p["last_price"], p["market_value"]) == (110_000, 103_510_000)
    assert p["unrealized_pnl"] == 2_807_897          # 가상의 매도 비용은 빼지 않는다
    assert p["holding_days"] == 1
    assert len(bt["trades"]) == 3                    # 기간 말 강제 청산 없음


def test_9_7_case2_equal_weight_two_stocks():
    run = run_hand(top_n=2, end=D1)
    t = _trades(run)
    assert [(x["code"], x["qty"], x["amount"], x["cost"]) for x in t] == [
        ("AAA", 970, 49_955_000, 7_493), ("BBB", 494, 49_894_000, 7_484)]
    snap = run["bt"]["snapshots"].to_dict("records")[0]
    assert snap["cash"] == 136_023 and snap["equity"] == 99_976_023


def test_9_7_case3_expensive_stock_qty_zero():
    assert backtest.calc_qty(20_000_000, 21_000_000, 0.00015) == 0
    days = [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21)]
    prices = {"AAA": make_df([(d, 210_000_000, 210_000_000 + i, 10) for i, d in enumerate(days)])}
    cal = data.build_calendar(prices)
    sched = [(days[1], days[2])]
    targets = pd.DataFrame([{"signal_date": days[1], "fill_date": days[2], "code": "AAA",
                             "rank": 1, "score": 0.1}])
    bt = backtest.run_backtest(prices, cal, sched, targets, days[2], days[2], CAPITAL, 1, COSTS)
    assert len(bt["trades"]) == 0
    assert bt["snapshots"]["cash"].iloc[0] == CAPITAL
    ev = [e for e in bt["events"] if e["code"] == "QTY_ZERO_SKIP"]
    assert len(ev) == 1
    assert ev[0]["stock"] == "AAA" and ev[0]["side"] == "BUY" and ev[0]["value"] == 210_000_000
    assert ev[0]["extra"] == {"alloc": CAPITAL}


def test_9_7_case4_half_up_rounding():
    assert backtest.calc_cost(30_000, 0.00015) == 5      # 4.5 → 5 (은행가 반올림이면 4)
    assert backtest.calc_cost(10_000, 0.00015) == 2      # 1.5 → 2
    assert backtest.calc_cost(10_000, 0.00215) == 22     # 21.5 → 22
    assert backtest.calc_cost(99_961_500, 0.00015) == 14_994
    assert backtest.calc_cost(100_932_000, 0.00215) == 217_004
    assert backtest.rate_to_int((0.015 + 0.20) / 100) == 215_000   # 부동소수 오차 흡수


def test_fill_is_next_day_open_not_signal_close():
    run = run_hand()
    prices = run["prices"]
    for t in _trades(run):
        df = prices[t["code"]]
        row = df[df["date"] == pd.Timestamp(t["date"])].iloc[0]
        assert t["price"] == row["open"]                 # T+1 시가
        assert t["signal_date"] < t["date"]              # 신호는 T
        cal = run["calendar"]
        assert cal.index(t["date"]) - cal.index(t["signal_date"]) == 1


def test_costs_apply_on_both_sides():
    free = run_hand(costs={"buy_rate": 0.0, "sell_rate": 0.0, "slippage_rate": 0.0})
    paid = run_hand()
    assert all(t["cost"] == 0 for t in _trades(free))
    sides = {t["side"]: t["cost"] for t in _trades(paid)}
    assert sides["BUY"] > 0 and sides["SELL"] > 0
    assert paid["bt"]["snapshots"]["equity"].iloc[-1] < free["bt"]["snapshots"]["equity"].iloc[-1]


def test_slippage_moves_fill_price_half_up():
    assert backtest.fill_price(51_500, 0.001, "BUY") == 51_552      # 51,551.5 → 51,552
    assert backtest.fill_price(51_500, 0.001, "SELL") == 51_449     # 51,448.5 → 51,449
    assert backtest.fill_price(51_500, 0.0, "BUY") == 51_500


def test_integer_quantities_and_cash_never_negative():
    for run in (run_hand(), run_hand(top_n=2), syn_run()):
        trades, snaps = run["bt"]["trades"], run["bt"]["snapshots"]
        assert len(trades) > 0
        for t in trades.to_dict("records"):
            assert isinstance(t["qty"], int) and t["qty"] > 0
            assert t["amount"] == t["qty"] * t["price"]
        assert (snaps["cash"] >= 0).all()
        cash = CAPITAL
        for t in trades.to_dict("records"):              # 체결 도중에도 음수가 되지 않는다
            cash += t["net_cash"]
            assert cash >= 0
        assert cash == snaps["cash"].iloc[-1]


def test_position_count_never_exceeds_max_and_sells_come_first():
    run = syn_run()
    trades, snaps = run["bt"]["trades"], run["bt"]["snapshots"]
    assert (snaps["position_count"] <= 2).all()
    assert (trades["side"] == "SELL").any() and (trades["side"] == "BUY").any()
    for _, day in trades.groupby("date"):
        sides = list(day.sort_values("id")["side"])
        assert sides == sorted(sides, key=lambda s: 0 if s == "SELL" else 1)
    fill_dates = {f for _, f in run["schedule"]}
    assert set(trades["date"]) <= fill_dates


def test_halted_stock_cannot_be_sold_and_keeps_its_slot():
    prices = hand_prices()
    prices["AAA"].loc[prices["AAA"]["date"] == pd.Timestamp("2026-09-28"), "volume"] = 0
    bt = run_hand(prices=prices)["bt"]
    assert list(bt["trades"]["side"]) == ["BUY"]          # 매도 실패 → 자리 없음 → BBB 매수도 없음
    ev = [e for e in bt["events"] if e["code"] == "UNTRADABLE_SKIP"]
    assert [(e["stock"], e["side"], e["date"]) for e in ev] == [("AAA", "SELL", D4)]
    assert list(bt["positions"]["code"]) == ["AAA"]
    assert bt["snapshots"]["equity"].iloc[-1] == 23_506 + 1941 * 50_500


def test_limit_up_open_blocks_buy_without_replacement():
    prices = hand_prices()
    sel = prices["AAA"]["date"] == pd.Timestamp("2026-09-21")
    prices["AAA"].loc[sel, "open"] = 66_300               # 직전 종가 51,000 대비 +30%
    bt = run_hand(prices=prices, end=D1)["bt"]
    assert len(bt["trades"]) == 0
    assert [(e["code"], e["stock"], e["side"]) for e in bt["events"]] == [("UNTRADABLE_SKIP", "AAA", "BUY")]
    assert bt["snapshots"]["cash"].iloc[0] == CAPITAL


def test_missing_bar_on_fill_day_blocks_buy():
    prices = hand_prices()
    prices["AAA"] = prices["AAA"][prices["AAA"]["date"] != pd.Timestamp("2026-09-21")].reset_index(drop=True)
    bt = run_hand(prices=prices, end=D1)["bt"]
    assert len(bt["trades"]) == 0 and bt["events"][0]["code"] == "UNTRADABLE_SKIP"


def test_future_data_does_not_change_past_fills():
    """항등식 7.1-4: 체결일보다 늦은 날짜의 데이터를 바꿔도 과거 체결은 그대로다."""
    base = run_hand()["bt"]["trades"]
    changed = hand_prices()
    for df in changed.values():
        future = df["date"] > pd.Timestamp("2026-09-21")
        df.loc[future, ["open", "high", "low", "close"]] = df.loc[future, ["open", "high", "low", "close"]] * 2
    after = run_hand(prices=changed)["bt"]["trades"]
    cut = D1
    a = base[base["date"] <= cut].reset_index(drop=True)
    b = after[after["date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 1


def test_no_targets_means_no_trades():
    run = run_hand()
    empty = run["targets"].iloc[0:0]
    bt = backtest.run_backtest(run["prices"], run["calendar"], run["schedule"], empty,
                               BT_START, HAND_END, CAPITAL, 1, COSTS)
    assert len(bt["trades"]) == 0 and len(bt["positions"]) == 0
    assert list(bt["snapshots"]["equity"]) == [CAPITAL] * 5
    assert list(bt["trades"].columns) == backtest.TRADE_COLUMNS
