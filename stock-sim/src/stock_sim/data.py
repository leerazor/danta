"""캐시 I/O, 응답 정규화, 구간 분할, 분봉 페이지네이션 (architecture.md 1.3절, 4.1·4.2절, 6절).

네트워크는 직접 쓰지 않고 넘겨받은 KisClient만 호출한다. 캐시가 있으면 호출하지 않는다.
분봉 캐시 CSV는 지우지 않는다(서버 보존이 약 250거래일 롤링이라 다시 받지 못할 수 있다).
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


class DataError(Exception):
    """데이터 오류(유효 종목 0개, 거래일 0일, 지수 없음). 종료 코드 3."""


def make_issue(code: str, stock: str | None = None, day: date | None = None, value=None,
               excluded: bool = False, side: str | None = None, extra: dict | None = None) -> dict:
    """architecture.md 4.8절 공통 모양."""
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


# ---- 분봉 (v2) ------------------------------------------------------------------
MINUTE_COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]
MINUTE_FIELDS = {"date": "stck_bsop_date", "hour": "stck_cntg_hour", "open": "stck_oprc",
                 "high": "stck_hgpr", "low": "stck_lwpr", "close": "stck_prpr", "volume": "cntg_vol"}
MINUTE_PAGE_LIMIT = 120
FIRST_BAR_WARN, LAST_BAR_WARN = "09:10", "15:00"


def minute_cache_path(cache_dir: Path, code: str, day: date) -> Path:
    """<cache_dir>/min/<code>_<YYYYMMDD>.csv"""
    return Path(cache_dir) / "min" / f"{code}_{day:%Y%m%d}.csv"


def _empty_minutes() -> pd.DataFrame:
    df = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "time": pd.Series(dtype="object"),
                       **{c: pd.Series(dtype="int64") for c in MINUTE_COLUMNS[2:]}})
    df.attrs["non_integer_price"] = False
    return df


def normalize_minute_rows(rows: list[dict], day: date, time_label: str = "start") -> pd.DataFrame:
    """KIS 분봉 원본 행 → 4.2절 DataFrame. 순수 함수.

    요청일 외 일자 행은 버리고, time_label == "end"면 1분을 빼 봉 시작 시각으로 맞춘다.
    (date, time) 오름차순, 같은 키는 마지막 것. 정수가 아닌 가격은 half-up + attrs 표시.
    체결 없는 분은 채우지 않는다(forward-fill 금지).
    """
    if time_label not in ("start", "end"):
        raise ValueError(f"time_label은 start 또는 end여야 합니다: {time_label!r}")
    want = f"{day:%Y%m%d}"
    recs = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = str(r.get(MINUTE_FIELDS["date"]) or "").strip()
        h = str(r.get(MINUTE_FIELDS["hour"]) or "").strip()
        if d != want or len(h) != 6 or not h.isdigit():
            continue
        minute = int(h[:2]) * 60 + int(h[2:4]) - (1 if time_label == "end" else 0)
        if not 0 <= minute < 24 * 60:
            continue
        recs.append({"date": d, "time": f"{minute // 60:02d}:{minute % 60:02d}",
                     **{c: r.get(MINUTE_FIELDS[c]) for c in MINUTE_COLUMNS[2:]}})
    if not recs:
        return _empty_minutes()
    df = pd.DataFrame(recs, columns=MINUTE_COLUMNS)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    for col in MINUTE_COLUMNS[2:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["date", "time"], kind="stable").drop_duplicates(["date", "time"], keep="last")
    non_integer = False
    for col in PRICE_COLS:
        vals = df[col].fillna(0.0).astype("float64")
        if len(vals) and bool(((vals % 1) != 0).any()):
            non_integer = True
        df[col] = ((vals + 0.5) // 1).astype("int64")      # half-up, 원 단위
    df["volume"] = ((df["volume"].fillna(0.0).astype("float64") + 0.5) // 1).astype("int64")
    df = df.reset_index(drop=True)
    df.attrs["non_integer_price"] = non_integer
    return df


def next_page_hour(rows: list[dict], day: date) -> str | None:
    """day 일자 행 중 가장 이른 stck_cntg_hour − 1분을 'HHMMSS'로. day 행이 없으면 None."""
    want = f"{day:%Y%m%d}"
    hours = [str(r.get("stck_cntg_hour") or "").strip() for r in rows or []
             if isinstance(r, dict) and str(r.get("stck_bsop_date") or "").strip() == want]
    hours = [h for h in hours if len(h) == 6 and h.isdigit()]
    if not hours:
        return None
    first = min(hours)
    minute = int(first[:2]) * 60 + int(first[2:4]) - 1
    if minute < 0:
        return None
    return f"{minute // 60:02d}{minute % 60:02d}00"


def fetch_minutes_day(client: KisClient, code: str, day: date, start_hour: str = "160000",
                      max_pages: int = 6) -> tuple[list[dict], bool]:
    """하루치 분봉 원본 행을 페이지 반복으로 모은다. (요청일 행만 합친 목록, truncated).

    종료: ① 이번 페이지의 요청일 행 0건 ② 가장 이른 시각 ≤ 090000 ③ 응답 행 수 < 120
    ④ 새로 추가된 (date, time) 없음. 상한(max_pages)에 닿으면 truncated = True.
    """
    want = f"{day:%Y%m%d}"
    hour, seen, kept = start_hour, set(), []
    for page in range(1, max_pages + 1):
        rows = client.minute_prices(code, day, hour)
        mine = [r for r in rows if isinstance(r, dict)
                and str(r.get("stck_bsop_date") or "").strip() == want]
        new = [r for r in mine if str(r.get("stck_cntg_hour")) not in seen]
        seen.update(str(r.get("stck_cntg_hour")) for r in new)
        kept.extend(new)
        log.debug("분봉 %s %s 페이지 %d: 응답 %d건, 요청일 %d건, 신규 %d건",
                  code, day, page, len(rows), len(mine), len(new))
        nxt = next_page_hour(mine, day)
        if not mine or not new or nxt is None:
            return kept, False
        earliest = min(str(r.get("stck_cntg_hour")) for r in mine)
        if earliest <= "090000" or len(rows) < MINUTE_PAGE_LIMIT:
            return kept, False
        hour = nxt
    log.warning("분봉 페이지 상한(%d) 도달: %s %s", max_pages, code, day)
    return kept, True


def read_minute_cache(path: Path) -> pd.DataFrame | None:
    """적중이면 DataFrame(0행 표식 포함), 없거나 깨졌으면 None."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8", dtype={"time": str})
        if any(c not in df.columns for c in MINUTE_COLUMNS):
            return None
        if len(df) == 0:
            return _empty_minutes()
        df = df[MINUTE_COLUMNS].copy()
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
        for col in MINUTE_COLUMNS[2:]:
            df[col] = df[col].astype("int64")
        df["time"] = df["time"].astype(str)
    except (ValueError, TypeError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    df = df.sort_values(["date", "time"], kind="stable").reset_index(drop=True)
    df.attrs["non_integer_price"] = False
    return df


def _log_saved(code: str, day: date, df: pd.DataFrame) -> None:
    """완결성 로그(6.2절): 첫·마지막 봉 시각과 행 수. 범위가 좁으면 WARNING."""
    if len(df) == 0:
        log.info("분봉 저장: %s %s (0행, 무데이터 표식)", code, day)
        return
    first, last = str(df["time"].iloc[0]), str(df["time"].iloc[-1])
    log.info("분봉 저장: %s %s %d행 (%s ~ %s)", code, day, len(df), first, last)
    if first > FIRST_BAR_WARN or last < LAST_BAR_WARN:
        log.warning("분봉 시간 범위가 좁습니다: %s %s 첫 봉 %s, 마지막 봉 %s", code, day, first, last)


def write_empty_markers(cache_dir: Path, pending: list[tuple[str, date]], fetched_days: int,
                        fetched_rows: int, env: str) -> None:
    """무데이터 표식(헤더만 있는 CSV)을 쓴다.

    이번 실행에서 받은 분봉 행 합계가 0이면(전 종목·전 일자 빈 응답) 표식을 쓰지 않고
    KisUnsupportedError를 낸다(DEV 미지원을 '무데이터'로 굳히지 않는다, 6.2절).
    """
    if fetched_days > 0 and fetched_rows == 0:
        raise KisUnsupportedError(unsupported_message(
            env, "주식일별분봉조회", None, "전 종목·전 일자 분봉 응답이 비었습니다"))
    for code, day in pending:
        _write_cache(_empty_minutes(), minute_cache_path(cache_dir, code, day))
        _log_saved(code, day, _empty_minutes())


def load_minutes(code: str, days: list[date], cache_dir: Path, client: KisClient | None,
                 time_label: str = "start", start_hour: str = "160000", max_pages: int = 6,
                 defer_empty: bool = False) -> tuple[pd.DataFrame, list[dict], dict]:
    """(여러 날 1분봉, data_issues, stats). 캐시 우선, 없으면 받아서 저장한다.

    stats = {"api_calls", "cache_hits", "empty_days", "files", "fetched_days", "fetched_rows",
    "pending_empty"}. defer_empty=True면 무데이터 표식을 쓰지 않고 pending_empty로 돌려준다
    (load_all이 전 종목을 본 뒤 write_empty_markers로 쓴다).
    """
    parts, issues = [], []
    stats = {"api_calls": 0, "cache_hits": 0, "empty_days": [], "files": 0, "fetched_days": 0,
             "fetched_rows": 0, "pending_empty": []}
    non_integer, truncated_any = False, False
    calls_before = client.call_count if client is not None else 0
    for day in days:
        path = minute_cache_path(cache_dir, code, day)
        cached = read_minute_cache(path)
        if cached is not None:
            stats["cache_hits"] += 1
            stats["files"] += 1
            non_integer = non_integer or bool(_read_issues(path).get("non_integer_price"))
            if len(cached) == 0:
                stats["empty_days"].append(day)
            parts.append(cached)
            continue
        if client is None:
            raise FileNotFoundError(f"분봉 캐시 파일이 없고 클라이언트도 없습니다: {path.name}")
        rows, truncated = fetch_minutes_day(client, code, day, start_hour, max_pages)
        df = normalize_minute_rows(rows, day, time_label)
        stats["fetched_days"] += 1
        stats["fetched_rows"] += len(df)
        non_integer = non_integer or bool(df.attrs.get("non_integer_price"))
        if truncated:
            truncated_any = True
            log.warning("잘림 의심 분봉이라 캐시에 저장하지 않습니다: %s", path.name)
        elif len(df) == 0:
            stats["pending_empty"].append((code, day))
            stats["empty_days"].append(day)
        else:
            _write_cache(df, path)
            _write_issues(path, bool(df.attrs.get("non_integer_price")))
            _log_saved(code, day, df)
            stats["files"] += 1
        parts.append(df)
    if not defer_empty:
        write_empty_markers(cache_dir, stats["pending_empty"], stats["fetched_days"],
                            stats["fetched_rows"], client.env if client is not None else "")
        stats["files"] += len(stats["pending_empty"])
        stats["pending_empty"] = []
    if non_integer:
        issues.append(make_issue("NON_INTEGER_PRICE", code))
    if truncated_any:
        issues.append(make_issue("TRUNCATION_SUSPECT", code))
    frames = [p for p in parts if len(p)]
    out = pd.concat(frames, ignore_index=True) if frames else _empty_minutes()
    out = out.sort_values(["date", "time"], kind="stable").reset_index(drop=True)
    stats["api_calls"] = (client.call_count - calls_before) if client is not None else 0
    return out, issues, stats


def trading_days(daily: dict[str, pd.DataFrame], start: date, end: date) -> list[date]:
    """종목 일봉 날짜의 합집합 중 [start, end]. 분봉을 요청할 후보 일자. 순수 함수."""
    out: set[date] = set()
    for df in (daily or {}).values():
        if df is None or len(df) == 0:
            continue
        for ts in pd.to_datetime(df["date"]):
            if start <= ts.date() <= end:
                out.add(ts.date())
    return sorted(out)


def load_all(cfg: dict, period: dict, client: KisClient | None, refresh: bool = False
             ) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame, list[dict], dict]:
    """(minutes{code}(제외 종목 빠짐), daily{code}, benchmark_df, data_issues, source_info).

    수집 순서: 종목 일봉 → 지수 일봉 → 후보 일자(trading_days) → 종목 × 일자 분봉.
    refresh=True(--refresh)는 일봉 캐시만 무시한다. 분봉 캐시는 그대로 쓴다.
    """
    fetch_start, start, end = period["daily_fetch_start"], period["start"], period["end"]
    cache_dir = cfg["paths"]["cache_dir"]
    dcfg = cfg.get("data", {})
    issues: list[dict] = []
    hits = 0
    daily: dict[str, pd.DataFrame] = {}
    for item in cfg["universe"]:
        code = item["code"]
        df = load_daily(code, fetch_start, end, cache_dir, client, refresh)
        hits += 1 if df.attrs.get("from_cache") else 0
        if df.attrs.get("non_integer_price"):
            issues.append(make_issue("NON_INTEGER_PRICE", code))
        if df.attrs.get("truncation"):
            issues.append(make_issue("TRUNCATION_SUSPECT", code))
        if len(df) == 0:
            log.warning("종목 일봉 0건: %s (가격제한폭 판정을 건너뜁니다)", code)
        daily[code] = df
    bench_code = cfg["benchmark"]["code"]
    bench = load_index(bench_code, fetch_start, end, cache_dir, client, refresh)
    hits += 1 if bench.attrs.get("from_cache") else 0
    if len(bench) == 0:
        raise DataError("벤치마크 지수 일봉이 없습니다(조회 결과 0건).")
    if bench.attrs.get("truncation"):
        issues.append(make_issue("TRUNCATION_SUSPECT", index_cache_code(bench_code)))
    days = trading_days(daily, start, end)
    if not days:
        raise DataError("종목 일봉이 없어 후보 거래일을 정할 수 없습니다.")
    minutes: dict[str, pd.DataFrame] = {}
    pending, fetched_days, fetched_rows, minute_files = [], 0, 0, 0
    empty_days: list[dict] = []
    for item in cfg["universe"]:
        code = item["code"]
        df, iss, st = load_minutes(code, days, cache_dir, client,
                                   time_label=dcfg.get("minute_time_label", "start"),
                                   start_hour=dcfg.get("minute_start_hour", "160000"),
                                   max_pages=int(dcfg.get("minute_max_pages", 6)), defer_empty=True)
        issues.extend(iss)
        hits += st["cache_hits"]
        pending.extend(st["pending_empty"])
        fetched_days += st["fetched_days"]
        fetched_rows += st["fetched_rows"]
        minute_files += st["files"]
        empty_days.extend({"code": code, "date": d} for d in st["empty_days"])
        minutes[code] = df
    write_empty_markers(cache_dir, pending, fetched_days, fetched_rows, cfg["kis"]["env"])
    minute_files += len(pending)
    for code in list(minutes):
        if len(minutes[code]) == 0:
            log.warning("분봉 전체 0행으로 제외한 종목: %s", code)
            issues.append(make_issue("DATA_MISSING", code, value=len(days), excluded=True))
            del minutes[code]
    if not minutes:
        raise DataError("유효 종목이 0개입니다(전 종목 분봉 없음).")
    source = {"api_calls": client.call_count if client is not None else 0, "cache_hits": hits,
              "minute_files": minute_files,
              "minute_rows": int(sum(len(df) for df in minutes.values())),
              "empty_days": sorted(empty_days, key=lambda x: (x["date"], x["code"]))}
    return minutes, daily, bench, issues, source


