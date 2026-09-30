"""KisClient 단위 테스트. requests를 가짜로 바꿔 네트워크 없이 돈다."""
import json
import logging
from datetime import date, datetime, timedelta

import pytest

from stock_sim import kis_client
from stock_sim.kis_client import (KisAuthError, KisClient, KisRateLimitError, KisUnsupportedError)

KEY, SECRET, TOKEN = "FAKEKEY-abcdef-123456", "FAKESECRET-zyxwvu-654321", "FAKETOKEN-qwerty"
S, E = date(2026, 9, 1), date(2026, 9, 29)


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeHttp:
    def __init__(self, gets=None, posts=None):
        self.gets, self.posts = list(gets or []), list(posts or [])
        self.get_calls, self.post_calls, self.sleeps = [], [], []

    def get(self, url, headers=None, params=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers, "params": params})
        item = self.gets.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, json=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "json": json})
        return self.posts.pop(0)


@pytest.fixture
def http(monkeypatch):
    fake = FakeHttp()
    monkeypatch.setattr(kis_client.requests, "get", fake.get)
    monkeypatch.setattr(kis_client.requests, "post", fake.post)
    monkeypatch.setattr(kis_client.time, "sleep", lambda s: fake.sleeps.append(s))
    return fake


def _token_resp():
    exp = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    return Resp(200, {"access_token": TOKEN, "access_token_token_expired": exp, "expires_in": 86400})


def _client(tmp_path, **kw):
    return KisClient("DEV", KEY, SECRET, tmp_path, min_interval_sec=0.0, **kw)


def _ok(rows):
    return Resp(200, {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상", "output2": rows})


def test_token_is_issued_once_cached_to_file_and_reused(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [_ok([{"stck_bsop_date": "20260901"}]), _ok([])]
    c = _client(tmp_path)
    assert c.daily_prices("005930", S, E) == [{"stck_bsop_date": "20260901"}]
    assert len(http.post_calls) == 1
    assert http.post_calls[0]["url"] == "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
    saved = json.loads((tmp_path / "token_dev.json").read_text(encoding="utf-8"))
    assert set(saved) == {"access_token", "expires_at", "issued_at", "env"}   # 앱키·시크릿은 저장하지 않는다
    # 새 클라이언트는 파일 캐시를 재사용하고 재발급하지 않는다
    c2 = _client(tmp_path)
    assert c2.daily_prices("005930", S, E) == []
    assert len(http.post_calls) == 1 and c2.call_count == 1


def test_expiring_token_is_reissued(tmp_path, http):
    soon = (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds")
    (tmp_path / "token_dev.json").write_text(json.dumps(
        {"access_token": "OLD", "expires_at": soon, "issued_at": soon, "env": "DEV"}), encoding="utf-8")
    http.posts = [_token_resp()]
    assert _client(tmp_path).get_token() == TOKEN


def test_request_shape_is_quote_only_and_adjusted_price(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [_ok([]), Resp(200, {"rt_cd": "0", "output2": [{"stck_bsop_date": "20260901"}]})]
    c = _client(tmp_path)
    c.daily_prices("005930", S, E)
    c.index_daily("0001", S, E)
    stock, index = http.get_calls
    assert stock["url"].endswith("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice")
    assert stock["params"] == {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930",
                               "FID_INPUT_DATE_1": "20260901", "FID_INPUT_DATE_2": "20260929",
                               "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
    assert stock["headers"]["tr_id"] == "FHKST03010100" and stock["headers"]["custtype"] == "P"
    assert index["url"].endswith("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice")
    assert index["params"]["FID_COND_MRKT_DIV_CODE"] == "U" and index["headers"]["tr_id"] == "FHKUP03500100"
    assert c.call_count == 2
    public = {n for n in dir(KisClient) if not n.startswith("_")}
    assert public == {"get_token", "daily_prices", "index_daily", "minute_prices"}   # 시세 조회만(R2)


def test_minute_request_shape_and_raw_rows(tmp_path, http):
    http.posts = [_token_resp()]
    raw = [{"stck_bsop_date": "20260929", "stck_cntg_hour": "153000", "stck_prpr": "272500"}]
    http.gets = [_ok(raw), _ok([])]
    c = _client(tmp_path)
    assert c.minute_prices("005930", date(2026, 9, 29), "160000") == raw      # 정규화하지 않는다
    assert c.minute_prices("005930", date(2026, 9, 24), "160000") == []       # 빈 배열은 예외 아님
    call = http.get_calls[0]
    assert call["url"] == ("https://openapivts.koreainvestment.com:29443"
                           "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice")
    assert call["params"] == {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930",
                              "FID_INPUT_DATE_1": "20260929", "FID_INPUT_HOUR_1": "160000",
                              "FID_PW_DATA_INCU_YN": "N", "FID_FAKE_TICK_INCU_YN": ""}
    assert call["headers"]["tr_id"] == "FHKST03010230" and call["headers"]["custtype"] == "P"
    assert call["headers"]["tr_cont"] == "" and c.call_count == 2


def test_minute_unsupported_does_not_switch_env(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [Resp(500, {"rt_cd": "1", "msg_cd": "OPSQ0002", "msg1": "없는 서비스 코드 입니다"})]
    with pytest.raises(KisUnsupportedError) as exc:
        _client(tmp_path).minute_prices("005930", date(2026, 9, 29), "160000")
    assert "주식일별분봉조회" in str(exc.value) and "자동으로 PROD로 전환하지 않습니다" in str(exc.value)
    assert len(http.get_calls) == 1 and "openapivts" in http.get_calls[0]["url"]


def test_default_min_interval_is_half_second(tmp_path):
    assert KisClient("DEV", KEY, SECRET, tmp_path)._min_interval == 0.5


def test_rate_limit_retries_with_backoff_then_succeeds(tmp_path, http):
    http.posts = [_token_resp()]
    limited = Resp(500, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."})
    http.gets = [limited, limited, _ok([{"stck_bsop_date": "20260901"}])]
    c = _client(tmp_path, max_retries=3, backoff_sec=2.0)
    assert len(c.daily_prices("005930", S, E)) == 1
    assert http.sleeps == [2.0, 4.0] and c.call_count == 3


def test_rate_limit_exhausted(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [Resp(429, {})] * 3
    with pytest.raises(KisRateLimitError):
        _client(tmp_path, max_retries=2).daily_prices("005930", S, E)


def test_network_error_message_has_no_repr_of_exception(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [kis_client.requests.ConnectionError(f"boom {SECRET}")] * 2
    with pytest.raises(kis_client.KisError) as exc:
        _client(tmp_path, max_retries=1).daily_prices("005930", S, E)
    assert SECRET not in str(exc.value) and "ConnectionError" in str(exc.value)


def test_unsupported_error_never_switches_env_and_hides_secrets(tmp_path, http, caplog):
    caplog.set_level(logging.DEBUG)
    http.posts = [_token_resp()]
    http.gets = [Resp(500, {"rt_cd": "1", "msg_cd": "OPSQ0002", "msg1": f"없는 서비스 코드 입니다 {KEY}"})]
    c = _client(tmp_path)
    with pytest.raises(KisUnsupportedError) as exc:
        c.index_daily("0001", S, E)
    msg = str(exc.value)
    assert "msg_cd=OPSQ0002" in msg and "HTTP=500" in msg and "자동으로 PROD로 전환하지 않습니다" in msg
    assert len(http.get_calls) == 1
    assert all("openapivts" in call["url"] for call in http.get_calls)     # 다른 도메인으로 재시도하지 않는다
    logs = caplog.text + msg
    for secret in (KEY, SECRET, TOKEN):
        assert secret not in logs
    assert "FAKE****" in caplog.text                                      # 앱키는 앞 4자리만


def test_index_without_daily_array_is_unsupported(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [Resp(200, {"rt_cd": "0", "output1": {"hts_kor_isnm": "코스피"}, "output2": []})]
    with pytest.raises(KisUnsupportedError):
        _client(tmp_path).index_daily("0001", S, E)


def test_server_rejected_token_is_reissued_once(tmp_path, http):
    http.posts = [_token_resp(), _token_resp()]
    http.gets = [Resp(401, {"msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."}), _ok([])]
    assert _client(tmp_path).daily_prices("005930", S, E) == []
    assert len(http.post_calls) == 2


def test_token_failure_waits_61s_retries_once_then_raises(tmp_path, http):
    bad = Resp(403, {"error_code": "EGW00133", "error_description": "접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)"})
    http.posts = [bad, bad]
    with pytest.raises(KisAuthError) as exc:
        _client(tmp_path).get_token()
    assert http.sleeps == [61] and len(http.post_calls) == 2
    assert "EGW00133" in str(exc.value) and SECRET not in str(exc.value)
    assert not (tmp_path / "token_dev.json").exists()


def test_min_interval_between_calls(tmp_path, http):
    http.posts = [_token_resp()]
    http.gets = [_ok([]), _ok([])]
    c = KisClient("DEV", KEY, SECRET, tmp_path, min_interval_sec=1.0)
    c.daily_prices("005930", S, E)
    c.daily_prices("000660", S, E)
    assert len(http.sleeps) == 1 and 0.9 < http.sleeps[0] <= 1.0


def test_unknown_env_rejected(tmp_path):
    with pytest.raises(kis_client.KisError):
        KisClient("PAPER", KEY, SECRET, tmp_path)
