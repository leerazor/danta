"""정규화·구간 분할·캐시 테스트. 네트워크 없음(가짜 클라이언트)."""
from datetime import date

import pandas as pd
import pytest

from helpers import FIXTURES, HAND_END, HAND_START, hand_prices, make_df
from stock_sim import data


class ExplodingClient:
    """호출되면 실패하는 가짜 객체: 캐시 적중 시 클라이언트를 부르지 않음을 증명한다."""
    call_count = 0

    def daily_prices(self, *a, **k):
        raise AssertionError("캐시가 있는데 API를 호출했습니다")

    index_daily = daily_prices


class FakeClient:
    def __init__(self, stock_rows=None, index_rows=None):
        self.stock_rows, self.index_rows = stock_rows or [], index_rows or []
        self.calls, self.call_count = [], 0

    def daily_prices(self, code, start, end):
        self.calls.append(("stock", code, start, end))
        self.call_count += 1
        return list(self.stock_rows)

    def index_daily(self, code, start, end):
        self.calls.append(("index", code, start, end))
        self.call_count += 1
        lo, hi = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        return [r for r in self.index_rows if lo <= r["stck_bsop_date"] <= hi]


def _stock_row(day, o, h, l, c, vol="1000", val="50000000"):
    return {"stck_bsop_date": day, "stck_oprc": o, "stck_hgpr": h, "stck_lwpr": l,
            "stck_clpr": c, "acml_vol": vol, "acml_tr_pbmn": val, "mod_yn": "N"}


def test_normalize_stock_rows_strings_desc_blank_duplicates():
    rows = [
        _stock_row("20260903", "71000", "72000", "70500", "71500"),
        _stock_row("20260902", "70000", "71000", "69000", "70500"),
        _stock_row("", "0", "0", "0", "0"),                      # 빈 날짜 → 버림
        _stock_row("2026xx01", "1", "1", "1", "1"),              # 파싱 실패 → 버림
        _stock_row("20260901", "69000", "70000", "68000", "69500"),
        _stock_row("20260902", "70001", "71001", "69001", "70501"),   # 중복 → 마지막 것
    ]
    df = data.normalize_stock_rows(rows)
    assert list(df.columns) == data.COLUMNS
    assert list(df["date"].dt.strftime("%Y-%m-%d")) == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert list(df["close"]) == [69500, 70501, 71500]
    assert str(df["date"].dtype).startswith("datetime64")
    for col in ("open", "high", "low", "close", "volume", "value"):
        assert df[col].dtype == "int64"
    assert list(df.index) == [0, 1, 2]
    assert df.attrs["non_integer_price"] is False


def test_normalize_stock_non_integer_price_rounds_half_up():
    df = data.normalize_stock_rows([_stock_row("20260901", "100.5", "101.4", "99.5", "100.49")])
    assert (df["open"].iloc[0], df["high"].iloc[0], df["low"].iloc[0], df["close"].iloc[0]) == (101, 101, 100, 100)
    assert df.attrs["non_integer_price"] is True


def test_normalize_empty_and_index_rows():
    assert len(data.normalize_stock_rows([])) == 0
    rows = [{"stck_bsop_date": "20260902", "bstp_nmix_oprc": "4025.10", "bstp_nmix_hgpr": "4040.00",
             "bstp_nmix_lwpr": "4020.00", "bstp_nmix_prpr": "4039.55", "acml_vol": "500000",
             "acml_tr_pbmn": "9000000"},
            {"stck_bsop_date": "20260901", "bstp_nmix_oprc": "", "bstp_nmix_hgpr": "4030.00",
             "bstp_nmix_lwpr": "4000.00", "bstp_nmix_prpr": "4020.12", "acml_vol": "400000",
             "acml_tr_pbmn": "8000000"}]
    df = data.normalize_index_rows(rows)
    assert list(df["close"]) == [4020.12, 4039.55]
    assert df["close"].dtype == "float64" and df["volume"].dtype == "int64"
    assert pd.isna(df["open"].iloc[0])                    # 지수 시가 없음은 그대로 둔다


def test_split_ranges():
    s, e = date(2026, 5, 31), date(2026, 9, 29)
    assert data.split_ranges(s, e, 130) == [(s, e)]
    parts = data.split_ranges(s, e, 60)
    assert parts == [(date(2026, 5, 31), date(2026, 7, 29)), (date(2026, 7, 30), date(2026, 9, 27)),
                     (date(2026, 9, 28), date(2026, 9, 29))]
    assert data.split_ranges(s, s, 60) == [(s, s)]
    assert data.split_ranges(e, s, 60) == []
    with pytest.raises(ValueError):
        data.split_ranges(s, e, 0)


def test_cache_path_names():
    p = data.cache_path(FIXTURES, "005930", date(2026, 5, 31), date(2026, 9, 29))
    assert p.name == "005930_20260531_20260929.csv"
    q = data.cache_path(FIXTURES, data.index_cache_code("0001"), date(2026, 5, 31), date(2026, 9, 29))
    assert q.name == "IDX0001_20260531_20260929.csv"


def test_cache_hit_never_calls_client():
    df = data.load_daily("AAA", HAND_START, HAND_END, FIXTURES, ExplodingClient())
    assert len(df) == 7 and df.attrs["from_cache"] is True
    assert list(df["date"]) == sorted(df["date"])
    idx = data.load_index("0001", HAND_START, HAND_END, FIXTURES, ExplodingClient())
    assert len(idx) == 5 and idx["close"].dtype == "float64"


def test_cache_miss_without_client_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        data.load_daily("AAA", HAND_START, HAND_END, tmp_path, None)


def test_fetch_then_cache_then_no_second_call(tmp_path):
    rows = [_stock_row("20260918", "50500", "51000", "50500", "51000"),
            _stock_row("20260917", "50000", "50000", "50000", "50000"),
            _stock_row("20260801", "1", "1", "1", "1")]              # 요청 구간 밖 → 버림
    client = FakeClient(stock_rows=rows)
    df = data.load_daily("123456", HAND_START, HAND_END, tmp_path, client)
    assert client.call_count == 1 and df.attrs["from_cache"] is False
    assert list(df["close"]) == [50000, 51000]
    path = data.cache_path(tmp_path, "123456", HAND_START, HAND_END)
    text = path.read_text(encoding="utf-8").splitlines()
    assert text[0] == "date,open,high,low,close,volume,value" and text[1].startswith("2026-09-17,")
    again = data.load_daily("123456", HAND_START, HAND_END, tmp_path, ExplodingClient())
    assert list(again["close"]) == [50000, 51000] and again["close"].dtype == "int64"
    data.load_daily("123456", HAND_START, HAND_END, tmp_path, client, refresh=True)
    assert client.call_count == 2                                    # --refresh는 캐시를 무시


def test_empty_response_is_not_cached_and_broken_cache_is_a_miss(tmp_path):
    client = FakeClient()
    df = data.load_daily("123456", HAND_START, HAND_END, tmp_path, client)
    path = data.cache_path(tmp_path, "123456", HAND_START, HAND_END)
    assert len(df) == 0 and not path.exists()
    path.write_text("date,open\n", encoding="utf-8")
    assert data.read_cache(path, True) is None
    path.write_text("", encoding="utf-8")
    assert data.read_cache(path, True) is None


def test_index_is_fetched_in_chunks_and_merged(tmp_path):
    days = pd.bdate_range("2026-06-01", "2026-09-29")
    rows = [{"stck_bsop_date": d.strftime("%Y%m%d"), "bstp_nmix_oprc": "4000.0",
             "bstp_nmix_hgpr": "4010.0", "bstp_nmix_lwpr": "3990.0", "bstp_nmix_prpr": f"{4000 + i}.5",
             "acml_vol": "1", "acml_tr_pbmn": "1"} for i, d in enumerate(days)][::-1]
    client = FakeClient(index_rows=rows)
    df = data.load_index("0001", date(2026, 5, 31), date(2026, 9, 29), tmp_path, client)
    assert client.call_count == 3                        # 60일 단위 3조각
    assert len(df) == len(days) and df["date"].is_monotonic_increasing and df["date"].is_unique
    assert df.attrs["truncation"] is False
    assert data.cache_path(tmp_path, "IDX0001", date(2026, 5, 31), date(2026, 9, 29)).exists()


def test_truncation_suspect_when_row_limit_hit(tmp_path):
    days = pd.bdate_range("2026-01-01", periods=100)
    rows = [_stock_row(d.strftime("%Y%m%d"), "10", "10", "10", "10") for d in days]
    df = data.load_daily("123456", date(2026, 1, 1), date(2026, 5, 10), tmp_path, FakeClient(stock_rows=rows))
    assert df.attrs["truncation"] is True


def test_build_calendar_is_sorted_union():
    prices = hand_prices()
    prices["BBB"] = prices["BBB"].iloc[1:]
    cal = data.build_calendar(prices)
    assert cal[0] == date(2026, 9, 17) and cal[-1] == date(2026, 9, 29) and len(cal) == 7
    assert cal == sorted(cal) and date(2026, 9, 24) not in cal


def test_check_data_missing_excluded_and_anomaly():
    prices = hand_prices()
    prices["BBB"] = prices["BBB"][prices["BBB"]["date"] != pd.Timestamp("2026-09-22")]
    prices["CCC"] = prices["AAA"].iloc[0:0]
    prices["DDD"] = make_df([(date(2026, 9, 17), 100, 100, 5), (date(2026, 9, 18), 100, 140, 5)])
    cal = data.build_calendar(prices)
    issues = data.check_data(prices, cal)
    by = {(i["code"], i["stock"]): i for i in issues}
    assert ("DATA_MISSING", "AAA") not in by
    assert by[("DATA_MISSING", "BBB")]["value"] == 1 and by[("DATA_MISSING", "BBB")]["excluded"] is False
    assert by[("DATA_MISSING", "CCC")]["excluded"] is True and by[("DATA_MISSING", "CCC")]["value"] == 7
    anomaly = by[("PRICE_ANOMALY", "DDD")]
    assert anomaly["date"] == date(2026, 9, 18) and anomaly["value"] == pytest.approx(0.4)
    assert set(issues[0]) == {"code", "stock", "date", "value", "excluded", "side", "extra"}
