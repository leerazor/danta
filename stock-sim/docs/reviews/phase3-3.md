# Phase 3 리뷰 · 3회차 (v2 `intraday_breakout` 구현 1회차)

- 일자: 2026-09-30 · 담당: reviewer
- 대상(워크트리 `intraday-scalping`): `stock-sim/src/stock_sim/*.py`(render.py 제외), `stock-sim/tests/`, `stock-sim/config.yaml`, `stock-sim/output/result.json`, `stock-sim/data/cache/min/`(읽기만)
- 기준: `docs/strategy.md` v2, `docs/architecture.md` 2.0, CLAUDE.md 2절·7절
- 제약 준수: 네트워크 호출 없음(`-m network` 미실행), `.env`·`data/cache/token_*.json` 열람 안 함, 검증 스크립트는 heredoc으로만 실행하고 파일로 남기지 않음

## 판정: **PASS**

High 0 · Med 0 · Low 8. 결과 수치를 바꾸는 오류, look-ahead, 보안 위반은 없다.
엔진 코드를 쓰지 않고 strategy.md 규칙만으로 20거래일 × 2종목을 다시 구현해 돌렸더니, result.json의 체결 74건(시각·신호 시각·수량·가격·비용·사유·실현 손익), 일별 마감 평가액 20개, 매매 중단일, 차단 집계가 모두 원 단위까지 같았다.

## findings

| # | 심각도 | 파일:줄 | 문제 | 근거 | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | Low | `src/stock_sim/backtest.py:111-118`, `cli.py:95-96` | `run_backtest`에 계약(architecture.md 1.5절)에 없는 인자 `session=None`이 있다. 기본값은 09:00~15:20이다. `BAR_MISSING`의 슬롯 수 계산에만 쓰이고 체결에는 영향이 없다 | 코드 확인: `session`은 `slot_count(...)` 호출(122줄)에만 쓰인다. `params = cfg["strategy"]`에는 `session.*`이 없어서 이 인자가 없으면 8절 3번의 "session.open~continuous_end 슬롯 수"를 계산할 수 없다. 즉 계약에 빠진 부분이다 | architecture.md 1.5절 시그니처에 `session: dict \| None = None`을 추가한다(구현 변경 없음) | architect |
| 2 | Low | `metrics.py:229`, `data.py:343`, `data.py:358-360`, `report.py:340-342` | 계약에 없는 인자·함수 4건: `weekly_trade_value(fills, days=None)`, `write_empty_markers(...)`, `load_minutes(..., start_hour, max_pages, defer_empty)`, `build_insights(..., days_label=30)` | 코드 확인. 각각 거래 없는 주를 0으로 채움(표시 전용), 6.2절 "전 종목·전 일자 빈 응답이면 표식 없이 `KisUnsupportedError`"를 종목을 넘나들며 판정하려고 표식 쓰기를 뒤로 미룸, config `data.*` 전달, 11.2절 뒷 절의 "30일"을 `backtest.days`로 채움. 매매 결과에는 영향이 없다 | architecture.md 1.3·1.6·1.7절 시그니처를 구현에 맞춘다 | architect |
| 3 | Low | `backtest.py:171-178`, `backtest.py:277-280` | 대체가 청산(8절 5번)에도 `fill_price`(슬리피지)와 하한가 검사(`PRICE_LIMIT_FILL`)를 적용한다. strategy.md 8절 5번은 "15:30 1분봉 종가에 전량 매도한 것으로 처리"라고만 적고 슬리피지를 적용할지는 말하지 않는다 | 대체가 경로도 `sell()`을 거친다(175·177줄). 기본 `slippage_rate = 0`이고 실데이터에는 대체가 청산이 0건이라(`exit_reasons.eod = 2`는 둘 다 15:15 봉 시가 체결, 재현 스크립트의 fallback 목록도 `[]`) 지금 결과는 바뀌지 않는다. `slippage_rate = 0.001` 옵션을 쓸 때만 차이가 난다 | strategy.md 8절 5번에 "대체 체결가에도 5.2절 슬리피지 적용, 8절 6번 하한가 알림 적용"을 명시한다(현재 구현을 승인하는 방향) | strategy-designer |
| 4 | Low | `report.py:495-521` | `charts.daily_pnl.best`는 수익일(`pnl > 0`) 중에서만, `worst`는 손실일 중에서만 고른다. architecture.md 5.5절은 이 한정을 적지 않았다 | 코드 확인. 5.5절 caption 규칙("수익일 또는 손실일이 없으면 해당 절을 뺀다")과는 맞는다. result.json: best 09-04 +522,241, worst 09-03 -1,126,529. `daily[]`에서 다시 뽑아도 같다 | 5.5절에 "best는 pnl>0 중 최대, worst는 pnl<0 중 최소, 해당일이 없으면 null"을 명시한다 | architect |
| 5 | Low | `report.py:204-211` | `DATA_MISSING`·`NON_INTEGER_PRICE`·`TRUNCATION_SUSPECT`는 종목마다 한 건으로 줄인다. strategy.md 11.3절은 "같은 코드가 여러 건이면 (날짜, 종목코드) 오름차순"이라고만 적었다 | 코드 확인. 일봉과 분봉이 같은 종목에 같은 이슈를 각각 낼 수 있어서 중복을 없앤 것이다. 표시 전용이다. 실데이터에서는 이 세 코드가 0건이다 | strategy.md 11.3절 정렬 규칙 아래에 "위 3개 코드는 종목당 1건"을 추가한다 | strategy-designer |
| 6 | Low | `tests/test_backtest.py` | strategy.md 4.6절 5번("매도 체결로 `halted`가 참이 되면 같은 봉의 대기 매수는 취소")을 직접 검증하는 단위 테스트가 없다 | 테스트 목록 확인(케이스 6은 대기 매수가 없는 상황이다). 동작은 맞다. 프로브로 확인했다: AAA는 손계산 봉, BBB는 같은 봉을 +25분 옮긴 입력이다. `daily_loss_limit_pct=0.01`이면 09:50에 AAA 매도 후 BBB 매수가 체결되고, `0.002`이면 AAA 매도로 halted가 되어 같은 봉 BBB 매수가 취소된다(체결 2건, halted True) | 위 프로브를 `test_backtest.py`에 테스트로 추가한다 | implementer |
| 7 | Low | `pyproject.toml:4` | description이 "KIS 과거 일봉 기반 …"으로 v1 문구 그대로다 | 파일 확인. 동작에는 영향이 없다 | "KIS 과거 분봉 기반 …"으로 고친다 | implementer |
| 8 | Low | `report.py`(789줄), `data.py`(496), `backtest.py`(295), `kis_client.py`(282), `config.py`(260), `metrics.py`(243) | 200줄 목표를 넘는 파일이 6개다 | `wc -l` | 분할은 사용자 승인 사항이라 기록만 한다 | (사용자 결정) |

계약과 다른 점(implementer 보고 목록)의 판정:

| 항목 | 결과가 바뀌나 | 처리 |
|---|---|---|
| `run_backtest(..., session=None)` | 아니오(BAR_MISSING 수만. 실데이터는 무효 슬롯 0) | 문서 갱신으로 충분(#1) |
| `weekly_trade_value(fills, days=None)` | 아니오(표시) | 문서 갱신(#2) |
| `load_minutes(..., start_hour, max_pages, defer_empty)`, `write_empty_markers` | 아니오(수집 경로. 6.2절 규칙을 그대로 구현) | 문서 갱신(#2) |
| `build_insights(..., days_label=30)` | 아니오(문장. 기본 설정에서 "30일" 그대로) | 문서 갱신(#2) |
| daily_pnl best/worst를 부호별로 한정 | 아니오(표시) | 문서 갱신(#4) |
| DAY_SKIPPED = 그 날 0봉인 종목도 포함 | 아니오. 8절 4번 "유효 봉 < min_bars_per_day"에 0봉이 포함되므로 계약과 같다 | 조치 없음 |
| 대체가에 슬리피지·하한가 검사 | 기본 설정에서는 아니오, 슬리피지 옵션에서는 예 | 문서 명확화(#3) |
| 일부 알림 종목별 중복 제거 | 아니오(표시) | 문서 명확화(#5) |
| 200줄 초과 6개 | – | 기록(#8) |

## 실행·재현 기록

### 1. 테스트 (stock-sim/에서 직접 실행)
```
uv run pytest -q
141 passed, 4 deselected in 5.37s
```
- 네트워크 차단 재실행: `socket.socket.connect`와 `socket.create_connection`을 예외로 바꾼 뒤 `pytest.main(["-q"])` → `141 passed, 4 deselected in 5.28s`. 네트워크 없이 돈다. deselected 4건은 `-m network` smoke다.

### 2. 독립 재현 (엔진 코드 import 없음)
`csv` 모듈로 `data/cache/min/*.csv` 40개와 일봉 캐시를 읽고, strategy.md 3.4(리샘플)·4.1(지표)·4.2(정수 비교식 8단계와 차단 집계 순서)·4.3·4.4·4.5(의사코드)·4.6·5.2(비용 `(amount×15+50000)//100000`, `(amount×215+50000)//100000`)·5.4(`realized×100 ≤ −E_start`)·6(`budget = E_start//2`, `qty = alloc×100000 // (price×100015)` 후 검증)·8절 3·5·6번만으로 다시 구현했다.

| 항목 | 재현 | result.json |
|---|---|---|
| 거래일 | 20 | 20 (`meta.period.trading_days`) |
| 종목·일별 유효 5분봉 | 모든 날 76 (무효 슬롯 0 → BAR_MISSING·DAY_SKIPPED 0건) | 해당 알림 없음 |
| 체결 | 74건, **튜플 74개 전부 일치**(date, time, signal_time, code, side, qty, price, cost, reason, realized_pnl) | 74 |
| 최종 평가액 | 95,253,068 | 95,253,068 |
| 일별 `e_end`·`halted` | 20일 전부 일치 | – |
| 매매 중단일 | 2일(09-01, 09-03) | `halt_days` 2 |
| 대체가 청산 | 0건 | `EOD_FALLBACK` 없음 |
| 차단 집계 | breakout 161, halt 6, cutoff 17, range 20, volume 79, vwap 2, max_entries 0, cooldown 0 | 같음 |
| UNTRADABLE·QTY_ZERO | 0건 | 해당 알림 없음 |

### 3. result.json 항등식(architecture.md 5.7절)과 체결 산술
- 5.7절 1~8번 모두 OK(스크립트로 판정). 텍스트에 `NaN`·`Infinity` 없음.
- 체결 74건 전부: `amount = qty × price`, `cost`가 half-up 규칙과 같음, `net_cash` 부호 규칙과 같음, `qty`는 양의 정수. 오류 0.
- 체결 순서대로 현금을 누적한 최저값은 241,399원(음수 없음). 종료 현금 95,253,068 = `final_equity`.
- 매 거래일 종료 시 종목별 순보유 0. `id`는 1..74 연속.
- 같은 봉 다중 체결 5곳 모두 (매도 먼저 → 매수, 종목코드 오름차순)을 지켰다. 예: 09-03 10:35 BUY 000660 → BUY 005930, 08-31 12:30 SELL 000660 → SELL 005930.
- 종목·일별 매수는 최대 3건(상한 4 이하). 매수 체결 시각 최댓값은 14:40(≤ 14:50). 모든 `signal_time`은 체결 시각보다 이르다.
- `closed_trades` 37건: 매수·매도 fill 대응, `gross_pnl`·`cost`·`pnl`·`hold_minutes` 재계산이 모두 일치.

### 4. KPI 직접 재계산
| KPI | 재계산 | result.json |
|---|---|---|
| 승률 | 11/37 = 29.7297% | 29.7297 |
| 손익비 | 0.8793 | 0.8793 |
| 연속 손실 | 9 | 9 |
| 평균 보유 시간 | 60.8분 | 60.8 |
| MDD | 95,253,068 / 100,285,888 − 1 = −5.0185% | −5.0185 (고점 08-31, 저점 09-29) |
| 회전율 | 1843.7199% | 1843.7199 |
| KOSPI 수익률 | 일봉 캐시 09-29 종가 / 08-31 시가 6,613.58 − 1 = +3.8894% | 3.8894 |
| 동일가중 | +10.0134% | 10.0134 |
| G / K / P | −626,250 / 4,120,682 / −4,746,932 (P = G − K) | 같음 |
| 매매 중단 판정 | 09-01 손실 1,071,036 ≥ 1,002,858.88(E_start의 1%), 09-03 손실 1,126,529 ≥ 1%. 09-03 halted 판정은 재현과 일치 | halted true 2일 |

### 5. 문장(strategy.md 11절) 대조
- ① "…KOSPI(+3.89%)보다 8.64%p 낮았습니다. …동일가중(+10.01%)보다 14.76%p 낮았습니다." 원값 차이는 −8.6363, −14.7603이다. 일치.
- ② 종목 절이 코드 오름차순(SK하이닉스 000660 → 삼성전자 005930)이다. 일치.
- ③ MDD −5.0185% ≤ −5% → "임계 -5.00%를 넘었습니다."와 `MDD_BREACH` 알림이 함께 나온다. 일치.
- 다음 조치: 데이터 알림 0, G < 0이라 4번 규칙이다. 손실 절댓값 상위가 삼성전자(2,425,377) → SK하이닉스(2,321,555) 순이다. 일치.
- 11.5: g = 6.7469 → 6.75%p, A = 102,000,000 − 95,253,068 = 6,746,932. 일치.
- 알림: MDD_BREACH·LOSS_STREAK·UNDERPERFORM(빨강) → COST_DRAG(주황) → DAILY_LOSS_HALT·OVERNIGHT_GAP_NOTE·LOW_SAMPLE(info). 순서·색·문구가 11.3절 표와 같다.

### 6. 분봉 캐시 점검(읽기만)
- 40개 파일 모두 첫 봉이 `09:00`이다. `data.minute_time_label: start` 판단과 맞는다.
- 40개 파일 모두 `15:30` 봉이 있다. 20개 파일에는 `16:00` 봉도 있다. 15:20 이후 시각은 `{15:30}` 또는 `{15:30, 16:00}`뿐이다.
- 40개 파일 모두 첫 1분봉 시가가 일봉 시가와 같고, 15:30 봉 종가가 일봉 종가와 같다(불일치 0).
- 15:30·16:00 봉은 `resample_bars`의 `m < continuous_end` 필터(`strategy.py:52`)로 5분봉에서 빠진다. `auction_closes`는 `time == "15:30"`만 쓴다(`strategy.py:134`). 그래서 16:00 봉은 신호에도 대체가에도 들어가지 않는다.

## 확인한 항목 (통과)

- **R1**: 워크트리에 `.env*` 파일이 없다(Glob 0건, 복사 없음). `find_env_file`(`config.py:158-174`)은 `STOCK_SIM_ENV_FILE`를 먼저 보고, 없으면 상위 폴더를 탐색하며 경로만 반환한다. 로그에는 경로만 남긴다(`config.py:203`). 앱키는 `_mask`로 앞 4자리만 남기고, 시크릿·토큰·헤더는 로그·예외에 없다(`_scrub`로 msg 값도 치환). `src/`에 `print(` 0건. `result.json`에서 `Users|.env|token|secret|appkey` 0건. 긴 키 형태 문자열(`PS[A-Za-z0-9]{30,}`, 120자 이상 base64형)도 0건.
- **R2**: `stock-sim/`(.venv·data 제외 아님, 전체) 검색에서 `trading/`, `order-cash`, `inquire-balance`는 `docs/reviews/*.md`의 규칙 인용문에만 나온다. src·tests·config·output에는 0건. `KisClient` 경로 상수는 토큰 1개와 quotations 3개다. `test_rules.py`가 금지 문자열 6종(조각 결합), requests import 위치, 공개 메서드 4개를 강제한다.
- **R3**: 기본값 `kis.env: DEV`(config.yaml, `DEFAULTS`). PROD는 `prod_approved_by_user is True`가 아니면 `ConfigError`. base URL은 생성자 `env` 하나로만 정해진다. 미지원 시 `KisUnsupportedError`에 고정 문안("자동으로 PROD로 전환하지 않습니다")을 쓰고 전환 분기가 없다.
- **R4**: result.json·per_stock·alerts에 계좌·잔고·개인정보가 없고 시뮬레이션 수치만 있다.
- **R5/look-ahead**: `hh·ll·sv·xl`은 날짜별 `shift(1)` 후 `rolling(N or M, min_periods)`로 봉 k 자신을 빼고 계산한다(`strategy.py:77-82`). `pv·cv`는 봉 k를 포함한 당일 누적이다. 매수·매도 모두 다음 유효 봉 시가에 체결하고, 매수는 `slot == signal_slot + 1`일 때만 체결한다(`backtest.py:222`). 15:15 이후 봉은 판정하지 않는다. `test_lookahead_*` 2건(봉 k+1 이후 값 변경, 유효 봉 수 유지 / 전일 변경)과 `test_flags_up_to_k_do_not_change_...`가 있다. 하루 봉 수 판정(DAY_SKIPPED)만 하루 전체를 보는데, 8절 4번이 허용한 데이터 품질 필터다.
- 비용: 매수·매도 양쪽에 half-up 정수 연산으로 적용한다. 수량은 정수이고, 현금이 음수가 되면 AssertionError를 낸다. 매일 마감 포지션이 0인지 assert한다.
- 체결 순서, halted 시 같은 봉 대기 매수 취소(프로브 확인), 쿨다운(매도 체결 봉 번호 기준), 횟수 상한(체결 기준 카운트), 강제 청산 사유 규칙(대기 매도가 있으면 EXIT_BREAKDOWN, 대체가면 EXIT_EOD·signal_time None).
- 캐시: 전부 적중하면 `client=None`이다(`cli.py:83-86`, result `api_calls 0`, `cache_hits 43`). 분봉 0행 표식, 잘림 시 저장하지 않음, `--refresh`는 일봉에만 적용.
- 토큰 캐시: 만료 1시간 전까지 재사용한다(`kis_client.py:113`). env 불일치면 재사용하지 않는다.
- 테스트 존재: 손계산 10.2~10.6(지표 전 행, 체결·장부), 보조 케이스 2·3·4·5(15:15·15:30 대체)·6·7·8, 8절 엣지(슬롯 건너뜀, 매도 이월, 상·하한가, DAY_SKIPPED/BAR_MISSING 63/PRICE_ANOMALY, QTY_ZERO), 9.2절 항등식, 11.6절 기대 문자열(`test_report.py:122-137`), 예시 파일 키 구조, 5.7 항등식.
- config.yaml이 architecture.md 3절 v2 스키마와 키·값이 같다. v1 키는 거부한다.
