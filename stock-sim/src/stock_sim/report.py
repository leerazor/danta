"""result.json 조립(좌표·비율·문장 포함)과 저장 (architecture.md 5절, strategy.md 10~11절).

build_result는 순수 함수다. % 변환·자리수 맞춤·좌표 계산은 이 모듈에서만 한다.
템플릿은 계산하지 않으므로 표시에 필요한 값은 전부 여기서 만든다.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

from stock_sim import metrics
from stock_sim.strategy import STRATEGIES

BLUE, RED, AMBER = "#1428A0", "#B0472F", "#C98A2E"
STOCK_COLORS = ["#1428A0", "#4B5CC0", "#7C9BFF", "#909BD6", "#C2C8E8"]
CASH_COLOR = "#DCE0E9"
FLOW_SEGMENTS = [("buy", "매수", "#1428A0"), ("sell", "매도", "#4B5CC0"),
                 ("holdings", "보유", "#7C9BFF"), ("cash", "현금", "#C2C8E8")]
AXIS_STEPS = [0.5, 1, 2, 5, 10, 20, 50]
STATUS_LABELS = {"held": "보유", "closed": "청산", "no_trade": "거래 없음",
                 "excluded": "제외(데이터 없음)"}
WARN_ORDER = ["MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM", "NO_TRADES", "DATA_MISSING",
              "PRICE_ANOMALY", "UNTRADABLE_SKIP", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT"]
INFO_ORDER = ["QTY_ZERO_SKIP", "CONCENTRATION", "BENCHMARK_BASE_FALLBACK", "LOW_SAMPLE"]
RED_CODES = {"MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM"}
MDD_LIMIT, STREAK_LIMIT, UNDERPERFORM_LIMIT, CONCENTRATION_LIMIT = -0.05, 3, -0.02, 30.0


# ---- 표시 변환 헬퍼 --------------------------------------------------------
def _r(x, nd: int = 4):
    """소수 nd자리 반올림(표시용 값). None·NaN은 None, -0.0은 0.0."""
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    v = round(x, nd)
    return 0.0 if v == 0 else v


def _pct(x):
    return _r(x * 100, 4) if x is not None else None


def _opt(x):
    """None·NaN → None."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return x


def _d(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else None


def _spct(v: float) -> str:
    """% 값 → '+1.86%' / '-2.15%' / '0.00%'."""
    return "0.00%" if round(v, 2) == 0 else f"{v:+.2f}%"


def _swon(v: int) -> str:
    return "0" if v == 0 else f"{int(v):+,}"


def _num(p: float) -> str:
    return f"{p:.2f}".rstrip("0").rstrip(".")


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sign_of(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)) or x == 0:
        return "zero"
    return "pos" if x > 0 else "neg"


def polyline_points(values: list[float], width: float, height: float,
                    y_min: float, y_max: float) -> str:
    """'x,y x,y ...' 소수 1자리. x_i = width × i / (점 수 − 1), y는 위가 y_max."""
    n = max(len(values) - 1, 1)
    span = y_max - y_min
    out = []
    for i, v in enumerate(values):
        y = height * (y_max - v) / span if span else height / 2
        out.append(f"{_r(width * i / n, 1)},{_r(y, 1)}")
    return " ".join(out)


def nice_axis(v_min: float, v_max: float) -> tuple[float, float, list[float]]:
    """(y_min, y_max, 위→아래 라벨 5개). 0을 포함하고 4칸이 범위를 덮는 가장 작은 간격."""
    lo, hi = min(v_min, 0.0), max(v_max, 0.0)
    steps = list(AXIS_STEPS)
    while True:
        for step in steps:
            y_min = math.floor(lo / step) * step
            if y_min + 4 * step >= hi:
                y_max = y_min + 4 * step
                labels = [_r(y_max - i * step, 4) for i in range(5)]
                return _r(y_min, 4), _r(y_max, 4), labels
        steps = [s * 10 for s in steps]


def _sparkline(values: list[float]) -> str:
    lo, hi = min(values), max(values)
    n = max(len(values) - 1, 1)
    out = []
    for i, v in enumerate(values):
        y = 22.0 if hi == lo else 41 - 38 * (v - lo) / (hi - lo)
        out.append(f"{_r(200 * i / n, 1)},{_r(y, 1)}")
    return " ".join(out)


def _bar_color(height_pct: float) -> str:
    if height_pct >= 75:
        return "#1428A0"
    if height_pct >= 50:
        return "#4B5CC0"
    return "#909BD6" if height_pct >= 25 else "#C2C8E8"


# ---- 알림·인사이트 (strategy.md 10절) ------------------------------------------
DATA_QUALITY_CODES = ("DATA_MISSING", "PRICE_ANOMALY", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT")
NEXT_SUFFIX = "1개월 표본이므로 전략 변경은 구간을 늘려 본 뒤 판단하세요."


def _disp(v: float) -> float:
    """소수 2자리 표시값(10.0절 4번: 비율 문장의 분기는 표시값으로 판정). -0.0은 0.0."""
    d = float(f"{v:.2f}")
    return 0.0 if d == 0 else d


def _upct(v: float) -> str:
    """부호 없는 절댓값 2자리('{x}%p'의 x)."""
    return f"{abs(_disp(v)):.2f}"


def _label(item: dict) -> str:
    """종목명, 없으면 종목코드(10.0절 6번)."""
    return item.get("name") or item["code"]


def _mdd_span(summary: dict) -> tuple[str, str]:
    """(고점일, 저점일). 고점이 E0이면 '초기 자본'(10.1절 ③)."""
    return _d(summary["mdd_peak_date"]) or "초기 자본", _d(summary["mdd_trough_date"]) or ""


def _top_abs(items: list[dict], key: str, k: int = 2) -> list[dict]:
    """절댓값 내림차순, 동률은 종목코드 오름차순."""
    return sorted(items, key=lambda x: (-abs(x[key]), x["code"]))[:k]


def build_alerts(summary: dict, stocks: list[dict], positions: list[dict],
                 issues: list[dict], events: list[dict], period: dict) -> list[dict]:
    """strategy.md 10.3절. title에는 날짜를 넣지 않고, 날짜 하나는 date, 구간은 detail에 쓴다."""
    names = {s["code"]: _label(s) for s in stocks}
    raw: list[tuple[str, str, str, str | None, str]] = []   # (code, title, detail, date, stock)

    def nm(code):
        return names.get(code, code)

    if summary["mdd"] <= MDD_LIMIT:
        peak, trough = _mdd_span(summary)
        raw.append(("MDD_BREACH", f"MDD {_spct(summary['mdd'] * 100)}, 임계 -5.00% 초과",
                    f"고점 {peak} → 저점 {trough}", None, ""))
    if summary["max_loss_streak"] >= STREAK_LIMIT:
        raw.append(("LOSS_STREAK", f"청산 거래 {summary['max_loss_streak']}회 연속 손실", "임계 3회", None, ""))
    if summary["excess_return"] <= UNDERPERFORM_LIMIT:
        raw.append(("UNDERPERFORM", f"KOSPI보다 {_upct(summary['excess_return'] * 100)}%p 낮았습니다.",
                    f"전략 {_spct(summary['total_return'] * 100)} · KOSPI "
                    f"{_spct(summary['benchmark_return'] * 100)}", None, ""))
    if summary["trade_count"] == 0:
        raw.append(("NO_TRADES", "백테스트 기간에 거래가 없습니다.", "", None, ""))
    for ev in list(issues) + list(events):
        code, stock, day = ev["code"], ev.get("stock") or "", _d(ev.get("date"))
        if code == "DATA_MISSING":
            title = (f"{nm(stock)} 데이터 없음: 유니버스에서 제외" if ev.get("excluded")
                     else f"{nm(stock)} 데이터 {int(ev['value'])}일 결측")
            raw.append((code, title, stock, None, stock))
        elif code == "PRICE_ANOMALY":
            raw.append((code, f"{nm(stock)} 등락 {_spct(ev['value'] * 100)}: 수정주가 확인 필요",
                        f"{stock} · 전일 종가 대비", day, stock))
        elif code == "UNTRADABLE_SKIP":
            side = "매수" if ev.get("side") == "BUY" else "매도"
            raw.append((code, f"{nm(stock)} {side} 불가로 건너뜀",
                        f"{stock} · 거래정지·결측 또는 가격제한폭 시가", day, stock))
        elif code == "NON_INTEGER_PRICE":
            raw.append((code, f"{nm(stock)} 가격에 정수가 아닌 값: 원 단위로 반올림", stock, None, stock))
        elif code == "TRUNCATION_SUSPECT":
            is_index = stock.startswith("IDX")
            label, detail = ("KOSPI 지수", stock[3:]) if is_index else (nm(stock), stock)
            raw.append((code, f"{label} 응답 건수가 상한에 닿음: 데이터 잘림 확인 필요", detail, None, stock))
        elif code == "QTY_ZERO_SKIP":
            alloc = (ev.get("extra") or {}).get("alloc")
            detail = f"{stock} · 체결가 {int(ev['value']):,}원"
            detail += f" · 배분금액 {int(alloc):,}원" if alloc is not None else ""
            raw.append((code, f"{nm(stock)} 1주 가격이 배분금액을 넘어 매수하지 못했습니다.", detail, day, stock))
        elif code == "BENCHMARK_BASE_FALLBACK":
            raw.append((code, "벤치마크 기준가를 직전 종가로 대체했습니다.", "", None, ""))
    for pos in positions:
        if pos["weight_pct"] > CONCENTRATION_LIMIT:
            raw.append(("CONCENTRATION", f"{_label(pos)} 비중 {pos['weight_pct']:.2f}%로 편중",
                        pos["code"], None, pos["code"]))
    n_days, months = period.get("trading_days", 0), period.get("months", 1)
    raw.append(("LOW_SAMPLE", f"{months}개월({n_days}거래일) 표본은 통계적 의미가 약합니다.",
                f"리밸런싱 {period.get('rebalances', 0)}회 · 청산 거래 {summary['closed_count']}건", None, ""))
    order = {c: i for i, c in enumerate(WARN_ORDER + INFO_ORDER)}
    raw.sort(key=lambda a: (order.get(a[0], len(order)), a[3] or "", a[4]))
    out = []
    for code, title, detail, day, _ in raw:
        level = "info" if code in INFO_ORDER else "warn"
        color = BLUE if level == "info" else (RED if code in RED_CODES else AMBER)
        out.append({"level": level, "code": code, "title": title, "detail": detail,
                    "date": day, "color": color})
    return out


def _benchmark_sentence(summary: dict, ew: float | None, ew_count: int | None) -> str:
    """10.1절 ①. 차이는 반올림 전 원값끼리 뺀다(10.0절 3번)."""
    r, bm = summary["total_return"] * 100, summary["benchmark_return"] * 100
    diff = (summary["total_return"] - summary["benchmark_return"]) * 100
    head = f"기간 수익률 {_spct(r)}, "
    if _disp(diff) > 0:
        head += f"KOSPI({_spct(bm)})보다 {_upct(diff)}%p 높았습니다."
    elif _disp(diff) < 0:
        head += f"KOSPI({_spct(bm)})보다 {_upct(diff)}%p 낮았습니다."
    else:
        head += f"KOSPI({_spct(bm)})와 같았습니다."
    if ew is None:
        return head
    ew_diff = (summary["total_return"] - ew) * 100
    tail = f"유니버스 {ew_count}종목 동일가중({_spct(ew * 100)})"
    if _disp(ew_diff) > 0:
        tail += f"보다 {_upct(ew_diff)}%p 높았습니다."
    elif _disp(ew_diff) < 0:
        tail += f"보다 {_upct(ew_diff)}%p 낮았습니다."
    else:
        tail += "과 같았습니다."
    return f"{head} {tail}"


def _position_clause(positions: list[dict], p_u: int, decisive: bool) -> str:
    """10.1절 ② 종목 절. 기간 말 보유 포지션의 평가손익으로 고른다(종목별 총손익이 아니다)."""
    if decisive:
        picked = [p for p in positions if p["unrealized_pnl"] * p_u > 0]
        label = "평가손실 상위" if p_u < 0 else "평가이익 상위"
    else:
        picked = [p for p in positions if p["unrealized_pnl"] != 0]
        label = "평가손익 상위"
    picked = _top_abs(picked, "unrealized_pnl")
    if not picked:
        return ""
    return f"{label}: " + ", ".join(f"{_label(p)} {_swon(p['unrealized_pnl'])}원" for p in picked) + "."


def _pnl_sentence(summary: dict, positions: list[dict]) -> str:
    """10.1절 ② 손익 분해(B0~B6, 위에서부터 첫 번째 분기)."""
    t, c, h = summary["trade_count"], summary["closed_count"], summary["holding_count"]
    p_r, p_u, p = summary["realized_pnl"], summary["unrealized_pnl"], summary["total_pnl"]
    if t == 0:
        return "백테스트 기간에 체결된 거래가 없어 전 기간 현금을 보유했습니다."
    opposite = p_r * p_u < 0
    if c == 0 and h >= 1:
        body, clause = f"청산된 거래가 없어 총손익 {_swon(p)}원은 전부 보유 {h}종목 평가손익입니다.", "general"
    elif c >= 1 and h == 0:
        body, clause = f"기간 말 보유 종목이 없어 총손익 {_swon(p)}원은 전부 실현 손익입니다(청산 {c}건).", None
    elif opposite and abs(p_u) > abs(p_r):
        body, clause = (f"실현 {_swon(p_r)}원이지만 보유 {h}종목 평가손익 {_swon(p_u)}원이 더 커 "
                        f"총손익 {_swon(p)}원입니다."), "decisive"
    elif opposite and abs(p_r) > abs(p_u):
        body, clause = (f"보유 {h}종목 평가손익 {_swon(p_u)}원이지만 실현 {_swon(p_r)}원이 더 커 "
                        f"총손익 {_swon(p)}원입니다."), "general"
    elif opposite:
        body, clause = (f"실현 {_swon(p_r)}원과 보유 {h}종목 평가손익 {_swon(p_u)}원이 상쇄되어 "
                        "총손익 0원입니다."), "general"
    else:
        body, clause = (f"실현 {_swon(p_r)}원, 보유 {h}종목 평가손익 {_swon(p_u)}원으로 "
                        f"총손익 {_swon(p)}원입니다."), "general"
    extra = _position_clause(positions, p_u, clause == "decisive") if clause else ""
    return f"{body} {extra}" if extra else body


def _risk_sentence(summary: dict, breach: bool) -> str:
    """10.1절 ③."""
    if summary["trade_count"] == 0:
        return "거래가 없어 최대 낙폭(MDD)은 0.00%입니다."
    mdd = summary["mdd"] * 100
    if _disp(mdd) == 0:
        return "최대 낙폭(MDD) 0.00%, 평가액이 직전 고점 아래로 내려간 날이 없습니다."
    peak, trough = _mdd_span(summary)
    tail = "임계 -5.00%를 넘었습니다." if breach else "임계 -5.00% 이내입니다."
    return f"최대 낙폭(MDD) {_spct(mdd)}, 고점 {peak} → 저점 {trough}. {tail}"


def _next_action(summary: dict, stocks: list[dict], positions: list[dict], alerts: list[dict]) -> str:
    """10.2절. 우선순위 1~7 중 첫 번째 앞 절 + 고정 뒷 절(1번은 뒷 절 없음)."""
    if summary["trade_count"] == 0:
        return "점검 필요의 데이터 알림과 백테스트 구간 설정을 먼저 확인하세요."
    codes = [a["code"] for a in alerts]
    n_data = sum(1 for c in codes if c in DATA_QUALITY_CODES)
    losers_u = _top_abs([p for p in positions if p["unrealized_pnl"] < 0], "unrealized_pnl")
    losers_r = _top_abs([s for s in stocks if s["realized_pnl"] < 0], "realized_pnl")
    diff = (summary["total_return"] - summary["benchmark_return"]) * 100
    if n_data >= 1:
        head = f"수치를 해석하기 전에 점검 필요의 데이터 알림 {n_data}건을 먼저 확인하세요."
    elif summary["total_pnl"] < 0 and losers_u:
        head = f"종목별 상세에서 평가손실 상위 종목({'·'.join(_label(p) for p in losers_u)})을 먼저 확인하세요."
    elif summary["total_pnl"] < 0 and losers_r:
        head = f"종목별 상세에서 실현 손실 상위 종목({'·'.join(_label(s) for s in losers_r)})을 먼저 확인하세요."
    elif "MDD_BREACH" in codes:
        peak, trough = _mdd_span(summary)
        head = f"자산 곡선에서 고점 {peak} → 저점 {trough} 구간을 먼저 확인하세요."
    elif _disp(diff) < 0:
        head = "자산 곡선에서 KOSPI와 차이가 벌어진 구간을 먼저 확인하세요."
    else:
        head = "종목별 상세에서 손익이 특정 종목에 몰렸는지 먼저 확인하세요."
    return f"{head} {NEXT_SUFFIX}"


def build_insights(summary: dict, stocks: list[dict], closed: pd.DataFrame, alerts: list[dict],
                   positions: list[dict] | None = None, equal_weight: float | None = None,
                   equal_weight_count: int | None = None) -> tuple[list[dict], dict]:
    """strategy.md 10.1·10.2절. (insights 3개, next_action).

    positions·equal_weight·equal_weight_count는 개정 10절 문장의 재료다(키워드 인자, 기본값 있음).
    closed는 architecture.md 1.7절 시그니처 호환을 위해 남긴다(10절 문장은 쓰지 않는다).
    """
    positions = positions or []
    if equal_weight is not None and equal_weight_count is None:
        equal_weight_count = len([s for s in stocks if s.get("status") != "excluded"])
    breach = any(a["code"] == "MDD_BREACH" for a in alerts)
    sentences = [("벤치마크 비교", _benchmark_sentence(summary, equal_weight, equal_weight_count)),
                 ("손익 분해", _pnl_sentence(summary, positions)),
                 ("리스크", _risk_sentence(summary, breach))]
    insights = [{"no": f"{i:02d}", "title": t, "detail": d} for i, (t, d) in enumerate(sentences, start=1)]
    return insights, {"label": "다음 조치", "text": _next_action(summary, stocks, positions, alerts)}


# ---- 섹션 조립 --------------------------------------------------------------
def _stocks(raw: list[dict], excluded: set[str]) -> list[dict]:
    traded = [s for s in raw if s["trade_count"] > 0]
    top = max((abs(s["total_pnl"]) for s in traded), default=0)
    out = []
    for s in raw:
        status = "excluded" if s["code"] in excluded else s["status"]
        out.append({
            "code": s["code"], "name": s["name"], "status": status,
            "status_label": STATUS_LABELS[status], "trade_count": s["trade_count"],
            "buy_count": s["buy_count"], "sell_count": s["sell_count"],
            "closed_count": s["closed_count"], "win_count": s["win_count"],
            "win_rate_pct": _pct(s["win_rate"]), "realized_pnl": s["realized_pnl"],
            "realized_pnl_sign": sign_of(s["realized_pnl"]),
            "unrealized_pnl": s["unrealized_pnl"], "total_pnl": s["total_pnl"],
            "return_pct": _pct(s["ret"]), "contribution_pct": _pct(s["contribution"]),
            "sign": sign_of(s["total_pnl"]),
            "bar_pct": _r(abs(s["total_pnl"]) / top * 100, 2) if top and s["trade_count"] else 0.0,
            "trade_value": s["trade_value"], "trade_volume": s["trade_volume"],
        })
    rank = {"no_trade": 1, "excluded": 2}
    order = {s["code"]: i for i, s in enumerate(raw)}
    out.sort(key=lambda s: (rank.get(s["status"], 0),
                            (-s["total_pnl"], s["code"]) if s["status"] in ("held", "closed")
                            else (order[s["code"]], "")))
    return out


def _top_contributors(stocks: list[dict], trade_count: int) -> dict:
    """architecture.md 5.5절(개정 1.1): |total_pnl| 내림차순 상위 5(held/closed, 동률 종목코드순).
    note는 strategy.md 10.4절: 유니버스 전 종목 기준, 한 종목은 한쪽에만 들어간다."""
    traded = _top_abs([s for s in stocks if s["status"] in ("held", "closed")], "total_pnl", 5)
    items = [{"rank": i, "code": s["code"], "name": s["name"], "pnl": s["total_pnl"],
              "sign": s["sign"], "bar_pct": s["bar_pct"]} for i, s in enumerate(traded, start=1)]
    gains = [s["total_pnl"] for s in stocks if s["total_pnl"] > 0]
    losses = [s["total_pnl"] for s in stocks if s["total_pnl"] < 0]
    n, x, m, y = len(gains), sum(gains), len(losses), -sum(losses)
    z = x - y
    if trade_count == 0:
        note = "거래가 없어 손익 기여 종목이 없습니다."
    elif n and m:
        note = f"이익 {n}종목 합계 {_swon(x)}원, 손실 {m}종목 합계 {_swon(-y)}원 → 총손익 {_swon(z)}원"
    elif n:
        note = f"이익 {n}종목 합계 {_swon(x)}원, 손실 종목 없음 → 총손익 {_swon(z)}원"
    elif m:
        note = f"이익 종목 없음, 손실 {m}종목 합계 {_swon(-y)}원 → 총손익 {_swon(z)}원"
    else:
        note = "손익이 발생한 종목이 없습니다 → 총손익 0원"
    return {"items": items, "note": note}


def _allocation(positions: list[dict], cash: int, total: int, as_of: str, cash_weight_pct: float) -> dict:
    parts = [("stock", p["code"], p["name"], p["market_value"],
              STOCK_COLORS[i % len(STOCK_COLORS)]) for i, p in
             enumerate(sorted(positions, key=lambda p: (-p["market_value"], p["code"])))]
    parts.append(("cash", None, "현금", cash, CASH_COLOR))
    segments, cum, start = [], 0.0, 0.0
    for i, (kind, code, label, value, color) in enumerate(parts):
        cum += value / total * 100 if total else 0.0
        end = 100.0 if i == len(parts) - 1 else min(_r(cum, 2), 100.0)
        segments.append({"kind": kind, "code": code, "label": label, "value": int(value),
                         "weight_pct": _r(value / total * 100, 4) if total else 0.0,
                         "start_pct": start, "end_pct": end, "color": color})
        start = end
    gradient = ", ".join(f"{s['color']} {_num(s['start_pct'])}% {_num(s['end_pct'])}%" for s in segments)
    return {"as_of": as_of, "total": int(total),
            "center": {"label": "주식 비중", "value_pct": _r(100 - cash_weight_pct, 4)},
            "conic_gradient": f"conic-gradient({gradient})", "segments": segments}


def _weekly(raw: list[dict]) -> list[dict]:
    out = []
    for w in raw:
        values = [w["buy_value"], w["sell_value"], w["holdings_value"], w["cash"]]
        total = sum(values)
        heights = [_r(v / total * 100, 2) if total else 0.0 for v in values[:3]]
        heights.append(_r(100 - sum(heights), 2) if total else 0.0)
        out.append({
            "label": w["start"].strftime("%m-%d"), "start": _d(w["start"]), "end": _d(w["end"]),
            "trading_days": w["trading_days"], "buy_value": w["buy_value"],
            "sell_value": w["sell_value"], "buy_count": w["buy_count"],
            "sell_count": w["sell_count"], "holdings_value": w["holdings_value"], "cash": w["cash"],
            "segments": [{"key": k, "label": lb, "value": int(v), "height_pct": h, "color": c}
                         for (k, lb, c), v, h in zip(FLOW_SEGMENTS, values, heights)],
        })
    return out


def _target(summary: dict, capital: int, target_pct: float) -> dict:
    target = target_pct / 100
    raw = summary["total_return"] / target * 100
    progress = _r(_clip(raw, 0, 100), 2)
    realized_w = _r(_clip(summary["realized_pnl"] / (capital * target) * 100, 0, progress), 2)
    target_equity = int(math.floor(capital * (1 + target) + 0.5))
    gap = max(target_equity - summary["final_equity"], 0)
    final = summary["final_equity"]
    achieved = final >= target_equity
    # strategy.md 10.5절: 달성 여부는 정수 원으로 판정, 진척률(달성률)은 문장에 쓰지 않는다.
    cur = _spct(summary["total_return"] * 100)
    g = _upct((summary["total_return"] - target) * 100)
    if final < target_equity:
        caption = (f"목표 {_spct(target_pct)}에 {g}%p 못 미쳤습니다(현재 {cur}). "
                   f"목표 평가금액까지 {target_equity - final:,}원 부족.")
    elif final == target_equity:
        caption = f"목표 {_spct(target_pct)}를 달성했습니다(현재 {cur})."
    else:
        caption = (f"목표 {_spct(target_pct)}를 {g}%p 넘었습니다(현재 {cur}). "
                   f"목표 평가금액보다 {final - target_equity:,}원 많습니다.")
    current = _pct(summary["total_return"])
    return {
        "target_return_pct": _r(target_pct, 4), "actual_return_pct": current,
        "sign": sign_of(current),
        "current_return_pct": current, "current_return_sign": sign_of(current),
        "gap_pct": _r((summary["total_return"] - target) * 100, 4),
        "target_equity": target_equity,
        "gap_amount": int(gap), "achieved": achieved, "progress_raw_pct": _r(raw, 4),
        "progress_pct": progress,
        "bar_segments": [
            {"key": "realized", "label": "실현", "width_pct": realized_w, "color": "#1428A0"},
            {"key": "unrealized", "label": "미실현", "width_pct": _r(progress - realized_w, 2),
             "color": "#7C9BFF"}],
        "caption": caption,
    }


def _charts(summary: dict, snaps: list[dict], bench_rets: list[float], weekly: list[dict]) -> dict:
    n = len(snaps)
    eq = [0.0] + [r * 100 for r in summary["cum_returns"]]           # 시작점(d1 시가 시점) 포함
    bm = [0.0] + [r * 100 for r in bench_rets]
    y_min, y_max, labels = nice_axis(min(eq + bm), max(eq + bm))
    eq_points = polyline_points(eq, 720, 250, y_min, y_max)
    zero_y = _r(250 * y_max / (y_max - y_min), 1)
    x_labels = [{"label": w["label"], "x_pct": _r((i + 1) / n * 100, 2)}
                for w in weekly for i, s in enumerate(snaps) if _d(s["date"]) == w["start"]]
    mdd = summary["mdd"]
    span = (f"({_d(summary['mdd_peak_date']) or '시작'} → {_d(summary['mdd_trough_date'])})"
            if mdd < 0 else "")
    caption = (f"전략 {_spct(summary['total_return'] * 100)}, KOSPI buy&hold "
               f"{_spct(summary['benchmark_return'] * 100)}. 초과수익 "
               f"{_spct(summary['excess_return'] * 100)}p, 최대 낙폭 {_spct(mdd * 100)}{span}.")
    top = max((w["buy_value"] + w["sell_value"] for w in weekly), default=0)
    bars = []
    for w in weekly:
        value = w["buy_value"] + w["sell_value"]
        h = _r(value / top * 100, 2) if top else 0.0
        bars.append({"label": w["label"], "value": value, "height_pct": h, "color": _bar_color(h)})
    win = _r(summary["win_rate"] * 100, 2) if summary["win_rate"] is not None else 0.0
    return {
        "equity": {
            "viewbox": "0 0 720 250", "width": 720, "height": 250, "unit": "누적 수익률(%)",
            "y_min": y_min, "y_max": y_max, "y_labels": labels,
            "zero_line_y": zero_y, "zero_line_top_pct": _r(zero_y / 250 * 100, 2),
            "equity_points": eq_points,
            "equity_area_path": "M" + " L".join(eq_points.split(" ")) + " L720.0,250.0 L0.0,250.0 Z",
            "benchmark_points": polyline_points(bm, 720, 250, y_min, y_max),
            "x_labels": x_labels, "caption": caption,
        },
        "sparklines": {
            "viewbox": "0 0 200 44", "equity": _sparkline(eq),
            "realized_pnl": _sparkline([0.0] + [float(s["realized_pnl_cum"]) for s in snaps]),
            "holdings": _sparkline([0.0] + [float(s["position_count"]) for s in snaps]),
        },
        "win_donut": {"win_pct": win,
                      "conic_gradient": f"conic-gradient(#1428A0 0% {_num(win)}%, #E1E4EC {_num(win)}% 100%)"},
        "trade_value_bars": bars,
    }


def _disclaimers(n_days: int, rebalances: int, months: int, params: dict, n_universe: int) -> list[str]:
    return [
        f"{months}개월({n_days}거래일, 리밸런싱 {rebalances}회) 표본은 통계적 의미가 약합니다. "
        "수익률·승률·MDD는 우연의 영향이 큽니다.",
        f"파라미터 최적화를 하지 않았습니다. {params.get('lookback_days')}일·{params.get('top_n')}종목·주간은 사전에 정한 값입니다.",
        f"유니버스 {n_universe}종목은 현재 시총 상위 대형주라 생존·선택 편향이 있습니다.",
        "시가 전량 체결, 슬리피지 0, 시장충격 없음, 당일 매도 대금 즉시 재사용을 가정했습니다.",
        "배당, 세후 수익, 최소 수수료는 반영하지 않았습니다. 벤치마크에는 비용이 없습니다.",
        "시뮬레이션 결과이며 투자 권유가 아닙니다. 실거래·모의투자 주문은 이 프로젝트 범위 밖입니다.",
    ]


def build_result(cfg: dict, period: dict, bt: dict, bench: pd.DataFrame, bench_info: dict,
                 issues: list[dict], source_info: dict, generated_at: str) -> dict:
    trades, snapshots, pos_df = bt["trades"], bt["snapshots"], bt["positions"]
    if len(snapshots) == 0:
        raise ValueError("백테스트 거래일이 0일입니다.")
    capital, universe = int(cfg["capital"]), cfg["universe"]
    names = {u["code"]: u["name"] for u in universe}
    params = cfg["strategy"]["params"]
    summ = metrics.summarize(trades, snapshots, pos_df, bench, capital)
    closed = metrics.closed_trades(trades)
    snaps = snapshots.to_dict("records")
    d1, dn, n_days = snaps[0]["date"], snaps[-1]["date"], len(snaps)
    weeks_raw = metrics.weekly_flow(trades, snapshots)
    months = int(cfg["backtest"]["months"])
    info = {"trading_days": n_days, "months": months,
            "rebalances": period.get("rebalances", len(weeks_raw))}
    excluded = [i["stock"] for i in issues if i.get("excluded")]
    stocks = _stocks(metrics.per_stock(trades, pos_df, universe, capital), set(excluded))
    final_equity = summ["final_equity"]

    positions = [{
        "code": p["code"], "name": names.get(p["code"], p["code"]), "qty": int(p["qty"]),
        "avg_price": int(p["entry_price"]), "cost_basis": int(p["buy_amount"]) + int(p["buy_cost"]),
        "last_price": int(p["last_price"]), "market_value": int(p["market_value"]),
        "weight_pct": _r(p["market_value"] / final_equity * 100, 4),
        "unrealized_pnl": int(p["unrealized_pnl"]), "unrealized_pnl_pct": _pct(p["unrealized_ret"]),
        "sign": sign_of(int(p["unrealized_pnl"])), "entry_date": _d(p["entry_date"]),
        "holding_days": int(p["holding_days"]),
    } for p in pos_df.to_dict("records")]
    positions.sort(key=lambda p: (-p["market_value"], p["code"]))

    events = list(bt.get("events", []))
    if bench_info.get("base_kind") == "prev_close":
        events.append({"code": "BENCHMARK_BASE_FALLBACK", "stock": None, "date": None,
                       "value": None, "excluded": False, "side": None, "extra": {}})
    alerts = build_alerts(summ, stocks, positions, issues, events, info)
    ew = bench_info.get("equal_weight_return")
    insights, next_action = build_insights(summ, stocks, closed, alerts, positions=positions,
                                           equal_weight=ew,
                                           equal_weight_count=bench_info.get("equal_weight_count"))
    weekly = _weekly(weeks_raw)
    ew_excess = _r((summ["total_return"] - ew) * 100, 4) if ew is not None else None
    pct = {k: _pct(summ[k]) for k in ("total_return", "benchmark_return", "mdd")}
    excess_pct = _r(summ["excess_return"] * 100, 4)
    cash_weight_pct = _pct(summ["cash_weight"])

    trade_rows = []
    for t in trades.to_dict("records"):
        pnl = _opt(t["realized_pnl"])
        hold = _opt(t["holding_days"])
        trade_rows.append({
            "id": int(t["id"]), "date": _d(t["date"]), "signal_date": _d(t["signal_date"]),
            "code": t["code"], "name": names.get(t["code"], t["code"]), "side": t["side"],
            "side_label": "매수" if t["side"] == "BUY" else "매도", "qty": int(t["qty"]),
            "price": int(t["price"]), "amount": int(t["amount"]), "cost": int(t["cost"]),
            "net_cash": int(t["net_cash"]), "realized_pnl": int(pnl) if pnl is not None else None,
            "realized_pnl_pct": _pct(_opt(t["realized_ret"])),
            "sign": sign_of(int(pnl)) if pnl is not None else "zero",
            "holding_days": int(hold) if hold is not None else None, "reason": t["reason"],
        })

    return {
        "schema_version": "1.1",
        "meta": {
            "is_example": False,
            "label": "STOCK-SIM · 모의투자 백테스트",
            "title": "주식 자동매매 시뮬레이션 대시보드",
            "period": {"requested_start": _d(period["requested_start"]), "start": _d(d1),
                       "end": _d(dn), "trading_days": n_days, "months": months},
            "generated_at": generated_at,
            "env": cfg["kis"]["env"],
            "strategy": {"name": cfg["strategy"]["name"],
                         "label": STRATEGIES[cfg["strategy"]["name"]]["label"](params),
                         "params": dict(params)},
            "data_source": {
                "provider": "KIS", "env": cfg["kis"]["env"], "adjusted_price": True,
                "fetch_start": _d(period["fetch_start"]), "fetch_end": _d(period["end"]),
                "api_calls": int(source_info.get("api_calls", 0)),
                "cache_hits": int(source_info.get("cache_hits", 0)),
                "excluded": [{"code": c, "name": names.get(c, c), "reason": "조회 결과 0건"}
                             for c in excluded],
            },
            "universe": [{"code": u["code"], "name": u["name"]} for u in universe],
            "benchmark": {"code": cfg["benchmark"]["code"], "name": cfg["benchmark"]["name"],
                          "base_price": _r(bench_info["base_price"], 2),
                          "base_kind": bench_info["base_kind"]},
            "capital": capital,
            "max_positions": int(cfg["max_positions"]),
            "costs": {"buy_cost_pct": _r(cfg["costs"]["buy_fee_pct"], 4),
                      "sell_cost_pct": _r(cfg["costs"]["sell_fee_pct"] + cfg["costs"]["sell_tax_pct"], 4),
                      "slippage_pct": _r(cfg["costs"]["slippage_pct"], 4)},
            "disclaimers": _disclaimers(n_days, info["rebalances"], months, params, len(universe)),
        },
        "flags": {
            "no_trades": summ["trade_count"] == 0,
            "no_closed_trades": summ["closed_count"] == 0,
            "no_positions": len(positions) == 0,
            "only_low_sample_alert": [a["code"] for a in alerts] == ["LOW_SAMPLE"],
        },
        "summary": {
            "initial_capital": capital, "final_equity": final_equity,
            "total_pnl": summ["total_pnl"], "total_pnl_sign": sign_of(summ["total_pnl"]),
            "total_return_pct": pct["total_return"], "total_return_sign": sign_of(pct["total_return"]),
            "benchmark_return_pct": pct["benchmark_return"],
            "benchmark_return_sign": sign_of(pct["benchmark_return"]),
            "excess_return_pct": excess_pct, "excess_return_sign": sign_of(excess_pct),
            "equal_weight_return_pct": _pct(ew), "equal_weight_return_sign": sign_of(_pct(ew)),
            "excess_vs_equal_weight_pct": ew_excess,
            "excess_vs_equal_weight_sign": sign_of(ew_excess),
            "mdd_pct": pct["mdd"], "mdd_sign": sign_of(pct["mdd"]),
            "mdd_peak_date": _d(summ["mdd_peak_date"]), "mdd_trough_date": _d(summ["mdd_trough_date"]),
            "trade_count": summ["trade_count"], "buy_count": summ["buy_count"],
            "sell_count": summ["sell_count"], "closed_count": summ["closed_count"],
            "win_count": summ["win_count"], "loss_count": summ["loss_count"],
            "win_rate_pct": _pct(summ["win_rate"]), "payoff_ratio": _r(summ["payoff_ratio"], 4),
            "max_loss_streak": summ["max_loss_streak"],
            "realized_pnl": summ["realized_pnl"], "realized_pnl_sign": sign_of(summ["realized_pnl"]),
            "unrealized_pnl": summ["unrealized_pnl"],
            "unrealized_pnl_sign": sign_of(summ["unrealized_pnl"]),
            "total_cost": summ["total_cost"], "holding_count": summ["holding_count"],
            "max_positions": int(cfg["max_positions"]), "cash": summ["cash"],
            "cash_weight_pct": cash_weight_pct, "total_trade_value": summ["total_trade_value"],
            "buy_value": summ["buy_value"], "sell_value": summ["sell_value"],
            "total_trade_volume": summ["total_trade_volume"], "turnover_pct": _pct(summ["turnover"]),
        },
        "equity_curve": [{
            "date": _d(s["date"]), "equity": int(s["equity"]), "cash": int(s["cash"]),
            "holdings_value": int(s["holdings_value"]), "return_pct": _pct(r),
            "drawdown_pct": _pct(dd), "position_count": int(s["position_count"]),
            "realized_pnl_cum": int(s["realized_pnl_cum"]),
        } for s, r, dd in zip(snaps, summ["cum_returns"], summ["drawdowns"])],
        "benchmark": [{"date": _d(b["date"]), "close": _r(b["close"], 2), "value": int(b["value"]),
                       "return_pct": _pct(b["ret"])} for b in bench.to_dict("records")],
        "charts": _charts(summ, snaps, [float(x) for x in bench["ret"]], weekly),
        "positions": positions,
        "allocation": _allocation(positions, summ["cash"], final_equity, _d(dn), cash_weight_pct),
        "trades": trade_rows,
        "per_stock": stocks,
        "top_contributors": _top_contributors(stocks, summ["trade_count"]),
        "weekly_flow": weekly,
        "alerts": alerts,
        "insights": insights,
        "next_action": next_action,
        "target": _target(summ, capital, float(cfg["target_return"])),
    }


def write_result(result: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, allow_nan=False)
        fh.write("\n")
    return path
