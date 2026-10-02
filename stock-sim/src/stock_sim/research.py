"""Bounded research and historical paper replay, using the existing intraday engine.

Selection data is NOT out-of-sample evidence. A frozen challenger must wait for
new trading dates after registration before it can replace the paper champion.
No LLM API, orders, or brokerage paper-account calls are made by this module.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import math
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_sim import backtest, config, data, metrics, report, strategy
from stock_sim.kis_client import KisClient, KisError
from stock_sim.render import render

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
ALLOWED_OVERRIDES = {
    "entry_lookback", "exit_lookback", "vol_mult", "min_range_pct",
    "entry_cutoff", "cooldown_bars", "max_entries_per_symbol_per_day",
}


def digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


@contextmanager
def single_writer(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "run.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def validate_policy(policy: dict) -> None:
    for key in ("history_calendar_days", "paper_calendar_days", "train_days",
                "validation_days", "holdout_days", "max_candidates", "min_closed_trades"):
        if type(policy.get(key)) is not int or policy[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    if policy["max_candidates"] > 6:
        raise ValueError("At most six preregistered candidates per round")
    for key in ("min_remaining_percent", "min_improvement", "max_mdd",
                "max_mdd_regression", "stress_slippage_rate"):
        value = policy.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid research policy: {key}")
    if not 0 < policy["min_remaining_percent"] <= 100:
        raise ValueError("Usage reserve must be between 0 and 100")
    if not 0 < policy["max_mdd"] < 1 or policy["min_improvement"] <= 0:
        raise ValueError("Promotion requires positive improvement and bounded drawdown")


def candidate_params(cfg: dict, candidates: list, policy: dict) -> list[dict]:
    if not isinstance(candidates, list) or len(candidates) > policy["max_candidates"]:
        raise ValueError("Candidate batch exceeds the research budget")
    found, rows = set(), []
    for item in candidates:
        identifier = item.get("id")
        overrides = item.get("overrides", {})
        if not isinstance(identifier, str) or not identifier or identifier in found:
            raise ValueError("Candidates need unique, nonempty ids")
        if not item.get("hypothesis") or not overrides or set(overrides) - ALLOWED_OVERRIDES:
            raise ValueError("Each candidate needs a hypothesis and permitted overrides")
        if any(isinstance(v, float) and not math.isfinite(v) for v in overrides.values()):
            raise ValueError("Candidate parameters must be finite")
        trial = copy.deepcopy(cfg)
        trial["strategy"].update(overrides)
        config._validate(trial)
        found.add(identifier)
        rows.append({**item, "params": trial["strategy"]})
    return rows


def context_fingerprint(cfg: dict, policy: dict) -> str:
    # Changes to the engine, capital, costs or gates cannot silently reuse a
    # pending experiment or an already promoted champion.
    modules = ("research.py", "backtest.py", "strategy.py", "metrics.py", "data.py", "report.py")
    return digest({
        "code": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                 for name in modules},
        "config": {key: cfg[key] for key in
                   ("universe", "benchmark", "session", "costs", "strategy", "data")},
        "capital": cfg["backtest"]["initial_cash"], "policy": policy,
    })


def load_snapshot(cfg: dict, policy: dict, end: date, collect: bool):
    cfg = copy.deepcopy(cfg)
    cfg["backtest"].update(end=end.isoformat(), days=policy["history_calendar_days"])
    period = config.resolve_period(cfg, end + timedelta(days=1))
    client = None
    if collect:
        if cfg["kis"]["env"] != "DEV":
            raise config.ConfigError("Automatic collection only supports KIS DEV")
        key, secret = config.load_credentials("DEV", cfg["paths"]["env_file"])
        k = cfg["kis"]
        client = KisClient("DEV", key, secret, cfg["paths"]["cache_dir"],
                           min_interval_sec=max(0.5, k["min_interval_sec"]),
                           max_retries=k["max_retries"], backoff_sec=k["backoff_sec"],
                           timeout_sec=k["timeout_sec"])
    minutes, daily, bench, issues, source = data.load_all(cfg, period, client)
    # Cache files must not expand a request into the future, even if their
    # filenames and contents disagree.
    def trim(frame, start):
        dates = pd.to_datetime(frame["date"]).dt.date
        return frame[(dates >= start) & (dates <= end)].copy().reset_index(drop=True)
    minutes = {c: trim(df, period["start"]) for c, df in minutes.items()}
    daily = {c: trim(df, period["daily_fetch_start"]) for c, df in daily.items()}
    bench = trim(bench, period["daily_fetch_start"])
    days = data.trading_days(daily, period["start"], end)
    if not days or not any(len(df) for df in minutes.values()):
        raise data.DataError("No completed historical sessions are available")
    signature = digest({
        "minutes": {c: df.to_csv(index=False) for c, df in minutes.items()},
        "daily": {c: df.to_csv(index=False) for c, df in daily.items()},
        "benchmark": bench.to_csv(index=False), "issues": issues,
    })
    return {"minutes": minutes, "daily": daily, "bench": bench, "issues": issues,
            "source": source, "days": days, "signature": signature, "period": period}


def simulate(cfg: dict, snapshot: dict, params: dict, days: list[date],
             slippage: float | None = None, full: bool = False):
    trial = copy.deepcopy(cfg)
    trial["strategy"] = copy.deepcopy(params)
    if slippage is not None:
        trial["costs"]["slippage_rate"] = max(slippage, cfg["costs"]["slippage_rate"])
    trial["backtest"]["days"] = (days[-1] - days[0]).days + 1
    wanted, bars, auction = set(days), {}, {}
    for code, frame in snapshot["minutes"].items():
        part = frame[pd.to_datetime(frame["date"]).dt.date.isin(wanted)].copy()
        raw = strategy.resample_bars(part, params["bar_minutes"],
                                    cfg["session"]["open"], cfg["session"]["continuous_end"])
        bars[code] = strategy.signals(raw, params)
        auction[code] = strategy.auction_closes(part)
    bt = backtest.run_backtest(bars, snapshot["daily"], auction, params,
                               config.cost_rates(trial), cfg["backtest"]["initial_cash"],
                               session=cfg["session"])
    actual_days = list(bt["days"]["date"])
    if actual_days != days:
        raise data.DataError("Minute data does not cover every requested trading day")
    capital = cfg["backtest"]["initial_cash"]
    daily = metrics.daily_table(bt["days"], bt["fills"], bt["closed"], capital)
    bench, info = metrics.benchmark_curve(snapshot["bench"], days, capital)
    info["equal_weight_return"] = metrics.equal_weight_return(snapshot["daily"], days)
    info["equal_weight_count"] = metrics.equal_weight_count(snapshot["daily"], days)
    result = metrics.summarize(bt["fills"], bt["closed"], daily, bench, capital)
    result = {k: result[k] for k in ("total_return", "benchmark_return", "mdd",
                                    "closed_count", "total_cost", "trading_days")}
    prices_complete = all(
        wanted <= set(pd.to_datetime(frame.loc[(frame["open"] > 0) &
                                               (frame["close"] > 0), "date"]).dt.date)
        for frame in [snapshot["bench"], *snapshot["daily"].values()])
    result["quality_ok"] = prices_complete and not snapshot["issues"] and not bt["events"] and not any(
        day["skipped_codes"] for day in bt["days"].to_dict("records"))
    if not full:
        return result
    period = {**snapshot["period"], "start": days[0], "end": days[-1]}
    rendered = report.build_result(trial, period, bt, daily, bench, info, snapshot["issues"],
                                   snapshot["source"], datetime.now(KST).isoformat(timespec="seconds"))
    return rendered


def passes(candidate: dict, baseline: dict, policy: dict, stress=False) -> bool:
    keys = ("total_return", "benchmark_return", "mdd", "closed_count")
    if not all(type(row.get(k)) in (int, float) and math.isfinite(row[k])
               for row in (candidate, baseline) for k in keys):
        return False
    improvement = 0 if stress else policy["min_improvement"]
    return bool(
        candidate.get("quality_ok") and baseline.get("quality_ok")
        and candidate["closed_count"] >= policy["min_closed_trades"]
        and candidate["total_return"] > 0
        and (stress or candidate["total_return"] > candidate["benchmark_return"])
        and candidate["total_return"] - baseline["total_return"] >= improvement
        and candidate["mdd"] >= -policy["max_mdd"]
        and candidate["mdd"] >= baseline["mdd"] - policy["max_mdd_regression"]
    )


def advance(state: dict, candidates: list[dict], policy: dict, days: list[date],
            signature: str, context: str, today: date, evaluate, research_allowed: bool):
    """Pure state transition; evaluate(params, days, stress) runs the real engine."""
    state = copy.deepcopy(state)
    if state["context"] != context:
        return state, {"status": "context_changed", "reason": "Preserve state; review engine/policy changes"}
    if not research_allowed:
        return state, {"status": "usage_reserve", "reason": "Research skipped; quota missing or below reserve"}
    pending = state.get("pending")
    if pending:
        cutoff = date.fromisoformat(pending["registered_through"])
        fresh = [d for d in days if cutoff < d < today]
        if len(fresh) < policy["holdout_days"]:
            return state, {"status": "awaiting_holdout", "available_days": len(fresh),
                           "required_days": policy["holdout_days"], "candidate": pending["id"]}
        if days[0] > cutoff + timedelta(days=7):
            return state, {"status": "holdout_expired", "reason": "Restore the original post-registration data"}
        holdout = fresh[:policy["holdout_days"]]
        scores = {}
        for label, params in (("baseline", state["champion"]), ("candidate", pending["params"])):
            scores[label] = evaluate(params, holdout, False)
            scores[label + "_stress"] = evaluate(params, holdout, True)
        accepted = passes(scores["candidate"], scores["baseline"], policy) and passes(
            scores["candidate_stress"], scores["baseline_stress"], policy, stress=True)
        outcome = {"status": "promoted" if accepted else "rejected", "candidate": pending["id"],
                   "holdout_start": str(holdout[0]), "holdout_end": str(holdout[-1]), "scores": scores}
        if accepted:
            state["champion"] = pending["params"]
        state["history"].append({**outcome, "params": pending["params"],
                                 "registered_through": pending["registered_through"]})
        state["pending"] = None
        # Rejected candidates may be researched again, but only on a new
        # snapshot, and their next holdout must again lie AFTER registration.
        state["last_selection"] = digest([signature, candidates])
        return state, outcome
    if len(days) < policy["train_days"] + policy["validation_days"]:
        return state, {"status": "insufficient_history", "available_days": len(days),
                       "required_days": policy["train_days"] + policy["validation_days"]}
    selection_id = digest([signature, candidates])
    if state.get("last_selection") == selection_id:
        return state, {"status": "no_new_data"}
    validation = days[-policy["validation_days"]:]
    training = days[-(policy["train_days"] + policy["validation_days"]):-policy["validation_days"]]
    baseline_train = evaluate(state["champion"], training, False)
    baseline_valid = evaluate(state["champion"], validation, False)
    baseline_stress = evaluate(state["champion"], validation, True)
    rows, eligible = [], []
    for candidate in candidates:
        if candidate["params"] == state["champion"]:
            continue
        train = evaluate(candidate["params"], training, False)
        valid = evaluate(candidate["params"], validation, False)
        stress = evaluate(candidate["params"], validation, True)
        ok = (passes(train, baseline_train, policy)
              and passes(valid, baseline_valid, policy)
              and passes(stress, baseline_stress, policy, stress=True))
        rows.append({"id": candidate["id"], "train": train, "validation": valid,
                     "stress": stress, "eligible": ok})
        if ok:
            eligible.append((valid["total_return"], valid["mdd"], candidate["id"], candidate))
    state["last_selection"] = selection_id
    outcome = {"status": "no_candidate", "selection": rows}
    if eligible:
        chosen = max(eligible, key=lambda item: item[:3])[3]
        state["pending"] = {
            **chosen, "registered_through": str(max(today, days[-1])),
            "selection_signature": signature,
        }
        outcome.update(status="challenger_registered", candidate=chosen["id"],
                       registered_through=state["pending"]["registered_through"])
    return state, outcome


def run(args) -> dict:
    cfg = config.load_config(args.config)
    policy = read_json(args.policy)
    validate_policy(policy)
    candidate_definitions = read_json(args.candidates)
    today = datetime.now(KST).date()
    end = args.end or today - timedelta(days=1)
    if end >= today:
        raise ValueError("Only completed historical dates before today are allowed")
    state_dir = args.state_dir or cfg["paths"]["root"] / "data" / "research"
    with single_writer(state_dir):
        state_path = state_dir / "state.json"
        context = context_fingerprint(cfg, policy)
        state = read_json(state_path, {"schema_version": 1, "context": context,
                                      "champion": cfg["strategy"], "pending": None, "history": []})
        if state.get("schema_version") != 1:
            raise ValueError("Unsupported research state version; keep the original state")
        if state["context"] != context:
            outcome = {"status": "context_changed", "reason": "Engine/policy changed; existing state retained"}
            write_json(state_dir / "latest.json", outcome)
            return outcome
        # New hypotheses build on the current paper champion, so improvements
        # can accumulate without rewriting the original configuration.
        candidates = candidate_params({**cfg, "strategy": state["champion"]},
                                      candidate_definitions, policy)
        try:
            snapshot = load_snapshot(cfg, policy, end, args.collect)
        except (FileNotFoundError, config.ConfigError, data.DataError, KisError) as exc:
            outcome = {"status": "data_unavailable", "reason": str(exc)}
            write_json(state_dir / "latest.json", outcome)
            return outcome
        def evaluate(params, days, stress):
            return simulate(cfg, snapshot, params, days,
                            policy["stress_slippage_rate"] if stress else None)
        remaining = args.remaining_percent
        allowed = (remaining is not None and math.isfinite(remaining)
                   and policy["min_remaining_percent"] <= remaining <= 100)
        state, outcome = advance(state, candidates, policy, snapshot["days"], snapshot["signature"],
                                 context, today, evaluate, allowed)
        # Persist consumed holdout evidence before publishing. A renderer or
        # publication failure cannot cause the holdout to be evaluated twice.
        write_json(state_path, state)
        if outcome["status"] in ("promoted", "rejected", "challenger_registered", "no_candidate"):
            event_id = digest([snapshot["signature"], outcome])
            write_json(state_dir / "rounds" / f"{event_id}.json", outcome)
        days = [d for d in snapshot["days"]
                if d >= end - timedelta(days=policy["paper_calendar_days"] - 1)]
        if not days:
            raise data.DataError("No trading sessions within the paper replay period")
        paper_id = digest([snapshot["signature"], state["champion"], str(end)])
        paper_dir = state_dir / "paper" / paper_id
        result_path = paper_dir / "result.json"
        if not result_path.exists():
            result = simulate(cfg, snapshot, state["champion"], days, full=True)
            result["meta"]["label"] = "DANTA · 과거 데이터 모의투자"
            write_json(result_path, result)
        render(result_path, cfg["paths"]["template"], paper_dir / "dashboard.html")
        if args.publish:
            destination = cfg["paths"]["root"] / "publish" / "result.json"
            write_json(destination, read_json(result_path))
        outcome = {**outcome, "data_end": str(snapshot["days"][-1]), "paper_id": paper_id,
                   "published": bool(args.publish)}
        write_json(state_dir / "latest.json", outcome)
        return outcome


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--policy", type=Path, default=ROOT / "research.json")
    parser.add_argument("--candidates", type=Path, default=ROOT / "research" / "candidates.json")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--remaining-percent", type=float)
    parser.add_argument("--collect", action="store_true", help="Collect missing historical quotes using KIS DEV")
    parser.add_argument("--publish", action="store_true", help="Stage real paper results for GitHub Pages")
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except FileExistsError:
        result = {"status": "busy", "reason": "Another run owns the lock; no duplicate work"}
    except (ValueError, OSError, config.ConfigError, data.DataError, KisError) as exc:
        log.error("%s", json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 1
    log.info("%s", json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
