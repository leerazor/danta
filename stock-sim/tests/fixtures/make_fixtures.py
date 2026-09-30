"""테스트 fixture 생성기(가짜 데이터). `uv run python tests/fixtures/make_fixtures.py`로 다시 만든다.

- bars5_AAA_20260921.csv : strategy.md 10.2절 5분봉 13개
- cache/min/<코드>_<YYYYMMDD>.csv : 가짜 1분봉(2종목 × 3일, 결측 분·통째 빈 슬롯·15:30·16:00 봉 포함)
- cache/<코드>_20260914_20260923.csv, cache/IDX0001_… : 같은 구간의 가짜 일봉
- minute_page_{1..4}.json : 가짜 KIS 분봉 응답 페이지(문자열 값, 내림차순, 마지막 페이지에 전 거래일 행 혼입)
실제 종목·가격이 아니다.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAYS = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
PRIOR = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
CODES = {"000001": 50_000, "000002": 200_000}
HAND = [  # 10.2절: 시각, 시가, 고가, 저가, 종가, 거래량
    ("09:00", 100000, 100400, 99800, 100200, 1000), ("09:05", 100200, 100300, 99900, 100000, 800),
    ("09:10", 100000, 100200, 99700, 99900, 600), ("09:15", 99900, 100300, 99800, 100100, 700),
    ("09:20", 100100, 100700, 100000, 100600, 1500), ("09:25", 100700, 101200, 100600, 101100, 1200),
    ("09:30", 101100, 101500, 101000, 101400, 900), ("09:35", 101400, 101600, 101200, 101300, 700),
    ("09:40", 101300, 101400, 100900, 101000, 800), ("09:45", 101000, 101100, 100500, 100600, 1100),
    ("09:50", 100500, 100700, 100300, 100400, 900), ("09:55", 100400, 100600, 100200, 100500, 600),
    ("10:00", 100500, 101300, 100500, 101200, 2000),
]


def tick(p: float, base: int) -> int:
    step = 50 if base < 100_000 else 500
    return int(round(p / step)) * step


def minute_rows(code: str, day_idx: int) -> list[dict]:
    """하루 1분봉. 파형: 완만한 추세 + 사인파. 상승 구간에 거래량을 키워 돌파가 생기게 한다."""
    base = CODES[code]
    phase = day_idx * 1.3 + (0.7 if code == "000002" else 0.0)
    rows, prev_close = [], None
    for i in range(380):                                   # 09:00 ~ 15:19
        m = 9 * 60 + i
        if i % 37 == 11:                                   # 흩어진 결측 분(슬롯 일부만 빔)
            continue
        if code == "000002" and day_idx == 1 and 180 <= i < 185:   # 12:00~12:04 통째로 없음 → 무효 슬롯
            continue
        x = i / 380
        mid = base * (1 + 0.012 * math.sin(2 * math.pi * (x * 2.2) + phase) + 0.004 * x * (1 if day_idx != 1 else -1))
        close = tick(mid, base)
        opn = prev_close if prev_close is not None else tick(base * (1 + 0.001 * day_idx), base)
        step = 50 if base < 100_000 else 500
        high, low = max(opn, close) + step, min(opn, close) - step
        rising = math.cos(2 * math.pi * (x * 2.2) + phase) > 0.3
        vol = 800 + (i * 37) % 400 + (2600 if rising else 0)
        rows.append({"time": f"{m // 60:02d}:{m % 60:02d}", "open": opn, "high": high, "low": low,
                     "close": close, "volume": vol})
        prev_close = close
    last = rows[-1]["close"]
    rows.append({"time": "15:30", "open": last, "high": last, "low": last, "close": last, "volume": 90_000})
    rows.append({"time": "16:00", "open": last, "high": last, "low": last, "close": last, "volume": 700})
    return rows


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)] + [",".join(str(v) for v in r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    write_csv(HERE / "bars5_AAA_20260921.csv", ["date", "time", "open", "high", "low", "close", "volume"],
              [["2026-09-21", *r] for r in HAND])
    daily_hdr = ["date", "open", "high", "low", "close", "volume", "value"]
    all_minutes: dict[tuple[str, date], list[dict]] = {}
    for code, base in CODES.items():
        drows = []
        for j, d in enumerate(PRIOR):
            c = tick(base * (1 - 0.002 * (len(PRIOR) - j)), base)
            drows.append([d.isoformat(), c, c, c, c, 1_000_000, c * 1_000_000])
        for k, d in enumerate(DAYS):
            rows = minute_rows(code, k)
            all_minutes[(code, d)] = rows
            write_csv(HERE / "cache" / "min" / f"{code}_{d:%Y%m%d}.csv",
                      ["date", "time", "open", "high", "low", "close", "volume"],
                      [[d.isoformat(), r["time"], r["open"], r["high"], r["low"], r["close"], r["volume"]]
                       for r in rows])
            o = rows[0]["open"]
            c = [r for r in rows if r["time"] == "15:30"][0]["close"]
            hi, lo = max(r["high"] for r in rows), min(r["low"] for r in rows)
            vol = sum(r["volume"] for r in rows)
            drows.append([d.isoformat(), o, hi, lo, c, vol, c * vol])
        write_csv(HERE / "cache" / f"{code}_20260914_20260923.csv", daily_hdr, drows)
    idx = []
    for j, d in enumerate(PRIOR + DAYS):
        o, c = 4000.0 + 5 * j, 4000.0 + 5 * j + 3
        idx.append([d.isoformat(), o, max(o, c), min(o, c), c, 500_000, 9_000_000])
    write_csv(HERE / "cache" / "IDX0001_20260914_20260923.csv", daily_hdr, idx)

    # 가짜 KIS 분봉 응답 페이지: 000001, 2026-09-22 (요청 시각 160000부터)
    def kis(d: date, r: dict) -> dict:
        return {"stck_bsop_date": f"{d:%Y%m%d}", "stck_cntg_hour": r["time"].replace(":", "") + "00",
                "stck_oprc": str(r["open"]), "stck_hgpr": str(r["high"]), "stck_lwpr": str(r["low"]),
                "stck_prpr": str(r["close"]), "cntg_vol": str(r["volume"]), "acml_tr_pbmn": "0"}
    day = [kis(DAYS[1], r) for r in reversed(all_minutes[("000001", DAYS[1])])]
    prev = [kis(DAYS[0], r) for r in reversed(all_minutes[("000001", DAYS[0])])]
    pages = [day[0:120], day[120:240], day[240:360]]
    rest = day[360:]
    pages.append(rest + prev[: max(0, 120 - len(rest))])   # 장 초반 요청: 전 거래일 행이 섞여 온다
    for i, page in enumerate(pages, start=1):
        (HERE / f"minute_page_{i}.json").write_text(json.dumps(page, ensure_ascii=False, indent=0),
                                                     encoding="utf-8")


if __name__ == "__main__":
    main()
