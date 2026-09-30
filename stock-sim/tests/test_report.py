"""result.json 계약 테스트 (architecture.md 5절, 8.3절)."""
import json
import math
import re

import pytest

from helpers import BT_START, CAPITAL, COSTS, DOCS, HAND_END, HAND_START, SYN_END, run_hand, syn_run
from stock_sim import backtest, data, metrics, report

EXAMPLE = json.loads((DOCS / "result.example.json").read_text(encoding="utf-8"))
GENERATED_AT = "2026-09-30T09:15:00+09:00"
EXTRA = [{"code": "000009", "name": "가상제외"}, {"code": "000008", "name": "가상무거래"}]
GEOMETRY_KEYS = ("width_pct", "height_pct", "bar_pct", "start_pct", "end_pct", "x_pct", "progress_pct")


def _build(run, issues=None, universe_extra=None, target=None):
    cfg = dict(run["cfg"])
    cfg["universe"] = cfg["universe"] + (universe_extra or [])
    if target is not None:
        cfg["target_return"] = target
    return report.build_result(cfg, run["period"], run["bt"], run["bench"], run["bench_info"],
                               issues or [], {"api_calls": 0, "cache_hits": 5}, GENERATED_AT)


@pytest.fixture(scope="module")
def result():
    run = syn_run()
    issues = [data.make_issue("DATA_MISSING", "000009", value=len(run["calendar"]), excluded=True)]
    return _build(run, issues, EXTRA)


@pytest.fixture(scope="module")
def empty_result():
    """거래 0건(목표 없음)."""
    run = syn_run()
    run["bt"] = backtest.run_backtest(run["prices"], run["calendar"], run["schedule"],
                                      run["targets"].iloc[0:0], run["days"][0], run["days"][-1],
                                      CAPITAL, 2, COSTS)
    return _build(run)


def _same_keys(actual, example, path="$"):
    if isinstance(example, dict):
        assert isinstance(actual, dict), f"{path}: dict가 아님"
        assert set(actual) == set(example), f"{path}: 키 불일치 {set(actual) ^ set(example)}"
        for key in example:
            _same_keys(actual[key], example[key], f"{path}.{key}")
    elif isinstance(example, list):
        assert isinstance(actual, list), f"{path}: list가 아님"
        if example and isinstance(example[0], (dict, list)):
            assert actual, f"{path}: 비교할 원소가 없음(fixture가 이 배열을 채워야 한다)"
            _same_keys(actual[0], example[0], f"{path}[0]")
    elif example is not None and actual is not None:
        kinds = (int, float) if isinstance(example, (int, float)) and not isinstance(example, bool) else type(example)
        assert isinstance(actual, kinds), f"{path}: 타입 불일치 {type(actual).__name__}"


def _walk(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


def test_key_structure_matches_example(result):
    _same_keys(result, EXAMPLE)
    for rows in ("equity_curve", "benchmark", "trades", "per_stock", "weekly_flow", "alerts", "positions"):
        keys = set(EXAMPLE[rows][0])
        assert all(set(r) == keys for r in result[rows]), rows


def test_empty_case_keeps_top_level_keys(empty_result):
    assert set(empty_result) == set(EXAMPLE)
    for key in ("meta", "flags", "summary", "allocation", "next_action", "target", "top_contributors"):
        assert set(empty_result[key]) == set(EXAMPLE[key]), key
    assert set(empty_result["charts"]["equity"]) == set(EXAMPLE["charts"]["equity"])


def test_json_serializable_without_nan(result, empty_result, tmp_path):
    for i, res in enumerate((result, empty_result)):
        path = report.write_result(res, tmp_path / "sub" / f"result{i}.json")
        text = path.read_text(encoding="utf-8")
        assert "NaN" not in text and "Infinity" not in text
        assert json.loads(text) == res
        assert "가상전자" in text                        # ensure_ascii=False
        for _, key, value in _walk(res):
            if isinstance(value, float):
                assert math.isfinite(value), key


def test_pct_digits(result):
    for path, key, value in _walk(result):
        if not isinstance(value, float):
            continue
        if key in GEOMETRY_KEYS:
            assert round(value, 2) == value, f"{path}.{key}"
        elif key.endswith("_pct"):
            assert round(value, 4) == value, f"{path}.{key}"


def test_signs_match_values(result, empty_result):
    def sign(v):
        return "zero" if v is None or v == 0 else ("pos" if v > 0 else "neg")
    for res in (result, empty_result):
        s = res["summary"]
        for name in ("total_pnl", "realized_pnl", "unrealized_pnl"):
            assert s[f"{name}_sign"] == sign(s[name])
        for name in ("total_return", "benchmark_return", "excess_return", "equal_weight_return"):
            assert s[f"{name}_sign"] == sign(s[f"{name}_pct"])
        assert s["excess_vs_equal_weight_sign"] == sign(s["excess_vs_equal_weight_pct"])
        if s["equal_weight_return_pct"] is not None:
            assert s["excess_vs_equal_weight_pct"] == pytest.approx(
                s["total_return_pct"] - s["equal_weight_return_pct"], abs=2e-4)
        assert s["mdd_sign"] == sign(s["mdd_pct"]) and s["mdd_pct"] <= 0
        for p in res["positions"]:
            assert p["sign"] == sign(p["unrealized_pnl"])
        for t in res["trades"]:
            assert t["sign"] == sign(t["realized_pnl"])
        for st in res["per_stock"]:
            assert st["sign"] == sign(st["total_pnl"])
            assert st["realized_pnl_sign"] == sign(st["realized_pnl"])
        for it in res["top_contributors"]["items"]:
            assert it["sign"] == sign(it["pnl"])
        t = res["target"]
        assert t["sign"] == sign(t["actual_return_pct"])
        assert t["current_return_sign"] == sign(t["current_return_pct"]) == s["total_return_sign"]
        assert t["current_return_pct"] == t["actual_return_pct"] == s["total_return_pct"]
        assert t["gap_pct"] == pytest.approx(t["current_return_pct"] - t["target_return_pct"], abs=2e-4)


def test_stack_and_donut_sums(result, empty_result):
    for res in (result, empty_result):
        for week in res["weekly_flow"]:
            assert [s["key"] for s in week["segments"]] == ["buy", "sell", "holdings", "cash"]
            assert sum(s["height_pct"] for s in week["segments"]) == pytest.approx(100.0, abs=1e-9)
            assert all(0 <= s["height_pct"] <= 100 for s in week["segments"])
        segs = res["allocation"]["segments"]
        assert segs[-1]["kind"] == "cash" and segs[-1]["end_pct"] == 100.0 and segs[0]["start_pct"] == 0.0
        for a, b in zip(segs, segs[1:]):
            assert a["end_pct"] == b["start_pct"]
        assert sum(s["value"] for s in segs) == res["allocation"]["total"] == res["summary"]["final_equity"]
        assert res["allocation"]["conic_gradient"].startswith("conic-gradient(#")
        assert res["allocation"]["conic_gradient"].endswith("100%)")


def test_summary_is_consistent_with_rows(result):
    s = result["summary"]
    assert s["final_equity"] == result["equity_curve"][-1]["equity"]
    assert s["total_pnl"] == s["realized_pnl"] + s["unrealized_pnl"]                 # 항등식 7.1-1
    assert s["trade_count"] == len(result["trades"]) == s["buy_count"] + s["sell_count"]
    assert s["sell_count"] >= 1 and s["closed_count"] == s["sell_count"]
    assert s["total_trade_value"] == sum(t["amount"] for t in result["trades"])
    assert s["total_cost"] == sum(t["cost"] for t in result["trades"])
    assert sum(st["total_pnl"] for st in result["per_stock"]) == s["total_pnl"]
    assert s["excess_return_pct"] == pytest.approx(s["total_return_pct"] - s["benchmark_return_pct"], abs=1e-4)
    assert s["holding_count"] == len(result["positions"]) <= s["max_positions"]
    assert len(result["equity_curve"]) == len(result["benchmark"]) == result["meta"]["period"]["trading_days"] == 20
    assert [e["date"] for e in result["equity_curve"]] == [b["date"] for b in result["benchmark"]]
    assert all(e["cash"] >= 0 for e in result["equity_curve"])
    assert result["meta"]["is_example"] is False and result["schema_version"] == "1.1"
    assert result["meta"]["period"]["start"] == "2026-08-31" and result["meta"]["period"]["end"] == SYN_END.isoformat()
    assert result["meta"]["costs"] == {"buy_cost_pct": 0.015, "sell_cost_pct": 0.215, "slippage_pct": 0.0}
    assert len(result["meta"]["disclaimers"]) == 6


def test_chart_geometry(result):
    eq = result["charts"]["equity"]
    n = len(result["equity_curve"])
    for name, w, h in (("equity_points", 720, 250), ("benchmark_points", 720, 250)):
        pts = [tuple(map(float, p.split(","))) for p in eq[name].split(" ")]
        assert len(pts) == n + 1 and pts[0][0] == 0.0 and pts[-1][0] == float(w)
        assert all(0 <= x <= w and 0 <= y <= h for x, y in pts)
        assert re.fullmatch(r"(-?\d+\.\d,-?\d+\.\d ?)+", eq[name])
    assert eq["equity_points"].split(" ")[0] == f"0.0,{eq['zero_line_y']}"          # 시작점은 수익률 0
    assert eq["equity_area_path"].startswith("M0.0,") and eq["equity_area_path"].endswith(" L720.0,250.0 L0.0,250.0 Z")
    labels = eq["y_labels"]
    assert len(labels) == 5 and labels[0] == eq["y_max"] and labels[-1] == eq["y_min"] and 0.0 in labels or eq["y_min"] < 0 < eq["y_max"]
    assert [x["label"] for x in eq["x_labels"]] == ["08-31", "09-07", "09-14", "09-21", "09-28"]
    assert [x["x_pct"] for x in eq["x_labels"]] == [5.0, 30.0, 55.0, 80.0, 95.0]
    for name in ("equity", "realized_pnl", "holdings"):
        pts = [tuple(map(float, p.split(","))) for p in result["charts"]["sparklines"][name].split(" ")]
        assert len(pts) == n + 1 and all(0 <= x <= 200 and 3 <= y <= 41 for x, y in pts)
    bars = result["charts"]["trade_value_bars"]
    assert len(bars) == len(result["weekly_flow"]) and max(b["height_pct"] for b in bars) == 100.0


def test_helpers():
    assert report.nice_axis(-1.1725, 1.8588) == (-2.0, 2.0, [2.0, 1.0, 0.0, -1.0, -2.0])
    assert report.nice_axis(0.2, 0.9) == (0.0, 2.0, [2.0, 1.5, 1.0, 0.5, 0.0])
    assert report.nice_axis(-300, 900)[1] >= 900
    assert report.polyline_points([0.0, 2.0, -2.0], 720, 250, -2.0, 2.0) == "0.0,125.0 360.0,0.0 720.0,250.0"
    assert [report.sign_of(v) for v in (1, -0.5, 0, None)] == ["pos", "neg", "zero", "zero"]


def test_per_stock_order_and_statuses(result):
    statuses = [s["status"] for s in result["per_stock"]]
    traded = [s for s in result["per_stock"] if s["status"] in ("held", "closed")]
    assert [s["total_pnl"] for s in traded] == sorted((s["total_pnl"] for s in traded), reverse=True)
    assert statuses[-2:] == ["no_trade", "excluded"]
    assert len(result["per_stock"]) == len(result["meta"]["universe"]) == 6
    last = result["per_stock"][-1]
    assert last["code"] == "000009" and last["status_label"] == "제외(데이터 없음)" and last["return_pct"] is None
    assert result["meta"]["data_source"]["excluded"] == [
        {"code": "000009", "name": "가상제외", "reason": "조회 결과 0건"}]
    assert max(s["bar_pct"] for s in traded) == 100.0
    top = result["top_contributors"]["items"]
    assert [i["rank"] for i in top] == list(range(1, len(top) + 1)) and len(top) <= 5
    # 개정 1.1: |total_pnl| 내림차순(동률 종목코드순), bar_pct 는 per_stock 과 같은 값
    expected = sorted(traded, key=lambda s: (-abs(s["total_pnl"]), s["code"]))[:5]
    assert [i["code"] for i in top] == [s["code"] for s in expected]
    by_code = {s["code"]: s for s in result["per_stock"]}
    assert all(i["bar_pct"] == by_code[i["code"]]["bar_pct"] and i["pnl"] == by_code[i["code"]]["total_pnl"]
               for i in top)
    assert top[0]["bar_pct"] == 100.0
    assert [i["bar_pct"] for i in top] == sorted((i["bar_pct"] for i in top), reverse=True)


def test_alerts_and_insights(result):
    alerts = result["alerts"]
    levels = [a["level"] for a in alerts]
    assert levels == sorted(levels, key=lambda lv: 0 if lv == "warn" else 1)      # warn 먼저
    missing = [a for a in alerts if a["code"] == "DATA_MISSING"][0]
    assert missing["title"] == "가상제외 데이터 없음: 유니버스에서 제외"
    assert missing["color"] == "#C98A2E" and missing["detail"] == "000009" and missing["date"] is None
    low = alerts[-1]
    assert low["code"] == "LOW_SAMPLE" and low["level"] == "info" and low["color"] == "#1428A0"
    assert low["title"] == "1개월(20거래일) 표본은 통계적 의미가 약합니다."
    assert low["detail"].startswith("리밸런싱 5회 · 청산 거래 ")
    assert result["flags"]["only_low_sample_alert"] is False
    assert [i["no"] for i in result["insights"]] == ["01", "02", "03"]
    assert [i["title"] for i in result["insights"]] == ["벤치마크 비교", "손익 분해", "리스크"]
    assert result["insights"][0]["detail"].startswith("기간 수익률 ")
    assert "유니버스 4종목 동일가중(" in result["insights"][0]["detail"]
    assert result["insights"][2]["detail"].startswith("최대 낙폭(MDD) ")
    assert result["next_action"]["label"] == "다음 조치"
    # 데이터 품질 알림(DATA_MISSING 1건)이 있으므로 10.2절 2번
    assert result["next_action"]["text"] == (
        "수치를 해석하기 전에 점검 필요의 데이터 알림 1건을 먼저 확인하세요. " + report.NEXT_SUFFIX)


def test_empty_case_5_6(empty_result):
    r = empty_result
    assert r["trades"] == [] and r["positions"] == [] and r["top_contributors"]["items"] == []
    assert r["flags"] == {"no_trades": True, "no_closed_trades": True, "no_positions": True,
                          "only_low_sample_alert": False}
    s = r["summary"]
    assert s["trade_count"] == 0 and s["win_rate_pct"] is None and s["payoff_ratio"] is None
    assert s["total_return_pct"] == 0.0 and s["mdd_pct"] == 0.0
    assert s["mdd_peak_date"] is None and s["mdd_trough_date"] is None
    assert r["charts"]["win_donut"]["win_pct"] == 0.0
    assert all(b["height_pct"] == 0.0 for b in r["charts"]["trade_value_bars"])
    assert len(r["weekly_flow"]) == 5 and all(w["buy_value"] == 0 == w["sell_value"] for w in r["weekly_flow"])
    no_trades = [a for a in r["alerts"] if a["code"] == "NO_TRADES"]
    assert len(no_trades) == 1 and no_trades[0]["level"] == "warn"
    assert no_trades[0]["title"] == "백테스트 기간에 거래가 없습니다."
    segs = r["allocation"]["segments"]
    assert len(segs) == 1 and segs[0]["kind"] == "cash" and (segs[0]["start_pct"], segs[0]["end_pct"]) == (0.0, 100.0)
    assert r["allocation"]["center"]["value_pct"] == 0.0
    assert all(st["status"] == "no_trade" and st["win_rate_pct"] is None for st in r["per_stock"])
    assert r["insights"][1]["detail"] == "백테스트 기간에 체결된 거래가 없어 전 기간 현금을 보유했습니다."
    assert r["insights"][2]["detail"] == "거래가 없어 최대 낙폭(MDD)은 0.00%입니다."
    assert r["insights"][0]["detail"].startswith("기간 수익률 0.00%, KOSPI(")
    assert r["next_action"]["text"] == "점검 필요의 데이터 알림과 백테스트 구간 설정을 먼저 확인하세요."
    assert r["top_contributors"]["note"] == "거래가 없어 손익 기여 종목이 없습니다."
    assert r["target"]["caption"] == (
        "목표 +2.00%에 2.00%p 못 미쳤습니다(현재 0.00%). 목표 평가금액까지 2,000,000원 부족.")
    assert r["charts"]["sparklines"]["equity"].split(" ")[0] == "0.0,22.0"
    assert r["target"]["progress_pct"] == 0.0 and r["target"]["achieved"] is False


def test_alert_rules_from_events():
    summary = {"mdd": -0.0612, "mdd_peak_date": None, "mdd_trough_date": SYN_END, "max_loss_streak": 3,
               "excess_return": -0.025, "total_return": -0.03, "benchmark_return": -0.005,
               "trade_count": 4, "closed_count": 3}
    stocks = [{"code": "000001", "name": "가상전자"}]
    positions = [{"code": "000001", "name": "가상전자", "weight_pct": 45.5}]
    events = [
        {"code": "QTY_ZERO_SKIP", "stock": "000001", "date": SYN_END, "value": 21_000_000,
         "excluded": False, "side": "BUY", "extra": {"alloc": 20_000_000}},
        {"code": "UNTRADABLE_SKIP", "stock": "000001", "date": SYN_END, "value": None,
         "excluded": False, "side": "SELL", "extra": {}},
        {"code": "BENCHMARK_BASE_FALLBACK", "stock": None, "date": None, "value": None,
         "excluded": False, "side": None, "extra": {}},
    ]
    issues = [data.make_issue("PRICE_ANOMALY", "000001", day=SYN_END, value=0.35),
              data.make_issue("DATA_MISSING", "000001", value=2)]
    alerts = report.build_alerts(summary, stocks, positions, issues, events,
                                 {"trading_days": 20, "months": 1, "rebalances": 5})
    assert [a["code"] for a in alerts] == [
        "MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM", "DATA_MISSING", "PRICE_ANOMALY", "UNTRADABLE_SKIP",
        "QTY_ZERO_SKIP", "CONCENTRATION", "BENCHMARK_BASE_FALLBACK", "LOW_SAMPLE"]
    by = {a["code"]: a for a in alerts}
    fields = {c: (a["title"], a["detail"], a["date"]) for c, a in by.items()}
    assert fields["MDD_BREACH"] == ("MDD -6.12%, 임계 -5.00% 초과", "고점 초기 자본 → 저점 2026-09-29", None)
    assert by["MDD_BREACH"]["color"] == "#B0472F"
    assert fields["LOSS_STREAK"] == ("청산 거래 3회 연속 손실", "임계 3회", None)
    assert fields["UNDERPERFORM"] == ("KOSPI보다 2.50%p 낮았습니다.", "전략 -3.00% · KOSPI -0.50%", None)
    assert fields["DATA_MISSING"] == ("가상전자 데이터 2일 결측", "000001", None)
    assert fields["PRICE_ANOMALY"] == ("가상전자 등락 +35.00%: 수정주가 확인 필요", "000001 · 전일 종가 대비",
                                       "2026-09-29")
    assert fields["UNTRADABLE_SKIP"] == ("가상전자 매도 불가로 건너뜀",
                                         "000001 · 거래정지·결측 또는 가격제한폭 시가", "2026-09-29")
    assert fields["QTY_ZERO_SKIP"] == ("가상전자 1주 가격이 배분금액을 넘어 매수하지 못했습니다.",
                                       "000001 · 체결가 21,000,000원 · 배분금액 20,000,000원", "2026-09-29")
    assert fields["CONCENTRATION"] == ("가상전자 비중 45.50%로 편중", "000001", None)
    assert fields["BENCHMARK_BASE_FALLBACK"] == ("벤치마크 기준가를 직전 종가로 대체했습니다.", "", None)
    for a in alerts:                                         # 10.3절: title 에 날짜 없음, 한 알림에 날짜 한 번
        assert not re.search(r"\d{4}-\d{2}-\d{2}", a["title"])
        text = a["detail"] + " " + (a["date"] or "")
        assert all(text.count(d) == 1 for d in re.findall(r"\d{4}-\d{2}-\d{2}", text))
    assert [a["level"] for a in alerts] == ["warn"] * 6 + ["info"] * 4


def test_only_low_sample_flag_and_target_clip():
    run = syn_run()
    res = _build(run, target=0.0001)                    # 아주 낮은 목표 → 진척 100%로 잘림(수익일 때)
    codes = [a["code"] for a in res["alerts"]]
    assert res["flags"]["only_low_sample_alert"] == (codes == ["LOW_SAMPLE"])
    t = res["target"]
    assert 0.0 <= t["progress_pct"] <= 100.0
    assert sum(b["width_pct"] for b in t["bar_segments"]) == pytest.approx(t["progress_pct"], abs=0.011)
    assert all(b["width_pct"] >= 0 for b in t["bar_segments"])
    assert t["achieved"] == (res["summary"]["final_equity"] >= t["target_equity"])
    assert t["gap_amount"] == max(t["target_equity"] - res["summary"]["final_equity"], 0)
