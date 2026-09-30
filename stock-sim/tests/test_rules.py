"""절대 규칙 검사 (CLAUDE.md R1~R3). 검사 대상은 src/ 전체다."""
import re

from helpers import SRC

# 금지 문자열은 조각을 이어 붙여 만든다(이 파일 자체에 리터럴이 나타나지 않게).
# "a" + "b"는 컴파일러가 상수로 접어 .pyc에 리터럴이 남으므로 실행 시점에 join으로 잇는다.
_PARTS = [("trad", "ing/"), ("order", "-cash"), ("inquire", "-balance"), ("order", "-rvsecncl"),
          ("inquire", "-psbl-order"), ("inquire", "-account")]
FORBIDDEN = ["".join(list(p)) for p in _PARTS]


def _sources():
    files = sorted(SRC.rglob("*.py"))
    assert files, "src/stock_sim 아래에 파이썬 파일이 없습니다"
    return [(p, p.read_text(encoding="utf-8")) for p in files]


def test_no_order_or_account_api_paths_in_src():
    for path, text in _sources():
        for word in FORBIDDEN:
            assert word not in text, f"{path.name}: 금지 문자열 발견(R2)"


def test_requests_is_imported_only_in_kis_client():
    pattern = re.compile(r"^\s*(import\s+requests\b|from\s+requests\b)", re.MULTILINE)
    net_libs = re.compile(r"^\s*(import|from)\s+(urllib|http\.client|httpx|aiohttp|socket)\b", re.MULTILINE)
    for path, text in _sources():
        if path.name != "kis_client.py":
            assert not pattern.search(text), f"{path.name}: requests import는 kis_client.py에서만"
        assert not net_libs.search(text), f"{path.name}: 다른 네트워크 라이브러리 사용 금지"


def test_client_has_only_token_and_three_quote_paths():
    text = (SRC / "kis_client.py").read_text(encoding="utf-8")
    paths = set(re.findall(r'"(/(?:uapi|oauth2)/[^"]+)"', text))
    assert paths == {"/oauth2/tokenP",
                     "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                     "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
                     "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"}
    assert all("/quotations/" in p for p in paths if p.startswith("/uapi/"))
    from stock_sim.kis_client import KisClient
    public = {n for n in dir(KisClient) if not n.startswith("_")}
    assert public == {"get_token", "daily_prices", "index_daily", "minute_prices"}   # call_count는 인스턴스 속성


def test_no_env_switching_or_secret_printing_in_src():
    for path, text in _sources():
        assert not re.search(r"^\s*print\(", text, re.MULTILINE) or path.name == "render.py", \
            f"{path.name}: print 대신 logging"
        if path.name in ("kis_client.py", "data.py", "cli.py"):
            # base URL은 생성자의 env 하나로만 정해진다: PROD URL을 직접 고르는 코드가 없어야 한다(R3)
            assert 'BASE_URLS["PROD"]' not in text and "BASE_URLS['PROD']" not in text
            assert not re.search(r'env\s*=\s*"PROD"', text), f"{path.name}: 환경 전환 분기 금지"


def test_pure_modules_do_not_touch_files_network_or_clock():
    for name in ("strategy.py", "backtest.py", "metrics.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        for word in ("open(", "requests", "datetime.now", "date.today", "time.time", "read_csv", "to_csv"):
            assert word not in text, f"{name}: 순수 함수 모듈에 {word} 사용"
