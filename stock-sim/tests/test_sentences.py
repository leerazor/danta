"""strategy.md 10절 문장 규칙 테스트. 10.6절 손계산 기대 문자열을 그대로 고정한다."""
import re
from datetime import date

import pytest

from helpers import BT_START, CAPITAL, HAND_END, HAND_START, run_hand, syn_run
from stock_sim import data, metrics, report

SUFFIX = "1개월 표본이므로 전략 변경은 구간을 늘려 본 뒤 판단하세요."


# ---- 9절 손계산 → 10.6절 기대 문자열 ----------------------------------------------
@pytest.fixture(scope="module")
def hand_result():
    run = run_hand(top_n=1)
    run["bench_info"]["equal_weight_return"] = metrics.equal_weight_return(run["prices"], run["days"])
    run["bench_info"]["equal_weight_count"] = metrics.equal_weight_count(run["prices"], run["days"])
    cfg = {
        "kis": {"env": "DEV"},
        "universe": [{"code": "AAA", "name": "AAA"}, {"code": "BBB", "name": "BBB"}],   # 종목명 없음 → 코드
        "benchmark": {"code": "0001", "name": "KOSPI"},
        "backtest": {"months": 1},
        "strategy": {"name": "momentum_topn", "params": run["params"]},
        "capital": CAPITAL, "max_positions": 1,
        "costs": {"buy_fee_pct": 0.015, "sell_fee_pct": 0.015, "sell_tax_pct": 0.20, "slippage_pct": 0.0},
        "target_return": 2.0,
    }
    period = {"fetch_start": HAND_START, "requested_start": BT_START, "end": HAND_END,
              "rebalances": len(run["schedule"])}
    return report.build_result(cfg, period, run["bt"], run["bench"], run["bench_info"], [],
                               {"api_calls": 0, "cache_hits": 3}, "2026-09-30T09:15:00+09:00")


def test_10_6_benchmark_sentence(hand_result):
    assert hand_result["insights"][0]["detail"] == (
        "기간 수익률 +3.55%, KOSPI(+2.00%)보다 1.55%p 높았습니다. "
        "유니버스 2종목 동일가중(+3.48%)보다 0.06%p 높았습니다.")


def test_10_6_pnl_sentence_b6(hand_result):
    assert hand_result["insights"][1]["detail"] == (
        "실현 +738,502원, 보유 1종목 평가손익 +2,807,897원으로 총손익 +3,546,399원입니다. "
        "평가손익 상위: BBB +2,807,897원.")


def test_10_6_risk_sentence(hand_result):
    assert hand_result["insights"][2]["detail"] == (
        "최대 낙폭(MDD) -1.20%, 고점 2026-09-22 → 저점 2026-09-28. 임계 -5.00% 이내입니다.")


def test_10_6_next_action_rule_7(hand_result):
    assert hand_result["next_action"]["text"] == (
        "종목별 상세에서 손익이 특정 종목에 몰렸는지 먼저 확인하세요. " + SUFFIX)


def test_10_6_top_contributors_note(hand_result):
    assert hand_result["top_contributors"]["note"] == (
        "이익 2종목 합계 +3,546,399원, 손실 종목 없음 → 총손익 +3,546,399원")


def test_10_6_target_caption(hand_result):
    assert hand_result["target"]["caption"] == (
        "목표 +2.00%를 1.55%p 넘었습니다(현재 +3.55%). 목표 평가금액보다 1,546,399원 많습니다.")
    t = hand_result["target"]
    assert t["current_return_pct"] == 3.5464 and t["current_return_sign"] == "pos"
    assert t["gap_pct"] == 1.5464 and t["gap_amount"] == 0 and t["achieved"] is True
    s = hand_result["summary"]
    assert s["excess_vs_equal_weight_pct"] == 0.0618 and s["excess_vs_equal_weight_sign"] == "pos"


def test_hand_titles_and_realized_sign(hand_result):
    assert [i["title"] for i in hand_result["insights"]] == ["벤치마크 비교", "손익 분해", "리스크"]
    by = {s["code"]: s for s in hand_result["per_stock"]}
    assert by["AAA"]["realized_pnl_sign"] == "pos" and by["BBB"]["realized_pnl_sign"] == "zero"
    assert by["BBB"]["sign"] == "pos"


# ---- 10.0절 공통 표기 규칙 ---------------------------------------------------------
def _sentences(res):
    out = [i["detail"] for i in res["insights"]] + [res["next_action"]["text"],
                                                     res["top_contributors"]["note"], res["target"]["caption"]]
    for a in res["alerts"]:
        out += [a["title"], a["detail"]]
    return out


@pytest.mark.parametrize("which", ["hand", "syn"])
def test_common_notation_rules(which, hand_result):
    res = hand_result if which == "hand" else _syn_result()
    for text in _sentences(res):
        assert "−" not in text and "–" not in text, text      # ASCII '-' 만
        assert "-0.00%" not in text and "+0.00%" not in text and "+0원" not in text and "-0원" not in text, text
        assert not re.search(r"\((이|가|은|는|을|를|와|과)\)", text), text   # 조사 병기 금지
        assert "달성률" not in text and "대비" not in text.replace("전일 종가 대비", ""), text


def _syn_result():
    run = syn_run()
    return report.build_result(run["cfg"], run["period"], run["bt"], run["bench"], run["bench_info"], [],
                               {"api_calls": 0, "cache_hits": 5}, "2026-09-30T09:15:00+09:00")


# ---- 10.1절 ② 분기 B1~B6 ------------------------------------------------------------
def _summ(**kw):
    base = {"trade_count": 5, "closed_count": 1, "holding_count": 2, "realized_pnl": 0,
            "unrealized_pnl": 0, "total_pnl": 0, "total_return": 0.0, "benchmark_return": 0.0,
            "excess_return": 0.0, "mdd": 0.0, "mdd_peak_date": None, "mdd_trough_date": None,
            "max_loss_streak": 0}
    base.update(kw)
    base["total_pnl"] = base["realized_pnl"] + base["unrealized_pnl"]
    return base


POS = [{"code": "000002", "name": "나종목", "unrealized_pnl": -300},
       {"code": "000001", "name": "가종목", "unrealized_pnl": -300},
       {"code": "000003", "name": "다종목", "unrealized_pnl": 500}]


def test_b1_no_closed():
    s = _summ(closed_count=0, holding_count=3, unrealized_pnl=-100)
    assert report._pnl_sentence(s, POS) == (
        "청산된 거래가 없어 총손익 -100원은 전부 보유 3종목 평가손익입니다. "
        "평가손익 상위: 다종목 +500원, 가종목 -300원.")


def test_b2_no_holdings():
    s = _summ(closed_count=2, holding_count=0, realized_pnl=1234)
    assert report._pnl_sentence(s, []) == "기간 말 보유 종목이 없어 총손익 +1,234원은 전부 실현 손익입니다(청산 2건)."


def test_b3_unrealized_decides_sign():
    s = _summ(holding_count=3, realized_pnl=925_024, unrealized_pnl=-1_763_880)
    assert report._pnl_sentence(s, POS) == (
        "실현 +925,024원이지만 보유 3종목 평가손익 -1,763,880원이 더 커 총손익 -838,856원입니다. "
        "평가손실 상위: 가종목 -300원, 나종목 -300원.")                      # 동률은 종목코드순


def test_b3_gain_label():
    s = _summ(holding_count=3, realized_pnl=-100, unrealized_pnl=200)
    assert report._pnl_sentence(s, POS).endswith("평가이익 상위: 다종목 +500원.")


def test_b4_realized_decides_sign():
    s = _summ(holding_count=3, realized_pnl=-1000, unrealized_pnl=100)
    assert report._pnl_sentence(s, POS) == (
        "보유 3종목 평가손익 +100원이지만 실현 -1,000원이 더 커 총손익 -900원입니다. "
        "평가손익 상위: 다종목 +500원, 가종목 -300원.")


def test_b5_offset():
    s = _summ(holding_count=3, realized_pnl=-100, unrealized_pnl=100)
    assert report._pnl_sentence(s, []) == "실현 -100원과 보유 3종목 평가손익 +100원이 상쇄되어 총손익 0원입니다."


def test_b6_same_direction_and_zero():
    s = _summ(holding_count=2, realized_pnl=0, unrealized_pnl=0)
    assert report._pnl_sentence(s, [{"code": "000001", "name": "가", "unrealized_pnl": 0}]) == (
        "실현 0원, 보유 2종목 평가손익 0원으로 총손익 0원입니다.")


# ---- 10.1절 ①·③ 분기 ------------------------------------------------------------------
def test_benchmark_sentence_branches():
    s = _summ(total_return=-0.008389, benchmark_return=0.038894)
    assert report._benchmark_sentence(s, -0.034216, 10) == (
        "기간 수익률 -0.84%, KOSPI(+3.89%)보다 4.73%p 낮았습니다. "
        "유니버스 10종목 동일가중(-3.42%)보다 2.58%p 높았습니다.")
    same = _summ(total_return=0.01001, benchmark_return=0.01)            # 표시값 0.00%p → 같았습니다
    assert report._benchmark_sentence(same, 0.01002, 3) == (
        "기간 수익률 +1.00%, KOSPI(+1.00%)와 같았습니다. 유니버스 3종목 동일가중(+1.00%)과 같았습니다.")
    assert report._benchmark_sentence(same, None, None) == "기간 수익률 +1.00%, KOSPI(+1.00%)와 같았습니다."


def test_risk_sentence_branches():
    base = dict(trade_count=3)
    assert report._risk_sentence(_summ(**base, mdd=0.0), False) == (
        "최대 낙폭(MDD) 0.00%, 평가액이 직전 고점 아래로 내려간 날이 없습니다.")
    assert report._risk_sentence(_summ(**base, mdd=-0.00004), False).startswith("최대 낙폭(MDD) 0.00%, 평가액이")
    s = _summ(**base, mdd=-0.0514, mdd_peak_date=None, mdd_trough_date=date(2026, 9, 3))
    assert report._risk_sentence(s, True) == (
        "최대 낙폭(MDD) -5.14%, 고점 초기 자본 → 저점 2026-09-03. 임계 -5.00%를 넘었습니다.")
    assert report._risk_sentence(_summ(trade_count=0), False) == "거래가 없어 최대 낙폭(MDD)은 0.00%입니다."


# ---- 10.2절 다음 조치 우선순위 ---------------------------------------------------------
STOCKS = [{"code": "000001", "name": "가종목", "realized_pnl": -50},
          {"code": "000002", "name": "나종목", "realized_pnl": -70},
          {"code": "000003", "name": "다종목", "realized_pnl": 10}]


def _alert(code):
    return {"code": code, "level": "warn"}


def test_next_action_priorities():
    loss = _summ(realized_pnl=-120, unrealized_pnl=-10)
    assert report._next_action(loss, STOCKS, POS, [_alert("PRICE_ANOMALY"), _alert("DATA_MISSING"),
                                                   _alert("MDD_BREACH")]) == (
        "수치를 해석하기 전에 점검 필요의 데이터 알림 2건을 먼저 확인하세요. " + SUFFIX)
    assert report._next_action(loss, STOCKS, POS, []) == (
        "종목별 상세에서 평가손실 상위 종목(가종목·나종목)을 먼저 확인하세요. " + SUFFIX)
    gains_only = [{"code": "000003", "name": "다종목", "unrealized_pnl": 5}]
    assert report._next_action(_summ(realized_pnl=-120, unrealized_pnl=5), STOCKS, gains_only, []) == (
        "종목별 상세에서 실현 손실 상위 종목(나종목·가종목)을 먼저 확인하세요. " + SUFFIX)
    breach = _summ(realized_pnl=10, mdd=-0.06, mdd_peak_date=date(2026, 9, 9),
                   mdd_trough_date=date(2026, 9, 29))
    assert report._next_action(breach, STOCKS, [], [_alert("MDD_BREACH")]) == (
        "자산 곡선에서 고점 2026-09-09 → 저점 2026-09-29 구간을 먼저 확인하세요. " + SUFFIX)
    under = _summ(realized_pnl=10, total_return=0.001, benchmark_return=0.03)
    assert report._next_action(under, STOCKS, [], []) == (
        "자산 곡선에서 KOSPI와 차이가 벌어진 구간을 먼저 확인하세요. " + SUFFIX)
    assert report._next_action(_summ(trade_count=0), STOCKS, [], [_alert("NO_TRADES")]) == (
        "점검 필요의 데이터 알림과 백테스트 구간 설정을 먼저 확인하세요.")


# ---- 10.3절 데이터 품질 알림 문구 --------------------------------------------------------
def test_data_quality_alert_texts():
    summ = _summ(trade_count=2)
    issues = [data.make_issue("NON_INTEGER_PRICE", "000001"),
              data.make_issue("TRUNCATION_SUSPECT", "000001"),
              data.make_issue("TRUNCATION_SUSPECT", "IDX0001")]
    alerts = report.build_alerts(summ, [{"code": "000001", "name": "가종목"}], [], issues, [],
                                 {"trading_days": 20, "months": 1, "rebalances": 5})
    got = [(a["code"], a["title"], a["detail"], a["date"], a["level"]) for a in alerts]
    assert got[:3] == [
        ("NON_INTEGER_PRICE", "가종목 가격에 정수가 아닌 값: 원 단위로 반올림", "000001", None, "warn"),
        ("TRUNCATION_SUSPECT", "가종목 응답 건수가 상한에 닿음: 데이터 잘림 확인 필요", "000001", None, "warn"),
        ("TRUNCATION_SUSPECT", "KOSPI 지수 응답 건수가 상한에 닿음: 데이터 잘림 확인 필요", "0001", None, "warn"),
    ]


def test_same_code_alerts_sorted_by_date_then_stock():
    ev = [data.make_issue("PRICE_ANOMALY", "000002", day=date(2026, 9, 2), value=0.31),
          data.make_issue("PRICE_ANOMALY", "000001", day=date(2026, 9, 3), value=-0.31),
          data.make_issue("PRICE_ANOMALY", "000003", day=date(2026, 9, 2), value=0.4)]
    alerts = report.build_alerts(_summ(), [], [], ev, [], {"trading_days": 20, "months": 1})
    assert [(a["date"], a["detail"][:6]) for a in alerts if a["code"] == "PRICE_ANOMALY"] == [
        ("2026-09-02", "000002"), ("2026-09-02", "000003"), ("2026-09-03", "000001")]


# ---- 10.4·10.5절 -------------------------------------------------------------------------
def _stock(code, pnl, status="held"):
    return {"code": code, "name": code, "total_pnl": pnl, "status": status, "sign": report.sign_of(pnl),
            "bar_pct": 0.0}


def test_top_contributors_note_branches_and_order():
    stocks = [_stock("A", 100), _stock("B", -300, "closed"), _stock("C", 0), _stock("D", -50),
              _stock("E", 300), _stock("F", 10), _stock("G", 0, "no_trade")]
    top = report._top_contributors(stocks, 6)
    assert [i["code"] for i in top["items"]] == ["B", "E", "A", "D", "F"]      # |pnl| 내림차순, 동률 코드순
    assert top["note"] == "이익 3종목 합계 +410원, 손실 2종목 합계 -350원 → 총손익 +60원"
    assert report._top_contributors([_stock("A", -5)], 1)["note"] == (
        "이익 종목 없음, 손실 1종목 합계 -5원 → 총손익 -5원")
    assert report._top_contributors([_stock("A", 0)], 2)["note"] == "손익이 발생한 종목이 없습니다 → 총손익 0원"


@pytest.mark.parametrize("final, expected", [
    (99_161_144, "목표 +2.00%에 2.84%p 못 미쳤습니다(현재 -0.84%). 목표 평가금액까지 2,838,856원 부족."),
    (102_000_000, "목표 +2.00%를 달성했습니다(현재 +2.00%)."),
    (102_500_000, "목표 +2.00%를 0.50%p 넘었습니다(현재 +2.50%). 목표 평가금액보다 500,000원 많습니다."),
])
def test_target_caption_branches(final, expected):
    s = {"final_equity": final, "total_return": final / CAPITAL - 1, "realized_pnl": 0}
    t = report._target(s, CAPITAL, 2.0)
    assert t["caption"] == expected
    assert t["gap_amount"] == max(102_000_000 - final, 0) and t["achieved"] == (final >= 102_000_000)
