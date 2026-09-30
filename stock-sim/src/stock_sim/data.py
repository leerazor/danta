"""캐시 I/O, 응답 정규화, 구간 분할, 데이터 검사 (architecture.md 1.3절, 4.1절, 6.1절).

네트워크는 직접 쓰지 않고 넘겨받은 KisClient만 호출한다. 캐시가 있으면 호출하지 않는다.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stock_sim.kis_client import KisClient, KisUnsupportedError, unsupported_message

log = logging.getLogger(__name__)

COLUMNS = ["date", "open", "high", "low", "close", "volume", "value"]
PRICE_COLS = ["open", "high", "low", "close"]
STOCK_FIELDS = {"date": "stck_bsop_date", "open": "stck_oprc", "high": "stck_hgpr",
                "low": "stck_lwpr", "close": "stck_clpr", "volume": "acml_vol",
                "value": "acml_tr_pbmn"}
INDEX_FIELDS = {"date": "stck_bsop_date", "open": "bstp_nmix_oprc", "high": "bstp_nmix_hgpr",
                "low": "bstp_nmix_lwpr", "close": "bstp_nmix_prpr", "volume": "acml_vol",
                "value": "acml_tr_pbmn"}
STOCK_MAX_DAYS, STOCK_ROW_LIMIT = 130, 100
INDEX_MAX_DAYS, INDEX_ROW_LIMIT = 60, 50
ANOMALY_LIMIT = 0.30


class DataError(Exception):
    """데이터 오류(유효 종목 0개, 지수 없음, 워밍업 부족). 종료 코드 3."""


def make_issue(code: str, stock: str | None = None, day: date | None = None, value=None,
               excluded: bool = False, side: str | None = None, extra: dict | None = None) -> dict:
    """architecture.md 4.4절 공통 모양."""
    return {"code": code, "stock": stock, "date": day, "value": value,
            "excluded": excluded, "side": side, "extra": extra or {}}


def cache_path(cache_dir: Path, code: str, start: date, end: date) -> Path:
    return Path(cache_dir) / f"{code}_{start:%Y%m%d}_{end:%Y%m%d}.csv"


def index_cache_code(index_code: str) -> str:
    return f"IDX{index_code}"


def split_ranges(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    """[start, end]를 달력일 max_days 이하의 겹치지 않는 조각으로 나눈다."""
    if max_days < 1:
        raise ValueError("max_days는 1 이상이어야 합니다.")
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=max_days - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def _normalize(rows: list[dict], fields: dict[str, str], integer_prices: bool) -> pd.DataFrame:
    recs = [{col: r.get(src) for col, src in fields.items()} for r in rows if isinstance(r, dict)]
    df = pd.DataFrame(recs, columns=COLUMNS)
    df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    for col in COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    df = df.reset_index(drop=True)
    non_integer = False
    if integer_prices:
        for col in PRICE_COLS:
            vals = df[col].fillna(0.0).astype("float64")
            if len(vals) and bool(((vals % 1) != 0).any()):
                non_integer = True
            df[col] = ((vals + 0.5) // 1).astype("int64")  # half-up(floor(x + 0.5)), 원 단위
    else:
        for col in PRICE_COLS:
            df[col] = df[col].astype("float64")
    for col in ("volume", "value"):
        df[col] = ((df[col].fillna(0.0).astype("float64") + 0.5) // 1).astype("int64")
    df.attrs["non_integer_price"] = non_integer
    return df


def normalize_stock_rows(rows: list[dict]) -> pd.DataFrame:
    return _normalize(rows, STOCK_FIELDS, integer_prices=True)


def normalize_index_rows(rows: list[dict]) -> pd.DataFrame:
    return _normalize(rows, INDEX_FIELDS, integer_prices=False)


def read_cache(path: Path, integer_prices: bool) -> pd.DataFrame | None:
    """적중이면 DataFrame, 없거나 깨졌거나 비었으면 None."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8")
        if any(c not in df.columns for c in COLUMNS) or len(df) == 0:
            return None
        df = df[COLUMNS].copy()
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
        ptype = "int64" if integer_prices else "float64"
        for col in PRICE_COLS:
            df[col] = df[col].astype(ptype)
        for col in ("volume", "value"):
            df[col] = df[col].astype("int64")
    except (ValueError, TypeError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    return df.sort_values("date").reset_index(drop=True)


def _write_cache(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8", date_format="%Y-%m-%d")


def issues_path(path: Path) -> Path:
    """캐시 CSV 옆의 보조 파일(`<캐시명>.issues.json`). 수집 때 발견한 데이터 이슈를 남긴다."""
    path = Path(path)
    return path.with_name(f"{path.stem}.issues.json")


def _write_issues(path: Path, non_integer: bool) -> None:
    """비정수 가격이 있었으면 보조 파일을 쓰고, 없으면 예전 보조 파일을 지운다."""
    side = issues_path(path)
    if non_integer:
        side.write_text(json.dumps({"non_integer_price": True}, ensure_ascii=False),
                        encoding="utf-8")
    elif side.exists():
        side.unlink()


def _read_issues(path: Path) -> dict:
    side = issues_path(path)
    if not side.is_file():
        return {}
    try:
        loaded = json.loads(side.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        log.warning("이슈 보조 파일을 읽지 못했습니다: %s", side.name)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load(kind: str, code: str, start: date, end: date, cache_dir: Path,
          client: KisClient | None, refresh: bool) -> pd.DataFrame:
    is_stock = kind == "stock"
    path = cache_path(cache_dir, code if is_stock else index_cache_code(code), start, end)
    if not refresh:
        cached = read_cache(path, integer_prices=is_stock)
        if cached is not None:
            log.info("캐시 적중: %s (%d행)", path.name, len(cached))
            saved = _read_issues(path)
            cached.attrs.update(from_cache=True, truncation=False,
                                non_integer_price=bool(saved.get("non_integer_price", False)))
            return cached
    if client is None:
        raise FileNotFoundError(f"캐시 파일이 없고 클라이언트도 없습니다: {path.name}")
    max_days, limit = (STOCK_MAX_DAYS, STOCK_ROW_LIMIT) if is_stock else (INDEX_MAX_DAYS, INDEX_ROW_LIMIT)
    parts, truncation, non_integer = [], False, False
    for a, b in split_ranges(start, end, max_days):
        rows = client.daily_prices(code, a, b) if is_stock else client.index_daily(code, a, b)
        part = normalize_stock_rows(rows) if is_stock else normalize_index_rows(rows)
        non_integer = non_integer or bool(part.attrs.get("non_integer_price"))
        if len(rows) >= limit:
            truncation = True
            log.warning("잘림 의심: %s %s~%s 응답 %d건(상한 %d건)", code, a, b, len(rows), limit)
        parts.append(part)
    df = pd.concat(parts, ignore_index=True) if parts else normalize_stock_rows([])
    df = df.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    df = df[(df["date"] >= lo) & (df["date"] <= hi)].reset_index(drop=True)
    if len(df) > 0 and truncation:
        # 잘렸을 수 있는 데이터는 캐시하지 않는다: 다음 실행에서 다시 받고 다시 경고한다.
        log.warning("잘림 의심 데이터라 캐시에 저장하지 않습니다: %s", path.name)
        for stale in (path, issues_path(path)):       # --refresh 전의 같은 이름 캐시도 남기지 않는다
            if stale.exists():
                stale.unlink()
    elif len(df) > 0:
        _write_cache(df, path)
        _write_issues(path, non_integer)
        log.info("캐시 저장: %s (%d행)", path.name, len(df))
    df.attrs.update(from_cache=False, non_integer_price=non_integer, truncation=truncation)
    return df


def load_daily(code: str, start: date, end: date, cache_dir: Path,
               client: KisClient | None, refresh: bool = False) -> pd.DataFrame:
    return _load("stock", code, start, end, cache_dir, client, refresh)


def load_index(index_code: str, start: date, end: date, cache_dir: Path,
               client: KisClient | None, refresh: bool = False) -> pd.DataFrame:
    return _load("index", index_code, start, end, cache_dir, client, refresh)


def build_calendar(prices: dict[str, pd.DataFrame]) -> list[date]:
    """종목 날짜의 합집합, 오름차순(워밍업 포함)."""
    days: set[date] = set()
    for df in prices.values():
        if df is not None and len(df):
            days.update(ts.date() for ts in pd.to_datetime(df["date"]))
    return sorted(days)


def check_data(prices: dict[str, pd.DataFrame], calendar: list[date]) -> list[dict]:
    """DATA_MISSING(0건이면 excluded), PRICE_ANOMALY(전일 종가 대비 ±30% 초과)."""
    issues: list[dict] = []
    for code, df in prices.items():
        if df is None or len(df) == 0:
            issues.append(make_issue("DATA_MISSING", code, value=len(calendar), excluded=True))
            continue
        days = [ts.date() for ts in pd.to_datetime(df["date"])]
        missing = len(set(calendar) - set(days))
        if missing > 0:
            issues.append(make_issue("DATA_MISSING", code, value=missing))
        prev = None
        for d, close in zip(days, df["close"]):
            close = int(close)
            if prev and close > 0:
                change = close / prev - 1.0
                if abs(change) > ANOMALY_LIMIT:
                    issues.append(make_issue("PRICE_ANOMALY", code, day=d, value=change))
            if close > 0:
                prev = close
    return issues


def load_all(cfg: dict, period: dict, client: KisClient | None, refresh: bool = False
             ) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[dict], dict]:
    """(prices{code: df}(제외 종목 빠짐), benchmark_df, data_issues, source_info)."""
    start, end = period["fetch_start"], period["end"]
    cache_dir = cfg["paths"]["cache_dir"]
    env = cfg["kis"]["env"]
    loaded: dict[str, pd.DataFrame] = {}
    extra: list[dict] = []
    hits = 0
    for item in cfg["universe"]:
        code = item["code"]
        df = load_daily(code, start, end, cache_dir, client, refresh)
        hits += 1 if df.attrs.get("from_cache") else 0
        if df.attrs.get("non_integer_price"):
            extra.append(make_issue("NON_INTEGER_PRICE", code))
        if df.attrs.get("truncation"):
            extra.append(make_issue("TRUNCATION_SUSPECT", code))
        loaded[code] = df
    prices = {c: df for c, df in loaded.items() if len(df) > 0}
    if not prices:
        if client is not None:
            raise KisUnsupportedError(unsupported_message(
                env, "국내주식 기간별시세(일봉)", None, "전 종목 조회 결과 0건"))
        raise DataError("유효 종목이 0개입니다(전 종목 데이터 없음).")
    excluded = [c for c in loaded if c not in prices]
    if excluded:
        log.warning("조회 결과 0건으로 제외한 종목: %s", ", ".join(excluded))
    bench_code = cfg["benchmark"]["code"]
    bench = load_index(bench_code, start, end, cache_dir, client, refresh)
    hits += 1 if bench.attrs.get("from_cache") else 0
    if len(bench) == 0:
        if client is not None:
            raise KisUnsupportedError(unsupported_message(
                env, "업종 기간별시세(지수 일봉)", None, "조회 결과 0건"))
        raise DataError("벤치마크 지수 데이터가 없습니다.")
    if bench.attrs.get("truncation"):
        extra.append(make_issue("TRUNCATION_SUSPECT", index_cache_code(bench_code)))
    calendar = build_calendar(prices)
    issues = check_data(loaded, calendar) + extra
    source = {"api_calls": client.call_count if client is not None else 0, "cache_hits": hits}
    return prices, bench, issues, source
