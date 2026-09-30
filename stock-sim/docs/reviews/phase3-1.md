# Phase 3 코드 리뷰 — 1회차

리뷰일 2026-09-30 · 담당: reviewer · 대상: `src/stock_sim/`(render.py 제외), `tests/`(test_render.py 제외), `config.yaml`, `pyproject.toml`, `output/result.json`, `data/cache/*.csv`

## 판정: **PASS** (High 0 · Med 2 · Low 5)

Med 2건은 다음 Phase(W4 최종 실행) 전에 처리할 것을 권고한다. 수치·규칙 구현에서는 문제를 찾지 못했다(독립 재계산이 result.json과 전부 일치).

## Findings

| # | 심각도 | 파일:줄 | 문제 | 근거(실행·재계산) | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | Med | `pyproject.toml:17-21` ↔ `CLAUDE.md` 7절, `docs/architecture.md` 9절, `docs/PLAN.md` 3절(Phase 5)·5절 | 문서에 적힌 유일한 진입점 명령이 현재 구성에서 실패한다. `[tool.uv] package = false`라 `stock_sim`이 venv에 설치되지 않는다. | `stock-sim/`에서 `uv run python -m stock_sim run --config config.yaml --no-render` → `python.exe: No module named stock_sim`. 대체 명령 `uv run --directory src python -m stock_sim run --config ../config.yaml`은 정상 종료(아래 실행 기록). implementer가 든 원인(한글 경로 + Python 3.11의 .pth cp949 디코딩)은 이 리뷰에서 재현하지 않았다. 확인한 것은 "문서 명령이 실패하고 대체 명령이 동작한다"까지다. | 둘 중 하나로 계약과 구현을 맞춘다. (a) 문서 3곳의 실행 명령을 대체 명령으로 고친다(architecture.md 9절 표의 전체 실행·`--refresh`·`render` 3행, CLAUDE.md 7절 "진입점 하나", PLAN.md Phase 5·5절). (b) 문서 명령이 그대로 돌도록 구현을 바꾼다. Phase 5 완료 조건이 이 명령 한 번 실행이므로 W4 전에 결정이 필요하다. | 오케스트레이터(CLAUDE.md·PLAN.md) + architect(architecture.md 9절) |
| 2 | Med | `src/stock_sim/data.py:130` | 캐시 적중 시 `non_integer_price`·`truncation` 플래그를 무조건 `False`로 덮어쓴다. 첫 수집 실행에서 나온 `TRUNCATION_SUSPECT`·`NON_INTEGER_PRICE` 알림이 같은 캐시로 재실행하면 사라진다. 잘린 데이터가 캐시에 남은 채 경고 없이 재사용된다. | 가짜 클라이언트(100행, 시가 `100.5`)로 `load_daily` 2회 호출: 1회차 attrs `{'from_cache': False, 'truncation': True, 'non_integer_price': True}` → 2회차(캐시) `{'from_cache': True, 'truncation': False, 'non_integer_price': False}`. 현재 실데이터는 해당 없음(종목당 82행 < 100, 캐시 CSV 시가 전부 정수, `alerts`에 두 코드 없음)이라 이번 result.json 수치에는 영향이 없다. | 플래그가 캐시 재실행에서도 유지되게 한다. 예: 잘림 의심 조각이 있으면 캐시에 쓰지 않는다(다음 실행에서 다시 받고 다시 경고), 또는 플래그를 캐시 옆 보조 파일에 저장해 적중 시 복원한다. 캐시 형식을 바꾸는 쪽이면 architecture.md 6.1절 갱신이 먼저다. 테스트 추가: "수집 → 캐시 재로드 후에도 이슈가 유지된다". | implementer (캐시 형식 변경 시 architect 선행) |
| 3 | Low | `src/stock_sim/data.py:11` | `numpy`를 직접 import하지만 `pyproject.toml` dependencies에 없다(pandas의 전이 의존성으로만 설치됨). CLAUDE.md 7절 의존성 목록에도 없다. | `data.py:11 import numpy as np`, 사용처는 `np.floor` 4곳(76·78·83줄). `pyproject.toml:6-12`에 numpy 없음. | `np.floor`를 pandas/표준 라이브러리 연산으로 바꾸거나, 의존성 추가를 보고하고 승인받아 명시한다. | implementer |
| 4 | Low | `src/stock_sim/report.py:26-27, 161-164` | `NON_INTEGER_PRICE`·`TRUNCATION_SUSPECT`를 warn 등급(색 `#C98A2E`)으로 정하고 문장도 직접 만들었다. strategy.md 10.3절 표에 두 코드가 없다(architecture.md 4.4절은 이슈 코드로만 언급). | strategy.md 380-392줄 표에 두 코드 없음. `WARN_ORDER` 끝 두 항목. 현재 result.json `alerts`는 `MDD_BREACH`, `UNDERPERFORM`, `LOW_SAMPLE` 3건뿐이라 표시 영향 없음. | 등급·문장 자체는 데이터 품질 경고로 타당하다. strategy.md 10.3절 표에 두 행(조건·등급·메시지 틀)을 추가해 계약에 올린다. | strategy-designer (변경 요청) |
| 5 | Low | `src/stock_sim/report.py:211-214` | strategy.md 10.1절에 없는 인사이트 문장 2개: 손실 종목만 있을 때 "수익 종목은 없었고, …", 거래 종목 손익이 모두 0일 때 "거래한 종목의 손익이 모두 0원입니다." | strategy.md 364-366줄은 "한쪽만 있음 → 있는 쪽 절만" + 수익 쪽 예시 1개만 정의. 현재 result.json의 인사이트 3문장은 모두 10.1절 틀과 일치(아래 확인 항목). | strategy.md 10.1절에 두 경우의 문장을 명시한다. 코드 수정은 불필요. | strategy-designer (변경 요청) |
| 6 | Low | `src/stock_sim/cli.py:97-98`, 각 모듈 | 계약(architecture.md 1절) 밖 전달 방식·공개 이름. `cli`가 `bench_info["equal_weight_return"]`, `period["rebalances"]`를 끼워 넣어 `build_result`에 넘긴다(시그니처는 문서와 동일). 문서에 없는 공개 이름: `config.cost_rates`, `data.DataError`·`make_issue`·`read_cache`·`index_cache_code`, `kis_client.unsupported_message`, `backtest.rate_to_int`·`calc_cost`·`fill_price`·`calc_qty`, `strategy.to_bars`·`is_valid_bar`, `STRATEGIES[...]["label"]`. | 코드 열람. 문서의 공개 함수 시그니처는 전부 그대로 존재하고 동작한다(테스트 120건 통과). | 동작상 문제 없음. architecture.md 1절에 `bench_info`·`period`의 추가 키와 보조 공개 이름을 한 줄씩 기록한다. | architect (변경 요청) |
| 7 | Low | `src/stock_sim/report.py` (546줄) | architecture.md 0절 "파일당 200줄 목표"를 넘는다. | `wc -l` 546. 1.7절은 초과 시 "비공개 헬퍼로 정리, 모듈 추가는 승인 후"라고만 정해 위반은 아니다. | 기록만. 모듈을 나누려면 승인 후. | – |

## 실행 기록

### `uv run pytest` (stock-sim/ 에서, 원문)
```
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
configfile: pyproject.toml
testpaths: tests
collected 122 items / 2 deselected / 120 selected

tests\test_backtest.py ................                                  [ 13%]
tests\test_config.py .................                                   [ 27%]
tests\test_data.py .............                                         [ 38%]
tests\test_e2e.py ......                                                 [ 43%]
tests\test_kis_client.py ............                                    [ 53%]
tests\test_metrics.py .............                                      [ 64%]
tests\test_render.py .............                                       [ 75%]
tests\test_report.py ..............                                      [ 86%]
tests\test_rules.py .....                                                [ 90%]
tests\test_strategy.py ...........                                       [100%]

====================== 120 passed, 2 deselected in 1.95s ======================
```
- 네트워크 없이 도는지: `socket.socket.connect`·`socket.create_connection`·`socket.getaddrinfo`를 예외로 바꾼 뒤 `pytest.main`(test_render.py 제외) → `107 passed, 15 deselected`. deselect 2건은 `-m network` 스모크(`test_kis_smoke.py`), 실행하지 않았다.

### 캐시 재실행 (`uv run --directory src python -m stock_sim run --config ../config.yaml`)
- 로그: "캐시가 모두 있어 API를 호출하지 않습니다(토큰 발급 없음)", 캐시 적중 11건(종목 10 + `IDX0001`, 각 82행), 종료 정상.
- 실행 전후 `data/cache/*.csv` 11개와 `token_*.json`의 수정 시각 불변(토큰 파일 내용은 열지 않았다).
- `result.json`: 실행 전 사본과 `generated_at` 한 줄만 다르고 나머지 동일. `dashboard.html` md5 동일(`784fcf6a…`).
- `meta.data_source`: `api_calls 0`, `cache_hits 11`, `env DEV`.

## 독립 재계산 (stock_sim을 import하지 않고 캐시 CSV만으로 다시 계산)

| 항목 | 재계산 | result.json | 일치 |
|---|---|---|---|
| 거래일 달력 / 백테스트 구간 | 82일(06-01~09-29) / 20일(08-31~09-29), 워밍업 62일 | `trading_days 20`, 08-31~09-29 | O |
| 스케줄(신호→체결) | 08-28→08-31, 09-04→09-07, 09-11→09-14, 09-18→09-21, **09-23→09-28** | trades의 `signal_date`/`date` | O |
| 첫 리밸런싱 상위 5 (신호 08-28, 기준일 07-30) | 000660 +25.038%, 005930 +24.155%, 373220 +15.625%, 005380 +13.818%, 035420 +13.251% (6위 005490 +12.313%) | 거래 1~5번 종목·순서 | O |
| 거래 13건 전체 | 날짜·신호일·종목·방향·수량·체결가·거래대금·비용·실현손익을 직접 시뮬레이션 | `trades[]` | 13/13 O |
| 체결가 = 체결일 시가 | 13건 모두 CSV `open`과 동일. 예: #1 000660 08-31 1,596,000 / #6 005380 09-07 389,500 / #12 068270 09-28 178,400 | | O |
| 비용(half-up 정수 연산) | #1 매수 19,152,000×0.015% = 2,872.8 → 2,873 / #6 매도 19,864,500×0.215% = 42,708.675 → 42,709 / #10 매도 21,120,000×0.215% = 45,408 | 2,873 / 42,709 / 45,408 | O |
| 사이징 | 08-31 alloc 20,000,000 / 09-07 E_ref 100,103,171 → alloc 20,020,634 / 09-21 alloc 20,600,155 / 09-28 alloc 20,292,780, 수량 전부 정수 | 수량 일치 | O |
| 최종 현금 / 최종 평가액 | 1,710,144 / 99,161,144 | 1,710,144 / 99,161,144 | O |
| 총수익률 | −0.838856% | −0.8389 | O |
| MDD | −5.144605%, 고점 09-09 → 저점 09-29 | −5.1446, 09-09, 09-29 | O |
| KOSPI 벤치마크 | 6870.81 / 6613.58(08-31 시가) − 1 = +3.889421% | +3.8894, `base_kind d1_open` | O |
| 초과수익 | −4.728277%p | −4.7283 | O |
| 동일가중 buy&hold | −3.421559% | −3.4216 | O |
| 실현 / 평가 손익 | +925,024 / −1,763,880, 합 = 최종 평가액 − 초기 자본 | 동일 | O |
| 총 비용 / 총 거래대금 / 거래량 | 201,956 / 260,908,100 / 987주 | 동일 | O |
| 회전율 | 128.2647% | 128.2647 | O |
| 청산 4건, 승 2·패 2, 승률 50% | 동일 | 동일 | O |
| 일별 equity·cash 20행 | 전부 일치, 현금 최솟값 1,010,277(≥ 0) | `equity_curve[]` | O |

## 확인한 항목 (통과)

### 공통
- R1: `src/`·`tests/`·`config.yaml`·`result.json`·캐시 CSV에 40자 이상 토큰 모양 문자열, `Bearer `, JWT 접두 0건. `print(` 0건(검토 범위). 앱키는 `_mask`로 앞 4자리만 로그, 시크릿·토큰은 로그·예외에 없음(`_scrub`, `test_unsupported_error_never_switches_env_and_hides_secrets`). 헤더·본문 덤프 코드 없음. `.env`와 `token_*.json`은 열지 않았다.
- R2: `src/`, `tests/`, `config.yaml`, `pyproject.toml`, `templates/`, `output/result.json`에서 `trading/`·`order-cash`·`inquire-balance` 0건. `stock-sim/` 전체로는 `docs/reviews/phase2-1.md:64`(규칙 인용문)만 걸린다. `kis_client.py`의 경로 상수는 토큰 1 + quotations 2개뿐.
- R3: 기본값 DEV(`config.py` DEFAULTS, `config.yaml:2`). `BASE_URLS[env]` 한 곳에서만 결정, 환경 전환 분기 없음. `env: PROD`인데 `prod_approved_by_user`가 true가 아니면 `ConfigError`(config.py:65, `test_config_error_returns_1`). 미지원 시 고정 문안만 내고 재시도 도메인 변경 없음.
- R4: `result.json`에 account/계좌/잔고/appkey/token/secret 문자열 0건.
- 산출물 경로: `src/stock_sim/*`, `tests/*`, `config.yaml`, `pyproject.toml`, `output/result.json` 존재.

### 코드
- look-ahead(R5): `strategy.signals`는 `signal_date`와 `calendar[i − lookback]` 봉만 읽는다. `run_backtest`는 `E_ref`에 신호일 종가(`closes[c][p]`), 체결에 체결일 시가(`bar[0]`)를 쓴다. 미래 데이터 불변 테스트 2건(`test_future_data_does_not_change_past_signals`, `test_future_data_does_not_change_past_fills`) 통과. 추석 주 09-23 → 09-28 확인.
- 비용: `rate_to_int` + 정수 나눗셈으로 half-up, 내장 `round()` 미사용. 매도는 합친 율(0.215%)로 1회 반올림. 매수·매도 양쪽 적용.
- 수량 정수(`calc_qty`의 정수 검증 루프), 현금 음수 시 `AssertionError`, 기간 말 미청산은 마지막 날 종가 평가(강제 청산 없음), 결측 종가는 직전 유효 종가(`_carried_closes`).
- strategy.md 9절 손계산 기대값 테스트(`test_9_4`~`test_9_7`, `test_9_6_expected_metrics`, `test_identities_7_1`) 통과.
- 캐시: 전 파일 적중이면 `client=None`(자격 증명도 읽지 않음), 토큰 미발급. 토큰 유효 판정 `now < expires_at − 1시간` + env 일치. 호출 간 `min_interval_sec` 대기, `EGW00201`/429/네트워크 오류는 `backoff × 시도` 재시도, 토큰 발급 실패는 61초 후 1회 재시도, 토큰 거부는 재발급 1회.
- `result.json`: 키 구조가 `docs/result.example.json`과 재귀 비교로 차이 0. `NaN`·`Infinity`·`"None"`·`"nan"` 없음. 모든 `sign`/`*_sign`이 값의 부호와 일치. `weekly_flow` 스택 합 100.0(5주), 도넛 마지막 `end_pct` 100.0. `per_stock` 10종목(제외 0).
- 인사이트·알림 문장: 현재 결과의 3문장과 `next_action`, 알림 3건(`MDD_BREACH` −5.14%, `UNDERPERFORM` −4.73%p, `LOW_SAMPLE`)이 strategy.md 10.1~10.3절 틀·임계와 일치.

### 설계와의 차이(위임 8번) 수용 여부
| 차이 | 판단 |
|---|---|
| `[tool.uv] package = false` + 대체 실행 명령 | 동작은 수용. 문서 명령 실패는 Finding 1(Med) |
| `build_result` 입력 전달(`bench_info`·`period`에 키 추가) | 수용. Finding 6(Low) |
| 문서 밖 공개 이름 | 수용. Finding 6(Low) |
| 알림 2종 등급(warn) | 수용. Finding 4(Low). 캐시 재실행 시 소실은 Finding 2(Med) |
| 임의로 채운 인사이트 문장 | 수용. Finding 5(Low) |
| `report.py` 546줄 | 수용. Finding 7(Low) |
| `numpy` 직접 import | Finding 3(Low) |

## 확인하지 않은 것
- `.env`, `data/cache/token_*.json`의 내용(금지). `-m network` 스모크 테스트(금지). 따라서 실 API 응답 형식과 DEV 지원 여부는 이 리뷰의 검증 범위 밖이다.
- 한글 경로에서 편집 가능 설치가 실패한다는 implementer의 원인 설명(재현하지 않음).
- `render.py`, `templates/`, `test_render.py`, `dashboard.html` 내용(Phase 4 리뷰 담당).
