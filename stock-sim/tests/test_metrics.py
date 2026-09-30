"""지표 테스트. 기대값은 strategy.md 9.5~9.6절, 항등식은 7.1절."""
from datetime import date

import pandas as pd
import pytest

from helpers import BT_START, CAPITAL, COSTS, HAND_END, hand_index, run_hand, syn_run
from stock_sim import backtest, metrics

universe = [{"code": "AAA", "name": "에이"}, {"code": "BBB", "name": "비"}]


def _summary(run):
    bt = run["bt"]
    return metrics.summarize(bt["trades"], bt["snapshots"], bt["positions"], run["bench"], CAPITAL)


def test_9_6_expected_metrics():
    run = run_hand()
    s = _summary(run)
    assert s["final_equity"] == 103_546_399
    assert s["total_return"] == pytest.approx(0.03546399, abs=1e-8)
    assert s["mdd"] == pytest.approx(-0.01197424, abs=1e-8)
    assert s["mdd_peak_date"] == date(2026, 9, 22) and s["mdd_trough_date"] == date(2026, 9, 28)
    assert (s["trade_count"], s["buy_count"], s["sell_count"]) == (3, 2, 1)
    assert (s["closed_count"], s["win_count"], s["loss_count"]) == (1, 1, 0)
    assert s["win_rate"] == 1.0
    assert s["payoff_ratio"] is None
    assert s["realized_pnl"] == 738_502 and s["unrealized_pnl"] == 2_807_897
    assert s["total_trade_value"] == 301_580_500
    assert s["total_cost"] == 247_101
    assert s["avg_equity"] == pytest.approx(102_197_763.2, abs=0.01)
    assert s["turnover"] == pytest.approx(1.475475, abs=1e-6)
    assert s["max_loss_streak"] == 0
    assert s["benchmark_return"] == pytest.approx(0.02, abs=1e-12)
    assert s["excess_return"] == pytest.approx(0.01546399, abs=1e-8)
    assert s["total_return"] / 0.02 == pytest.approx(1.7732, abs=1e-4)
    assert s["cash"] == 36_399 and s["holding_count"] == 1
    assert s["total_trade_volume"] == 1941 + 1941 + 941


def test_9_5_daily_returns_and_drawdowns():
    s = _summary(run_hand())
    expected = [0.00955506, 0.01922629, -0.00943181, -0.00256664, 0.01851189]
    assert s["daily_returns"] == pytest.approx(expected, abs=1e-7)
    assert s["drawdowns"] == pytest.approx([0, 0, -0.00943181, -0.01197424, 0], abs=1e-7)


def test_benchmark_curve_uses_d1_open():
    run = run_hand()
    assert run["bench_info"] == {"base_price": 4000.0, "base_kind": "d1_open"}
    assert list(run["bench"]["value"]) == [100_500_000, 101_000_000, 100_250_000,
                                           101_500_000, 102_000_000]
    assert run["bench"]["ret"].iloc[-1] == pytest.approx(0.02)


def test_benchmark_falls_back_to_prev_close_and_fills_gaps():
    idx = hand_index()
    idx.loc[idx["date"] == pd.Timestamp("2026-09-22"), "open"] = 0.0
    idx = idx[idx["date"] != pd.Timestamp("2026-09-23")]
    days = [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 28)]
    bench, info = metrics.benchmark_curve(idx, days, CAPITAL)
    assert info == {"base_price": 4020.0, "base_kind": "prev_close"}
    assert list(bench["close"]) == [4040.0, 4040.0, 4060.0]      # 결측일은 직전 값
    with pytest.raises(ValueError):
        metrics.benchmark_curve(idx.iloc[0:0], days, CAPITAL)


def test_equal_weight_buy_and_hold():
    run = run_hand()
    assert metrics.equal_weight_return(run["prices"], run["days"]) == pytest.approx(0.03484572, abs=1e-8)
    assert metrics.equal_weight_return({}, run["days"]) is None


def test_closed_trades_and_per_stock():
    run = run_hand()
    bt = run["bt"]
    closed = metrics.closed_trades(bt["trades"]).to_dict("records")
    assert len(closed) == 1
    c = closed[0]
    assert (c["code"], c["pnl"], c["cost_basis"]) == ("AAA", 738_502, 99_976_494)
    assert c["ret"] == pytest.approx(0.00738676, abs=1e-7)
    stocks = {s["code"]: s for s in metrics.per_stock(bt["trades"], bt["positions"], universe, CAPITAL)}
    a, b = stocks["AAA"], stocks["BBB"]
    assert (a["status"], a["trade_count"], a["closed_count"], a["win_count"]) == ("closed", 2, 1, 1)
    assert (a["realized_pnl"], a["unrealized_pnl"], a["total_pnl"]) == (738_502, 0, 738_502)
    assert a["win_rate"] == 1.0 and a["trade_value"] == 99_961_500 + 100_932_000
    assert (b["status"], b["realized_pnl"], b["unrealized_pnl"]) == ("held", 0, 2_807_897)
    assert b["win_rate"] is None
    assert b["ret"] == pytest.approx(2_807_897 / (100_687_000 + 15_103))
    assert a["contribution"] + b["contribution"] == pytest.approx(0.03546399, abs=1e-8)


def test_weekly_flow():
    bt = run_hand()["bt"]
    weeks = metrics.weekly_flow(bt["trades"], bt["snapshots"])
    assert len(weeks) == 2
    w1, w2 = weeks
    assert (w1["start"], w1["end"], w1["trading_days"]) == (date(2026, 9, 21), date(2026, 9, 23), 3)
    assert (w1["buy_value"], w1["sell_value"], w1["buy_count"], w1["sell_count"]) == (99_961_500, 0, 1, 0)
    assert (w1["holdings_value"], w1["cash"]) == (101_902_500, 23_506)
    assert (w2["buy_value"], w2["sell_value"]) == (100_687_000, 100_932_000)
    assert (w2["holdings_value"], w2["cash"], w2["trading_days"]) == (103_510_000, 36_399, 2)


@pytest.mark.parametrize("make", [run_hand, lambda: run_hand(top_n=2), syn_run])
def test_identities_7_1(make):
    run = make()
    bt = run["bt"]
    trades, snaps = bt["trades"], bt["snapshots"]
    s = metrics.summarize(trades, snaps, bt["positions"], run["bench"], CAPITAL)
    # 1. E(dn) − E0 = 실현 손익 합 + 평가 손익 합
    assert s["final_equity"] - CAPITAL == s["realized_pnl"] + s["unrealized_pnl"]
    # 2. 최종 현금 = E0 − Σ(매수 거래대금 + 비용) + Σ(매도 거래대금 − 비용)
    buys, sells = trades[trades["side"] == "BUY"], trades[trades["side"] == "SELL"]
    cash = (CAPITAL - int(buys["amount"].sum() + buys["cost"].sum())
            + int(sells["amount"].sum() - sells["cost"].sum()))
    assert cash == s["cash"] == int(snaps["cash"].iloc[-1])
    # 3. 현금 ≥ 0, 수량은 양의 정수
    assert (snaps["cash"] >= 0).all() and (trades["qty"] > 0).all()
    assert (snaps["equity"] == snaps["cash"] + snaps["holdings_value"]).all()
    # 종목별 합 = 전체
    uni = [{"code": c, "name": c} for c in run["prices"]]
    stocks = metrics.per_stock(trades, bt["positions"], uni, CAPITAL)
    assert sum(x["total_pnl"] for x in stocks) == s["total_pnl"]
    assert s["mdd"] <= 0


def test_mdd_peak_is_start_when_first_day_is_below_capital():
    run = run_hand(top_n=2, end=date(2026, 9, 21))       # D1 평가액 99,976,023 < E0
    s = _summary(run)
    assert s["mdd"] == pytest.approx(99_976_023 / CAPITAL - 1)
    assert s["mdd_peak_date"] is None and s["mdd_trough_date"] == date(2026, 9, 21)


def test_mdd_peak_tie_takes_day_closest_to_trough():
    days = [date(2026, 9, d) for d in range(1, 6)]
    dd = metrics._drawdown([101, 100, 101, 99, 99], days, 100)   # strategy.md 10.1절 ③ 동률 규칙
    assert dd["mdd_peak_date"] == date(2026, 9, 3) and dd["mdd_trough_date"] == date(2026, 9, 4)
    assert dd["mdd"] == pytest.approx(99 / 101 - 1)


def test_zero_trades():
    run = run_hand()
    bt = backtest.run_backtest(run["prices"], run["calendar"], run["schedule"],
                               run["targets"].iloc[0:0], BT_START, HAND_END, CAPITAL, 1, COSTS)
    s = metrics.summarize(bt["trades"], bt["snapshots"], bt["positions"], run["bench"], CAPITAL)
    assert s["final_equity"] == CAPITAL and s["total_return"] == 0 and s["mdd"] == 0
    assert s["mdd_peak_date"] is None and s["mdd_trough_date"] is None
    assert s["trade_count"] == 0 and s["win_rate"] is None and s["payoff_ratio"] is None
    assert s["turnover"] == 0 and s["total_cost"] == 0 and s["realized_pnl"] == 0
    assert len(metrics.closed_trades(bt["trades"])) == 0
    stocks = metrics.per_stock(bt["trades"], bt["positions"], universe, CAPITAL)
    assert all(x["status"] == "no_trade" and x["ret"] is None for x in stocks)
    weeks = metrics.weekly_flow(bt["trades"], bt["snapshots"])
    assert len(weeks) == 2 and all(w["buy_value"] == 0 and w["sell_value"] == 0 for w in weeks)


def test_loss_streak_and_payoff_ratio():
    rows, day = [], date(2026, 9, 1)
    def pair(i, code, buy, sell):
        d_in, d_out = date(2026, 9, 1 + i), date(2026, 9, 10 + i)
        rows.append({"id": len(rows) + 1, "date": d_in, "signal_date": d_in, "code": code, "side": "BUY",
                     "qty": 10, "price": buy, "amount": 10 * buy, "cost": 0, "net_cash": -10 * buy,
                     "realized_pnl": None, "realized_ret": None, "holding_days": None, "reason": ""})
        rows.append({"id": len(rows) + 1, "date": d_out, "signal_date": d_in, "code": code, "side": "SELL",
                     "qty": 10, "price": sell, "amount": 10 * sell, "cost": 0, "net_cash": 10 * sell,
                     "realized_pnl": 10 * (sell - buy), "realized_ret": sell / buy - 1,
                     "holding_days": 9, "reason": ""})
    pair(0, "A", 100, 90); pair(1, "B", 100, 95); pair(2, "C", 100, 100); pair(3, "D", 100, 80); pair(4, "E", 100, 130)
    trades = pd.DataFrame(rows)
    closed = metrics.closed_trades(trades)
    assert list(closed["pnl"]) == [-100, -50, 0, -200, 300]
    snaps = pd.DataFrame([{"date": day, "cash": 1000, "holdings_value": 0, "equity": 1000,
                           "position_count": 0, "realized_pnl_cum": 0}])
    bench = pd.DataFrame([{"date": day, "close": 1.0, "value": 1000, "ret": 0.0}])
    pos = pd.DataFrame(columns=backtest.POSITION_COLUMNS)
    s = metrics.summarize(trades, snaps, pos, bench, 1000)
    assert s["max_loss_streak"] == 2                     # 손익 0인 거래가 연속 손실을 끊는다
    assert s["win_rate"] == pytest.approx(1 / 5)         # 손익 0도 분모에 들어간다
    assert s["payoff_ratio"] == pytest.approx(300 / (350 / 3))
