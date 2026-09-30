"""통합 테스트: fixture 캐시 폴더 + 임시 config로 cli를 돌린다. 네트워크 0회."""
import json

import pytest
import yaml

from helpers import DOCS, SYN_END, SYN_FETCH_START, syn_cfg, write_syn_cache
from stock_sim import cli, data


@pytest.fixture
def no_network(monkeypatch):
    import requests

    def boom(*a, **k):
        raise AssertionError("테스트에서 네트워크를 호출했습니다")
    monkeypatch.setattr(requests.sessions.Session, "request", boom)


def _project(tmp_path, **override):
    root = tmp_path / "stock-sim"
    root.mkdir(parents=True)
    cfg = syn_cfg()
    cfg.update(override)
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return root, path


def test_run_from_cache_writes_result_without_network(tmp_path, no_network):
    root, cfg_path = _project(tmp_path)
    write_syn_cache(root / "data" / "cache")
    code = cli.main(["run", "--config", str(cfg_path), "--no-render"])
    assert code == 0
    result = json.loads((root / "output" / "result.json").read_text(encoding="utf-8"))
    example = json.loads((DOCS / "result.example.json").read_text(encoding="utf-8"))
    assert set(result) == set(example)
    assert result["meta"]["env"] == "DEV" and result["meta"]["is_example"] is False
    assert result["meta"]["period"] == {"requested_start": "2026-08-29", "start": "2026-08-31",
                                        "end": "2026-09-29", "trading_days": 20, "months": 1}
    assert result["meta"]["data_source"]["api_calls"] == 0
    assert result["meta"]["data_source"]["cache_hits"] == 5          # 종목 4 + 지수 1
    assert result["summary"]["trade_count"] > 0
    assert not (root / "data" / "cache" / "token_dev.json").exists()   # 토큰도 발급하지 않는다
    assert not (root / "output" / "dashboard.html").exists()


def test_run_is_deterministic_except_timestamp(tmp_path, no_network):
    root, cfg_path = _project(tmp_path)
    write_syn_cache(root / "data" / "cache")
    out = root / "output" / "result.json"
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 0
    first = json.loads(out.read_text(encoding="utf-8"))
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 0
    second = json.loads(out.read_text(encoding="utf-8"))
    first["meta"].pop("generated_at"), second["meta"].pop("generated_at")
    assert first == second


def test_render_failure_keeps_result_and_returns_2(tmp_path, no_network):
    """템플릿이 없으면(또는 render.py가 아직 없으면) result.json은 남기고 종료 코드 2."""
    root, cfg_path = _project(tmp_path)
    write_syn_cache(root / "data" / "cache")
    assert cli.main(["run", "--config", str(cfg_path)]) == 2
    assert (root / "output" / "result.json").is_file()
    assert cli.main(["render", "--config", str(cfg_path)]) == 2


def test_config_error_returns_1(tmp_path, no_network):
    _, cfg_path = _project(tmp_path, max_positions=3)
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 1
    _, prod = _project(tmp_path / "p", kis={"env": "PROD"})
    assert cli.main(["run", "--config", str(prod), "--no-render"]) == 1      # R3: 승인 없는 PROD 거부


def test_missing_credentials_returns_1_without_network(tmp_path, no_network, monkeypatch):
    for name in ("KIS_DEV_APP_KEY", "KIS_DEV_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    _, cfg_path = _project(tmp_path)                     # 캐시 없음 → 클라이언트 필요 → .env 없음
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 1


def test_warmup_shortage_returns_3(tmp_path, no_network):
    root, cfg_path = _project(tmp_path, backtest={"end": SYN_END.isoformat(), "months": 1, "warmup_days": 20})
    cache = root / "data" / "cache"
    write_syn_cache(cache)
    start = cli.config.resolve_period(cli.config.load_config(cfg_path), SYN_END)["fetch_start"]
    for path in list(cache.glob("*.csv")):               # 짧은 수집 구간 이름으로 다시 저장
        code = path.name.split("_")[0]
        df = data.read_cache(path, not code.startswith("IDX"))
        df = df[df["date"] >= str(start)]
        df.to_csv(data.cache_path(cache, code, start, SYN_END), index=False, encoding="utf-8",
                  date_format="%Y-%m-%d")
    assert start > SYN_FETCH_START
    assert cli.main(["run", "--config", str(cfg_path), "--no-render"]) == 3
    assert not (root / "output" / "result.json").exists()
