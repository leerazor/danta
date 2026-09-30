"""진입점. `python -m stock_sim run --config config.yaml` / `render` (architecture.md 1.9절).

종료 코드: 0 성공 / 1 설정 오류 / 2 렌더 실패 / 3 KIS·데이터 오류.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stock_sim import backtest, config, data, metrics, report
from stock_sim.config import ConfigError
from stock_sim.data import DataError
from stock_sim.kis_client import KisClient, KisError
from stock_sim.strategy import STRATEGIES

log = logging.getLogger("stock_sim")
KST = timezone(timedelta(hours=9))
EXIT_OK, EXIT_CONFIG, EXIT_RENDER, EXIT_DATA = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock_sim", description="주식 자동매매 백테스트 시뮬레이션")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="데이터 수집 → 백테스트 → result.json → dashboard.html")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--refresh", action="store_true", help="일봉 캐시 무시(토큰 캐시는 유지)")
    run.add_argument("--no-render", action="store_true", help="result.json까지만 만든다")
    run.add_argument("--verbose", action="store_true")
    rend = sub.add_parser("render", help="기존 result.json으로 HTML만 다시 만든다")
    rend.add_argument("--config", required=True, type=Path)
    rend.add_argument("--result", type=Path, default=None)
    rend.add_argument("--out", type=Path, default=None)
    rend.add_argument("--verbose", action="store_true")
    return parser


def _all_cached(cfg: dict, period: dict) -> bool:
    cache_dir, start, end = cfg["paths"]["cache_dir"], period["fetch_start"], period["end"]
    for item in cfg["universe"]:
        if data.read_cache(data.cache_path(cache_dir, item["code"], start, end), True) is None:
            return False
    idx = data.index_cache_code(cfg["benchmark"]["code"])
    return data.read_cache(data.cache_path(cache_dir, idx, start, end), False) is not None


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
    except Exception as exc:                      # ImportError, FileNotFoundError, Jinja2 예외 등
        log.error("대시보드 렌더 실패(%s): %s. result.json은 그대로 둡니다.", type(exc).__name__, exc,
                  exc_info=verbose)
        return EXIT_RENDER
    log.info("대시보드 저장: %s", out_path)
    return EXIT_OK


def _run(args) -> int:
    cfg = config.load_config(args.config)
    today = datetime.now(KST).date()
    period = config.resolve_period(cfg, today)
    log.info("환경 %s, 수집 구간 %s ~ %s, 백테스트 요청 시작 %s", cfg["kis"]["env"],
             period["fetch_start"], period["end"], period["requested_start"])
    client = None
    if args.refresh or not _all_cached(cfg, period):
        client = _make_client(cfg)
    else:
        log.info("캐시가 모두 있어 API를 호출하지 않습니다(토큰 발급 없음).")
    prices, bench, issues, source = data.load_all(cfg, period, client, refresh=args.refresh)
    calendar = data.build_calendar(prices)
    days = [d for d in calendar if period["requested_start"] <= d <= period["end"]]
    if not days:
        raise DataError("백테스트 구간에 거래일이 0일입니다.")
    strat = STRATEGIES[cfg["strategy"]["name"]]
    params = cfg["strategy"]["params"]
    need, have = strat["min_warmup"](params), calendar.index(days[0])
    if have < need:
        raise DataError(f"워밍업 부족: 백테스트 시작일 이전 거래일이 {need}일 필요한데 {have}일만 확보했습니다.")
    schedule = strat["schedule"](calendar, days[0], days[-1], params)
    targets = strat["targets"](prices, calendar, schedule, params)
    bt = backtest.run_backtest(prices, calendar, schedule, targets, days[0], days[-1],
                               cfg["capital"], cfg["max_positions"], config.cost_rates(cfg))
    try:
        bench_df, bench_info = metrics.benchmark_curve(bench, days, cfg["capital"])
    except ValueError as exc:
        raise DataError(str(exc)) from None
    bench_info["equal_weight_return"] = metrics.equal_weight_return(prices, days)
    period["rebalances"] = len(schedule)
    generated_at = datetime.now(KST).isoformat(timespec="seconds")
    result = report.build_result(cfg, period, bt, bench_df, bench_info, issues, source, generated_at)
    path = report.write_result(result, cfg["paths"]["result"])
    s = result["summary"]
    log.info("result.json 저장: %s (수익률 %.2f%%, KOSPI %.2f%%, MDD %.2f%%, 체결 %d건)", path,
             s["total_return_pct"], s["benchmark_return_pct"], s["mdd_pct"], s["trade_count"])
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
