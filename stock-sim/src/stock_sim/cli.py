"""진입점. `python -m stock_sim run --config config.yaml` / `render` (architecture.md 1.9절, 2절).

종료 코드: 0 성공 / 1 설정 오류 / 2 렌더 실패 / 3 KIS·데이터 오류.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_sim import backtest, config, data, metrics, report, strategy
from stock_sim.config import ConfigError
from stock_sim.data import DataError
from stock_sim.kis_client import KisClient, KisError

log = logging.getLogger("stock_sim")
KST = timezone(timedelta(hours=9))
EXIT_OK, EXIT_CONFIG, EXIT_RENDER, EXIT_DATA = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock_sim", description="주식 자동매매 백테스트 시뮬레이션")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="데이터 수집 → 백테스트 → result.json → dashboard.html")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--refresh", action="store_true",
                     help="일봉 캐시만 무시(분봉 캐시·토큰 캐시는 그대로 쓴다)")
    run.add_argument("--no-render", action="store_true", help="result.json까지만 만든다")
    run.add_argument("--verbose", action="store_true")
    rend = sub.add_parser("render", help="기존 result.json으로 HTML만 다시 만든다")
    rend.add_argument("--config", required=True, type=Path)
    rend.add_argument("--result", type=Path, default=None)
    rend.add_argument("--out", type=Path, default=None)
    rend.add_argument("--verbose", action="store_true")
    return parser


def _all_cached(cfg: dict, period: dict) -> bool:
    """일봉 3개 + (그 일봉으로 정한 후보 일자의) 분봉 파일이 전부 있으면 True."""
    cache_dir, start, end = cfg["paths"]["cache_dir"], period["daily_fetch_start"], period["end"]
    daily = {}
    for item in cfg["universe"]:
        df = data.read_cache(data.cache_path(cache_dir, item["code"], start, end), True)
        if df is None:
            return False
        daily[item["code"]] = df
    idx = data.index_cache_code(cfg["benchmark"]["code"])
    if data.read_cache(data.cache_path(cache_dir, idx, start, end), False) is None:
        return False
    days = data.trading_days(daily, period["start"], end)
    return all(data.read_minute_cache(data.minute_cache_path(cache_dir, item["code"], d)) is not None
               for item in cfg["universe"] for d in days)


def _make_client(cfg: dict) -> KisClient:
    kis = cfg["kis"]
    key, secret = config.load_credentials(kis["env"], cfg["paths"]["env_file"])
    return KisClient(kis["env"], key, secret, cfg["paths"]["cache_dir"],
                     min_interval_sec=kis["min_interval_sec"], max_retries=kis["max_retries"],
                     backoff_sec=kis["backoff_sec"], timeout_sec=kis["timeout_sec"])


def _render(cfg: dict, result_path: Path, out_path: Path, verbose: bool) -> int:
    try:
        from stock_sim.render import render      # 지연 import: render.py가 없어도 나머지는 돈다
        render(result_path=result_path, template_path=cfg["paths"]["template"], out_path=out_path)
    except Exception as exc:                      # ImportError, FileNotFoundError, ValueError, Jinja2 예외
        log.error("대시보드 렌더 실패(%s): %s. result.json은 그대로 둡니다.", type(exc).__name__, exc,
                  exc_info=verbose)
        return EXIT_RENDER
    log.info("대시보드 저장: %s", out_path)
    return EXIT_OK


def _run(args) -> int:
    cfg = config.load_config(args.config)
    today = datetime.now(KST).date()
    period = config.resolve_period(cfg, today)
    log.info("환경 %s, 백테스트 구간 %s ~ %s, 일봉 수집 시작 %s", cfg["kis"]["env"],
             period["start"], period["end"], period["daily_fetch_start"])
    client = None
    if args.refresh or not _all_cached(cfg, period):
        client = _make_client(cfg)
    else:
        log.info("캐시가 모두 있어 API를 호출하지 않습니다(토큰 발급 없음).")
    minutes, daily, bench, issues, source = data.load_all(cfg, period, client, refresh=args.refresh)
    params = cfg["strategy"]
    sess = cfg["session"]
    bars, auction = {}, {}
    for code, df in minutes.items():
        five = strategy.resample_bars(df, params["bar_minutes"], sess["open"], sess["continuous_end"])
        bars[code] = strategy.signals(five, params)
        auction[code] = strategy.auction_closes(df)
    bt = backtest.run_backtest(bars, daily, auction, params, config.cost_rates(cfg),
                               cfg["backtest"]["initial_cash"], session=sess)
    if len(bt["days"]) == 0:
        raise DataError("백테스트 구간에 거래일이 0일입니다.")
    capital = cfg["backtest"]["initial_cash"]
    days = list(bt["days"]["date"])
    daily_tab = metrics.daily_table(bt["days"], bt["fills"], bt["closed"], capital)
    try:
        bench_df, bench_info = metrics.benchmark_curve(bench, days, capital)
    except ValueError as exc:
        raise DataError(str(exc)) from None
    bench_info["equal_weight_return"] = metrics.equal_weight_return(daily, days)
    bench_info["equal_weight_count"] = metrics.equal_weight_count(daily, days)
    generated_at = datetime.now(KST).isoformat(timespec="seconds")
    result = report.build_result(cfg, period, bt, daily_tab, bench_df, bench_info, issues, source,
                                 generated_at)
    path = report.write_result(result, cfg["paths"]["result"])
    s = result["summary"]
    log.info("result.json 저장: %s (수익률 %.2f%%, KOSPI %.2f%%, MDD %.2f%%, 체결 %d건, 청산 %d건)", path,
             s["total_return_pct"], s["benchmark_return_pct"], s["mdd_pct"], s["trade_count"],
             s["closed_count"])
    if args.no_render:
        return EXIT_OK
    return _render(cfg, cfg["paths"]["result"], cfg["paths"]["dashboard"], args.verbose)


def _render_only(args) -> int:
    cfg = config.load_config(args.config)
    result_path = Path(args.result).resolve() if args.result else cfg["paths"]["result"]
    out_path = Path(args.out).resolve() if args.out else cfg["paths"]["dashboard"]
    return _render(cfg, result_path, out_path, args.verbose)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)   # 요청 상세는 DEBUG에서도 남기지 않는다
    try:
        return _run(args) if args.command == "run" else _render_only(args)
    except ConfigError as exc:
        log.error("설정 오류: %s", exc, exc_info=args.verbose)
        return EXIT_CONFIG
    except (KisError, DataError, FileNotFoundError) as exc:
        log.error("KIS·데이터 오류: %s", exc, exc_info=args.verbose)
        return EXIT_DATA
