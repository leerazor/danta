"""data.py: 분봉 정규화·페이지네이션·캐시 규칙(architecture.md 1.3절, 4.2절, 6.2절). 네트워크 없음."""
import copy
import json
import shutil
from datetime import date

import pandas as pd
import pytest

from helpers import FIX_CACHE, FIXTURES
from stock_sim import config, data
from stock_sim.kis_client import KisUnsupportedError

DAY = date(2026, 9, 22)
PREV = date(2026, 9, 21)


def _row(d, h, o=100, hi=101, lo=99, c=100, v=10):
    return {"stck_bsop_date": d, "stck_cntg_hour": h, "stck_oprc": str(o), "stck_hgpr": str(hi),
            "stck_lwpr": str(lo), "stck_prpr": str(c), "cntg_vol": str(v), "acml_tr_pbmn": "0"}


def _pages():
    return [json.loads((FIXTURES / f"minute_page_{i}.json").read_text(encoding="utf-8")) for i in range(1, 5)]


class PageClient:
    """가짜 KIS 클라이언트: 요청 시각 이하 행을 내림차순 120건씩 준다(전 거래일 행으로 채움)."""

    env = "DEV"

    def __init__(self, rows_by_day: dict[str, list[dict]] | None = None, pages: list | None = None):
        self.rows_by_day = rows_by_day or {}
        self.pages = list(pages or [])
        self.calls: list[tuple[str, date, str]] = []
        self.call_count = 0

    def minute_prices(self, code, day, hour):
        self.calls.append((code, day, hour))
        self.call_count += 1
        if self.pages:
            return self.pages.pop(0)
        want = f"{day:%Y%m%d}"
        rows = [r for r in self.rows_by_day.get(want, []) if r["stck_cntg_hour"] <= hour]
        rows.sort(key=lambda r: r["stck_cntg_hour"], reverse=True)
        out = rows[:120]
        for d in sorted((k for k in self.rows_by_day if k < want), reverse=True):
            if len(out) >= 120:
                break
            out += sorted(self.rows_by_day[d], key=lambda r: r["stck_cntg_hour"], reverse=True)[:120 - len(out)]
        return out


class ExplodingClient:
    env = "DEV"
    call_count = 0

    def minute_prices(self, *a, **k):
        raise AssertionError("캐시 적중인데 API를 호출했습니다")

    daily_prices = index_daily = minute_prices


# ---- normalize_minute_rows / next_page_hour ------------------------------------------
def test_normalize_filters_other_days_sorts_dedups_and_casts():
    rows = [_row("20260922", "090200", c=103), _row("20260921", "153000", c=1),
            _row("20260922", "090000", c=101), _row("20260922", "090000", c=102),
            _row("20260922", "0901", c=9), _row("20260922", "090100", o="100.5", c=104)]
    df = data.normalize_minute_rows(rows, DAY)
    assert list(df.columns) == data.MINUTE_COLUMNS
    assert list(df["time"]) == ["09:00", "09:01", "09:02"]
    assert list(df["close"]) == [102, 104, 103]                 # 같은 키는 마지막 것
    assert df["open"].iloc[1] == 101 and df.attrs["non_integer_price"] is True   # 100.5 → 101 (half-up)
    assert str(df["date"].dtype).startswith("datetime64") and (df["date"] == pd.Timestamp(DAY)).all()
    assert df["volume"].dtype == "int64"


def test_normalize_end_label_shifts_one_minute_and_empty():
    df = data.normalize_minute_rows([_row("20260922", "090100"), _row("20260922", "153000")], DAY, "end")
    assert list(df["time"]) == ["09:00", "15:29"]
    empty = data.normalize_minute_rows([_row("20260921", "090000")], DAY)
    assert len(empty) == 0 and list(empty.columns) == data.MINUTE_COLUMNS


def test_next_page_hour():
    rows = [_row("20260922", "131900"), _row("20260922", "140000"), _row("20260921", "100000")]
    assert data.next_page_hour(rows, DAY) == "131800"
    assert data.next_page_hour([_row("20260922", "090000")], DAY) == "085900"
    assert data.next_page_hour([_row("20260921", "100000")], DAY) is None
    assert data.next_page_hour([], DAY) is None


# ---- fetch_minutes_day -------------------------------------------------------------
def test_fetch_with_fixture_pages_stops_at_0900_and_drops_previous_day():
    client = PageClient(pages=_pages())
    rows, truncated = data.fetch_minutes_day(client, "000001", DAY)
    assert truncated is False
    assert [c[2] for c in client.calls] == ["160000", "131800", "111500", "091200"]
    assert {r["stck_bsop_date"] for r in rows} == {"20260922"}
    expected = pd.read_csv(FIX_CACHE / "min" / "000001_20260922.csv", encoding="utf-8")
    assert len(rows) == len(expected)
    df = data.normalize_minute_rows(rows, DAY)
    assert list(df["time"]) == list(expected["time"])


def _day_rows(n_minutes: int, d="20260922", start=9 * 60):
    return [_row(d, f"{(start + i) // 60:02d}{(start + i) % 60:02d}00") for i in range(n_minutes)]


def test_fetch_stop_conditions():
    # ③ 응답 < 120건
    c = PageClient({"20260922": _day_rows(50, start=10 * 60)})
    rows, tr = data.fetch_minutes_day(c, "X", DAY)
    assert (len(rows), tr, len(c.calls)) == (50, False, 1)
    # ① 요청일 행 0건(휴장일): 전 거래일 행만 온다
    c = PageClient({"20260921": _day_rows(200, d="20260921")})
    rows, tr = data.fetch_minutes_day(c, "X", DAY)
    assert (rows, tr, len(c.calls)) == ([], False, 1)
    # ④ 새 행 없음: 같은 페이지가 반복된다
    page = _day_rows(120, start=10 * 60)
    c = PageClient(pages=[page, page, page])
    rows, tr = data.fetch_minutes_day(c, "X", DAY)
    assert (len(rows), tr, len(c.calls)) == (120, False, 2)
    # ② 가장 이른 시각 ≤ 090000 (행 120건이어도 종료)
    c = PageClient(pages=[_day_rows(120, start=9 * 60)])
    rows, tr = data.fetch_minutes_day(c, "X", DAY)
    assert (len(rows), tr, len(c.calls)) == (120, False, 1)


def test_fetch_truncated_at_max_pages():
    c = PageClient({"20260922": _day_rows(400, start=9 * 60)})
    rows, tr = data.fetch_minutes_day(c, "X", DAY, start_hour="160000", max_pages=2)
    assert tr is True and len(c.calls) == 2 and len(rows) == 240


# ---- load_minutes / 캐시 -------------------------------------------------------------
def test_cache_hit_does_not_call_client(tmp_path):
    shutil.copytree(FIX_CACHE, tmp_path / "cache")
    df, issues, st = data.load_minutes("000001", [PREV, DAY], tmp_path / "cache", ExplodingClient())
    assert st["cache_hits"] == 2 and st["api_calls"] == 0 and issues == []
    assert df["date"].nunique() == 2 and df["time"].iloc[0] == "09:00"


def test_fetch_writes_cache_and_empty_marker(tmp_path):
    rows = {"20260922": _day_rows(60, start=14 * 60)}
    c = PageClient(rows)
    df, issues, st = data.load_minutes("000009", [PREV, DAY], tmp_path, c)
    assert st["fetched_days"] == 2 and st["empty_days"] == [PREV] and len(df) == 60
    marker = data.minute_cache_path(tmp_path, "000009", PREV)
    assert marker.read_text(encoding="utf-8").strip() == ",".join(data.MINUTE_COLUMNS)   # 헤더만
    cached = data.read_minute_cache(marker)
    assert cached is not None and len(cached) == 0                                      # 0행도 적중
    df2, _, st2 = data.load_minutes("000009", [PREV, DAY], tmp_path, ExplodingClient())
    assert st2["cache_hits"] == 2 and len(df2) == 60


def test_all_empty_responses_raise_and_write_no_marker(tmp_path):
    c = PageClient({})
    with pytest.raises(KisUnsupportedError) as exc:
        data.load_minutes("000009", [PREV, DAY], tmp_path, c)
    assert "자동으로 PROD로 전환하지 않습니다" in str(exc.value)
    assert not (tmp_path / "min").exists() or not list((tmp_path / "min").glob("*.csv"))


def test_truncated_day_is_not_cached(tmp_path):
    c = PageClient({"20260922": _day_rows(400, start=9 * 60)})
    df, issues, st = data.load_minutes("000009", [DAY], tmp_path, c, max_pages=2)
    assert [i["code"] for i in issues] == ["TRUNCATION_SUSPECT"]
    assert len(df) == 240 and not data.minute_cache_path(tmp_path, "000009", DAY).exists()


def test_minute_files_are_never_deleted(tmp_path):
    shutil.copytree(FIX_CACHE, tmp_path / "cache")
    before = sorted(p.name for p in (tmp_path / "cache" / "min").iterdir())
    broken = tmp_path / "cache" / "min" / "000001_20260923.csv"
    broken.write_text("garbage\n", encoding="utf-8")                         # 깨진 파일은 미적중 → 다시 받는다
    rows = {"20260923": _day_rows(100, d="20260923", start=13 * 60)}
    data.load_minutes("000001", [PREV, DAY, date(2026, 9, 23)], tmp_path / "cache", PageClient(rows))
    after = sorted(p.name for p in (tmp_path / "cache" / "min").iterdir())
    assert before == after


def test_no_client_and_no_cache_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        data.load_minutes("000001", [DAY], tmp_path, None)


# ---- load_all / trading_days -------------------------------------------------------------
def _fixture_cfg(tmp_path):
    shutil.copytree(FIX_CACHE, tmp_path / "cache")
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["universe"] = [{"code": "000001", "name": "가상전자"}, {"code": "000002", "name": "가상화학"}]
    cfg["backtest"] = {"end": "2026-09-23", "days": 3, "initial_cash": 100_000_000}
    cfg["paths"] = {"cache_dir": tmp_path / "cache"}
    return cfg


def test_load_all_from_fixture_cache_offline(tmp_path):
    cfg = _fixture_cfg(tmp_path)
    period = config.resolve_period(cfg, date(2026, 9, 24))
    assert period == {"start": date(2026, 9, 21), "end": date(2026, 9, 23),
                      "daily_fetch_start": date(2026, 9, 14)}
    minutes, daily, bench, issues, source = data.load_all(cfg, period, None)
    assert sorted(minutes) == ["000001", "000002"] and issues == []
    assert source["minute_files"] == 6 and source["api_calls"] == 0 and source["empty_days"] == []
    assert source["cache_hits"] == 3 + 6
    assert data.trading_days(daily, period["start"], period["end"]) == \
        [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    assert len(bench) == 8


def test_load_all_excludes_code_without_minutes(tmp_path):
    cfg = _fixture_cfg(tmp_path)
    for f in (tmp_path / "cache" / "min").glob("000002_*.csv"):
        f.write_text(",".join(data.MINUTE_COLUMNS) + "\n", encoding="utf-8")
    period = config.resolve_period(cfg, date(2026, 9, 24))
    minutes, _, _, issues, source = data.load_all(cfg, period, None)
    assert list(minutes) == ["000001"]
    assert [(i["code"], i["stock"], i["excluded"]) for i in issues] == [("DATA_MISSING", "000002", True)]
    assert len(source["empty_days"]) == 3
