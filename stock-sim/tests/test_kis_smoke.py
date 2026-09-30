"""실 API 스모크 테스트. `uv run pytest -m network`로만 실행된다(기본 실행에서 제외).

DEV(모의투자) 키로 시세 조회 2종만 호출한다. 실패해도 PROD로 바꾸지 않는다(R3).
토큰은 실제 캐시 폴더(data/cache)에 저장해 재발급을 반복하지 않는다.
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from stock_sim import config, data
from stock_sim.kis_client import KisClient

pytestmark = pytest.mark.network
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    cfg = config.load_config(ROOT / "config.yaml")
    assert cfg["kis"]["env"] == "DEV"
    key, secret = config.load_credentials("DEV", cfg["paths"]["env_file"])
    return KisClient("DEV", key, secret, cfg["paths"]["cache_dir"], min_interval_sec=1.0)


def test_dev_daily_prices_samsung_recent_days(client):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=14)
    rows = client.daily_prices("005930", start, end)
    df = data.normalize_stock_rows(rows)
    assert len(df) >= 5, f"최근 5영업일 미만: {len(df)}건"
    assert list(df.columns) == data.COLUMNS
    assert df["date"].is_monotonic_increasing and df["date"].is_unique
    tail = df.tail(5)
    assert (tail["open"] > 0).all() and (tail["close"] > 0).all() and (tail["volume"] > 0).all()
    assert df.attrs["non_integer_price"] is False


def test_dev_index_daily_kospi(client):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=14)
    rows = client.index_daily("0001", start, end)
    df = data.normalize_index_rows(rows)
    lo, hi = str(start), str(end)
    inside = df[(df["date"] >= lo) & (df["date"] <= hi)]
    assert len(inside) >= 5, f"구간 내 지수 일봉이 5건 미만: {len(inside)}건(응답 {len(rows)}건)"
    assert inside["date"].is_monotonic_increasing
    assert (inside["close"] > 0).all()
