"""render.py + dashboard.html.j2 테스트 (dashboard-builder 소유).

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
    # 샘플의 회사명이 남아 있지 않다(R4)
    assert "SAMSUNG" not in html and "DS혁신" not in html


def test_example_kpi_values_shown(example, tmp_path):
    html = render_dict(example, tmp_path)
    for text in (
        "+1.86%",          # summary.total_return_pct
        "+1.01%p",         # summary.excess_return_pct
        "-2.15%",          # summary.mdd_pct
        "2026-09-04 → 2026-09-14",
        "11회",            # summary.trade_count
        "매수 8 · 매도 3",
        "101,858,842원",   # summary.final_equity
        "-516,743원",      # summary.realized_pnl
        "보유 종목 평가손익",
        "+2,375,585원",    # summary.unrealized_pnl
        "+1,858,842원",    # summary.total_pnl (합계)
        "현재 수익률",
        "33.33%",          # summary.win_rate_pct
        "1승 2패",
        "5종목",           # summary.holding_count
        "217,799,000원",   # summary.total_trade_value
        "1,360주",
        "99.96%",          # allocation.center.value_pct
        "92.94%",          # target.progress_pct
        "102,000,000원",   # target.target_equity
    ):
        assert text in html, text


def test_example_sections_and_data_passthrough(example, tmp_path):
    html = render_dict(example, tmp_path)
    for title in ("자산 곡선과 벤치마크", "포지션 비중", "주차별 매매 구성", "종목별 손익 기여 상위 5",
                  "분석 요약", "종목별 상세", "점검 필요", "목표 수익률 진척"):
        assert title in html, title
    assert "매매 내역" in html  # 12번째 섹션(개정 1.1)
    for t in example["trades"]:
        assert t["reason"] in html and t["date"] in html
    assert "거래대금 19,750,000원 · 79주" in html  # per_stock 보조줄(NAVER)
    assert example["target"]["caption"] in html
    assert html.index("종목별 상세") < html.index("매매 내역")
    # JSON 의 기하 값이 그대로 들어간다
    assert example["charts"]["equity"]["equity_points"] in html
    assert example["charts"]["equity"]["benchmark_points"] in html
    assert example["charts"]["equity"]["equity_area_path"] in html
    assert example["allocation"]["conic_gradient"] in html
    assert example["charts"]["win_donut"]["conic_gradient"] in html
    for spark in ("equity", "realized_pnl", "holdings"):
        assert example["charts"]["sparklines"][spark] in html
    for row in example["per_stock"]:
        assert row["name"] in html and row["status_label"] in html
    for a in example["alerts"]:
        assert a["title"] in html
    for i in example["insights"]:
        assert i["no"] in html
    assert example["next_action"]["text"] in html
    assert example["top_contributors"]["note"] in html
    for d in example["meta"]["disclaimers"]:
        assert d in html
    # 자동 이스케이프
    assert "buy&amp;hold" in html and "buy&hold" not in html


def test_sign_and_color_agree(example, tmp_path):
    html = render_dict(example, tmp_path)
    found = assert_sign_color_agree(html)
    assert len(found) >= 25
    assert {PROFIT, LOSS, DARK_PROFIT, DARK_LOSS} <= {c for c, _, _ in found}
    # 헤더 KPI: 수익률·초과수익은 어두운 배경 수익색, MDD 는 어두운 배경 손실색
    header = html.split("<main")[0]
    assert f'color: {DARK_PROFIT};">+1.86%<' in header
    assert f'color: {DARK_PROFIT};">+1.01%p<' in header
    assert f'color: {DARK_LOSS};">-2.15%<' in header
    assert "시장 상회" in header


def test_neutral_colored_pnl_is_caught():
    """검사기 자체: 중립색·반대색·무색 손익은 실패로 잡아야 한다(phase4-1 M2)."""
    with pytest.raises(AssertionError):
        assert_sign_color_agree('<div style="color: #4A5568;">+1,151,604원</div>')
    with pytest.raises(AssertionError):
        assert_sign_color_agree(f'<div style="color: {PROFIT};">-147,704원</div>')
    with pytest.raises(AssertionError):
        assert_sign_color_agree('<div>+3.00%</div>')
    assert_sign_color_agree(f'<div style="color: {LOSS};"><span>-1원</span></div>')


def test_realized_sign_differs_from_total_sign(example, tmp_path):
    """실현 이익 + 더 큰 평가손실: 실현손익 열은 블루, 총손익·수익률은 손실색."""
    d = copy.deepcopy(example)
    d["per_stock"][0].update(realized_pnl=1151604, realized_pnl_sign="pos", unrealized_pnl=-2006634,
                             total_pnl=-855030, return_pct=-4.3, sign="neg")
    html = render_dict(d, tmp_path)
    found = assert_sign_color_agree(html)
    assert (PROFIT, "+", "+1,151,604원") in found
    assert (LOSS, "-", "-855,030원") in found
    assert (LOSS, "-", "-4.30%") in found


# ---------- 변형 입력(architecture.md 5.6절) ----------
def _no_trades(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["flags"].update(no_trades=True, no_closed_trades=True, no_positions=True, only_low_sample_alert=False)
    s = d["summary"]
    for k in ("trade_count", "buy_count", "sell_count", "closed_count", "win_count", "loss_count",
              "realized_pnl", "unrealized_pnl", "total_pnl", "total_cost", "holding_count",
              "total_trade_value", "buy_value", "sell_value", "total_trade_volume", "max_loss_streak"):
        s[k] = 0
    for k in ("total_return_pct", "excess_return_pct", "mdd_pct", "turnover_pct"):
        s[k] = 0.0
    s["excess_return_pct"] = -0.85
    for k in ("total_pnl_sign", "total_return_sign", "mdd_sign", "realized_pnl_sign", "unrealized_pnl_sign"):
        s[k] = "zero"
    s["excess_return_sign"] = "neg"
    s.update(win_rate_pct=None, payoff_ratio=None, mdd_peak_date=None, mdd_trough_date=None,
             equal_weight_return_pct=None, final_equity=100000000, cash=100000000, cash_weight_pct=100.0)
    d["trades"], d["positions"] = [], []
    d["top_contributors"] = {"items": [], "note": "거래한 종목이 없습니다."}
    flat = " ".join(f"{i * 10.0:.1f},22.0" for i in range(21))
    d["charts"]["sparklines"].update(equity=flat, realized_pnl=flat, holdings=flat)
    d["charts"]["win_donut"] = {"win_pct": 0, "conic_gradient": "conic-gradient(#1428A0 0% 0%, #E1E4EC 0% 100%)"}
    for b in d["charts"]["trade_value_bars"]:
        b.update(value=0, height_pct=0.0, color="#C2C8E8")
    d["allocation"].update(
        total=100000000, center={"label": "주식 비중", "value_pct": 0},
        conic_gradient="conic-gradient(#DCE0E9 0% 100%)",
        segments=[{"kind": "cash", "code": None, "label": "현금", "value": 100000000,
                   "weight_pct": 100.0, "start_pct": 0.0, "end_pct": 100.0, "color": "#DCE0E9"}])
    for w in d["weekly_flow"]:
        for seg, h in zip(w["segments"], (0.0, 0.0, 0.0, 100.0)):
            seg.update(value=0, height_pct=h)
    for r in d["per_stock"]:
        if r["status"] != "excluded":
            r.update(status="no_trade", status_label="거래 없음")
        r.update(trade_count=0, buy_count=0, sell_count=0, closed_count=0, win_count=0, win_rate_pct=None,
                 realized_pnl=0, unrealized_pnl=0, total_pnl=0, return_pct=None, contribution_pct=0.0,
                 sign="zero", bar_pct=0.0, trade_value=0, trade_volume=0)
    d["alerts"].insert(0, {"level": "warn", "code": "NO_TRADES", "title": "백테스트 기간에 거래가 없습니다.",
                           "detail": "", "date": None, "color": "#C98A2E"})
    d["target"].update(actual_return_pct=0.0, sign="zero", progress_raw_pct=0.0, progress_pct=0.0)
    for b in d["target"]["bar_segments"]:
        b["width_pct"] = 0.0
    return d


def test_no_trades_case(example, tmp_path):
    html = render_dict(_no_trades(example), tmp_path)
    assert_clean(html)
    assert "거래 없음" in html
    assert "해당 없음" in html          # 상위 기여 자리
    assert "청산 없음" in html
    assert "낙폭 없음" in html          # MDD 0, 두 날짜 null
    assert "기말 보유 종목 없음" in html
    assert "백테스트 기간에 거래가 없습니다." in html
    assert ">–<" in html                # null 은 '–'
    assert "0종목" in html
    assert "매매 내역" in html          # 카드는 남는다(5.6절)
    assert "거래 없음 (백테스트 구간에 체결된 매매가 없습니다)" in html
    assert "비용 합계" not in html


def test_loss_case_red_alert_and_null_peak(example, tmp_path):
    d = copy.deepcopy(example)
    s = d["summary"]
    s.update(total_return_pct=-6.2345, total_return_sign="neg", total_pnl=-6234500, total_pnl_sign="neg",
             final_equity=93765500, excess_return_pct=-7.0845, excess_return_sign="neg",
             mdd_pct=-7.5, mdd_sign="neg", mdd_peak_date=None, mdd_trough_date="2026-09-14",
             unrealized_pnl=-1200000, unrealized_pnl_sign="neg")
    d["top_contributors"]["items"][4].update(pnl=-298485, sign="neg")
    d["alerts"].insert(0, {"level": "warn", "code": "MDD_BREACH",
                           "title": "MDD -7.50%가 임계 -5.00%를 넘었습니다.",
                           "detail": "고점 시작 → 저점 2026-09-14", "date": None, "color": LOSS})
    d["alerts"].insert(1, {"level": "warn", "code": "LOSS_STREAK", "title": "연속 손실 3회.",
                           "detail": "", "date": "2026-09-21", "color": LOSS})
    d["alerts"].insert(2, {"level": "warn", "code": "UNDERPERFORM", "title": "벤치마크 하회.",
                           "detail": "KOSPI보다 7.08%p 낮음", "date": "2026-09-29", "color": LOSS})
    d["target"].update(actual_return_pct=-6.2345, sign="neg", current_return_pct=-6.2345,
                       current_return_sign="neg", gap_pct=-8.2345, progress_raw_pct=-311.725, progress_pct=0.0)
    for b in d["target"]["bar_segments"]:
        b["width_pct"] = 0.0
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert "-6.23%" in html and "-7.08%p" in html and "-7.50%" in html
    assert "시작 → 2026-09-14" in html   # mdd_peak_date null
    assert f"background: {LOSS}; margin-top: 6px;" in html   # 빨간 알림 점
    assert "-298,485원" in html
    assert_sign_color_agree(html)
    header = html.split("<main")[0]
    assert f'color: {DARK_LOSS};">-6.23%<' in header and "시장 하회" in header
    assert f'color: {LOSS};">-6.23%<' in html          # 목표 카드 현재 수익률
    assert "수익률이 0% 아래라 진척 0%" in html
    # 알림: detail 이 있으면 date 를 덧붙이지 않고, detail 이 비면 date 를 보인다(phase4-1 L3)
    assert ">고점 시작 → 저점 2026-09-14</div>" in html
    assert ">KOSPI보다 7.08%p 낮음</div>" in html
    assert "2026-09-29</div>" not in html.split("점검 필요")[1].split("목표 수익률 진척")[0]
    assert ">2026-09-21</div>" in html
    # 경고/참고 텍스트 라벨(점 색 외 구분). 예시 알림 warn 1 + info 1 에 warn 3 추가
    assert html.count(">경고</span>") == 4 and html.count(">참고</span>") == 1


def test_only_low_sample_and_thin_slice(example, tmp_path):
    d = copy.deepcopy(example)
    d["alerts"] = [a for a in d["alerts"] if a["code"] == "LOW_SAMPLE"]
    d["flags"]["only_low_sample_alert"] = True
    segs = d["allocation"]["segments"]
    segs[4].update(weight_pct=0.01, start_pct=80.67, end_pct=80.68)
    segs[5].update(weight_pct=19.32, start_pct=80.68)
    d["allocation"]["conic_gradient"] = (
        "conic-gradient(#1428A0 0% 20.4%, #4B5CC0 20.4% 40.69%, #7C9BFF 40.69% 60.72%, "
        "#909BD6 60.72% 80.67%, #C2C8E8 80.67% 80.68%, #DCE0E9 80.68% 100%)")
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert "특이 리스크 없음" in html
    assert "0.01%" in html
    assert d["allocation"]["conic_gradient"] in html


def test_empty_alerts_and_disclaimers(example, tmp_path):
    d = copy.deepcopy(example)
    d["alerts"] = []
    d["meta"]["is_example"] = False
    html = render_dict(d, tmp_path)
    assert_clean(html)
    assert "해당 없음" in html
    assert "예시 데이터" not in html.split("<main")[0]


# ---------- 예외 ----------
def test_missing_files_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_mod.render(tmp_path / "nope.json", TEMPLATE, tmp_path / "o.html")
    with pytest.raises(FileNotFoundError):
        render_mod.render(EXAMPLE, tmp_path / "nope.j2", tmp_path / "o.html")


def test_schema_major_mismatch_raises(example, tmp_path):
    example["schema_version"] = "2.0"
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
