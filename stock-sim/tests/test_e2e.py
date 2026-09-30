"""e2e: fixture 캐시 + 임시 config로 cli.main(run --no-render) → result.json. 네트워크 0회, .env 없이 통과."""
import json
import shutil

import pytest
import yaml

from helpers import FIX_CACHE
from stock_sim import cli, config, kis_client
from test_report import EXAMPLE, check_identities, key_shape_diff, no_nan


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv(config.ENV_FILE_VAR, raising=False)

    def boom(*a, **k):
        raise AssertionError("네트워크 호출 금지")
    monkeypatch.setattr(kis_client.requests, "get", boom)
    monkeypatch.setattr(kis_client.requests, "post", boom)
    shutil.copytree(FIX_CACHE, tmp_path / "data" / "cache")
    body = {"universe": [{"code": "000001", "name": "가상전자"}, {"code": "000002", "name": "가상화학"}],
            "backtest": {"end": "2026-09-23", "days": 3, "initial_cash": 100_000_000}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return tmp_path, path


def test_run_offline_creates_result_json(project):
    root, cfg_path = project
    before = sorted(p.name for p in (root / "data" / "cache" / "min").iterdir())
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 0
    result = json.loads((root / "output" / "result.json").read_text(encoding="utf-8"))
    assert key_shape_diff(EXAMPLE, result) == []
    check_identities(result)
    assert no_nan(result)
    assert result["meta"]["period"] == {"start": "2026-09-21", "end": "2026-09-23", "days": 3, "trading_days": 3}
    ds = result["meta"]["data_source"]
    assert (ds["api_calls"], ds["minute_files"], ds["cache_hits"]) == (0, 6, 9)
    assert result["summary"]["trade_count"] > 0                   # 합성 데이터에서 체결이 생긴다
    bar_missing = [a for a in result["alerts"] if a["code"] == "BAR_MISSING"]
    assert [(a["title"], a["detail"]) for a in bar_missing] == [("가상화학 5분봉 1개 결측", "000002 · 1거래일에 걸침")]
    for t in result["trades"]:
        if t["signal_time"] is not None:
            assert t["time"] > t["signal_time"]
    assert not (root / "output" / "dashboard.html").exists()
    after = sorted(p.name for p in (root / "data" / "cache" / "min").iterdir())
    assert before == after                                        # 분봉 캐시를 지우지 않는다


def test_missing_minute_cache_without_env_is_config_error(project):
    root, cfg_path = project
    (root / "data" / "cache" / "min" / "000001_20260922.csv").unlink()
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) in (1, 3)


def test_render_failure_keeps_result(project, monkeypatch):
    root, cfg_path = project
    import stock_sim.render as render_mod
    def fail(**kw):
        raise ValueError("테스트용 렌더 실패")
    monkeypatch.setattr(render_mod, "render", fail)
    assert cli.main(["run", "--config", str(cfg_path)]) == 2
    assert (root / "output" / "result.json").is_file()
