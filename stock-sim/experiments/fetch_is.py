"""IS용 12개월 일봉 수집(캐시). stock_sim.data 로더만 쓴다. 환경은 config.yaml의 kis.env 그대로.

예상 호출 수: 종목 10 × 3조각(130일) + 지수 1 × 7조각(60일) = 37회 (+ 토큰 캐시 만료 시 발급 1회).
이미 캐시가 있으면 호출 0회. 실패하면 우회하지 않고 메시지만 남기고 끝난다.
실행: uv run python experiments/fetch_is.py
"""
from __future__ import annotations

import logging

import common
from stock_sim import data
from stock_sim.cli import _make_client
from stock_sim.kis_client import KisError


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    cfg = common.load_cfg()
    cache = cfg["paths"]["cache_dir"]
    codes = [(u["code"], True) for u in cfg["universe"]]
    codes.append((cfg["benchmark"]["code"], False))
    missing = []
    for code, is_stock in codes:
        name = code if is_stock else data.index_cache_code(code)
        if data.read_cache(data.cache_path(cache, name, common.EXT_START, common.EXT_END), is_stock) is None:
            missing.append((code, is_stock))
    if not missing:
        print("모두 캐시에 있음. API 호출 0회.")
        return 0
    print(f"env={cfg['kis']['env']}, 수집 대상 {len(missing)}건, 구간 {common.EXT_START}~{common.EXT_END}")
    client = _make_client(cfg)
    try:
        for code, is_stock in missing:
            loader = data.load_daily if is_stock else data.load_index
            df = loader(code, common.EXT_START, common.EXT_END, cache, client)
            print(f"{code}: {len(df)}행 {df['date'].min().date()}~{df['date'].max().date()} "
                  f"truncation={df.attrs.get('truncation')} non_integer={df.attrs.get('non_integer_price')}")
    except KisError as exc:
        print(f"수집 실패(우회하지 않음): {exc}")
        print(f"API 호출 수: {client.call_count}")
        return 3
    print(f"API 호출 수: {client.call_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
