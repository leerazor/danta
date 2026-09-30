"""strategy.py: 리샘플(3.4절·케이스 8), 지표(10.2절 표 전 행), 신호 플래그(10.3절), look-ahead."""
from datetime import date

import pandas as pd
import pytest

from helpers import HAND_PARAMS, as_bars, hand_bars5, hand_signals
from stock_sim import strategy

D = date(2026, 9, 21)
# 10.2절: (HH, LL, SV, XL, PV, CV). None = 정의되지 않음
EXPECTED = [
    (None, None, None, None, 300_400_000, 1_000),
    (None, None, None, None, 540_560_000, 1_800),
    (None, None, None, 99_800, 720_440_000, 2_400),
    (100_400, 99_700, 2_400, 99_700, 930_580_000, 3_100),
    (100_300, 99_700, 2_100, 99_700, 1_382_530_000, 4_600),
    (100_700, 99_700, 2_800, 99_800, 1_746_010_000, 5_800),
    (101_200, 99_800, 3_400, 100_000, 2_019_520_000, 6_700),
    (101_500, 100_000, 3_600, 100_600, 2_232_390_000, 7_400),
    (101_600, 100_600, 2_800, 101_000, 2_475_030_000, 8_200),
    (101_600, 100_900, 2_400, 100_900, 2_807_450_000, 9_300),
    (101_600, 100_500, 2_600, 100_500, 3_078_710_000, 10_200),
    (101_400, 100_300, 2_800, 100_300, 3_259_490_000, 10_800),
    (101_100, 100_200, 2_600, 100_200, 3_865_490_000, 12_800),
]


def _minutes(rows, day="2026-09-21"):
    return pd.DataFrame({"date": pd.to_datetime([day] * len(rows)), "time": [r[0] for r in rows],
                         "open": [r[1] for r in rows], "high": [r[2] for r in rows],
                         "low": [r[3] for r in rows], "close": [r[4] for r in rows],
                         "volume": [r[5] for r in rows]})


def test_resample_case8_partial_slot():
    m = _minutes([("09:00", 100, 102, 99, 101, 10), ("09:01", 101, 103, 101, 102, 5),
                  ("09:03", 102, 102, 100, 100, 7), ("09:04", 100, 101, 98, 99, 8)])
    bars = strategy.resample_bars(m)
    assert len(bars) == 1
    b = bars.iloc[0]
    assert (b["time"], b["slot"], b["k"]) == ("09:00", 0, 0)
    assert (b["open"], b["high"], b["low"], b["close"], b["volume"]) == (100, 103, 98, 99, 30)


def test_resample_drops_after_continuous_end_and_invalid_slots_get_no_k():
    m = _minutes([("09:00", 100, 100, 100, 100, 1), ("09:05", 0, 0, 0, 0, 0),      # 시가 0 → 무효
                  ("09:10", 101, 101, 101, 101, 3), ("09:11", 101, 101, 101, 101, 0),
                  ("09:15", 102, 102, 102, 102, 0),                                   # 거래량 0 → 무효
                  ("15:19", 105, 105, 105, 105, 2), ("15:20", 106, 106, 106, 106, 9),
                  ("15:30", 107, 107, 107, 107, 99), ("16:00", 108, 108, 108, 108, 1)])
    bars = strategy.resample_bars(m)
    assert list(bars["time"]) == ["09:00", "09:10", "15:15"]
    assert list(bars["slot"]) == [0, 2, 75]
    assert list(bars["k"]) == [0, 1, 2]
    assert bars.iloc[-1]["close"] == 105                                             # 15:20 이후 제외
    assert strategy.slot_count("09:00", "15:20", 5) == 76
    assert strategy.slot_count("09:00", "10:05", 5) == 13


def test_resample_resets_k_each_day():
    m = pd.concat([_minutes([("09:00", 1, 1, 1, 1, 1), ("09:05", 1, 1, 1, 1, 1)]),
                   _minutes([("09:10", 1, 1, 1, 1, 1)], day="2026-09-22")], ignore_index=True)
    bars = strategy.resample_bars(m)
    assert list(bars["k"]) == [0, 1, 0]
    assert bars["date"].iloc[-1] == date(2026, 9, 22)


def test_indicators_match_hand_table_every_row():
    sig = hand_signals()
    assert len(sig) == 13
    for k, (hh, ll, sv, xl, pv, cv) in enumerate(EXPECTED):
        row = sig.iloc[k]
        for col, exp in (("hh", hh), ("ll", ll), ("sv", sv), ("xl", xl)):
            if exp is None:
                assert pd.isna(row[col]), (k, col)
            else:
                assert int(row[col]) == exp, (k, col)
        assert (int(row["pv"]), int(row["cv"])) == (pv, cv), k


def test_signal_flags_match_10_3():
    sig = hand_signals()
    assert [bool(x) for x in sig["breakout"]] == [False] * 3 + [False, True, True, True, False,
                                                                False, False, False, False, True]
    b4 = sig.iloc[4]
    assert b4["breakout"] and b4["range_ok"] and b4["volume_ok"] and b4["vwap_ok"] and b4["cutoff_ok"]
    b12 = sig.iloc[12]
    assert b12["breakout"] and b12["range_ok"] and b12["volume_ok"] and b12["vwap_ok"]
    assert not b12["cutoff_ok"]                                # 10.1절 entry_cutoff 10:00, 봉 12 종료 10:05
    exits = [bool(x) for x in sig["exit_signal"]]
    assert exits[9] is True and exits[8] is False              # 봉 8: 101,000 = XL 101,000 (등호는 신호 아님)
    assert [k for k, e in enumerate(exits) if e] == [9, 10]


def test_case3_equal_close_is_not_breakout():
    df5 = hand_bars5()
    df5.loc[3, "close"] = 100_400
    sig = hand_signals(df5=df5)
    assert int(sig.iloc[3]["hh"]) == 100_400 and not sig.iloc[3]["breakout"]


def test_cutoff_uses_bar_end_time():
    params = {**HAND_PARAMS, "entry_cutoff": "14:50"}
    df5 = pd.DataFrame({"date": [D, D], "time": ["14:45", "14:50"], "open": [1, 1], "high": [1, 1],
                        "low": [1, 1], "close": [1, 1], "volume": [1, 1]})
    sig = strategy.signals(as_bars(df5), params)
    assert list(sig["cutoff_ok"]) == [True, False]


def test_flags_up_to_k_do_not_change_when_later_bars_or_previous_day_change():
    base = hand_signals()
    for k in range(12):
        df5 = hand_bars5()
        later = df5.index > k
        df5.loc[later, "high"] = df5.loc[later, "high"] + 5_000
        df5.loc[later, "low"] = df5.loc[later, "low"] - 3_000
        df5.loc[later, "close"] = df5.loc[later, "close"] + 1_000
        df5.loc[later, "volume"] = df5.loc[later, "volume"] * 7
        df5.loc[k + 1:, "open"] = df5.loc[k + 1:, "open"] + 700     # k+1 이후 시가도 바꾼다
        changed = hand_signals(df5=df5)
        cols = ["hh", "ll", "sv", "xl", "pv", "cv"] + strategy.FLAG_COLUMNS
        pd.testing.assert_frame_equal(changed.loc[:k, cols], base.loc[:k, cols])
    prev = hand_bars5().assign(date=date(2026, 9, 18))
    prev["close"] = prev["close"] * 2
    both = pd.concat([prev, hand_bars5()], ignore_index=True)
    sig = strategy.signals(as_bars(both), HAND_PARAMS)
    today = sig[sig["date"] == D].reset_index(drop=True)
    cols = ["k", "hh", "ll", "sv", "xl", "pv", "cv"] + strategy.FLAG_COLUMNS
    pd.testing.assert_frame_equal(today[cols], base[cols])


def test_auction_closes_and_label():
    m = _minutes([("15:19", 1, 1, 1, 10, 1), ("15:30", 1, 1, 1, 11, 1), ("16:00", 1, 1, 1, 12, 1)])
    assert strategy.auction_closes(m) == {D: 11}
    assert strategy.auction_closes(m.iloc[:1]) == {}
    assert strategy.label({"bar_minutes": 5}) == "5분봉 채널 돌파 · 당일 청산"
    assert "intraday_breakout" in strategy.STRATEGIES


@pytest.mark.parametrize("close,expected", [(100_800, True), (100_801, False)])
def test_range_filter_is_exact_at_the_boundary(close, expected):
    # HH 100,600, LL 100,096 → 폭 504. 504 × 1000 = 504,000 vs 5 × 종가(100,800 → 504,000: 등호 참)
    prev = [(100_600, 100_300), (100_400, 100_096), (100_500, 100_200)]
    rows = [(f"09:{5 * i:02d}", 100_300, h, lo, 100_300, 10) for i, (h, lo) in enumerate(prev)]
    rows.append(("09:15", 100_300, close, 100_300, close, 100))
    df5 = pd.DataFrame({"date": [D] * 4, "time": [r[0] for r in rows], "open": [r[1] for r in rows],
                        "high": [r[2] for r in rows], "low": [r[3] for r in rows],
                        "close": [r[4] for r in rows], "volume": [r[5] for r in rows]})
    sig = strategy.signals(as_bars(df5), HAND_PARAMS)
    assert bool(sig.iloc[3]["breakout"])
    assert bool(sig.iloc[3]["range_ok"]) is expected
