# Phase 3 코드 리뷰 — 2회차

리뷰일 2026-09-30 · 담당: reviewer · 대상: `src/stock_sim/{report,data,metrics,cli}.py`, `tests/{test_report,test_data,test_sentences,helpers}.py`, `output/result.json`(generated_at `2026-09-30T15:02:20+09:00`), `data/cache/*.csv`
기준: strategy.md 10.0~10.6절, architecture.md "(개정 1.1)" 부분·6.1절, phase3-1.md

## 판정: **PASS** (High 0 · Med 0 · Low 3)

phase3-1의 Med 2(캐시 적중 시 이슈 플래그 소실)와 Low 3(numpy)은 해결됐다. 매매·지표 수치는 1회차와 같고, 새 필드와 문장은 독립 재계산 결과와 strategy.md 10.6절 기대 문자열에 모두 맞는다.

## Findings

| # | 심각도 | 파일:줄 | 문제 | 근거 | 수정 제안 | 담당 agent |
|---|---|---|---|---|---|---|
| 1 | Low | `docs/PLAN.md:66`, `docs/PLAN.md:70` | phase3-1 Med 1의 후속 조치가 PLAN.md에는 빠졌다. CLAUDE.md:144와 architecture.md:598-600은 새 명령 `uv run --directory src python -m stock_sim run --config ../config.yaml`로 고쳐졌는데, PLAN.md 두 곳은 아직 옛 명령 `uv run python -m stock_sim run --config config.yaml`이다(1회차에서 `No module named stock_sim`으로 실패한 명령). | `grep -n "python -m stock_sim" CLAUDE.md stock-sim/docs/PLAN.md stock-sim/docs/architecture.md` | PLAN.md 66·70줄을 CLAUDE.md 7절 명령으로 바꾼다. W4 최종 실행 전에 한다. | 오케스트레이터 |
| 2 | Low | `src/stock_sim/metrics.py:118` | `>` → `>=` 변경(고점일 = 같은 평가액 중 저점일에 가장 가까운 날, strategy.md 10.1절 ③)을 고정하는 단위 테스트가 없다. 동작은 맞다. | 직접 호출 `_drawdown([101,100,101,99,99], 9/1~9/5, E0=100)` → peak 09-03, trough 09-04, MDD -1.98%(09-01이 아니라 저점에 가까운 09-03). `[100,99,100,100,98]` → peak 09-04, trough 09-05. `[99,98,99,99,99]` → peak None("초기 자본"), trough 09-02. 세 경우 모두 MDD 값은 `>` 버전과 같다. 기존 `test_mdd_peak_is_start_when_first_day_is_below_capital`은 동률을 다루지 않는다. | `tests/test_metrics.py`에 동률 고점 케이스 1건(위 첫 입력과 기대값)을 추가한다. | implementer |
| 3 | Low | `src/stock_sim/report.py` (677줄) | architecture.md 0절 목표인 파일당 200줄을 넘는다. 1회차 546줄에서 더 늘었다. 1.7절은 초과 시 비공개 헬퍼로 정리하라고만 하므로 위반은 아니다(1회차 #7과 같은 사항). | `wc -l src/stock_sim/report.py` → 677 | 기록만 한다. 모듈을 나누려면 사용자 승인이 필요하다. | – |

## 확인 1. phase3-1 지적 해결 여부

| 1회차 항목 | 결과 | 재현 방법 |
|---|---|---|
| Med 2 캐시 적중 시 `non_integer_price`·`truncation` 소실 | **해결** | `src/`에서 `data.load_daily`를 가짜 클라이언트로 두 번 호출(임시 폴더, stdin 스크립트). ① 비정수 가격만 있음: 1회차 attrs `non_integer_price True`, 파일 `…csv` + `…issues.json` → 캐시 재로드(client None) `from_cache True, non_integer_price True`, 호출 0회. ② 100행(상한) + 비정수: 캐시와 보조 파일을 모두 쓰지 않는다(`잘림 의심 데이터라 캐시에 저장하지 않습니다`). client None 재실행은 `FileNotFoundError`, 클라이언트 재실행은 다시 받아 `truncation True`(호출 1회). ③ 깨끗한 데이터로 `--refresh`하면 예전 `issues.json`을 지운다. 새 테스트 3건(`test_truncated_data_is_not_cached_so_issue_survives_rerun`, `test_non_integer_price_issue_survives_cache_reload`, `test_load_all_keeps_data_issues_after_cache_reload`) 통과. |
| Low 3 numpy 직접 import | **해결** | `grep -rn "numpy\|np\." src/` 0건. `data.py:78,83`은 `(x + 0.5) // 1`(pandas 연산)로 바뀌었다. 회귀 테스트 `test_data_module_does_not_import_numpy`. |
| Low 4·5 (strategy.md 10절에 없던 알림 2종·문장) | 계약 반영 확인 | strategy.md 10.3절 8·9행(`NON_INTEGER_PRICE`, `TRUNCATION_SUSPECT`), 10.1절 ② B0~B6. `report.py:192-197` 문구가 표 틀과 일치. |
| Med 1 진입점 명령 | CLAUDE.md·architecture.md는 갱신, PLAN.md는 남음 | Finding 1 |

실데이터 캐시에는 `*.issues.json`이 없다. 종목 CSV 10개(각 82행)의 open·high·low·close가 전부 정수 문자열이어서 보조 파일이 없는 것이 맞다.

## 확인 2. 수치 불변 (stock_sim을 import하지 않고 캐시 CSV와 result.json만으로 재계산)

| 항목 | 재계산 | result.json | 일치 |
|---|---|---|---|
| 거래 13건 체결가 = 체결일 시가(CSV `open`) | 13/13 | `trades[].price` | O |
| 비용 half-up 정수 (매수 15/100000, 매도 215/100000) | 13/13 | `trades[].cost` | O |
| `signal_date < date` | 13/13 | | O |
| 일별 평가액 20행(현금 + Σ수량×종가) | 전부 일치 | `equity_curve[].equity` | O |
| 최종 평가액 | 99,161,144 | 99,161,144 | O |
| 총수익률 | -0.838856% | -0.8389 | O |
| MDD | -5.144605%, 고점 2026-09-09 → 저점 2026-09-29 | -5.1446, 09-09, 09-29 | O |
| 현금(E0 + Σnet_cash) / 최솟값 | 1,710,144 / 1,010,277(≥ 0) | 1,710,144 | O |
| KOSPI | +3.889421%, 초과 -4.728277%p | +3.8894 / -4.7283 | O |
| 동일가중 | -3.421559% | -3.4216 | O |
| 실현 합 | +925,024 | +925,024 | O |

- `metrics._drawdown`의 `>=` 변경: 평가액이 고점과 같은 날은 `dd = 0`이라 MDD 값과 저점일은 바뀌지 않고, 동률일 때 고점일만 바뀐다. 실데이터 평가액 20개에는 중복값이 없고 E0과 같은 날도 없다. `>`와 `>=` 두 방식으로 모두 재계산해 MDD -5.1446%, 고점 09-09로 같았다. 루프는 `zip(days, equities)`를 앞에서부터 한 번 돌며 당일까지의 값만 쓰므로 look-ahead가 없다.
- `meta.data_source`: `api_calls 0`, `cache_hits 11`, `env DEV`, `fetch 2026-05-31 ~ 2026-09-29`.

## 확인 3. 새 필드 산식 (독립 재계산)

| 필드 | 재계산 | result.json | 일치 |
|---|---|---|---|
| `per_stock[].realized_pnl_sign` | 10종목 모두 `sign(realized_pnl)`. 예: 삼성전자 실현 +1,151,604 → pos, 총손익 sign도 pos. SK하이닉스 실현 0 → zero, 총손익 sign pos. 현대차 실현 -147,704 → neg | 불일치 0 | O |
| `summary.excess_vs_equal_weight_pct` | (-0.8388560% - (-3.4215594%)) = 2.5827%p, sign pos | 2.5827 / pos | O |
| `target.current_return_pct` / `current_return_sign` | -0.8389 / neg (= `summary.total_return_pct`, `actual_return_pct`) | -0.8389 / neg | O |
| `target.gap_pct` | -0.838856 - 2 = -2.8389 | -2.8389 | O |
| `target.gap_amount` / `target_equity` / `achieved` | 102,000,000 - 99,161,144 = 2,838,856 / 102,000,000 / false | 동일 | O |
| `top_contributors.items` | held·closed 8종목을 \|total_pnl\| 내림차순: POSCO홀딩스 -2,068,000, SK하이닉스 +2,025,127, LG에너지솔루션 -839,981, 삼성전자 +296,574, 셀트리온 -172,195 | 순서·pnl 동일 | O |
| `items[].bar_pct` | 100.0, 97.93, 40.62, 14.34, 8.33 (= \|pnl\| / 2,068,000 × 100). 같은 종목의 `per_stock[].bar_pct`와 5/5 동일 | 동일 | O |
| note 합계 | 이익 3종목 +2,415,020, 손실 5종목 -3,253,876, 합 -838,856 = `summary.total_pnl`. 종목은 한쪽에만 들어간다(0인 2종목은 제외) | note 문자열 동일 | O |
| Σ `per_stock[].total_pnl` | -838,856 | `summary.total_pnl` -838,856 | O |

## 확인 4. 문장 규칙 (strategy.md 10.0~10.6)

- 10.6절 실데이터 기대 문자열 8개(①, ②(B3), ③, 다음 조치(3번), 10.4, 10.5, `MDD_BREACH` title·detail·date, `UNDERPERFORM` title·detail·date)는 strategy.md에서 추출한 문자열과 `result.json` 값을 UTF-8로 `==` 비교해 **8/8 일치**했다.
- `insights[].title`은 `["벤치마크 비교", "손익 분해", "리스크"]`이다.
- result.json 전체 텍스트에 U+2212 0건, U+2013 0건, U+2014 0건.
- 조사 병기 패턴(`(이)`, `(가)`, `이(가)`, `을(를)`, `은(는)`, `와(과)`, `(으)로` 등) 0건.
- "달성" 문자열 0건. 음수 진척률 표현이 없다. `progress_raw_pct`(-41.9428)는 필드로만 있다.
- 알림 3건(`MDD_BREACH`, `UNDERPERFORM`, `LOW_SAMPLE`)의 title에 `YYYY-MM-DD` 0건, `date`는 3건 모두 null. `MDD_BREACH`의 구간 날짜는 detail에만 있다.
- 정렬은 warn(MDD_BREACH → UNDERPERFORM) 다음 info(LOW_SAMPLE)로, 10.3절 표 순서다. `LOW_SAMPLE` detail은 "리밸런싱 5회 · 청산 거래 4건"이다.
- 코드 대조: `_spct`/`_swon`은 0을 부호 없이 쓰고 `-0.00%`를 만들지 않는다(`report.py:60-66`). `%p` 분기는 표시값(`_disp`)으로, 알림 조건은 원값(`report.py:167,173`)으로 판정한다(10.0절 4번). 차이는 원값끼리 뺀다(`report.py:226,236,443`). 10.5절 달성 판정은 정수 원(`report.py:444-451`)으로 한다.
- 범위 밖으로 판단한 것: `charts.equity.caption`은 10절 문장이 아니고 architecture.md 5.5절 caption 갱신 대상이다(위임 지시에 따라 finding으로 올리지 않음).

## 확인 5. 공통 규칙·실행

### `uv run pytest` (stock-sim/에서 실행, 원문. ANSI 색 코드만 제거)
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.6.0
configfile: pyproject.toml
testpaths: tests
collected 153 items / 2 deselected / 151 selected

tests\test_backtest.py ................                                  [ 10%]
tests\test_config.py .................                                   [ 21%]
tests\test_data.py .................                                     [ 33%]
tests\test_e2e.py ......                                                 [ 37%]
tests\test_kis_client.py ............                                    [ 45%]
tests\test_metrics.py .............                                      [ 53%]
tests\test_render.py ...............                                     [ 63%]
tests\test_report.py ..............                                      [ 72%]
tests\test_rules.py .....                                                [ 76%]
tests\test_sentences.py .........................                        [ 92%]
tests\test_strategy.py ...........                                       [100%]

====================== 151 passed, 2 deselected in 2.52s ======================
```
- 네트워크 없이 도는지: `socket.socket.connect`, `socket.create_connection`, `socket.getaddrinfo`를 예외로 바꾼 뒤 `pytest.main(--ignore=tests/test_render.py)`을 실행했다. 결과는 `136 passed, 2 deselected`. deselect 2건은 `-m network` 스모크이고 실행하지 않았다.

### R1~R4
- R1: `src/`, `tests/`, `config.yaml`, `output/result.json`에서 `print(`는 0건이다(`test_render.py:438`의 검사 문자열은 제외). JWT 접두 `eyJ`도 0건이다. `Bearer`는 `kis_client.py:193`의 요청 헤더 조립 한 곳뿐이고 로그에 나가지 않는다(1회차에서 확인한 것과 같다). `.env`와 `token_*.json`은 열지 않았다.
- R2: `.py`/`.yaml`/`.toml`/`.json`/`.j2`/`.csv`에서 `trading/`, `order-cash`, `inquire-balance` 0건(`.venv` 제외).
- R3: `config.yaml:2` `env: DEV`, `config.py:24` 기본값 DEV. `config.py:65`에서 PROD는 `prod_approved_by_user`가 true일 때만 허용한다. 자동 전환 분기는 없다.
- R4: result.json에서 `account`, `계좌`, `잔고`, `appkey`, `secret`, `token` 0건(대소문자 무시).
- 산출물: `output/result.json`(schema_version `1.1`)이 있다. `NaN`, `Infinity`, `"None"` 0건.

### 캐시 적중 시 API·토큰 0회
- `cli.py:75-78`: `_all_cached`가 참이고 `--refresh`가 없으면 `client=None`이다. 이 경우 `load_credentials`를 호출하지 않으므로 자격 증명을 읽지 않고 토큰도 발급하지 않는다.
- `data.py:154-161`: 캐시 적중이면 클라이언트를 건드리지 않고 보조 파일만 읽는다. 잘림 의심 데이터는 캐시하지 않으므로 다음 실행에서 `_all_cached`가 거짓이 되어 다시 받는다. 경고를 다시 내기 위한 의도된 동작이다.
- 파일 시각: `result.json`은 15:02:20에 만들어졌고 `token_dev.json` 수정 시각은 14:32:02다. 15:02 실행에서 토큰 파일을 다시 쓰지 않았다(내용은 열지 않음). `meta.data_source.api_calls 0`, `cache_hits 11`.
- 테스트: `test_cache_hit_never_calls_client`, `test_load_all_keeps_data_issues_after_cache_reload`(`src2 == {"api_calls": 0, "cache_hits": 2}`)가 통과했다.

## 확인하지 않은 것
- `.env`, `data/cache/token_*.json`의 내용(금지). `-m network` 스모크(금지). `run` 재실행(지시에 따라 기존 output만 읽음).
- `render.py`, `templates/`, `dashboard.html`(Phase 4 리뷰 담당).
- 관찰(판정 무관): `data/cache/`에 이번 result.json이 쓰지 않는 다른 수집 구간 파일(`*_20250506_20260530.csv` 11개, 14:42~14:44 생성)이 있다. 이번 리뷰 범위의 산출물과는 무관하다.
