"""Research gates must hold independently of candidate profitability."""
import copy
import json
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from helpers import FIX_CACHE
from stock_sim import cli, config, kis_client, research


@pytest.fixture(autouse=True)
def capture_research_logs(caplog):
    caplog.set_level(logging.INFO, logger="stock_sim.research")


@pytest.fixture
def policy():
    return research.read_json(Path(__file__).resolve().parents[1] / "research.json")


def calendar(n, first=date(2026, 1, 1)):
    return [first + timedelta(days=i) for i in range(n)]


def score(ret, **updates):
    return {"total_return": ret, "benchmark_return": 0.0, "mdd": -0.02,
            "closed_count": 20, "quality_ok": True, **updates}


def initial():
    return {"schema_version": 1, "context": "same", "champion": {"id": "base"},
            "pending": None, "history": []}


def proposals():
    return [{"id": "one", "hypothesis": "test", "params": {"id": "one"}}]


def evaluator(params, days, stress):
    return score(0.02 if params["id"] == "one" else 0.001)


def registered(policy):
    days = calendar(60)
    state, outcome = research.advance(initial(), proposals(), policy, days, "data-1", "same",
                                       days[-1] + timedelta(days=1), evaluator, True)
    assert outcome["status"] == "challenger_registered"
    return state, days


def test_selection_never_promotes_and_waits_after_registration(policy):
    seen = []
    days = calendar(60)
    today = days[-1] + timedelta(days=12)  # stale historical data is not a future holdout
    def evaluate(params, selected_days, stress):
        seen.append(selected_days)
        return evaluator(params, selected_days, stress)
    original = initial()
    state, result = research.advance(original, proposals(), policy, days, "a", "same",
                                     today, evaluate, True)
    assert original["pending"] is None
    assert state["champion"] == original["champion"]
    assert result["status"] == "challenger_registered"
    assert state["pending"]["registered_through"] == str(today)
    assert all(d < today for fold in seen for d in fold)
    assert set(seen[0]).isdisjoint(seen[1])
    assert len(seen[0]) == 40 and len(seen[1]) == 20
    def forbidden(*args):
        pytest.fail("No evaluation before fresh holdout exists")
    same, outcome = research.advance(state, [], policy, days, "a", "same", today, forbidden, True)
    assert same == state and outcome["status"] == "awaiting_holdout"


def test_holdout_uses_frozen_candidate_on_exactly_new_dates(policy):
    state, days = registered(policy)
    cutoff = date.fromisoformat(state["pending"]["registered_through"])
    fresh = calendar(12, cutoff + timedelta(days=1))
    seen = []
    def evaluate(params, subset, stress):
        seen.append((params, subset, stress))
        return evaluator(params, subset, stress)
    state, result = research.advance(state, [{"id": "tampered", "params": {"id": "bad"}}],
                                     policy, days + fresh, "new", "same",
                                     fresh[-1] + timedelta(days=1), evaluate, True)
    assert result["status"] == "promoted"
    assert state["champion"] == {"id": "one"} and state["pending"] is None
    assert all(subset == fresh[:10] for _, subset, _ in seen)
    assert len(seen) == 4
    assert {p["id"] for p, _, _ in seen} == {"base", "one"}
    assert len(state["history"]) == 1


@pytest.mark.parametrize("bad", [
    {"total_return": -0.01}, {"total_return": 0.003}, {"mdd": -0.3},
    {"mdd": -0.03}, {"closed_count": 0}, {"quality_ok": False},
    {"total_return": float("nan")}, {"benchmark_return": 0.04},
])
def test_profitable_candidate_must_also_pass_risk_and_quality(policy, bad):
    assert not research.passes(score(0.02, **bad), score(0.001), policy)


def test_failed_stress_rejects_and_consumes_holdout(policy):
    state, old = registered(policy)
    cutoff = date.fromisoformat(state["pending"]["registered_through"])
    days = old + calendar(10, cutoff + timedelta(days=1))
    def evaluate(params, dates, stress):
        if stress and params["id"] == "one":
            return score(-0.01)
        return evaluator(params, dates, stress)
    state, result = research.advance(state, proposals(), policy, days, "new", "same",
                                     days[-1] + timedelta(days=1), evaluate, True)
    assert result["status"] == "rejected"
    assert state["champion"] == {"id": "base"} and state["pending"] is None
    def forbidden(*args):
        pytest.fail("Do not repeat an unchanged experiment")
    _, again = research.advance(state, proposals(), policy, days, "new", "same",
                                 days[-1] + timedelta(days=1), forbidden, True)
    assert again["status"] == "no_new_data"
    assert len(state["history"]) == 1


def test_usage_and_engine_changes_do_not_evaluate(policy):
    state, days = registered(policy)
    def forbidden(*args):
        pytest.fail("Research should be gated")
    same, result = research.advance(state, proposals(), policy, days, "x", "same",
                                    days[-1], forbidden, False)
    assert same == state and result["status"] == "usage_reserve"
    same, result = research.advance(state, proposals(), policy, days, "x", "changed",
                                    days[-1], forbidden, True)
    assert same == state and result["status"] == "context_changed"


def test_risk_budget_and_credentials_cannot_be_candidate_parameters(policy):
    cfg = copy.deepcopy(config.DEFAULTS)
    for key in ("position_pct", "daily_loss_limit_pct", "name", "force_exit_time"):
        with pytest.raises(ValueError):
            research.candidate_params(cfg, [{"id": "x", "hypothesis": "x",
                                             "overrides": {key: 1}}], policy)
    with pytest.raises(ValueError):
        research.candidate_params(cfg, [{"id": "x", "hypothesis": "x",
                                        "overrides": {"vol_mult": float("nan")}}], policy)
    with pytest.raises(ValueError):
        research.candidate_params(cfg, [{"id": str(i), "hypothesis": "x",
                                        "overrides": {"vol_mult": 2}} for i in range(7)], policy)


def test_new_hypothesis_preserves_previous_champion_improvements(policy):
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["strategy"]["entry_lookback"] = 12
    rows = research.candidate_params(cfg, [{"id": "volume", "hypothesis": "test",
                                           "overrides": {"vol_mult": 2}}], policy)
    assert rows[0]["params"]["entry_lookback"] == 12
    assert rows[0]["params"]["vol_mult"] == 2
    assert cfg["strategy"]["vol_mult"] == 1.5


@pytest.fixture
def offline(tmp_path, monkeypatch, policy):
    monkeypatch.delenv(config.ENV_FILE_VAR, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("No network in offline research tests")
    monkeypatch.setattr(kis_client.requests, "get", forbidden)
    monkeypatch.setattr(kis_client.requests, "post", forbidden)
    shutil.copytree(FIX_CACHE, tmp_path / "data" / "cache")
    root = Path(__file__).resolve().parents[1]
    settings = {"universe": [{"code": "000001", "name": "가상전자"},
                              {"code": "000002", "name": "가상화학"}],
                "backtest": {"end": "2026-09-23", "days": 3},
                "output": {"template": str(root / "templates" / "dashboard.html.j2")}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    local_policy = {**policy, "history_calendar_days": 3}
    research.write_json(tmp_path / "research.json", local_policy)
    args = ["--config", str(path), "--policy", str(tmp_path / "research.json"),
            "--end", "2026-09-23"]
    return tmp_path, config.load_config(path), local_policy, args


def test_replay_uses_existing_engine_and_preserves_quality_alerts(offline):
    root, cfg, policy, args = offline
    snapshot = research.load_snapshot(cfg, policy, date(2026, 9, 23), False)
    result = research.simulate(cfg, snapshot, cfg["strategy"], snapshot["days"], full=True)
    assert cli.main(["run", "--config", str(root / "config.yaml"), "--no-render"]) == 0
    original = research.read_json(root / "output" / "result.json")
    assert result["summary"] == original["summary"]
    assert result["trades"] == original["trades"]
    assert result["alerts"] == original["alerts"]
    assert research.simulate(cfg, snapshot, cfg["strategy"], snapshot["days"])["quality_ok"] is False
    assert research.main(args + ["--remaining-percent", "10"]) == 0
    latest = research.read_json(root / "data" / "research" / "latest.json")
    assert latest["status"] == "usage_reserve"
    paper = root / "data" / "research" / "paper" / latest["paper_id"]
    assert (paper / "dashboard.html").exists()
    assert not (root / "publish" / "result.json").exists()


def test_missing_data_never_overwrites_published_results(offline, caplog):
    root, _, _, args = offline
    research.write_json(root / "publish" / "result.json", {"previous": True})
    (root / "data" / "cache" / "min" / "000001_20260922.csv").unlink()
    assert research.main(args + ["--publish", "--remaining-percent", "80"]) == 0
    assert json.loads(caplog.records[-1].message)["status"] == "data_unavailable"
    assert research.read_json(root / "publish" / "result.json") == {"previous": True}


def test_single_writer_blocks_duplicate_run_and_releases_lock(tmp_path):
    with research.single_writer(tmp_path):
        with pytest.raises(FileExistsError):
            with research.single_writer(tmp_path):
                pytest.fail("Duplicate writer")
    assert not (tmp_path / "run.lock").exists()


def test_benchmark_gaps_cannot_support_promotion(offline):
    _, cfg, policy, _ = offline
    snapshot = research.load_snapshot(cfg, policy, date(2026, 9, 23), False)
    snapshot["bench"] = snapshot["bench"].iloc[:1]
    result = research.simulate(cfg, snapshot, cfg["strategy"], snapshot["days"])
    assert result["quality_ok"] is False


def test_today_cannot_be_used_as_completed_history(offline, caplog):
    _, _, _, args = offline
    today = research.datetime.now(research.KST).date()
    assert research.main(args + ["--end", str(today)]) == 1
    assert json.loads(caplog.records[-1].message)["status"] == "error"


def test_policy_change_preserves_existing_experiment(offline, caplog):
    root, _, _, args = offline
    assert research.main(args) == 0
    caplog.clear()
    path = root / "data" / "research" / "state.json"
    previous = path.read_bytes()
    policy = research.read_json(root / "research.json")
    policy["holdout_days"] += 1
    research.write_json(root / "research.json", policy)
    assert research.main(args + ["--publish"]) == 0
    assert json.loads(caplog.records[-1].message)["status"] == "context_changed"
    assert path.read_bytes() == previous
    assert not (root / "publish" / "result.json").exists()
