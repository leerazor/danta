"""스케줄·신호 테스트 (strategy.md 2.4절, 3.1절, 9.3절)."""
from datetime import date

import pandas as pd
import pytest

from helpers import BT_START, HAND_END, hand_prices, make_df, syn_days
from stock_sim import data, strategy

P1 = {"lookback_days": 1, "top_n": 1, "rebalance": "weekly"}


def test_schedule_hand_calendar_holiday_week():
    cal = data.build_calendar(hand_prices())
    sched = strategy.rebalance_schedule(cal, BT_START, HAND_END, P1)
    # 09-24·09-25 휴장 → 신호일 09-23, 체결일 09-28
    assert sched == [(date(2026, 9, 18), date(2026, 9, 21)), (date(2026, 9, 23), date(2026, 9, 28))]


def test_schedule_default_period_has_five_fills():
    cal = syn_days()
    sched = strategy.rebalance_schedule(cal, date(2026, 8, 31), date(2026, 9, 29), P1)
    assert [f for _, f in sched] == [date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 14),
                                     date(2026, 9, 21), date(2026, 9, 28)]
    assert [s for s, _ in sched] == [date(2026, 8, 28), date(2026, 9, 4), date(2026, 9, 11),
                                     date(2026, 9, 18), date(2026, 9, 23)]
    for s, f in sched:                      # 신호일은 항상 체결일 직전 거래일
        assert cal.index(f) - cal.index(s) == 1


def test_schedule_midweek_start_waits_for_next_week():
    cal = data.build_calendar(hand_prices())
    sched = strategy.rebalance_schedule(cal, date(2026, 9, 22), HAND_END, P1)
    assert sched == [(date(2026, 9, 23), date(2026, 9, 28))]


def test_schedule_rejects_unknown_mode():
    with pytest.raises(ValueError):
        strategy.rebalance_schedule(syn_days(), date(2026, 8, 31), date(2026, 9, 29),
                                    {"rebalance": "daily"})


def test_signals_match_hand_calc():
    prices = hand_prices()
    cal = data.build_calendar(prices)
    sched = strategy.rebalance_schedule(cal, BT_START, HAND_END, P1)
    both = strategy.signals(prices, cal, sched, {**P1, "top_n": 2})
    first = both[both["signal_date"] == date(2026, 9, 18)]
    assert list(first["code"]) == ["AAA", "BBB"] and list(first["rank"]) == [1, 2]
    assert first["score"].iloc[0] == pytest.approx(0.02, abs=1e-9)
    assert first["score"].iloc[1] == pytest.approx(0.01, abs=1e-9)
    second = both[both["signal_date"] == date(2026, 9, 23)]
    assert list(second["code"]) == ["BBB", "AAA"]
    assert second["score"].iloc[0] == pytest.approx(0.0392157, abs=1e-6)
    assert second["score"].iloc[1] == pytest.approx(-0.0094340, abs=1e-6)
    top1 = strategy.signals(prices, cal, sched, P1)
    assert list(top1["code"]) == ["AAA", "BBB"]
    assert list(top1["fill_date"]) == [date(2026, 9, 21), date(2026, 9, 28)]


def _three(closes_by_code: dict, volume: int = 100) -> dict:
    days = [date(2026, 9, 17), date(2026, 9, 18), date(2026, 9, 21)]
    return {c: make_df([(d, v, v, volume) for d, v in zip(days, vals)])
            for c, vals in closes_by_code.items()}


def test_tie_breaks_by_code_ascending():
    prices = _three({"CCC": [100, 110, 110], "AAA": [200, 220, 220], "BBB": [50, 55, 55]})
    cal = data.build_calendar(prices)
    sched = [(date(2026, 9, 18), date(2026, 9, 21))]
    out = strategy.signals(prices, cal, sched, {"lookback_days": 1, "top_n": 2})
    assert list(out["code"]) == ["AAA", "BBB"]


def test_negative_momentum_still_selected_and_fewer_than_top_n():
    prices = _three({"AAA": [100, 90, 90], "BBB": [100, 80, 80]})
    cal = data.build_calendar(prices)
    out = strategy.signals(prices, cal, [(date(2026, 9, 18), date(2026, 9, 21))],
                           {"lookback_days": 1, "top_n": 5})
    assert list(out["code"]) == ["AAA", "BBB"]            # 있는 만큼만, 음수여도 목표


def test_missing_or_halted_bar_is_not_eligible():
    prices = _three({"AAA": [100, 110, 110], "BBB": [100, 150, 150], "CCC": [100, 140, 140]})
    prices["BBB"] = prices["BBB"][prices["BBB"]["date"] != pd.Timestamp("2026-09-18")]  # 신호일 결측
    prices["CCC"].loc[prices["CCC"]["date"] == pd.Timestamp("2026-09-17"), "volume"] = 0  # T−L 거래정지
    cal = data.build_calendar(prices)
    out = strategy.signals(prices, cal, [(date(2026, 9, 18), date(2026, 9, 21))],
                           {"lookback_days": 1, "top_n": 3})
    assert list(out["code"]) == ["AAA"]


def test_no_lookback_history_gives_no_rows():
    prices = hand_prices()
    cal = data.build_calendar(prices)
    out = strategy.signals(prices, cal, [(date(2026, 9, 18), date(2026, 9, 21))],
                           {"lookback_days": 20, "top_n": 1})
    assert len(out) == 0 and list(out.columns) == strategy.TARGET_COLUMNS


def test_future_data_does_not_change_past_signals():
    """R5: 신호일 이후 가격을 바꿔도 그 신호일까지의 목표는 그대로다."""
    prices = hand_prices()
    cal = data.build_calendar(prices)
    sched = strategy.rebalance_schedule(cal, BT_START, HAND_END, P1)
    before = strategy.signals(prices, cal, sched, {**P1, "top_n": 2})
    changed = hand_prices()
    for df in changed.values():
        future = df["date"] > pd.Timestamp("2026-09-18")
        df.loc[future, ["open", "high", "low", "close"]] = df.loc[future, ["open", "high", "low", "close"]] * 3
    after = strategy.signals(changed, cal, sched, {**P1, "top_n": 2})
    cut = date(2026, 9, 18)
    a = before[before["signal_date"] <= cut].reset_index(drop=True)
    b = after[after["signal_date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_registry_and_warmup():
    assert set(strategy.STRATEGIES) == {"momentum_topn"}
    assert strategy.min_warmup_days("momentum_topn", {"lookback_days": 20}) == 30
