"""실 API 스모크 테스트(architecture.md 8.4절). `uv run pytest -m network`로만 실행된다(기본 실행 제외).

DEV(모의투자) 키로 시세 조회만 호출한다. 실패해도 PROD로 바꾸지 않는다(R3).
토큰은 실제 캐시 폴더(data/cache)에 저장해 재발급을 반복하지 않는다(분당 1회 제한).
분봉 테스트: `uv run pytest -m network -k minute`
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from stock_sim import config, data
from stock_sim.kis_client import KisClient

pytestmark = pytest.mark.network
ROOT = Path(__file__).resolve().parents[1]
SMOKE_DAY = date(2026, 9, 29)
FIELDS = ("stck_bsop_date", "stck_cntg_hour", "stck_oprc", "stck_hgpr", "stck_lwpr", "stck_prpr", "cntg_vol")


@pytest.fixture(scope="module")
def client():
    cfg = config.load_config(ROOT / "config.yaml")
    assert cfg["kis"]["env"] == "DEV"
    key, secret = config.load_credentials("DEV", cfg["paths"]["env_file"])
    return KisClient("DEV", key, secret, cfg["paths"]["cache_dir"], min_interval_sec=0.5)


def test_minute_first_page_dev(client):
    """1단계·2단계: 005930 하루 1페이지. rt_cd 0, output2 1행 이상, 필드 존재."""
    rows = client.minute_prices("005930", SMOKE_DAY, "160000")
    assert len(rows) >= 1, "DEV output2가 비었습니다(보고 후 사용자 결정, PROD 전환 금지)"
    for f in FIELDS:
        assert f in rows[0], f


def test_minute_full_day_label_and_daily_match(client):
    """4~7단계: 하루치 페이지네이션, 시각 라벨(090000 → start), 15:30 단일가 봉, 일봉 대조."""
    rows, truncated = data.fetch_minutes_day(client, "005930", SMOKE_DAY)
    assert not truncated
    hours = sorted(r["stck_cntg_hour"] for r in rows)
    assert hours[0] == "090000"                                   # 봉 시작 시각 라벨 → minute_time_label: start
    assert "153000" in hours                                      # 종가 단일가 봉
    df = data.normalize_minute_rows(rows, SMOKE_DAY, "start")
    daily = data.normalize_stock_rows(client.daily_prices("005930", SMOKE_DAY - timedelta(days=3), SMOKE_DAY))
    d = daily[daily["date"] == str(SMOKE_DAY)].iloc[0]
    assert int(df["open"].iloc[0]) == int(d["open"])
    assert int(df[df["time"] == "15:30"]["close"].iloc[0]) == int(d["close"])


def test_dev_daily_prices_samsung_recent_days(client):
    end = SMOKE_DAY
    rows = client.daily_prices("005930", end - timedelta(days=14), end)
    df = data.normalize_stock_rows(rows)
    assert len(df) >= 5 and list(df.columns) == data.COLUMNS
    assert df["date"].is_monotonic_increasing and df["date"].is_unique


def test_dev_index_daily_kospi(client):
    end = SMOKE_DAY
    start = end - timedelta(days=14)
    df = data.normalize_index_rows(client.index_daily("0001", start, end))
    inside = df[(df["date"] >= str(start)) & (df["date"] <= str(end))]
    assert len(inside) >= 5 and (inside["close"] > 0).all()
