"""설정 로드·검증·기간 해석 테스트."""
from datetime import date
from pathlib import Path

import pytest
import yaml

from stock_sim import config
from stock_sim.config import ConfigError

PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def _write(tmp_path, body: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


def test_project_config_matches_plan_defaults():
    cfg = config.load_config(PROJECT_CONFIG)
    assert cfg["kis"]["env"] == "DEV" and cfg["kis"]["prod_approved_by_user"] is False
    assert cfg["capital"] == 100_000_000 and cfg["max_positions"] == 5
    assert cfg["strategy"] == {"name": "momentum_topn",
                               "params": {"lookback_days": 20, "top_n": 5, "rebalance": "weekly"}}
    assert [u["code"] for u in cfg["universe"]] == [
        "005930", "000660", "373220", "207940", "005380", "000270", "068270", "035420", "105560", "005490"]
    assert config.cost_rates(cfg) == pytest.approx(
        {"buy_rate": 0.00015, "sell_rate": 0.00215, "slippage_rate": 0.0})
    root = PROJECT_CONFIG.parent
    assert cfg["paths"]["result"] == root / "output" / "result.json"
    assert cfg["paths"]["cache_dir"] == root / "data" / "cache"
    assert cfg["paths"]["env_file"] == root.parent / ".env"


def test_empty_file_gets_defaults(tmp_path):
    cfg = config.load_config(_write(tmp_path, {}))
    assert cfg["kis"]["env"] == "DEV" and len(cfg["universe"]) == 10
    assert cfg["paths"]["template"] == tmp_path.resolve() / "templates" / "dashboard.html.j2"


@pytest.mark.parametrize("body, word", [
    ({"kis": {"env": "PROD"}}, "R3"),                                    # 승인 없는 PROD 거부
    ({"kis": {"env": "TEST"}}, "kis.env"),
    ({"universe": []}, "universe"),
    ({"universe": [{"code": 5930, "name": "x"}]}, "6자리"),
    ({"universe": [{"code": "005930", "name": "a"}, {"code": "005930", "name": "b"}]}, "중복"),
    ({"capital": 0}, "capital"),
    ({"max_positions": 3}, "top_n"),
    ({"costs": {"buy_fee_pct": -1}}, "costs"),
    ({"strategy": {"name": "sma_cross"}}, "strategy.name"),
])
def test_invalid_config_raises(tmp_path, body, word):
    with pytest.raises(ConfigError) as exc:
        config.load_config(_write(tmp_path, body))
    assert word in str(exc.value)


def test_prod_allowed_only_with_explicit_user_approval(tmp_path):
    cfg = config.load_config(_write(tmp_path, {"kis": {"env": "PROD", "prod_approved_by_user": True}}))
    assert cfg["kis"]["env"] == "PROD"


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        config.load_config(tmp_path / "nope.yaml")


def test_resolve_period_default_run():
    cfg = config.load_config(PROJECT_CONFIG)
    period = config.resolve_period(cfg, date(2026, 9, 30))
    assert period == {"fetch_start": date(2026, 5, 31), "requested_start": date(2026, 8, 29),
                      "end": date(2026, 9, 29)}


def test_resolve_period_explicit_end(tmp_path):
    cfg = config.load_config(_write(tmp_path, {"backtest": {"end": "2026-03-31", "months": 1, "warmup_days": 10}}))
    period = config.resolve_period(cfg, date(2026, 9, 30))
    assert period["end"] == date(2026, 3, 31) and period["requested_start"] == date(2026, 2, 28)
    assert period["fetch_start"] == date(2026, 2, 18)
    cfg["backtest"]["end"] = "어제"
    with pytest.raises(ConfigError):
        config.resolve_period(cfg, date(2026, 9, 30))


def test_mask():
    assert config.mask("ABCDEFGHIJ") == "ABCD****"
    assert config.mask("ABCD") == "****" and config.mask("") == "****"


def test_load_credentials_reports_names_only(tmp_path, monkeypatch):
    for name in ("KIS_DEV_APP_KEY", "KIS_DEV_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("KIS_DEV_APP_KEY=FAKEKEY1234567890\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        config.load_credentials("DEV", env_file)
    assert "KIS_DEV_APP_SECRET" in str(exc.value) and "FAKEKEY" not in str(exc.value)
    monkeypatch.setenv("KIS_DEV_APP_SECRET", "FAKESECRET")
    monkeypatch.setenv("KIS_DEV_APP_KEY", "FAKEKEY1234567890")
    assert config.load_credentials("DEV", env_file) == ("FAKEKEY1234567890", "FAKESECRET")
