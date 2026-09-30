"""render.py + dashboard.html.j2 테스트 (dashboard-builder 소유, result.json 스키마 2.0).

패키지 설치 여부와 무관하게 돌도록 render.py 를 파일 경로로 import 한다.
실행: uv run --with jinja2 --with pytest pytest tests/test_render.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]  # stock-sim/
RENDER_PY = ROOT / "src" / "stock_sim" / "render.py"
TEMPLATE = ROOT / "templates" / "dashboard.html.j2"
EXAMPLE = ROOT / "docs" / "result.example.json"

_spec = importlib.util.spec_from_file_location("stock_sim_render_under_test", RENDER_PY)
render_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_mod)

PROFIT = "#1428A0"
LOSS = "#B0472F"
DARK_PROFIT = "#7C9BFF"
DARK_LOSS = "#E29A80"
ALLOWED_BY_SIGN = {"+": {PROFIT, DARK_PROFIT}, "-": {LOSS, DARK_LOSS}}
SIGNED_VALUE = re.compile(r"^([+-])[\d,]+(?:\.\d+)?(?:원|%p?)$")
VOID_TAGS = {"meta", "link", "br", "hr", "img", "input"}


# ---------- 도우미 ----------
@pytest.fixture()
def example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def render_dict(data: dict, tmp_path: Path) -> str:
    src = tmp_path / "result.json"
    src.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    out = render_mod.render(result_path=src, template_path=TEMPLATE, out_path=tmp_path / "out" / "d.html")
    return out.read_text(encoding="utf-8")


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> at {self.getpos()} (stack top: {self.stack[-1:]})")
        else:
            self.stack.pop()


class _SignedColors(HTMLParser):
    """부호 있는 값만 담은 텍스트 노드마다 (실효 글자색, 부호, 값)을 모은다.

    실효 글자색 = 가장 가까운 조상의 인라인 color. 없으면 None(중립 취급 -> 실패).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.colors: list[str | None] = []
        self.found: list[tuple[str | None, str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        style = dict(attrs).get("style") or ""
        m = re.search(r"(?:^|;)\s*color:\s*(#[0-9A-Fa-f]{6})", style)
        inherited = self.colors[-1] if self.colors else None
        self.colors.append(m.group(1).upper() if m else inherited)

    def handle_endtag(self, tag):
        if tag not in VOID_TAGS and self.colors:
            self.colors.pop()

    def handle_data(self, data):
        m = SIGNED_VALUE.match(data.strip())
        if m:
            self.found.append((self.colors[-1] if self.colors else None, m.group(1), data.strip()))


def assert_sign_color_agree(html: str) -> list[tuple[str | None, str, str]]:
    """부호 있는 값은 전부 부호에 맞는 색이어야 한다(흰 배경 블루/손실색, 어두운 배경 #7C9BFF/#E29A80).
    중립색(#4A5568 등)이나 색 없음도 실패다(phase4-1 M2)."""
    p = _SignedColors()
    p.feed(html)
    p.close()
    bad = [(c, v) for c, sign, v in p.found if c not in ALLOWED_BY_SIGN[sign]]
    assert not bad, f"부호와 색 불일치: {bad}"
    return p.found


def parse(html: str) -> _Balance:
    p = _Balance()
    p.feed(html)
    p.close()
    return p


def assert_clean(html: str) -> None:
    """잔여물·태그 균형·좌표 범위 등 모든 렌더 결과가 지켜야 하는 조건."""
    for token in ("{{", "}}", "{%", "%}", "{#", "None", "Undefined"):
        assert token not in html, f"잔여물 {token!r}"
    assert not re.search(r"\bnan\b", html, flags=re.IGNORECASE), "nan 잔여"
    p = parse(html)
    assert not p.errors, p.errors
    assert not p.stack, f"닫히지 않은 태그: {p.stack}"
    # 외부 JS 없음, 외부 리소스는 폰트 링크뿐
    assert "<script" not in html.lower()
    for tag, attrs in p.tags:
        for key in ("href", "src"):
            url = attrs.get(key)
            if url and url.startswith("http"):
                assert tag == "link" and url.startswith(
                    ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
                ), f"허용되지 않은 외부 리소스: {url}"
    # SVG 좌표는 viewBox 안
    svg_box = None
    for tag, attrs in p.tags:
        if tag == "svg":
            _, _, w, h = (float(v) for v in attrs["viewbox"].split())
            svg_box = (w, h)
        elif tag == "polyline":
            assert svg_box is not None
            pts = attrs["points"].split()
            assert len(pts) >= 2
            for pt in pts:
                x, y = (float(v) for v in pt.split(","))
                assert 0 <= x <= svg_box[0] and 0 <= y <= svg_box[1], f"범위 밖 좌표 {pt}"
    # CSS 의 width/height % 는 0~100
    for m in re.finditer(r"(?:width|height): (-?[\d.]+)%", html):
        assert 0 <= float(m.group(1)) <= 100, m.group(0)


# ---------- 필터 ----------
def test_filters_match_contract():
    f = render_mod.FILTERS
    assert set(f) == {"won", "signed_won", "pct", "signed_pct", "sign_color", "sign_color_dark"}
    assert len(f) == 6
    assert f["won"](101858842) == "101,858,842원"
    assert f["signed_won"](-516743) == "-516,743원"
    assert f["signed_won"](906237) == "+906,237원"
    assert f["signed_won"](0) == "0원"
    assert f["pct"](33.3333) == "33.33%"
    assert f["signed_pct"](1.8588) == "+1.86%"
    assert f["signed_pct"](-2.1491) == "-2.15%"
    assert f["signed_pct"](0) == "0.00%"
    assert f["sign_color"]("pos") == PROFIT
    assert f["sign_color"]("neg") == LOSS
    assert f["sign_color"]("zero") == "#6E7688"
    assert f["sign_color"](None) == "#6E7688"
    assert f["sign_color_dark"]("pos") == DARK_PROFIT
    assert f["sign_color_dark"]("neg") == DARK_LOSS
    assert f["sign_color_dark"]("zero") == "#FFFFFF"
    assert f["sign_color_dark"](None) == "#FFFFFF"
    for name in ("won", "signed_won", "pct", "signed_pct"):
        assert f[name](None) == "–"


# ---------- 도우미(v2) ----------
def section(html: str, start: str, end: str | None = None) -> str:
    """start 제목 이후 ~ end 제목 이전의 HTML 조각."""
    part = html.split(start, 1)[1]
    return part.split(end, 1)[0] if end else part


def trade_table_part(html: str) -> str:
    return section(html, ">매매 내역<", "용어 ·")


def set_trade_table(d: dict, keep: int | None = None) -> dict:
    """trades 를 앞에서 keep 건만 남기고 in_table·trade_table 을 계약(5.5절)대로 맞춘다(테스트 입력 준비용)."""
    if keep is not None:
        d["trades"] = d["trades"][:keep]
    total = len(d["trades"])
    limit = d["trade_table"]["limit"]
    for i, t in enumerate(d["trades"]):
        t["in_table"] = i >= total - limit
    shown = min(total, limit)
    truncated = total > limit
    d["trade_table"].update(total=total, shown=shown, truncated=truncated,
                            caption=(f"최근 {shown}건 표시 · 전체 {total}건은 result.json의 trades[]에 있습니다."
                                     if truncated else (f"전체 {total}건" if total else "")))
    d["flags"]["trades_truncated"] = truncated
    return d


# ---------- 예시 렌더 ----------
def test_example_renders_clean(example, tmp_path):
    out = tmp_path / "nested" / "dashboard.html"
    got = render_mod.render(EXAMPLE, TEMPLATE, out)
    assert got == out and out.is_file()
    html = out.read_text(encoding="utf-8")
    assert_clean(html)
    assert "STOCK-SIM · 모의투자 백테스트" in html
    assert "<h1" in html and "주식 자동매매 시뮬레이션 대시보드" in html
    assert "2026-08-31 ~ 2026-09-29" in html
    assert "5분봉 채널 돌파 · 당일 청산" in html and "삼성전자·SK하이닉스" in html
    assert "예시 데이터(가짜 수치)" in html.split("<main")[0]
    # 샘플의 회사명이 남아 있지 않다(R4)
    assert "SAMSUNG" not in html and "DS혁신" not in html


def test_example_kpi_values_shown(example, tmp_path):
    html = render_dict(example, tmp_path)
    for text in (
        "-0.79%",            # summary.total_return_pct
        "-2.14%p",           # summary.excess_return_pct
        "KOSPI +1.35%",      # summary.benchmark_return_pct
        "-1.42%",            # summary.mdd_pct
        "2026-08-31 → 2026-09-10",
        "24회",              # summary.trade_count
        "매수 12 · 매도 12",
        "99,206,996원",      # summary.final_equity
        "-793,004원",        # summary.realized_pnl
        "비용 전 손익",
        "+577,200원",        # summary.gross_pnl
        "1,370,204원",       # summary.total_cost
        "41.67%",            # summary.win_rate_pct
        "5승 7패",
        "86.7분",            # summary.avg_hold_minutes
        "일평균 청산 0.60건 · 체결 1.20건",  # 소수 2자리 표시(phase4-3 Low 2)
        "1,190,979,600원",   # summary.total_trade_value
        "9,586주",
        "24건",              # trade_value_share.center
        "58.47%", "41.53%",  # trade_value_share.segments[].share_pct
        "왕복 0.23%",        # meta.costs.round_trip_pct
        "102,000,000원",     # target.target_equity
        "전체 24건 중 최근 20건",
    ):
        assert text in html, text


def test_example_sections_and_data_passthrough(example, tmp_path):
    html = render_dict(example, tmp_path)
    titles = ("자산 곡선과 벤치마크", "종목별 거래대금 비중", "일별 손익", "종목별 손익 기여 상위 5",
              "분석 요약", "종목별 상세", "점검 필요", "진입 차단 집계", "목표 수익률 진척", "매매 내역")
    for title in titles:
        assert title in html, title
    pos = [html.index(f">{t}") for t in titles]
    assert pos == sorted(pos), "섹션 순서"
    # v1 섹션 잔재가 없다
    for gone in ("포지션 비중", "주차별 매매 구성", "보유 종목 수", "평가손익"):
        assert gone not in html, gone
    # JSON 의 기하 값이 그대로 들어간다
    eq = example["charts"]["equity"]
    for key in ("equity_points", "benchmark_points", "equity_area_path"):
        assert eq[key] in html
    assert example["trade_value_share"]["conic_gradient"] in html
    assert example["charts"]["win_donut"]["conic_gradient"] in html
    for spark in ("equity", "realized_pnl", "daily_fills"):
        assert example["charts"]["sparklines"][spark] in html
    for b in example["charts"]["trade_value_bars"]:
        assert f"height: {b['height_pct']}%; background: {b['color']};" in html
    for row in example["per_stock"]:
        assert row["name"] in html and row["status_label"] in html
    assert "78.6분" in html and "98.0분" in html          # per_stock.avg_hold_minutes
    for a in example["alerts"]:
        assert a["title"] in html
    for i in example["insights"]:
        assert i["no"] in html and i["detail"] in html
    assert example["next_action"]["text"] in html
    assert example["top_contributors"]["note"] in html
    assert example["charts"]["daily_pnl"]["caption"] in html
    assert example["charts"]["equity"]["caption"].replace("&", "&amp;") in html
    assert example["blocks"]["caption"] in html
    for b in example["blocks"]["items"]:
        assert f">{b['label']}<" in html and f"width: {b['bar_pct']}%;" in html
    assert example["target"]["caption"] in html
    for d in example["meta"]["disclaimers"]:
        assert d in html
    # 슬리피지 고지는 점검 필요 카드 안(목표 카드 앞)
    assert example["meta"]["slippage_note"] in section(html, ">점검 필요<", ">목표 수익률 진척<")
    # 자동 이스케이프
    assert "buy&amp;hold" in html and "buy&hold" not in html


def test_daily_pnl_bars_follow_json(example, tmp_path):
    """일별 손익 막대: 거래일마다 gain(위)·loss(아래) 두 조각, 높이·색은 JSON 그대로, 색이 곧 부호."""
    html = render_dict(example, tmp_path)
    part = section(html, ">일별 손익<", ">종목별 손익 기여 상위 5<")
    for d in example["daily"]:
        gain = next(s for s in d["segments"] if s["key"] == "gain")
        loss = next(s for s in d["segments"] if s["key"] == "loss")
        assert gain["color"] == PROFIT and loss["color"] == LOSS
        if d["sign"] == "pos":
            assert gain["height_pct"] > 0 and loss["height_pct"] == 0
        elif d["sign"] == "neg":
            assert loss["height_pct"] > 0 and gain["height_pct"] == 0
        # 날짜별 막대의 조각 순서: gain(위 절반) → loss(아래 절반)
        col = part.split(f'title="{d["date"]} 손익 ', 1)[1].split("</div>\n            </div>", 1)[0]
        g = f"height: {gain['height_pct']}%; background: {gain['color']};"
        lo = f"height: {loss['height_pct']}%; background: {loss['color']};"
        assert g in col and lo in col and col.index(g) < col.index(lo), d["date"]
    # 축 라벨은 show_label 인 날만
    for d in example["daily"]:
        assert (f">{d['label']}</div>" in part) == d["show_label"], d["label"]
    # 매매 중단일 표식(주의색 링) 수 = halt_days (+ 범례 1)
    assert part.count("border: 2px solid #C98A2E;") == example["summary"]["halt_days"] + 1
    assert "09-08" not in part.split("title=")[0]


def test_trade_table_shows_only_in_table_rows(example, tmp_path):
    html = render_dict(example, tmp_path)
    part = trade_table_part(html)
    shown = [t for t in example["trades"] if t["in_table"]]
    hidden = [t for t in example["trades"] if not t["in_table"]]
    assert len(shown) == example["trade_table"]["shown"] == 20 and hidden
    # 표 행 수 = in_table 행 수(사유 라벨 셀로 센다)
    labels = {t["reason_label"] for t in example["trades"]}
    assert sum(part.count(f">{lb}</div>") for lb in labels) == len(shown)
    # 배열 순서대로 날짜·시각이 나온다
    cursor = 0
    for t in shown:
        i = part.index(f">{t['date']}</div>", cursor)
        j = part.index(f">{t['time']}</div>", i)
        cursor = j
    # 숨긴 행의 날짜(08-31, 09-01)는 표에 없다
    for t in hidden:
        assert f">{t['date']}</div>" not in part
    # 매도 행: 실현손익 + 보유 시간, 매수 행: '–'
    assert "보유 335분" in part and "-689,578원" in part
    assert part.count("보유 ") == sum(1 for t in shown if t["hold_minutes"] is not None)
    assert example["trade_table"]["caption"] in part


def test_sign_and_color_agree(example, tmp_path):
    html = render_dict(example, tmp_path)
    found = assert_sign_color_agree(html)
    assert len(found) >= 20
    assert {PROFIT, LOSS, DARK_LOSS} <= {c for c, _, _ in found}   # 예시 헤더 KPI 는 전부 음수
    header = html.split("<main")[0]
    assert f'color: {DARK_LOSS};">-0.79%<' in header
    assert f'color: {DARK_LOSS};">-2.14%p<' in header
    assert f'color: {DARK_LOSS};">-1.42%<' in header
    assert "시장 하회" in header
    assert (PROFIT, "+", "+577,200원") in found      # 비용 전 손익(pos) vs 실현 손익(neg)
    assert (LOSS, "-", "-793,004원") in found


def test_neutral_colored_pnl_is_caught():
    """검사기 자체: 중립색·반대색·무색 손익은 실패로 잡아야 한다(phase4-1 M2)."""
    with pytest.raises(AssertionError):
        assert_sign_color_agree('<div style="color: #4A5568;">+1,151,604원</div>')
    with pytest.raises(AssertionError):
        assert_sign_color_agree(f'<div style="color: {PROFIT};">-147,704원</div>')
    with pytest.raises(AssertionError):
        assert_sign_color_agree('<div>+3.00%</div>')
    assert_sign_color_agree(f'<div style="color: {LOSS};"><span>-1원</span></div>')


# ---------- 변형 입력(architecture.md 5.6절) ----------
def _no_trades(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["flags"].update(no_trades=True, only_baseline_alerts=False, trades_truncated=False)
    s = d["summary"]
    for k in ("total_pnl", "trade_count", "buy_count", "sell_count", "closed_count", "win_count", "loss_count",
              "even_count", "max_loss_streak", "realized_pnl", "gross_pnl", "total_cost", "buy_cost", "sell_cost",
              "halt_days", "total_trade_value", "buy_value", "sell_value", "total_trade_volume"):
        s[k] = 0
    for k in ("total_return_pct", "mdd_pct", "cost_to_capital_pct", "avg_closed_per_day", "avg_fills_per_day",
              "turnover_pct"):
        s[k] = 0.0
    s.update(excess_return_pct=-1.35, excess_return_sign="neg", excess_vs_equal_weight_pct=-2.1,
             excess_vs_equal_weight_sign="neg", final_equity=100000000, win_rate_pct=None, payoff_ratio=None,
             avg_hold_minutes=None, mdd_peak_date=None, mdd_trough_date=None,
             exit_reasons={"breakdown": 0, "eod": 0})
    for k in ("total_pnl_sign", "total_return_sign", "mdd_sign", "realized_pnl_sign", "gross_pnl_sign"):
        s[k] = "zero"
    d["trades"], d["closed_trades"] = [], []
    d["trade_table"].update(total=0, shown=0, truncated=False, caption="")
    for row in d["equity_curve"]:
        row.update(equity=100000000, return_pct=0.0, drawdown_pct=0.0, realized_pnl_cum=0)
    for row in d["daily"]:
        row.update(e_start=100000000, e_end=100000000, pnl=0, sign="zero", return_pct=0.0, buy_count=0,
                   sell_count=0, closed_count=0, trade_value=0, cost=0, halted=False)
        for seg in row["segments"]:
            seg.update(value=0, height_pct=0.0)
    d["charts"]["daily_pnl"].update(max_abs=0, win_days=0, loss_days=0, flat_days=len(d["daily"]),
                                    best=None, worst=None, caption="거래가 없어 일별 손익이 없습니다.")
    flat = " ".join(f"{i * 10.0:.1f},22.0" for i in range(21))
    d["charts"]["sparklines"].update(equity=flat, realized_pnl=flat, daily_fills=flat)
    d["charts"]["win_donut"] = {"win_pct": 0, "conic_gradient": "conic-gradient(#1428A0 0% 0%, #E1E4EC 0% 100%)"}
    for b in d["charts"]["trade_value_bars"]:
        b.update(value=0, height_pct=0.0, color="#C2C8E8")
    d["trade_value_share"].update(total=0, center={"label": "체결 건수", "value": 0, "unit": "건"},
                                  conic_gradient="conic-gradient(#DCE0E9 0% 100%)", segments=[])
    for r in d["per_stock"]:
        r.update(status="no_trade", status_label="거래 없음", trade_count=0, buy_count=0, sell_count=0,
                 closed_count=0, win_count=0, loss_count=0, win_rate_pct=None, gross_pnl=0, cost=0,
                 realized_pnl=0, sign="zero", return_pct=None, contribution_pct=0.0, bar_pct=0.0,
                 trade_value=0, trade_value_share_pct=0.0, trade_volume=0, avg_hold_minutes=None)
    d["top_contributors"] = {"items": [], "note": "거래가 없어 손익 기여 종목이 없습니다."}
    d["blocks"].update(entries=0, blocked=d["blocks"]["breakout"])
    d["alerts"] = [a for a in d["alerts"] if a["code"] != "COST_DRAG" and a["code"] != "DAILY_LOSS_HALT"]
    d["alerts"].insert(1, {"level": "warn", "code": "NO_TRADES", "title": "백테스트 기간에 거래가 없습니다.",
                           "detail": "", "date": None, "color": "#C98A2E"})
    d["target"].update(current_return_pct=0.0, current_return_sign="zero", gap_pct=-2.0, gap_amount=2000000,
                       progress_raw_pct=0.0, progress_pct=0.0)
    return d


def test_no_trades_case(example, tmp_path):
    html = render_dict(_no_trades(example), tmp_path)
    assert_clean(html)
    assert_sign_color_agree(html)
    assert "청산 없음" in html
    assert "낙폭 없음" in html                                   # MDD 0, 두 날짜 null
    assert "백테스트 기간에 거래가 없습니다." in html
    assert "거래가 없어 일별 손익이 없습니다." in html
    assert "conic-gradient(#DCE0E9 0% 100%)" in html               # 회색 도넛
    assert "0건" in html and "해당 없음 (체결된 매매가 없습니다)" in html
    assert "해당 없음 (거래한 종목이 없습니다)" in html            # 상위 기여
    assert "거래 없음 (백테스트 구간에 체결된 매매가 없습니다)" in html
    assert "비용 합계" not in html and "매매 중단일" not in html
    assert "분</div>" not in section(html, ">평균 보유 시간<", ">총 거래대금<")   # null → '–'
    assert ">–<" in html
    assert "진입 차단 집계" in html and example["blocks"]["caption"] in html


def test_excluded_stock_and_day_skipped(example, tmp_path):
    d = copy.deepcopy(example)
    d["meta"]["data_source"]["excluded"] = [{"code": "000660", "name": "SK하이닉스", "reason": "DATA_MISSING"}]
    d["per_stock"].append({"code": "123456", "name": "제외종목", "status": "excluded",
                           "status_label": "제외(데이터 없음)", "trade_count": 0, "buy_count": 0, "sell_count": 0,
                           "closed_count": 0, "win_count": 0, "loss_count": 0, "win_rate_pct": None,
                           "gross_pnl": 0, "cost": 0, "realized_pnl": 0, "sign": "zero", "return_pct": None,
                           "contribution_pct": 0.0, "bar_pct": 0.0, "trade_value": 0,
                           "trade_value_share_pct": 0.0, "trade_volume": 0, "avg_hold_minutes": None})
    d["meta"]["universe"].append({"code": "123456", "name": "제외종목"})
    d["alerts"][0:0] = [
        {"level": "warn", "code": "DATA_MISSING", "title": "제외종목 데이터 없음: 유니버스에서 제외",
         "detail": "123456", "date": None, "color": "#C98A2E"},
        {"level": "warn", "code": "DAY_SKIPPED", "title": "삼성전자 분봉 부족으로 매매하지 않음",
         "detail": "", "date": "2026-09-16", "color": "#C98A2E"},
    ]
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert_sign_color_agree(html)
    detail = section(html, ">종목별 상세<", ">점검 필요<")
    assert "제외종목" in detail and "123456 · 제외(데이터 없음)" in detail
    assert "유니버스 3종목" in detail
    row = detail.split("제외종목", 1)[1]
    assert row.count(">–<") >= 4                   # 실현손익·승률·평균 보유·수익률
    alerts = section(html, ">점검 필요<", ">진입 차단 집계<")
    assert "제외종목 데이터 없음: 유니버스에서 제외" in alerts
    assert ">2026-09-16</div>" in alerts            # detail 이 비면 date 를 보인다
    assert html.count(">경고</span>") == 4


def test_trade_table_not_truncated(example, tmp_path):
    d = set_trade_table(copy.deepcopy(example), keep=18)
    assert not d["trade_table"]["truncated"] and all(t["in_table"] for t in d["trades"])
    html = render_dict(d, tmp_path)
    assert_clean(html)
    part = trade_table_part(html)
    assert "전체 18건" in part and "최근" not in part
    labels = {t["reason_label"] for t in d["trades"]}
    assert sum(part.count(f">{lb}</div>") for lb in labels) == 18
    assert ">2026-08-31</div>" in part and ">09:35</div>" in part


def test_all_loss_case(example, tmp_path):
    """전부 손실: 수익 색이 손익 자리에 나오지 않고 헤더·카드·표 모두 손실색."""
    d = copy.deepcopy(example)
    s = d["summary"]
    s.update(gross_pnl=-500000, gross_pnl_sign="neg", win_count=0, loss_count=12, win_rate_pct=0.0,
             mdd_pct=-6.1, mdd_sign="neg", mdd_peak_date=None, mdd_trough_date="2026-09-28")
    for t in d["trades"]:
        if t["side"] == "SELL" and t["sign"] == "pos":
            t.update(realized_pnl=-t["realized_pnl"], realized_pnl_pct=-t["realized_pnl_pct"], sign="neg")
    for row in d["daily"]:
        gain, loss = row["segments"]
        if row["sign"] == "pos":
            row.update(pnl=-row["pnl"], sign="neg", return_pct=-row["return_pct"])
            loss.update(value=gain["value"], height_pct=gain["height_pct"])
            gain.update(value=0, height_pct=0.0)
    d["charts"]["win_donut"] = {"win_pct": 0.0, "conic_gradient": "conic-gradient(#1428A0 0% 0.0%, #E1E4EC 0.0% 100%)"}
    d["alerts"].insert(0, {"level": "warn", "code": "MDD_BREACH", "title": "MDD -6.10%, 임계 -5.00% 초과",
                           "detail": "고점 초기 자본 → 저점 2026-09-28", "date": None, "color": LOSS})
    html = render_dict(d, tmp_path)
    assert_clean(html)
    found = assert_sign_color_agree(html)
    assert not [v for c, sign, v in found if sign == "+" and "원" in v and c == PROFIT]
    assert "0승 12패" in html and "0.00%" in html
    assert "시작 → 2026-09-28" in html.split("<main")[0]
    assert f"background: {LOSS}; margin-top: 6px;" in html          # 빨간 알림 점
    part = section(html, ">일별 손익<", ">종목별 손익 기여 상위 5<")
    assert f"background: {PROFIT}; border-radius: 3px 3px 0 0" not in part.replace(
        f"height: 0.0%; background: {PROFIT}; border-radius: 3px 3px 0 0", "")
    assert "수익률이 0% 아래라 진척 0%" in html


def test_only_baseline_alerts(example, tmp_path):
    d = copy.deepcopy(example)
    d["alerts"] = [a for a in d["alerts"] if a["code"] in ("OVERNIGHT_GAP_NOTE", "LOW_SAMPLE")]
    d["flags"]["only_baseline_alerts"] = True
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert "특이 리스크 없음" in html
    assert html.count(">참고</span>") == 2 and ">경고</span>" not in html


def test_empty_alerts_and_real_data_flag(example, tmp_path):
    d = copy.deepcopy(example)
    d["alerts"] = []
    d["meta"]["is_example"] = False
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert "해당 없음" in section(html, ">점검 필요<", ">진입 차단 집계<")
    assert "예시 데이터" not in html.split("<main")[0]


# ---------- 예외 ----------
def test_missing_files_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_mod.render(tmp_path / "nope.json", TEMPLATE, tmp_path / "o.html")
    with pytest.raises(FileNotFoundError):
        render_mod.render(EXAMPLE, tmp_path / "nope.j2", tmp_path / "o.html")


def test_schema_major_mismatch_raises(example, tmp_path):
    example["schema_version"] = "1.1"
    with pytest.raises(ValueError):
        render_dict(example, tmp_path)


def test_missing_key_is_not_silently_blank(example, tmp_path):
    from jinja2 import UndefinedError

    del example["summary"]["final_equity"]
    with pytest.raises(UndefinedError):
        render_dict(example, tmp_path)


def test_render_module_is_standalone():
    src = RENDER_PY.read_text(encoding="utf-8")
    assert "import requests" not in src and "print(" not in src
    assert not re.search(r"^\s*(from|import) stock_sim", src, flags=re.MULTILINE)
