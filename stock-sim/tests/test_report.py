"""report.py: result.json 계약(키 구조 = docs/result.example.json), 5.7절 항등식, 11.6절 문자열, 5.6절 빈 경우."""
import copy
import json
import math

import pandas as pd
import pytest

from helpers import CAPITAL, DOCS, hand_result
from stock_sim import report

EXAMPLE = json.loads((DOCS / "result.example.json").read_text(encoding="utf-8"))


def key_shape_diff(example, actual, path="$") -> list[str]:
    """dict는 키 집합이 같아야 하고, 배열은 첫 원소끼리 비교한다. 한쪽이 null이거나 빈 배열이면 건너뛴다."""
    out = []
    if isinstance(example, dict) and isinstance(actual, dict):
        if set(example) != set(actual):
            out.append(f"{path}: 빠진 키 {sorted(set(example) - set(actual))}, 남는 키 {sorted(set(actual) - set(example))}")
        for k in set(example) & set(actual):
            out += key_shape_diff(example[k], actual[k], f"{path}.{k}")
    elif isinstance(example, list) and isinstance(actual, list):
        if example and actual:
            out += key_shape_diff(example[0], actual[0], f"{path}[0]")
    elif example is not None and actual is not None:
        if isinstance(example, (dict, list)) != isinstance(actual, (dict, list)):
            out.append(f"{path}: 형이 다름")
    return out


def check_identities(r: dict) -> None:
    """architecture.md 5.7절 항등식 1~8."""
    s = r["summary"]
    cap = s["initial_capital"]
    assert s["final_equity"] - cap == s["total_pnl"] == s["realized_pnl"] == s["gross_pnl"] - s["total_cost"]
    assert r["equity_curve"][-1]["equity"] == r["daily"][-1]["e_end"] == s["final_equity"]
    assert r["daily"][0]["e_start"] == cap
    for a, b in zip(r["daily"], r["daily"][1:]):
        assert b["e_start"] == a["e_end"]
    assert sum(d["pnl"] for d in r["daily"]) == sum(c["pnl"] for c in r["closed_trades"]) \
        == sum(p["realized_pnl"] for p in r["per_stock"]) == s["realized_pnl"]
    assert s["buy_count"] == s["sell_count"] == s["closed_count"]
    assert s["trade_count"] == len(r["trades"])
    assert s["win_count"] + s["loss_count"] + s["even_count"] == s["closed_count"]
    assert sum(t["amount"] for t in r["trades"]) == s["total_trade_value"] \
        == sum(d["trade_value"] for d in r["daily"]) == r["trade_value_share"]["total"]
    assert sum(t["cost"] for t in r["trades"]) == s["total_cost"] == sum(d["cost"] for d in r["daily"])
    assert sum(t["net_cash"] for t in r["trades"]) == s["total_pnl"]
    assert s["sell_value"] - s["buy_value"] == s["gross_pnl"]
    assert s["halt_days"] == sum(1 for d in r["daily"] if d["halted"])
    assert r["blocks"]["breakout"] == r["blocks"]["entries"] + r["blocks"]["blocked"]
    for key in ("total_pnl", "total_return", "benchmark_return", "excess_return", "mdd",
                "realized_pnl", "gross_pnl", "equal_weight_return", "excess_vs_equal_weight"):
        val = s.get(key) if key in s else s.get(f"{key}_pct")
        assert s[f"{key}_sign"] == report.sign_of(val), key
    for row in r["daily"] + r["closed_trades"]:
        assert row["sign"] == report.sign_of(row["pnl"])
    for t in r["trades"]:
        assert t["sign"] == report.sign_of(t["realized_pnl"])
    for p in r["per_stock"]:
        assert p["sign"] == report.sign_of(p["realized_pnl"])
        if p["return_pct"] is not None:
            assert report.sign_of(p["return_pct"]) == p["sign"]
    segs = r["trade_value_share"]["segments"]
    if segs:
        assert segs[-1]["end_pct"] == 100.0


def no_nan(obj) -> bool:
    if isinstance(obj, float):
        return not (math.isnan(obj) or math.isinf(obj))
    if isinstance(obj, dict):
        return all(no_nan(v) for v in obj.values())
    if isinstance(obj, list):
        return all(no_nan(v) for v in obj)
    return True


# ---- 예시 파일 자체 ----------------------------------------------------------------------
def test_example_file_satisfies_identities():
    check_identities(EXAMPLE)


# ---- 10절 fixture 결과 -----------------------------------------------------------------
@pytest.fixture(scope="module")
def hand():
    return hand_result()


def test_hand_result_has_example_key_structure(hand):
    assert key_shape_diff(EXAMPLE, hand) == []
    assert hand["schema_version"] == "2.0" and hand["meta"]["is_example"] is False
    json.dumps(hand, ensure_ascii=False, allow_nan=False)
    assert no_nan(hand)


def test_hand_result_identities_and_values(hand):
    check_identities(hand)
    s = hand["summary"]
    assert (s["final_equity"], s["total_pnl"], s["gross_pnl"], s["total_cost"]) == \
        (99_786_135, -213_865, -99_200, 114_665)
    assert (s["total_return_pct"], s["mdd_pct"], s["benchmark_return_pct"]) == (-0.2139, -0.2139, 0.5)
    assert (s["mdd_peak_date"], s["mdd_trough_date"]) == (None, "2026-09-21")
    assert (s["win_rate_pct"], s["payoff_ratio"], s["avg_hold_minutes"]) == (0.0, None, 25.0)
    assert (s["turnover_pct"], s["cost_to_capital_pct"]) == (50.0045, 0.1147)
    assert s["exit_reasons"] == {"breakdown": 1, "eod": 0}
    assert hand["meta"]["costs"] == {"buy_cost_pct": 0.015, "sell_cost_pct": 0.215, "slippage_pct": 0.0,
                                     "round_trip_pct": 0.2305}
    t = hand["trades"]
    assert [(x["time"], x["signal_time"], x["reason_label"], x["in_table"]) for x in t] == [
        ("09:25", "09:20", "돌파 매수", True), ("09:50", "09:45", "하락 이탈 매도", True)]
    assert hand["trade_table"] == {"limit": 20, "total": 2, "shown": 2, "truncated": False,
                                   "caption": "전체 2건"}
    assert hand["blocks"]["caption"] == \
        "돌파 2회 중 1회 매수 신호, 1회 차단(쿨다운 1 · 매매 중단 0 · 횟수 상한 0 · 시간 0 · 변동폭 0 · 거래량 0 · VWAP 0)"
    assert hand["charts"]["daily_pnl"]["caption"] == "수익 0일, 손실 1일, 손익 없음 0일. 최대 손실 -213,865원(2026-09-21)."
    seg = hand["daily"][0]["segments"]
    assert [(x["key"], x["value"], x["height_pct"]) for x in seg] == [("gain", 0, 0.0), ("loss", 213_865, 100.0)]


def test_hand_sentences_match_11_6(hand):
    ins = [i["detail"] for i in hand["insights"]]
    assert ins[0] == ("기간 수익률 -0.21%, KOSPI(+0.50%)보다 0.71%p 낮았습니다. "
                      "유니버스 1종목 동일가중(+0.80%)보다 1.01%p 낮았습니다.")
    assert ins[1] == ("비용 전 손익 -99,200원에서 비용 114,665원을 빼 총손익 -213,865원입니다(청산 1건). "
                      "종목별: AAA -213,865원.")
    assert ins[2] == "최대 낙폭(MDD) -0.21%, 고점 초기 자본 → 저점 2026-09-21. 임계 -5.00% 이내입니다."
    assert hand["next_action"]["text"] == ("종목별 상세에서 실현 손실 상위 종목(AAA)을 먼저 확인하세요. "
                                           "30일 표본이므로 전략 변경은 구간을 늘려 본 뒤 판단하세요.")
    assert hand["top_contributors"]["note"] == "이익 종목 없음, 손실 1종목 합계 -213,865원 → 총손익 -213,865원"
    assert hand["target"]["caption"] == \
        "목표 +2.00%에 2.21%p 못 미쳤습니다(현재 -0.21%). 목표 평가금액까지 2,213,865원 부족."
    assert [(a["level"], a["code"]) for a in hand["alerts"]] == [("info", "OVERNIGHT_GAP_NOTE"),
                                                                  ("info", "LOW_SAMPLE")]
    low = hand["alerts"][1]
    assert (low["title"], low["detail"]) == ("30일(1거래일) 표본은 통계적 의미가 약합니다.", "청산 거래 1건")
    assert hand["flags"] == {"no_trades": False, "only_baseline_alerts": True, "trades_truncated": False}


# ---- 알림·표시 규칙 ------------------------------------------------------------------------
def _summary(**kw):
    base = {"mdd": -0.01, "mdd_peak_date": None, "mdd_trough_date": None, "max_loss_streak": 0,
            "excess_return": 0.0, "total_return": 0.0, "benchmark_return": 0.0, "total_cost": 0,
            "initial_capital": CAPITAL, "trade_count": 2, "gross_pnl": 0, "closed_count": 1,
            "halt_days": 0}
    base.update(kw)
    return base


def test_alert_order_levels_colors_and_aggregation():
    from datetime import date
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    ev = [{"code": "BAR_MISSING", "stock": "000660", "date": d1, "value": 2, "extra": {}},
          {"code": "BAR_MISSING", "stock": "000660", "date": d2, "value": 3, "extra": {}},
          {"code": "DAY_SKIPPED", "stock": "005930", "date": d2, "value": 41, "extra": {}},
          {"code": "EOD_FALLBACK", "stock": "005930", "date": d1, "value": 70_000, "extra": {}},
          {"code": "PRICE_ANOMALY", "stock": "005930", "date": d1, "value": 0.1234, "extra": {"time": "10:05"}},
          {"code": "QTY_ZERO_SKIP", "stock": "005930", "date": d1, "value": 900_000, "extra": {"alloc": 500_000}}]
    issues = [{"code": "NON_INTEGER_PRICE", "stock": "005930", "date": None, "value": None, "excluded": False},
              {"code": "NON_INTEGER_PRICE", "stock": "005930", "date": None, "value": None, "excluded": False},
              {"code": "TRUNCATION_SUSPECT", "stock": "IDX0001", "date": None, "value": None, "excluded": False}]
    stocks = [{"code": "005930", "name": "삼성전자"}, {"code": "000660", "name": "SK하이닉스"}]
    s = _summary(mdd=-0.06, max_loss_streak=3, excess_return=-0.025, total_return=-0.01,
                 benchmark_return=0.015, total_cost=1_000_000, gross_pnl=500, halt_days=2)
    alerts = report.build_alerts(s, stocks, issues, ev, {"days": 30, "trading_days": 20},
                                 {"daily_loss_limit_pct": 0.01})
    codes = [a["code"] for a in alerts]
    assert codes == ["MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM", "COST_DRAG", "DAY_SKIPPED", "BAR_MISSING",
                     "EOD_FALLBACK", "PRICE_ANOMALY", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT",
                     "DAILY_LOSS_HALT", "QTY_ZERO_SKIP", "OVERNIGHT_GAP_NOTE", "LOW_SAMPLE"]
    by = {a["code"]: a for a in alerts}
    assert by["MDD_BREACH"]["color"] == "#B0472F" and by["COST_DRAG"]["color"] == "#C98A2E"
    assert by["DAILY_LOSS_HALT"]["color"] == "#1428A0" and by["DAILY_LOSS_HALT"]["level"] == "info"
    assert (by["COST_DRAG"]["title"], by["COST_DRAG"]["detail"]) == \
        ("총 비용 1,000,000원, 초기 자본의 1.00%", "체결 2건 · 비용 전 손익 +500원")
    assert (by["BAR_MISSING"]["title"], by["BAR_MISSING"]["detail"]) == \
        ("SK하이닉스 5분봉 5개 결측", "000660 · 2거래일에 걸침")
    assert (by["DAY_SKIPPED"]["detail"], by["DAY_SKIPPED"]["date"]) == ("005930 · 유효 5분봉 41개", "2026-09-02")
    assert by["PRICE_ANOMALY"]["title"] == "삼성전자 5분 등락 +12.34%: 데이터 확인 필요"
    assert by["PRICE_ANOMALY"]["detail"] == "005930 · 10:05 봉"
    assert by["EOD_FALLBACK"]["detail"] == "005930 · 체결가 70,000원"
    assert by["QTY_ZERO_SKIP"]["detail"] == "005930 · 체결가 900,000원 · 배분금액 500,000원"
    assert by["TRUNCATION_SUSPECT"]["title"].startswith("KOSPI 지수") and by["TRUNCATION_SUSPECT"]["detail"] == "0001"
    assert by["DAILY_LOSS_HALT"]["title"] == "일일 손실 한도로 신규 매수를 중단한 날 2일"
    assert by["DAILY_LOSS_HALT"]["detail"] == "한도 -1.00%"
    assert by["MDD_BREACH"]["title"] == "MDD -6.00%, 임계 -5.00% 초과"
    # 다음 조치 2번: 데이터 품질 알림 수
    _, nxt = report.build_insights({**s, "total_pnl": -1, "realized_pnl": -1}, [], alerts)
    assert nxt["text"].startswith("수치를 해석하기 전에 점검 필요의 데이터 알림 6건을 먼저 확인하세요.")


def test_next_action_rules():
    stocks = [{"code": "000660", "name": "SK하이닉스", "realized_pnl": -5, "buy_count": 1},
              {"code": "005930", "name": "삼성전자", "realized_pnl": -5, "buy_count": 1}]
    s = _summary(total_pnl=-10, gross_pnl=3)
    assert report.build_insights(s, stocks, [])[1]["text"].startswith("비용 전 손익은 손실이 아니지만")
    s = _summary(total_pnl=-10, gross_pnl=-3)
    assert report.build_insights(s, stocks, [])[1]["text"].startswith(
        "종목별 상세에서 실현 손실 상위 종목(SK하이닉스·삼성전자)을")
    s = _summary(total_pnl=0, trade_count=0)
    assert report.build_insights(s, stocks, [])[1]["text"] == \
        "점검 필요의 데이터 알림과 진입 조건별 차단 횟수를 먼저 확인하세요."


def test_pnl_sentence_lists_bought_stocks_by_code():
    stocks = [{"code": "005930", "name": "삼성전자", "realized_pnl": -232_231, "buy_count": 7},
              {"code": "000660", "name": "SK하이닉스", "realized_pnl": -560_773, "buy_count": 5},
              {"code": "000001", "name": "가상", "realized_pnl": 0, "buy_count": 0}]
    s = _summary(gross_pnl=577_200, total_cost=1_370_204, total_pnl=-793_004, closed_count=12)
    text = report.build_insights(s, stocks, [])[0][1]["detail"]
    assert text == example_detail("손익 분해")


def example_detail(title):
    return next(i["detail"] for i in EXAMPLE["insights"] if i["title"] == title)


def _zero_trade_result():
    from helpers import hand_bars5, run_hand, hand_cfg, hand_index
    from stock_sim import metrics
    df5 = hand_bars5()
    df5["volume"] = 1
    bt = run_hand(df5=df5)
    days = list(bt["days"]["date"])
    daily_tab = metrics.daily_table(bt["days"], bt["fills"], bt["closed"], CAPITAL)
    bench, info = metrics.benchmark_curve(hand_index(), days, CAPITAL)
    info.update(equal_weight_return=None, equal_weight_count=0)
    cfg = hand_cfg()
    cfg["universe"] = [{"code": "AAA", "name": "가"}, {"code": "BBB", "name": "나"}]
    cfg["strategy"]["position_pct"] = 0.5
    issues = [{"code": "DATA_MISSING", "stock": "BBB", "date": None, "value": 1, "excluded": True,
               "side": None, "extra": {}}]
    from datetime import date
    period = {"start": days[0], "end": days[0], "daily_fetch_start": date(2026, 9, 14)}
    return report.build_result(cfg, period, bt, daily_tab, bench, info, issues,
                               {"empty_days": [{"code": "BBB", "date": days[0]}]}, "2026-09-30T09:00:00+09:00")


def test_empty_cases_5_6():
    r = _zero_trade_result()
    assert key_shape_diff(EXAMPLE, r) == []
    check_identities(r)
    assert r["flags"]["no_trades"] is True and r["trades"] == [] and r["closed_trades"] == []
    assert r["trade_table"] == {"limit": 20, "total": 0, "shown": 0, "truncated": False, "caption": ""}
    s = r["summary"]
    assert (s["win_rate_pct"], s["payoff_ratio"], s["avg_hold_minutes"]) == (None, None, None)
    assert r["trade_value_share"]["segments"] == [] and r["trade_value_share"]["total"] == 0
    assert r["trade_value_share"]["conic_gradient"] == "conic-gradient(#DCE0E9 0% 100%)"
    assert r["top_contributors"]["items"] == []
    assert r["charts"]["daily_pnl"]["best"] is None and r["charts"]["daily_pnl"]["worst"] is None
    assert r["charts"]["daily_pnl"]["caption"] == "거래가 없어 일별 손익이 없습니다."
    assert all(x["height_pct"] == 0.0 for d in r["daily"] for x in d["segments"])
    codes = [a["code"] for a in r["alerts"]]
    assert "NO_TRADES" in codes and "DATA_MISSING" in codes
    assert r["blocks"]["breakout"] >= 1 and len(r["blocks"]["items"]) == 7
    status = {p["code"]: p["status"] for p in r["per_stock"]}
    assert status == {"AAA": "no_trade", "BBB": "excluded"}
    assert r["meta"]["data_source"]["excluded"] == [{"code": "BBB", "name": "나", "reason": "분봉 데이터 없음"}]
    assert r["meta"]["data_source"]["empty_days"] == [{"code": "BBB", "date": "2026-09-21"}]
    assert r["insights"][1]["detail"] == "백테스트 기간에 체결된 거래가 없어 전 기간 현금을 보유했습니다."
    assert len(r["insights"]) == 3


def test_trade_table_keeps_all_trades_and_marks_last_20():
    fills = pd.DataFrame([{
        "id": i, "date": pd.Timestamp("2026-09-21").date(), "time": "09:30", "signal_time": "09:25",
        "code": "AAA", "side": "BUY" if i % 2 else "SELL", "qty": 1, "price": 10, "amount": 10, "cost": 0,
        "net_cash": -10 if i % 2 else 10, "reason": "ENTRY_BREAKOUT" if i % 2 else "EXIT_BREAKDOWN",
        "closed_id": (i + 1) // 2, "realized_pnl": None if i % 2 else 0, "realized_ret": None if i % 2 else 0.0,
        "hold_minutes": None if i % 2 else 5} for i in range(1, 25)])
    rows = report._trade_rows(fills, {"AAA": "가"})
    assert len(rows) == 24
    assert [r["in_table"] for r in rows] == [False] * 4 + [True] * 20


def test_axis_and_polyline_helpers():
    assert report.nice_axis(-1.4, 1.35) == (-2.0, 2.0, [2.0, 1.0, 0.0, -1.0, -2.0])
    assert report.polyline_points([0.0, 2.0, -2.0], 720, 250, -2.0, 2.0) == "0.0,125.0 360.0,0.0 720.0,250.0"
    assert report.sign_of(-0.0) == "zero" and report.sign_of(None) == "zero" and report.sign_of(3) == "pos"


def test_example_copy_still_matches_itself():
    assert key_shape_diff(EXAMPLE, copy.deepcopy(EXAMPLE)) == []
