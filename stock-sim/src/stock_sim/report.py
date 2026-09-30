"""result.json(schema 2.0) 조립과 저장 (architecture.md 5절, strategy.md 9·11절).

build_result는 순수 함수다. % 변환·자리수 맞춤·좌표·문장은 이 모듈에서만 만든다.
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

SCHEMA_VERSION = "2.0"
BLUE, RED, AMBER = "#1428A0", "#B0472F", "#C98A2E"
SHARE_COLORS = ["#1428A0", "#4B5CC0", "#7C9BFF", "#909BD6", "#C2C8E8"]
EMPTY_DONUT = "conic-gradient(#DCE0E9 0% 100%)"
AXIS_STEPS = [0.5, 1, 2, 5, 10, 20, 50]
TABLE_LIMIT = 20
STATUS_LABELS = {"traded": "거래", "no_trade": "거래 없음", "excluded": "제외(데이터 없음)"}
REASON_LABELS = {"ENTRY_BREAKOUT": "돌파 매수", "EXIT_BREAKDOWN": "하락 이탈 매도",
                 "EXIT_EOD": "마감 청산"}
BLOCK_LABELS = [("halt", "매매 중단"), ("max_entries", "횟수 상한"), ("cooldown", "쿨다운"),
                ("cutoff", "시간"), ("range", "변동폭"), ("volume", "거래량"), ("vwap", "VWAP")]
WARN_ORDER = ["MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM", "COST_DRAG", "NO_TRADES",
              "DATA_MISSING", "DAY_SKIPPED", "BAR_MISSING", "EOD_FALLBACK", "PRICE_ANOMALY",
              "PRICE_LIMIT_FILL", "UNTRADABLE_SKIP", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT"]
INFO_ORDER = ["DAILY_LOSS_HALT", "QTY_ZERO_SKIP", "BENCHMARK_BASE_FALLBACK",
              "OVERNIGHT_GAP_NOTE", "LOW_SAMPLE"]
BASELINE_INFO = {"OVERNIGHT_GAP_NOTE", "LOW_SAMPLE"}
RED_CODES = {"MDD_BREACH", "LOSS_STREAK", "UNDERPERFORM"}
DATA_QUALITY_CODES = ("DATA_MISSING", "BAR_MISSING", "DAY_SKIPPED", "EOD_FALLBACK",
                      "PRICE_ANOMALY", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT")
MDD_LIMIT, STREAK_LIMIT, UNDERPERFORM_LIMIT = -0.05, 3, -0.02


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
    if isinstance(d, pd.Timestamp):
        d = d.date()
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


def _disp(v: float) -> float:
    """소수 2자리 표시값(11.0절 4번: 비율 문장의 분기는 표시값으로 판정). -0.0은 0.0."""
    d = float(f"{v:.2f}")
    return 0.0 if d == 0 else d


def _upct(v: float) -> str:
    """부호 없는 절댓값 2자리('{x}%p'의 x)."""
    return f"{abs(_disp(v)):.2f}"


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


def _label(item: dict) -> str:
    """종목명, 없으면 종목코드(11.0절 6번)."""
    return item.get("name") or item["code"]


def _mdd_span(summary: dict) -> tuple[str, str]:
    """(고점일, 저점일). 고점이 E0이면 '초기 자본'(11.1절 ③)."""
    return _d(summary["mdd_peak_date"]) or "초기 자본", _d(summary["mdd_trough_date"]) or ""


def _top_abs(items: list[dict], key: str, k: int = 2) -> list[dict]:
    """절댓값 내림차순, 동률은 종목코드 오름차순."""
    return sorted(items, key=lambda x: (-abs(x[key]), x["code"]))[:k]


def _is_first_of_week(days: list[date]) -> list[bool]:
    out, seen = [], set()
    for d in days:
        wk = d.isocalendar()[:2]
        out.append(wk not in seen)
        seen.add(wk)
    return out


# ---- 알림·인사이트 (strategy.md 11절) ----------------------------------------------
def build_alerts(summary: dict, stocks: list[dict], issues: list[dict], events: list[dict],
                 period: dict, params: dict) -> list[dict]:
    """strategy.md 11.3절. 날짜는 한 알림에서 한 곳(date 또는 문장)에만 쓴다."""
    names = {s["code"]: _label(s) for s in stocks}
    raw: list[tuple[str, str, str, str | None, str]] = []   # (code, title, detail, date, stock)

    def nm(code: str) -> str:
        if code.startswith("IDX"):
            return "KOSPI 지수"
        return names.get(code, code)

    def plain(code: str) -> str:
        return code[3:] if code.startswith("IDX") else code

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
    cost, capital = summary["total_cost"], summary["initial_capital"]
    if cost * 100 >= capital:
        raw.append(("COST_DRAG", f"총 비용 {cost:,}원, 초기 자본의 {cost / capital * 100:.2f}%",
                    f"체결 {summary['trade_count']}건 · 비용 전 손익 {_swon(summary['gross_pnl'])}원",
                    None, ""))
    if summary["trade_count"] == 0:
        raw.append(("NO_TRADES", "백테스트 기간에 거래가 없습니다.", "", None, ""))
    seen_once: set[tuple[str, str]] = set()
    bar_missing: dict[str, list[int]] = {}
    for ev in list(issues) + list(events):
        code, stock, day = ev["code"], ev.get("stock") or "", _d(ev.get("date"))
        if code in ("DATA_MISSING", "NON_INTEGER_PRICE", "TRUNCATION_SUSPECT"):
            if (code, stock) in seen_once:
                continue
            seen_once.add((code, stock))
        if code == "DATA_MISSING":
            raw.append((code, f"{nm(stock)} 데이터 없음: 유니버스에서 제외", stock, None, stock))
        elif code == "DAY_SKIPPED":
            raw.append((code, f"{nm(stock)} 분봉 부족으로 매매하지 않음",
                        f"{stock} · 유효 5분봉 {int(ev['value'])}개", day, stock))
        elif code == "BAR_MISSING":
            bar_missing.setdefault(stock, []).append(int(ev["value"]))
        elif code == "EOD_FALLBACK":
            raw.append((code, f"{nm(stock)} 마감 청산을 대체 가격으로 처리",
                        f"{stock} · 체결가 {int(ev['value']):,}원", day, stock))
        elif code == "PRICE_ANOMALY":
            t = (ev.get("extra") or {}).get("time", "")
            raw.append((code, f"{nm(stock)} 5분 등락 {_spct(ev['value'] * 100)}: 데이터 확인 필요",
                        f"{stock} · {t} 봉", day, stock))
        elif code == "PRICE_LIMIT_FILL":
            raw.append((code, f"{nm(stock)} 하한가 부근 매도 체결: 실제로는 체결되지 않을 수 있음",
                        f"{stock} · 체결가 {int(ev['value']):,}원", day, stock))
        elif code == "UNTRADABLE_SKIP":
            raw.append((code, f"{nm(stock)} 매수 불가로 건너뜀", f"{stock} · 가격제한폭 시가", day, stock))
        elif code == "NON_INTEGER_PRICE":
            raw.append((code, f"{nm(stock)} 가격에 정수가 아닌 값: 원 단위로 반올림", plain(stock), None, stock))
        elif code == "TRUNCATION_SUSPECT":
            raw.append((code, f"{nm(stock)} 응답 건수가 상한에 닿음: 데이터 잘림 확인 필요",
                        plain(stock), None, stock))
        elif code == "QTY_ZERO_SKIP":
            alloc = (ev.get("extra") or {}).get("alloc")
            detail = f"{stock} · 체결가 {int(ev['value']):,}원"
            detail += f" · 배분금액 {int(alloc):,}원" if alloc is not None else ""
            raw.append((code, f"{nm(stock)} 1주 가격이 배분금액을 넘어 매수하지 못했습니다.", detail, day, stock))
        elif code == "BENCHMARK_BASE_FALLBACK":
            raw.append((code, "벤치마크 기준가를 직전 종가로 대체했습니다.", "", None, ""))
    for stock, counts in bar_missing.items():
        raw.append(("BAR_MISSING", f"{nm(stock)} 5분봉 {sum(counts)}개 결측",
                    f"{stock} · {len(counts)}거래일에 걸침", None, stock))
    if summary["halt_days"] >= 1:
        limit = float(params.get("daily_loss_limit_pct", 0.01))
        raw.append(("DAILY_LOSS_HALT", f"일일 손실 한도로 신규 매수를 중단한 날 {summary['halt_days']}일",
                    f"한도 {_spct(-limit * 100)}", None, ""))
    raw.append(("OVERNIGHT_GAP_NOTE", "전략은 매일 장 마감 전에 현금화해 밤사이 가격 변동을 받지 않습니다.",
                "벤치마크는 밤사이 변동을 포함", None, ""))
    raw.append(("LOW_SAMPLE", f"{period.get('days', 30)}일({period.get('trading_days', 0)}거래일) "
                "표본은 통계적 의미가 약합니다.", f"청산 거래 {summary['closed_count']}건", None, ""))
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
    """11.1절 ①. 차이는 반올림 전 원값끼리 뺀다(11.0절 3번)."""
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


def _pnl_sentence(summary: dict, stocks: list[dict]) -> str:
    """11.1절 ② 손익 분해."""
    if summary["trade_count"] == 0:
        return "백테스트 기간에 체결된 거래가 없어 전 기간 현금을 보유했습니다."
    body = (f"비용 전 손익 {_swon(summary['gross_pnl'])}원에서 비용 {summary['total_cost']:,}원을 빼 "
            f"총손익 {_swon(summary['total_pnl'])}원입니다(청산 {summary['closed_count']}건).")
    bought = sorted((s for s in stocks if s["buy_count"] > 0), key=lambda s: s["code"])
    if not bought:
        return body
    clause = ", ".join(f"{_label(s)} {_swon(s['realized_pnl'])}원" for s in bought)
    return f"{body} 종목별: {clause}."


def _risk_sentence(summary: dict, breach: bool) -> str:
    """11.1절 ③."""
    if summary["trade_count"] == 0:
        return "거래가 없어 최대 낙폭(MDD)은 0.00%입니다."
    mdd = summary["mdd"] * 100
    if _disp(mdd) == 0:
        return "최대 낙폭(MDD) 0.00%, 평가액이 직전 고점 아래로 내려간 날이 없습니다."
    peak, trough = _mdd_span(summary)
    tail = "임계 -5.00%를 넘었습니다." if breach else "임계 -5.00% 이내입니다."
    return f"최대 낙폭(MDD) {_spct(mdd)}, 고점 {peak} → 저점 {trough}. {tail}"


def _next_action(summary: dict, stocks: list[dict], alerts: list[dict], days_label: int) -> str:
    """11.2절. 우선순위 1~7 중 첫 번째 앞 절 + 고정 뒷 절(1번은 뒷 절 없음)."""
    if summary["trade_count"] == 0:
        return "점검 필요의 데이터 알림과 진입 조건별 차단 횟수를 먼저 확인하세요."
    codes = [a["code"] for a in alerts]
    n_data = sum(1 for c in codes if c in DATA_QUALITY_CODES)
    p, g = summary["total_pnl"], summary["gross_pnl"]
    diff = (summary["total_return"] - summary["benchmark_return"]) * 100
    if n_data >= 1:
        head = f"수치를 해석하기 전에 점검 필요의 데이터 알림 {n_data}건을 먼저 확인하세요."
    elif p < 0 and g >= 0:
        head = ("비용 전 손익은 손실이 아니지만 비용이 더 컸습니다. "
                "매매 내역에서 거래 횟수와 비용을 먼저 확인하세요.")
    elif p < 0:
        losers = _top_abs([s for s in stocks if s["realized_pnl"] < 0], "realized_pnl")
        head = f"종목별 상세에서 실현 손실 상위 종목({'·'.join(_label(s) for s in losers)})을 먼저 확인하세요."
    elif "MDD_BREACH" in codes:
        peak, trough = _mdd_span(summary)
        head = f"자산 곡선에서 고점 {peak} → 저점 {trough} 구간을 먼저 확인하세요."
    elif _disp(diff) < 0:
        head = "자산 곡선에서 KOSPI와 차이가 벌어진 구간을 먼저 확인하세요."
    else:
        head = "종목별 상세에서 손익이 특정 종목에 몰렸는지 먼저 확인하세요."
    return f"{head} {days_label}일 표본이므로 전략 변경은 구간을 늘려 본 뒤 판단하세요."


def build_insights(summary: dict, stocks: list[dict], alerts: list[dict],
                   equal_weight: float | None = None, equal_weight_count: int | None = None,
                   days_label: int = 30) -> tuple[list[dict], dict]:
    """strategy.md 11.1·11.2절. (insights 3개, next_action)."""
    if equal_weight is not None and equal_weight_count is None:
        equal_weight_count = len([s for s in stocks if s.get("status") != "excluded"])
    breach = any(a["code"] == "MDD_BREACH" for a in alerts)
    sentences = [("벤치마크 비교", _benchmark_sentence(summary, equal_weight, equal_weight_count)),
                 ("손익 분해", _pnl_sentence(summary, stocks)),
                 ("리스크", _risk_sentence(summary, breach))]
    insights = [{"no": f"{i:02d}", "title": t, "detail": d} for i, (t, d) in enumerate(sentences, start=1)]
    return insights, {"label": "다음 조치", "text": _next_action(summary, stocks, alerts, days_label)}


# ---- 섹션 조립 --------------------------------------------------------------
def _share(stocks_raw: list[dict], trade_count: int) -> dict:
    """종목별 거래대금 비중 도넛(5.5절)."""
    parts = sorted((s for s in stocks_raw if s["trade_value"] > 0),
                   key=lambda s: (-s["trade_value"], s["code"]))
    total = sum(s["trade_value"] for s in parts)
    center = {"label": "체결 건수", "value": int(trade_count), "unit": "건"}
    if not parts:
        return {"total": 0, "center": center, "conic_gradient": EMPTY_DONUT, "segments": []}
    segments, cum, start = [], 0.0, 0.0
    for i, s in enumerate(parts):
        cum += s["trade_value"] / total * 100
        end = 100.0 if i == len(parts) - 1 else min(_r(cum, 2), 100.0)
        segments.append({"code": s["code"], "label": _label(s), "value": int(s["trade_value"]),
                         "share_pct": _r(s["trade_value"] / total * 100, 4), "start_pct": start,
                         "end_pct": end, "color": SHARE_COLORS[i % len(SHARE_COLORS)]})
        start = end
    grad = ", ".join(f"{s['color']} {_num(s['start_pct'])}% {_num(s['end_pct'])}%" for s in segments)
    return {"total": int(total), "center": center, "conic_gradient": f"conic-gradient({grad})",
            "segments": segments}


def _stocks(raw: list[dict], excluded: set[str], share: dict) -> list[dict]:
    shares = {s["code"]: s["share_pct"] for s in share["segments"]}
    traded = [s for s in raw if s["trade_count"] > 0 and s["code"] not in excluded]
    top = max((abs(s["realized_pnl"]) for s in traded), default=0)
    out = []
    for s in raw:
        status = "excluded" if s["code"] in excluded else s["status"]
        out.append({
            "code": s["code"], "name": s["name"], "status": status,
            "status_label": STATUS_LABELS[status], "trade_count": s["trade_count"],
            "buy_count": s["buy_count"], "sell_count": s["sell_count"],
            "closed_count": s["closed_count"], "win_count": s["win_count"],
            "loss_count": s["loss_count"], "win_rate_pct": _pct(s["win_rate"]),
            "gross_pnl": s["gross_pnl"], "cost": s["cost"], "realized_pnl": s["realized_pnl"],
            "sign": sign_of(s["realized_pnl"]), "return_pct": _pct(s["ret"]),
            "contribution_pct": _pct(s["contribution"]),
            "bar_pct": (_r(abs(s["realized_pnl"]) / top * 100, 2)
                        if top and status == "traded" else 0.0),
            "trade_value": s["trade_value"], "trade_value_share_pct": shares.get(s["code"], 0.0),
            "trade_volume": s["trade_volume"], "avg_hold_minutes": _r(s["avg_hold_minutes"], 1),
        })
    rank = {"traded": 0, "no_trade": 1, "excluded": 2}
    order = {s["code"]: i for i, s in enumerate(raw)}
    out.sort(key=lambda s: (rank[s["status"]],
                            (-s["realized_pnl"], s["code"]) if s["status"] == "traded"
                            else (order[s["code"]], "")))
    return out


def _top_contributors(stocks: list[dict], trade_count: int) -> dict:
    """5.5절: traded 종목 |realized_pnl| 내림차순 상위 5. note는 strategy.md 11.4절."""
    traded = _top_abs([s for s in stocks if s["status"] == "traded"], "realized_pnl", 5)
    items = [{"rank": i, "code": s["code"], "name": s["name"], "pnl": s["realized_pnl"],
              "sign": s["sign"], "bar_pct": s["bar_pct"]} for i, s in enumerate(traded, start=1)]
    gains = [s["realized_pnl"] for s in stocks if s["realized_pnl"] > 0]
    losses = [s["realized_pnl"] for s in stocks if s["realized_pnl"] < 0]
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


def _blocks(raw: dict) -> dict:
    counts = {k: int(raw.get(k, 0)) for k, _ in BLOCK_LABELS}
    blocked = sum(counts.values())
    breakout = int(raw.get("breakout", 0))
    entries = breakout - blocked
    top = max(counts.values(), default=0)
    items = [{"key": k, "label": lb, "count": counts[k],
              "bar_pct": _r(counts[k] / top * 100, 2) if top else 0.0} for k, lb in BLOCK_LABELS]
    ranked = sorted(items, key=lambda it: -it["count"])            # 동률은 4.2절 순서(안정 정렬)
    inner = " · ".join(f"{it['label']} {it['count']}" for it in ranked)
    caption = f"돌파 {breakout}회 중 {entries}회 매수 신호, {blocked}회 차단({inner})"
    return {"breakout": breakout, "entries": entries, "blocked": blocked, "items": items,
            "caption": caption}


def _target(summary: dict, capital: int, target: float) -> dict:
    raw = summary["total_return"] / target * 100
    progress = _r(_clip(raw, 0, 100), 2)
    target_equity = int(math.floor(capital * (1 + target) + 0.5))
    final = summary["final_equity"]
    cur = _spct(summary["total_return"] * 100)
    tgt = _spct(target * 100)
    g = _upct((summary["total_return"] - target) * 100)
    if final < target_equity:
        caption = (f"목표 {tgt}에 {g}%p 못 미쳤습니다(현재 {cur}). "
                   f"목표 평가금액까지 {target_equity - final:,}원 부족.")
    elif final == target_equity:
        caption = f"목표 {tgt}를 달성했습니다(현재 {cur})."
    else:
        caption = (f"목표 {tgt}를 {g}%p 넘었습니다(현재 {cur}). "
                   f"목표 평가금액보다 {final - target_equity:,}원 많습니다.")
    current = _pct(summary["total_return"])
    return {
        "target_return_pct": _r(target * 100, 4), "current_return_pct": current,
        "current_return_sign": sign_of(current),
        "gap_pct": _r((summary["total_return"] - target) * 100, 4),
        "target_equity": target_equity, "gap_amount": int(max(target_equity - final, 0)),
        "achieved": final >= target_equity, "progress_raw_pct": _r(raw, 4),
        "progress_pct": progress,
        "bar_segments": [{"key": "realized", "label": "실현", "width_pct": progress, "color": BLUE}],
        "caption": caption,
    }


def _daily_rows(daily: pd.DataFrame) -> tuple[list[dict], dict]:
    recs = daily.to_dict("records")
    days = [r["date"] for r in recs]
    firsts = _is_first_of_week(days)
    max_abs = max((abs(int(r["pnl"])) for r in recs), default=0)
    rows = []
    for r, first in zip(recs, firsts):
        pnl = int(r["pnl"])
        gain, loss = max(pnl, 0), max(-pnl, 0)
        rows.append({
            "date": _d(r["date"]), "label": r["date"].strftime("%m-%d"), "show_label": first,
            "e_start": int(r["e_start"]), "e_end": int(r["e_end"]), "pnl": pnl, "sign": sign_of(pnl),
            "return_pct": _pct(r["ret"]), "buy_count": int(r["buy_count"]),
            "sell_count": int(r["sell_count"]), "closed_count": int(r["closed_count"]),
            "trade_value": int(r["trade_value"]), "cost": int(r["cost"]), "halted": bool(r["halted"]),
            "segments": [
                {"key": "gain", "label": "수익", "value": gain,
                 "height_pct": _r(gain / max_abs * 100, 2) if max_abs else 0.0, "color": BLUE},
                {"key": "loss", "label": "손실", "value": loss,
                 "height_pct": _r(loss / max_abs * 100, 2) if max_abs else 0.0, "color": RED}],
        })
    return rows, {"max_abs": max_abs}


def _daily_pnl_chart(rows: list[dict], max_abs: int, trade_count: int) -> dict:
    win = [r for r in rows if r["pnl"] > 0]
    loss = [r for r in rows if r["pnl"] < 0]
    flat = len(rows) - len(win) - len(loss)
    best = worst = None                     # 같은 값이면 이른 날
    for r in win:
        if best is None or r["pnl"] > best["pnl"]:
            best = r
    for r in loss:
        if worst is None or r["pnl"] < worst["pnl"]:
            worst = r
    if trade_count == 0:
        caption = "거래가 없어 일별 손익이 없습니다."
        best = worst = None
    else:
        parts = []
        if best:
            parts.append(f"최대 수익 {_swon(best['pnl'])}원({best['date']})")
        if worst:
            parts.append(f"최대 손실 {_swon(worst['pnl'])}원({worst['date']})")
        caption = f"수익 {len(win)}일, 손실 {len(loss)}일, 손익 없음 {flat}일."
        if parts:
            caption += " " + ", ".join(parts) + "."
    return {"max_abs": int(max_abs), "win_days": len(win), "loss_days": len(loss), "flat_days": flat,
            "best": {"date": best["date"], "pnl": best["pnl"]} if best else None,
            "worst": {"date": worst["date"], "pnl": worst["pnl"]} if worst else None,
            "caption": caption}


def _charts(summary: dict, daily_rows: list[dict], bench_rets: list[float], weekly: list[dict],
            chart_daily: dict) -> dict:
    days = [date.fromisoformat(r["date"]) for r in daily_rows]
    n = len(days)
    eq = [0.0] + [r * 100 for r in summary["cum_returns"]]           # 시작점 포함(n + 1점)
    bm = [0.0] + [r * 100 for r in bench_rets]
    y_min, y_max, labels = nice_axis(min(eq + bm), max(eq + bm))
    eq_points = polyline_points(eq, 720, 250, y_min, y_max)
    zero_y = _r(250 * y_max / (y_max - y_min), 1)
    x_labels = [{"label": d.strftime("%m-%d"), "x_pct": _r((i + 1) / n * 100, 2)}
                for i, (d, first) in enumerate(zip(days, _is_first_of_week(days))) if first]
    mdd = summary["mdd"]
    span = (f"({_d(summary['mdd_peak_date']) or '시작'} → {_d(summary['mdd_trough_date'])})"
            if mdd < 0 else "")
    caption = (f"전략 {_spct(summary['total_return'] * 100)}, KOSPI buy&hold "
               f"{_spct(summary['benchmark_return'] * 100)}. 초과수익 "
               f"{_spct(summary['excess_return'] * 100)}p, 최대 낙폭 {_spct(mdd * 100)}{span}.")
    top = max((w["value"] for w in weekly), default=0)
    bars = []
    for w in weekly:
        h = _r(w["value"] / top * 100, 2) if top else 0.0
        bars.append({"label": w["start"].strftime("%m-%d"), "value": int(w["value"]),
                     "height_pct": h, "color": _bar_color(h)})
    win = _r(summary["win_rate"] * 100, 2) if summary["win_rate"] is not None else 0.0
    realized_cum, acc = [0.0], 0
    for r in daily_rows:
        acc += r["pnl"]
        realized_cum.append(float(acc))
    fills_per_day = [0.0] + [float(r["buy_count"] + r["sell_count"]) for r in daily_rows]
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
        "sparklines": {"viewbox": "0 0 200 44", "equity": _sparkline(eq),
                       "realized_pnl": _sparkline(realized_cum), "daily_fills": _sparkline(fills_per_day)},
        "win_donut": {"win_pct": win,
                      "conic_gradient": f"conic-gradient(#1428A0 0% {_num(win)}%, #E1E4EC {_num(win)}% 100%)"},
        "trade_value_bars": bars,
        "daily_pnl": chart_daily,
    }


def _disclaimers(cal_days: int, n_days: int, slippage: float, n_universe: int) -> list[str]:
    slip = ("슬리피지 0" if slippage == 0 else f"슬리피지 {_num(slippage * 100)}%")
    return [
        "왕복 비용이 약 0.23%라 매수가보다 0.2305% 넘게 올라야 본전입니다. "
        "빈번한 단타는 비용 때문에 손실로 끝날 가능성이 높습니다.",
        f"{cal_days}일({n_days}거래일) 표본은 통계적 의미가 약합니다. 결과는 우연의 영향이 큽니다.",
        "파라미터는 사전에 정한 고정값이며 최적화하지 않았습니다.",
        f"다음 봉 시가 전량 체결, {slip}, 시장충격 없음을 가정했습니다. 단타에서는 낙관적인 가정입니다.",
        "MDD는 일별 장 마감 평가액 기준이라 장중 낙폭은 잡히지 않습니다.",
        "전략은 밤사이 가격 변동을 받지 않고 비용을 내며, 벤치마크는 밤사이 변동을 받고 비용이 없습니다.",
        "당일 매도 대금 즉시 재사용, 최소 수수료 없음, 하한가에서도 매도 체결을 가정했습니다.",
        f"같은 업종 {n_universe}종목만 거래해 분산 효과가 거의 없습니다.",
        "시뮬레이션 결과이며 투자 권유가 아닙니다. 실거래·모의투자 주문은 이 프로젝트 범위 밖입니다.",
    ]


def _slippage_note(slippage: float) -> str:
    if slippage == 0:
        return ("슬리피지 0 가정: 실제 시장가 주문은 호가 차이(보통 1틱, 주가의 0.07~0.17%)만큼 불리하게 "
                "체결됩니다. 단타에서는 이 차이가 왕복 비용(0.23%)만큼 커서 실제 성과는 더 나쁠 수 있습니다.")
    return f"슬리피지 {_num(slippage * 100)}%를 매수·매도 체결가에 반영했습니다."


def _trade_rows(fills: pd.DataFrame, names: dict[str, str]) -> list[dict]:
    recs = fills.to_dict("records") if len(fills) else []
    first_shown = max(len(recs) - TABLE_LIMIT, 0)
    rows = []
    for i, t in enumerate(recs):
        pnl = _opt(t["realized_pnl"])
        hold = _opt(t["hold_minutes"])
        closed_id = _opt(t["closed_id"])
        rows.append({
            "id": int(t["id"]), "date": _d(t["date"]), "time": t["time"],
            "signal_time": _opt(t["signal_time"]), "code": t["code"],
            "name": names.get(t["code"], t["code"]), "side": t["side"],
            "side_label": "매수" if t["side"] == "BUY" else "매도", "qty": int(t["qty"]),
            "price": int(t["price"]), "amount": int(t["amount"]), "cost": int(t["cost"]),
            "net_cash": int(t["net_cash"]), "realized_pnl": int(pnl) if pnl is not None else None,
            "realized_pnl_pct": _pct(_opt(t["realized_ret"])),
            "sign": sign_of(int(pnl)) if pnl is not None else "zero",
            "hold_minutes": int(hold) if hold is not None else None, "reason": t["reason"],
            "reason_label": REASON_LABELS[t["reason"]],
            "closed_id": int(closed_id) if closed_id is not None else None,
            "in_table": i >= first_shown,
        })
    return rows


def _closed_rows(closed: pd.DataFrame, names: dict[str, str]) -> list[dict]:
    out = []
    for c in (closed.to_dict("records") if len(closed) else []):
        out.append({
            "id": int(c["id"]), "code": c["code"], "name": names.get(c["code"], c["code"]),
            "date": _d(c["date"]), "entry_time": c["entry_time"], "exit_time": c["exit_time"],
            "hold_minutes": int(c["hold_minutes"]), "qty": int(c["qty"]),
            "entry_price": int(c["entry_price"]), "exit_price": int(c["exit_price"]),
            "gross_pnl": int(c["gross_pnl"]), "cost": int(c["cost"]), "pnl": int(c["pnl"]),
            "return_pct": _pct(c["ret"]), "sign": sign_of(int(c["pnl"])),
            "exit_reason": c["exit_reason"], "exit_reason_label": REASON_LABELS[c["exit_reason"]],
            "buy_fill_id": int(c["buy_fill_id"]), "sell_fill_id": int(c["sell_fill_id"]),
        })
    return out


def build_result(cfg: dict, period: dict, bt: dict, daily: pd.DataFrame, bench: pd.DataFrame,
                 bench_info: dict, issues: list[dict], source_info: dict, generated_at: str) -> dict:
    """result.json(dict). 순수 함수. daily = metrics.daily_table 결과."""
    fills, closed = bt["fills"], bt["closed"]
    if len(daily) == 0:
        raise ValueError("백테스트 거래일이 0일입니다.")
    capital = int(cfg["backtest"]["initial_cash"])
    universe = cfg["universe"]
    names = {u["code"]: u["name"] for u in universe}
    st_cfg = cfg["strategy"]
    params = {k: v for k, v in st_cfg.items() if k != "name"}
    cal_days = int(cfg["backtest"]["days"])
    target = float(cfg["target"]["monthly_return"])
    costs = cfg["costs"]
    summ = metrics.summarize(fills, closed, daily, bench, capital)
    n_days = summ["trading_days"]
    days = list(daily["date"])
    excluded = [i["stock"] for i in issues if i.get("excluded")]
    stocks_raw = metrics.per_stock(fills, closed, universe, capital)
    share = _share([s for s in stocks_raw if s["code"] not in excluded], summ["trade_count"])
    stocks = _stocks(stocks_raw, set(excluded), share)
    info = {"trading_days": n_days, "days": cal_days}
    events = list(bt.get("events", []))
    if bench_info.get("base_kind") == "prev_close":
        events.append({"code": "BENCHMARK_BASE_FALLBACK", "stock": None, "date": None,
                       "value": None, "excluded": False, "side": None, "extra": {}})
    alerts = build_alerts(summ, stocks, issues, events, info, st_cfg)
    ew = bench_info.get("equal_weight_return")
    insights, next_action = build_insights(summ, stocks, alerts, equal_weight=ew,
                                           equal_weight_count=bench_info.get("equal_weight_count"),
                                           days_label=cal_days)
    daily_rows, dinfo = _daily_rows(daily)
    chart_daily = _daily_pnl_chart(daily_rows, dinfo["max_abs"], summ["trade_count"])
    weekly = metrics.weekly_trade_value(fills, days)
    trades = _trade_rows(fills, names)
    total = len(trades)
    shown = min(total, TABLE_LIMIT)
    truncated = total > TABLE_LIMIT
    if total == 0:
        tcap = ""
    elif truncated:
        tcap = f"최근 {shown}건 표시 · 전체 {total}건은 result.json의 trades[]에 있습니다."
    else:
        tcap = f"전체 {total}건"
    ew_excess = _r((summ["total_return"] - ew) * 100, 4) if ew is not None else None
    pct = {k: _pct(summ[k]) for k in ("total_return", "benchmark_return", "mdd")}
    excess_pct = _r(summ["excess_return"] * 100, 4)
    warn = [a for a in alerts if a["level"] == "warn"]
    info_codes = {a["code"] for a in alerts if a["level"] == "info"}
    buy_rate, sell_rate, slip = float(costs["buy_rate"]), float(costs["sell_rate"]), float(costs["slippage_rate"])
    empty_days = [{"code": e["code"], "date": _d(e["date"])} for e in source_info.get("empty_days", [])]
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "is_example": False,
            "label": "STOCK-SIM · 모의투자 백테스트",
            "title": "주식 자동매매 시뮬레이션 대시보드",
            "period": {"start": _d(days[0]), "end": _d(days[-1]), "days": cal_days,
                       "trading_days": n_days},
            "generated_at": generated_at,
            "env": cfg["kis"]["env"],
            "strategy": {"name": st_cfg["name"], "label": STRATEGIES[st_cfg["name"]]["label"](st_cfg),
                         "params": params},
            "session": {"open": cfg["session"]["open"],
                        "continuous_end": cfg["session"]["continuous_end"]},
            "data_source": {
                "provider": "KIS", "env": cfg["kis"]["env"], "minute_tr_id": "FHKST03010230",
                "minute_time_label": cfg.get("data", {}).get("minute_time_label", "start"),
                "daily_adjusted": True, "minute_adjusted": False,
                "daily_fetch_start": _d(period["daily_fetch_start"]), "fetch_end": _d(period["end"]),
                "minute_files": int(source_info.get("minute_files", 0)),
                "minute_rows": int(source_info.get("minute_rows", 0)),
                "api_calls": int(source_info.get("api_calls", 0)),
                "cache_hits": int(source_info.get("cache_hits", 0)),
                "excluded": [{"code": c, "name": names.get(c, c), "reason": "분봉 데이터 없음"}
                             for c in excluded],
                "empty_days": empty_days,
            },
            "universe": [{"code": u["code"], "name": u["name"]} for u in universe],
            "benchmark": {"code": cfg["benchmark"]["code"], "name": cfg["benchmark"]["name"],
                          "base_price": _r(bench_info["base_price"], 2),
                          "base_kind": bench_info["base_kind"]},
            "capital": capital,
            "costs": {"buy_cost_pct": _r(buy_rate * 100, 4), "sell_cost_pct": _r(sell_rate * 100, 4),
                      "slippage_pct": _r(slip * 100, 4),
                      "round_trip_pct": _r(((1 + buy_rate) / (1 - sell_rate) - 1) * 100, 4)},
            "slippage_note": _slippage_note(slip),
            "disclaimers": _disclaimers(cal_days, n_days, slip, len(universe)),
        },
        "flags": {
            "no_trades": summ["trade_count"] == 0,
            "only_baseline_alerts": not warn and info_codes <= BASELINE_INFO,
            "trades_truncated": truncated,
        },
        "summary": {
            "initial_capital": capital, "final_equity": summ["final_equity"],
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
            "even_count": summ["even_count"],
            "win_rate_pct": _pct(summ["win_rate"]), "payoff_ratio": _r(summ["payoff_ratio"], 4),
            "max_loss_streak": summ["max_loss_streak"],
            "realized_pnl": summ["realized_pnl"], "realized_pnl_sign": sign_of(summ["realized_pnl"]),
            "gross_pnl": summ["gross_pnl"], "gross_pnl_sign": sign_of(summ["gross_pnl"]),
            "total_cost": summ["total_cost"], "buy_cost": summ["buy_cost"],
            "sell_cost": summ["sell_cost"], "cost_to_capital_pct": _pct(summ["cost_to_capital"]),
            "avg_hold_minutes": _r(summ["avg_hold_minutes"], 1),
            "avg_closed_per_day": _r(summ["avg_closed_per_day"], 2),
            "avg_fills_per_day": _r(summ["avg_fills_per_day"], 2),
            "halt_days": summ["halt_days"], "exit_reasons": dict(summ["exit_reasons"]),
            "total_trade_value": summ["total_trade_value"], "buy_value": summ["buy_value"],
            "sell_value": summ["sell_value"], "total_trade_volume": summ["total_trade_volume"],
            "turnover_pct": _pct(summ["turnover"]),
        },
        "equity_curve": [{
            "date": r["date"], "equity": r["e_end"], "return_pct": _pct(cr), "drawdown_pct": _pct(dd),
            "realized_pnl_cum": r["e_end"] - capital,
        } for r, cr, dd in zip(daily_rows, summ["cum_returns"], summ["drawdowns"])],
        "benchmark": [{"date": _d(b["date"]), "close": _r(b["close"], 2), "value": int(b["value"]),
                       "return_pct": _pct(b["ret"])} for b in bench.to_dict("records")],
        "daily": daily_rows,
        "charts": _charts(summ, daily_rows, [float(x) for x in bench["ret"]], weekly, chart_daily),
        "trade_value_share": share,
        "trades": trades,
        "trade_table": {"limit": TABLE_LIMIT, "total": total, "shown": shown, "truncated": truncated,
                        "caption": tcap},
        "closed_trades": _closed_rows(closed, names),
        "per_stock": stocks,
        "top_contributors": _top_contributors(stocks, summ["trade_count"]),
        "blocks": _blocks(bt.get("blocks", {})),
        "alerts": alerts,
        "insights": insights,
        "next_action": next_action,
        "target": _target(summ, capital, target),
    }


def write_result(result: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, allow_nan=False)
        fh.write("\n")
    return path
