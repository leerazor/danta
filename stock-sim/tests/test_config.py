"""설정 로드·검증·기간 해석·.env 탐색 테스트(architecture.md 1.1절, 3절). 가짜 .env만 쓴다."""
from datetime import date
from pathlib import Path

import pytest
import yaml

from stock_sim import config
from stock_sim.config import ConfigError

PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv(config.ENV_FILE_VAR, raising=False)


def _write(tmp_path, body: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


def test_project_config_is_v2_defaults():
    cfg = config.load_config(PROJECT_CONFIG)
    assert cfg["kis"]["env"] == "DEV" and cfg["kis"]["prod_approved_by_user"] is False
    assert cfg["kis"]["min_interval_sec"] == 0.5
    assert [u["code"] for u in cfg["universe"]] == ["005930", "000660"]
    assert cfg["strategy"] == config.DEFAULTS["strategy"]
    assert cfg["session"] == {"open": "09:00", "continuous_end": "15:20"}
    assert cfg["backtest"] == {"end": "2026-09-29", "days": 30, "initial_cash": 100_000_000}
    assert cfg["data"]["minute_time_label"] == "start"
    assert cfg["target"] == {"monthly_return": 0.02}
    assert config.cost_rates(cfg) == {"buy_rate": 0.00015, "sell_rate": 0.00215, "slippage_rate": 0.0}
    root = PROJECT_CONFIG.parent
    assert cfg["paths"]["result"] == root / "output" / "result.json"
    assert cfg["paths"]["cache_dir"] == root / "data" / "cache"
    assert cfg["paths"]["minute_cache_dir"] == root / "data" / "cache" / "min"


def test_empty_file_gets_defaults(tmp_path):
    cfg = config.load_config(_write(tmp_path, {}))
    assert cfg["kis"]["env"] == "DEV" and len(cfg["universe"]) == 2
    assert cfg["strategy"]["name"] == "intraday_breakout"
    assert cfg["paths"]["template"] == tmp_path.resolve() / "templates" / "dashboard.html.j2"


@pytest.mark.parametrize("body, word", [
    ({"capital": 1}, "capital"),
    ({"max_positions": 5}, "max_positions"),
    ({"target_return": 2.0}, "target_return"),
    ({"strategy": {"params": {"lookback_days": 20}}}, "strategy.params"),
    ({"strategy": {"top_n": 5}}, "strategy.top_n"),
    ({"backtest": {"months": 1}}, "backtest.months"),
    ({"backtest": {"warmup_days": 90}}, "backtest.warmup_days"),
    ({"costs": {"buy_fee_pct": 0.015}}, "costs.buy_fee_pct"),
])
def test_v1_keys_are_rejected(tmp_path, body, word):
    with pytest.raises(ConfigError) as exc:
        config.load_config(_write(tmp_path, body))
    assert word in str(exc.value) and "v1" in str(exc.value)


@pytest.mark.parametrize("body, word", [
    ({"kis": {"env": "PROD"}}, "R3"),                                    # 승인 없는 PROD 거부
    ({"kis": {"env": "TEST"}}, "kis.env"),
    ({"universe": []}, "universe"),
    ({"universe": [{"code": 5930, "name": "x"}]}, "6자리"),
    ({"universe": [{"code": "005930", "name": "a"}, {"code": "005930", "name": "b"}]}, "중복"),
    ({"strategy": {"name": "sma_cross"}}, "strategy.name"),
    ({"strategy": {"bar_minutes": 0}}, "bar_minutes"),
    ({"strategy": {"entry_lookback": 0}}, "entry_lookback"),
    ({"strategy": {"position_pct": 0}}, "position_pct"),
    ({"strategy": {"position_pct": 0.6}}, "position_pct"),             # 0.6 × 2종목 > 1
    ({"strategy": {"entry_cutoff": "9:30"}}, "HH:MM"),
    ({"strategy": {"force_exit_time": "14:00"}}, "시각 순서"),
    ({"session": {"continuous_end": "15:10"}}, "시각 순서"),
    ({"backtest": {"days": 0}}, "backtest.days"),
    ({"backtest": {"initial_cash": 0}}, "initial_cash"),
    ({"costs": {"buy_rate": -0.1}}, "costs.buy_rate"),
    ({"data": {"minute_time_label": "middle"}}, "minute_time_label"),
])
def test_invalid_config_raises(tmp_path, body, word):
    with pytest.raises(ConfigError) as exc:
        config.load_config(_write(tmp_path, body))
    assert word in str(exc.value)


def test_off_grid_times_are_allowed_if_ordered(tmp_path):
    # strategy.md 10.1절 테스트 설정: 형식·순서만 검증한다(5분 격자 밖 10:04 허용)
    body = {"session": {"open": "09:00", "continuous_end": "10:05"},
            "strategy": {"entry_cutoff": "10:00", "force_exit_time": "10:04"}}
    cfg = config.load_config(_write(tmp_path, body))
    assert cfg["strategy"]["force_exit_time"] == "10:04"


def test_prod_allowed_only_with_explicit_user_approval(tmp_path):
    cfg = config.load_config(_write(tmp_path, {"kis": {"env": "PROD", "prod_approved_by_user": True}}))
    assert cfg["kis"]["env"] == "PROD"


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        config.load_config(tmp_path / "nope.yaml")


def test_resolve_period_default_run():
    cfg = config.load_config(PROJECT_CONFIG)
    period = config.resolve_period(cfg, date(2026, 9, 30))
    assert period == {"start": date(2026, 8, 31), "end": date(2026, 9, 29),
                      "daily_fetch_start": date(2026, 8, 24)}


def test_resolve_period_auto_and_bad_end(tmp_path):
    cfg = config.load_config(_write(tmp_path, {"backtest": {"end": "auto", "days": 10}}))
    period = config.resolve_period(cfg, date(2026, 9, 30))
    assert period["end"] == date(2026, 9, 29) and period["start"] == date(2026, 9, 20)
    cfg["backtest"]["end"] = "어제"
    with pytest.raises(ConfigError):
        config.resolve_period(cfg, date(2026, 9, 30))


def test_find_env_file_prefers_env_var_then_walks_up(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    deep = root / ".claude" / "worktrees" / "wt" / "stock-sim"
    deep.mkdir(parents=True)
    assert config.find_env_file(deep) is None or not str(config.find_env_file(deep)).startswith(str(root))
    (root / ".env").write_text("KIS_DEV_APP_KEY=FAKE\n", encoding="utf-8")
    assert config.find_env_file(deep) == root / ".env"                  # 상위로 올라가 루트 .env
    other = tmp_path / "elsewhere.env"
    other.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setenv(config.ENV_FILE_VAR, str(other))
    assert config.find_env_file(deep) == other.resolve()                # 환경변수 우선
    monkeypatch.setenv(config.ENV_FILE_VAR, str(tmp_path / "missing.env"))
    with pytest.raises(ConfigError) as exc:
        config.find_env_file(deep)
    assert config.ENV_FILE_VAR in str(exc.value)


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
    with pytest.raises(ConfigError) as exc:
        config.load_credentials("DEV", None)
    assert config.ENV_FILE_VAR in str(exc.value) and "KIS_DEV_APP_KEY" in str(exc.value)
    monkeypatch.setenv("KIS_DEV_APP_SECRET", "FAKESECRET")
    monkeypatch.setenv("KIS_DEV_APP_KEY", "FAKEKEY1234567890")
    assert config.load_credentials("DEV", env_file) == ("FAKEKEY1234567890", "FAKESECRET")
