"""metrics.py: 10.6절 기대 지표, 일별 집계, MDD(E0 고점), 연속 손실 정렬, 거래 0건 null 규칙."""
from datetime import date

import pandas as pd
import pytest

from helpers import CAPITAL, hand_daily, hand_index, run_hand
from stock_sim import metrics

D = date(2026, 9, 21)


def _summary(bt):
    days = list(bt["days"]["date"])
    daily = metrics.daily_table(bt["days"], bt["fills"], bt["closed"], CAPITAL)
    bench, _ = metrics.benchmark_curve(hand_index(), days, CAPITAL)
    return metrics.summarize(bt["fills"], bt["closed"], daily, bench, CAPITAL), daily


def test_hand_metrics_10_6():
    s, daily = _summary(run_hand())
    assert s["final_equity"] == 99_786_135
    assert s["total_return"] == pytest.approx(-0.00213865, abs=1e-10)
    assert s["mdd"] == pytest.approx(-0.00213865, abs=1e-10)
    assert s["mdd_peak_date"] is None and s["mdd_trough_date"] == D
    assert (s["trade_count"], s["buy_count"], s["sell_count"], s["closed_count"]) == (2, 1, 1, 1)
    assert (s["win_rate"], s["payoff_ratio"], s["avg_hold_minutes"]) == (0.0, None, 25.0)
    assert (s["gross_pnl"], s["total_cost"], s["realized_pnl"]) == (-99_200, 114_665, -213_865)
    assert (s["buy_cost"], s["sell_cost"]) == (7_492, 107_173)
    assert s["total_trade_value"] == 99_795_200
    assert s["turnover"] == pytest.approx(0.50004542, abs=1e-8)
    assert (s["max_loss_streak"], s["halt_days"], s["even_count"]) == (1, 0, 0)
    assert s["exit_reasons"] == {"breakdown": 1, "eod": 0}
    assert s["benchmark_return"] == pytest.approx(0.005)
    row = daily.iloc[0]
    assert (row["pnl"], row["buy_count"], row["sell_count"], row["closed_count"]) == (-213_865, 1, 1, 1)
    assert (row["trade_value"], row["cost"]) == (99_795_200, 114_665)
    assert row["ret"] == pytest.approx(-0.00213865, abs=1e-10)


def test_equal_weight_and_benchmark_from_daily():
    assert metrics.equal_weight_return(hand_daily(), [D]) == pytest.approx(0.008)
    assert metrics.equal_weight_count(hand_daily(), [D]) == 1
    bench, info = metrics.benchmark_curve(hand_index(), [D], CAPITAL)
    assert info == {"base_price": 4000.0, "base_kind": "d1_open"}
    assert bench.iloc[0]["value"] == 100_500_000


def _days(equities, halted=None):
    ds = [date(2026, 9, 21 + i) for i in range(len(equities))]
    starts = [CAPITAL] + equities[:-1]
    return pd.DataFrame({"date": ds, "e_start": starts, "e_end": equities,
                         "halted": halted or [False] * len(ds), "skipped_codes": [[]] * len(ds)})


def test_mdd_uses_e0_as_peak_and_nearest_peak_on_ties():
    empty = pd.DataFrame(columns=["date", "side", "amount", "cost", "qty", "code"])
    closed = pd.DataFrame(columns=["pnl", "gross_pnl", "hold_minutes", "exit_reason", "code", "date"])
    days = _days([101_000_000, 100_000_000, 101_000_000, 99_000_000])
    daily = metrics.daily_table(days, empty, closed, CAPITAL)
    bench = pd.DataFrame({"ret": [0.0] * 4})
    s = metrics.summarize(empty, closed, daily, bench, CAPITAL)
    assert s["mdd"] == pytest.approx(99 / 101 - 1)
    assert s["mdd_peak_date"] == date(2026, 9, 23) and s["mdd_trough_date"] == date(2026, 9, 24)
    assert list(daily["drawdown"].round(6)) == [0.0, round(100 / 101 - 1, 6), 0.0, round(99 / 101 - 1, 6)]


def test_zero_trades_nulls():
    empty = pd.DataFrame(columns=["date", "side", "amount", "cost", "qty", "code"])
    closed = pd.DataFrame(columns=["pnl", "gross_pnl", "hold_minutes", "exit_reason", "code", "date"])
    daily = metrics.daily_table(_days([CAPITAL, CAPITAL]), empty, closed, CAPITAL)
    s = metrics.summarize(empty, closed, daily, pd.DataFrame({"ret": [0.0, 0.01]}), CAPITAL)
    assert (s["win_rate"], s["payoff_ratio"], s["avg_hold_minutes"]) == (None, None, None)
    assert (s["mdd"], s["trade_count"], s["max_loss_streak"], s["total_cost"]) == (0.0, 0, 0, 0)
    stocks = metrics.per_stock(empty, closed, [{"code": "AAA", "name": "가"}], CAPITAL)
    assert stocks[0]["status"] == "no_trade" and stocks[0]["ret"] is None
    assert stocks[0]["avg_hold_minutes"] is None


def test_loss_streak_follows_closed_order():
    closed = pd.DataFrame({"pnl": [-1, -2, 0, -3, -4, -5, 7], "gross_pnl": [0] * 7,
                           "hold_minutes": [5] * 7, "exit_reason": ["EXIT_BREAKDOWN"] * 7,
                           "code": ["A"] * 7, "date": [D] * 7})
    empty = pd.DataFrame(columns=["date", "side", "amount", "cost", "qty", "code"])
    daily = metrics.daily_table(_days([CAPITAL - 8]), empty, closed, CAPITAL)
    s = metrics.summarize(empty, closed, daily, pd.DataFrame({"ret": [0.0]}), CAPITAL)
    assert s["max_loss_streak"] == 3 and s["even_count"] == 1
    assert s["payoff_ratio"] == pytest.approx(7 / 3)


def test_per_stock_and_weekly():
    bt = run_hand()
    stocks = metrics.per_stock(bt["fills"], bt["closed"], [{"code": "AAA", "name": ""}, {"code": "BBB", "name": "B"}],
                               CAPITAL)
    a, b = stocks
    assert (a["status"], a["trade_count"], a["realized_pnl"], a["gross_pnl"], a["cost"]) == \
        ("traded", 2, -213_865, -99_200, 114_665)
    assert a["ret"] == pytest.approx(-213_865 / 49_954_692)
    assert a["contribution"] == pytest.approx(-0.00213865)
    assert (a["avg_hold_minutes"], a["loss_count"], a["name"]) == (25.0, 1, "AAA")
    assert b["status"] == "no_trade"
    weeks = metrics.weekly_trade_value(bt["fills"], [D, date(2026, 9, 28)])
    assert [(w["start"], w["value"]) for w in weeks] == [(D, 99_795_200), (date(2026, 9, 28), 0)]
