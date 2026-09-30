# Phase 2 리뷰 (2회차) — v2 계약: strategy.md v2 · architecture.md 2.0 · result.example.json 2.0

리뷰일 2026-09-30 · 담당 reviewer · 대상 커밋: 워크트리 `intraday-scalping` 직전 커밋
검토 대상: `stock-sim/docs/strategy.md`(v2), `stock-sim/docs/architecture.md`(2.0), `stock-sim/docs/result.example.json`(schema 2.0)
기준 문서: CLAUDE.md 1·2·7·8절, `docs/research/intraday-data.md`, `docs/research/market-rules.md`

## 판정: **PASS** (High 0 · Med 1 · Low 6)

Med 1건(strategy.md 11.6절 기대 문자열과 8절 3번 `BAR_MISSING` 규칙의 충돌)은 구현 자체가 아니라 **테스트 기대값**의 모순이라 구현 착수를 막지 않는다. 다만 architecture.md 8.3절이 11.6절을 `test_report.py` 기준으로 지정하므로, implementer가 `test_report`를 쓰기 전(즉 W3 진행 중)에 strategy-designer가 고쳐야 한다. Low는 기록만.

## findings

| # | 심각도 | 문서·절 | 문제 | 근거 | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | **Med** | strategy.md 11.6절 ↔ 8절 3번·11.2절·11.3절 8번 | 10절 손계산 fixture(하루 유효 5분봉 13개, `min_bars_per_day = 1`)는 8절 3번대로면 무효 슬롯 76 − 13 = **63개**가 `BAR_MISSING`(warn, "AAA 5분봉 63개 결측")으로 집계된다. 그러면 11.6절의 "알림: warn 없음"과 "다음 조치 (4번)" 기대값이 틀리고, 11.2절 규칙 2(데이터 품질 알림 ≥ 1건 → "수치를 해석하기 전에 점검 필요의 데이터 알림 1건을 먼저 확인하세요.")가 먼저 걸린다. `flags.only_baseline_alerts`도 false가 된다. architecture.md 8.3절이 11.6절 문자열을 `test_report.py` 기준으로 지정하므로 implementer가 그대로 쓰면 테스트 기대값이 규칙과 모순된다 | 8절 3번: "종목·날짜별 무효 슬롯 수를 alert `BAR_MISSING`으로 남긴다. 집계 범위: 그 종목이 `DAY_SKIPPED`가 아닌 날의 무효 슬롯만 센다". 3.4절: 하루 76슬롯. 10.1절: 봉 13개, `min_bars_per_day = 1`. 11.3절 8번 조건 "무효 슬롯 합 ≥ 1". 11.6절: "warn 없음", "다음 조치 (4번)" | 둘 중 하나로 확정: (a) 11.6절 기대값을 규칙대로 고친다 — 알림에 `BAR_MISSING` warn "AAA 5분봉 63개 결측" / "AAA · 1거래일에 걸침" 추가, 다음 조치는 11.2절 2번 문장("수치를 해석하기 전에 점검 필요의 데이터 알림 1건을 먼저 확인하세요. 30일 표본이므로 …"), `only_baseline_alerts = false`. (b) 10.1절 fixture에 `session.continuous_end = "10:05"`(슬롯 13개)를 명시해 무효 슬롯 0으로 만들고 11.6절은 그대로 둔다. 어느 쪽이든 "무효 슬롯 수 = `session.open`~`continuous_end` 슬롯 수 − 유효 봉 수"임을 8절 3번에 한 줄로 못 박는다(마지막 유효 봉 이후 슬롯도 센다는 뜻) | strategy-designer |
| 2 | Low | architecture.md 11절 6·7번 | "strategy.md 8절 3번에 명시가 없다", "…로 해석했다"는 strategy.md 개정 전 문장이다. 현재 strategy.md 8절 3번은 `BAR_MISSING` 집계 범위를, 8절 7번은 `PRICE_ANOMALY` 당일 한정을 명시하고 있어 "해석"이 아니라 "일치"다 | strategy.md 8절 3번 "**집계 범위**: 그 종목이 `DAY_SKIPPED`(4번)가 **아닌 날**의 무효 슬롯만 센다", 8절 7번 "**당일 한정**" | 두 행을 "strategy.md 8절 3·7번과 같다"로 고친다(내용 변경 없음) | architect |
| 3 | Low | strategy.md 9.2절 6번 ↔ 4.5절·8절 4번 | look-ahead 테스트 "봉 k+1 이후 봉을 바꿔도 봉 k+1 시가까지의 체결이 불변"은 하루 시작 시점에 그 날 전체 유효 봉 수로 `active`(`DAY_SKIPPED`)를 정하는 4.5절과 충돌할 수 있다(뒤 봉의 volume을 0으로 바꾸면 유효 봉 수가 `min_bars_per_day` 아래로 떨어져 그 날 체결이 전부 사라진다). 하루 단위 데이터 품질 필터라 매매 신호의 look-ahead는 아니지만 테스트 조건이 불완전하다 | 4.5절 `active = [code … if 유효 봉 수(code, d) ≥ min_bars_per_day]`, 9.2절 6번 | 9.2절 6번에 "유효 봉 수(무효 슬롯 여부)는 유지한 채 값만 바꾼다"를 덧붙이고, 4.5절 또는 8절 4번에 "하루 봉 수 판정은 그 날 전체 데이터를 보는 데이터 품질 필터이며 신호 계산에는 쓰지 않는다"를 한 줄 적는다 | strategy-designer |
| 4 | Low | strategy.md 4.4절 3번 ↔ 8절 5번 | 15:10 봉 종가에 `EXIT_BREAKDOWN` 신호가 났는데 15:15 유효 봉이 없어 8절 5번 대체가(15:30)로 청산되는 경우, 사유를 `EXIT_BREAKDOWN`으로 적는지 `EXIT_EOD`로 적는지 정해져 있지 않다. 손익에는 영향이 없고 `summary.exit_reasons`·`reason_label`만 갈린다 | 4.4절 3번은 "같은 봉 시가에 한 번만 팔고 사유는 `EXIT_BREAKDOWN`"(15:15 봉 존재 전제), 8절 5번은 사유를 언급하지 않음 | 8절 5번에 "대기 매도 신호가 있었어도 대체가 청산은 `EXIT_EOD`로 적고 `signal_time`은 None"(또는 반대) 한 줄 추가 | strategy-designer |
| 5 | Low | architecture.md 5.1·5.5절, result.example.json `charts.equity.benchmark_points` | 좌표 소수 1자리의 반올림 방식이 없다. 예시 파일은 half-up(250 × (2 − 0.3) / 4 = 106.25 → `106.3`, 56.25 → `56.3`)인데 Python `round`/`%.1f`는 `106.2`/`56.2`를 낸다. 계약 테스트가 "형식·범위만" 보므로 판정에는 영향이 없다 | 재계산: `equity_points` 21점은 `%.1f`와 완전 일치, `benchmark_points`는 2점(36.0, 576.0)만 0.1 차이 | 5.1절 "기하 값" 행에 "반올림 방식은 구현이 정하며 계약 테스트는 형식만 본다"를 명시하거나 half-up으로 통일 | architect |
| 6 | Low | strategy.md 8절 6번 ↔ architecture.md 4.2절 8번 | 상·하한가 판정이 "체결 봉 시가(원시 분봉) vs 전일 **일봉** 종가(수정주가)"다. 구간 안에 권리락·분할이 있으면 비율이 틀어져 매수가 전부 `UNTRADABLE_SKIP`될 수 있다. architecture는 smoke test 6단계에서 대조하겠다고만 한다 | architecture.md 4.2절 8번 "분봉은 원시 가격 … 일봉은 수정주가", 8.4절 6단계 | 전일 기준가를 "전일 마지막 유효 5분봉 종가(없으면 15:30 1분봉 종가, 없으면 일봉 종가)"로 바꾸면 같은 가격 체계끼리 비교된다. 30일 구간·2종목에서 실제 발생 가능성은 낮으므로 기록만 | strategy-designer(규칙) / architect(데이터 근거) |
| 7 | Low(정보) | CLAUDE.md 8절 섹션 매핑 표 ↔ architecture.md 5.4절 | 대시보드 세 자리(도넛 → 종목별 거래대금 비중, KPI ④ → 평균 보유 시간, 스택 바 → 일별 손익 막대)와 매매 내역 표 추가가 CLAUDE.md 8절 표와 다르다. 두 문서 모두 "오케스트레이터 결정, 사용자 최종 확인 전"으로 표기해 두었으므로 문서 결함은 아니지만, W3 시작 전 사용자 확인과 CLAUDE.md 8절 표 갱신이 남아 있다 | strategy.md 12·14절 4번, architecture.md 5.4절 머리말·11절 10번, PLAN.md V2-5 | 오케스트레이터가 사용자 확인 후 CLAUDE.md 8절 표를 갱신(agent 산출물 아님) | (오케스트레이터) |

## 확인한 항목 (통과)

### 보안·공통 규칙
- R1: 세 문서와 예시 JSON에 키·시크릿·`.env` 값 없음. `.env` 탐색 설계(architecture 1.1절)는 환경변수 `STOCK_SIM_ENV_FILE` → 상위 폴더 탐색이며 "복사하지 않는다", "로그에는 경로만" 명시. `load_credentials`는 키 이름만 언급.
- R2: `stock-sim/` 전체에서 `trading/`, `order-cash`, `inquire-balance` 검색 → `docs/reviews/*.md`(규칙 인용문)만 5건, strategy.md·architecture.md·result.example.json 0건. `KisClient` 공개 메서드 4개(`get_token`, `daily_prices`, `index_daily`, `minute_prices`)만 정의, `test_rules.py`로 강제.
- R3: `kis.env` 기본 `DEV`, base URL은 이 값 하나로 결정. `PROD`는 `prod_approved_by_user: true` 없이는 `ConfigError`. DEV 분봉 미지원 시 "자동으로 PROD로 전환하지 않는다" 고정 문안(7절), smoke test 3단계 "PROD로 바꾸지 않는다".
- R4: 예시 JSON에 `NaN`, `APP_KEY`, 계좌 문자열 없음. 시뮬레이션 수치만.
- 사용자 확정 사항 대조: 유니버스 005930·000660(strategy 3.1, config 3절), 구간 2026-08-31~09-29 달력 30일(`backtest.end` 고정 + `days: 30`), 초기 자본 1억, 매수 0.00015, 매도 0.00215, 슬리피지 0 — 모두 일치. market-rules.md 결론(매도 0.215% = 0.015% + 0.05% + 0.15%)과 일치.

### 중점 1 — look-ahead
- 매수·매도 신호는 봉 `k` 종가 시점 정보만(4.1절: `HH/LL/SV/XL`은 `k−N..k−1`, `PV/CV`는 `0..k`), 체결은 다음 유효 봉 `k+1` 시가(4.2·4.3·5.1절). architecture 1.4절 플래그 정의가 동일(`hh, ll, sv, xl` 직전 봉, `pv, cv` 당일 누적 포함).
- VWAP·거래량 평균·채널의 현재 봉 포함/제외가 명확: 채널·거래량 합은 현재 봉 제외, VWAP은 현재 봉 포함(종가 시점 정보라 누수 아님).
- 강제 청산은 시각 조건(15:15 봉 시가), 대체 체결가는 장 마감 후 확정값(15:30 단일가 종가 → 일봉 종가 → 마지막 유효 봉 종가)으로 포지션 정리 전용. 사이징은 `E_start(d)`(전일 종료 현금)와 체결 시점 현금만.
- 매수 신호에 봉 안의 고저 터치 체결 없음(5.1절 "봉 안의 저가에 닿았다고 그 가격에 체결한 것으로 보지 않는다").
- 예시 JSON 24건 전부 `time − signal_time = 5분`(EOD는 `signal_time: null`), 매수 신호 봉 시작 시각 ≤ 14:45, 첫 매수 09:35(= `k=6` 봉 종가 신호).

### 중점 2 — 손계산 예시 재계산 (Python으로 원 단위 검증)
- 10.2절 표 13행: `S×V`, `PV`, `CV`, `VWAP`, `HH`, `LL`, `SV`, `XL` 전부 일치.
- 10.3절 판정: 봉 4 매수 신호(돌파·변동폭 600,000 ≥ 503,000·거래량 45,000 ≥ 31,500·VWAP 1,388,280,000 > 1,382,530,000), 봉 8 등호 보유, 봉 9 매도 신호(100,600 < 100,900), 봉 12 돌파 참·쿨다운 12 < 13 차단 — 일치. `breakout` 집계 2(봉 4·12; 봉 5·6은 보유 중이라 판정 없음) 일치.
- 10.4절: 수량 `floor(50,000,000 / 100,715.105) = 496`(정수식 `50,000,000×100,000 // (100,700×100,015)`도 496), 거래대금 49,947,200, 매수 비용 7,492, 현금 50,045,308, 매도 거래대금 49,848,000, 매도 비용 107,173, 현금 99,786,135, 손익 −213,865, 수익률 −0.00428118 — 전부 일치.
- 10.6절: G −99,200, K 114,665, G−K = −213,865 = E(dn) − E0, 회전율 0.50004542 — 일치.
- 10.7절 케이스 2(매도가 100,700/100,900/101,000 → 비용 107,386/107,600/107,706, 손익 −114,878/−15,892/+33,602), 케이스 5(EOD +33,602, 350분/365분), 케이스 7(4.5 → 5, 21.5 → 22) — 일치. 1.1절 본전 표(필요 상승폭 161.3/230.5/345.7/691.5/1,383원, 최소 틱 2/3/4/2/2) — 일치. 1.2절 √t 어림(0.10/0.23/0.39/0.55%) — 일치.
- 11.6절 문장 수치(−0.71%p, −1.01%p, 2,213,865원) — 일치(단, 알림·다음 조치 기대값은 finding 1).

### 중점 3 — result.example.json 항등식 (architecture 5.7절, Python으로 실행)
- 파싱 성공. 항등식 1~8 **전부 통과**: 최종 평가액 − 초기 자본 = 총손익 = 실현 손익 = G − K(577,200 − 1,370,204 = −793,004) / 자산 곡선 끝값 = `daily[-1].e_end` = `final_equity`, `e_start` 연쇄 / Σ daily.pnl = Σ closed.pnl = Σ per_stock.realized_pnl / 건수(12=12=12, 24 = len(trades), 5+7+0=12) / Σ amount = 1,190,979,600 = Σ daily.trade_value = 도넛 total, Σ cost = 1,370,204 / Σ net_cash = 총손익, sell_value − buy_value = G / halt_days 1 = halted 행 수, breakout 68 = 12 + 56 = 7개 차단 합 / 부호 플래그 전부 일치(summary·daily·trades·closed·per_stock), 도넛 끝 100.0.
- 체결 24건 개별: `amount = qty×price`, 비용 half-up(매수 15/10만, 매도 215/10만), `net_cash` — 전부 일치. 매수 12건의 수량이 6절 사이징(`min(floor(E_start×0.5), 현금)`, `floor(alloc/(price×1.00015))`)과 전부 일치. 현금은 항상 ≥ 0.
- 청산 12건: `gross_pnl`, `cost`(매수+매도), `pnl`, `return_pct`(4자리), `hold_minutes`, `buy/sell_fill_id`·`closed_id` 상호 참조 — 전부 일치. 청산 id는 (매도 일시, 코드) 순.
- 일별 20행: `pnl = e_end − e_start = Σ net_cash`, 거래대금·비용·건수·`return_pct` 일치. `halted`는 5.4절 규칙으로 재계산해 09-08만 참(첫 매도 −689,578 > −1,000,531, 두 번째 누적 −1,112,362 ≤ −1,000,531) — 일치. 중단 후 매수 없음.
- 지표 재계산: MDD −1.4165%(고점 08-31 100,321,045 → 저점 09-10), 승률 41.6667%, 손익비 0.9713, 연속 손실 2, 평균 보유 86.7분, 회전율 598.9497%, 비용/자본 1.3702%, 초과수익 −2.143/−2.893%p, 청산 사유 10/2, 일평균 0.6/1.2, 종목별 `return_pct`·`contribution_pct`·`avg_hold_minutes`·`win_count`·`trade_value_share_pct`, `bar_pct` 41.41 — 전부 일치.
- 차트: `equity_points` 21점 `%.1f`와 완전 일치, `benchmark_points`는 반올림 방식 차이 2점(finding 5), 벤치마크 `value = 1e8×close/4000` 일치, 스파크라인 첫 점 11.6 검산 일치, `daily[].segments.height_pct = |pnl|/1,112,362×100` 전 행 일치, 주별 거래대금 막대 5개(ISO 36~40주) 값·색 임계(75/50/25) 일치, `x_labels` = ISO 주 첫 거래일 5개, `show_label` 동일 5일, `daily_pnl` 4/5/11일 일치, `blocks.bar_pct`·caption 내림차순 일치.
- 문장: 인사이트 3개·다음 조치(11.2절 3번)·손익 기여 문구(11.4절)·목표 진척(2.79%p, 2,793,004원)·`daily_pnl.caption`·`trade_table.caption` — 11절 틀과 일치. 알림 순서(warn: UNDERPERFORM, COST_DRAG → info: DAILY_LOSS_HALT, OVERNIGHT_GAP_NOTE, LOW_SAMPLE)와 발생 조건(초과 −2.143 ≤ −2, 비용 1,370,204 ≥ 1,000,000, 연속 손실 2 < 3, MDD > −5%) 일치.
- 사례 포함 확인: 손실 청산 7건·손실일 5일·중단일 1일·거래 없는 날 11일·EOD 2건·표 잘림(24 중 20, `in_table=false`가 id 1~4)·빈 배열(`excluded`, `empty_days`)·목표 미달(진척 0).

### 중점 4 — 두 문서 정합성
- config 키: strategy 2절 22개 키가 architecture 3절에 이름 그대로(`strategy.*` 12개, `session.*` 2, `backtest.days/initial_cash`, `costs.*_rate` 3, `target.monthly_return`). architecture 추가 키(`backtest.end`, `data.*`, `kis.*`)는 수집 설정. v1 키 거부 규칙 있음.
- 사유 코드 3개(`ENTRY_BREAKOUT`/`EXIT_BREAKDOWN`/`EXIT_EOD`)와 알림 코드 19개가 두 문서에서 동일(architecture 4.8절 발생 모듈 분배 = strategy 11.3절 목록). 색·`date` 사용 코드 6개도 일치.
- 체결 순서(매도 전부 → 매수, 각 종목코드 오름차순), 대기 매수 취소 규칙(halted / 다음 슬롯 무효 / 상한가), 일별 손실 한도(두 종목 합산, 매도 체결마다 갱신, 보유는 유지), 지표 정의(MDD E0 포함, 회전율, 종목별 수익률 분모, 연속 손실 정렬) — 일치.
- 비교식 등호: 돌파 `>`, 변동폭 `≥`, 거래량 `≥`, VWAP `>`, 청산 `<` — 두 문서 같음. 정수·유리수 비교 요구 같음.
- architecture 11절 1·2·3·4·5·8·9·10번은 현재 strategy.md와 맞음(6·7번은 finding 2, 표현만).
- architecture 5.6절 빈 경우 표와 strategy 8절 8번(거래 0건: null 규칙, `NO_TRADES`, 차단 집계 유지) 일치.

### 중점 5 — 구현 가능성·결정성
- 반올림: half-up 정수식 `(거래대금×율 + 50,000) // 100,000`, 체결가 half-up, 은행가 반올림 금지 명시. 비율은 원값 저장·표시 시 2자리.
- 결측: 1분봉 생략 시 채우지 않음(양 문서), 무효 슬롯은 `k` 번호 없음, 매도 대기 이월·매수 대기 취소 규칙, `min_bars_per_day` 미달 종목만 휴식.
- 동시 신호 현금 배분: 000660 먼저, `alloc = min(budget, 현금)`, 예산 합 ≤ E_start 검증(config).
- 수량 0·상한가·하한가·이상 등락·마지막 날·강제 청산 봉 없음·종목 분봉 전체 없음·응답 잘림 — 8절 16항목 처리 명시.
- 시각 라벨(시작/끝) 미확정은 `data.minute_time_label` 한 곳 + `normalize_minute_rows` 한 곳으로 격리, smoke test 5단계로 확정.

### 중점 6 — 보안 (위 "보안·공통 규칙" 참조). 추가로 토큰 캐시(만료 1시간 전 재사용, 분당 1회), 분봉 캐시 적중 시 HTTP 0회·토큰 미발급, `--refresh`가 분봉에 미적용.

### 중점 7 — 대시보드 매핑
- architecture 5.4절이 CLAUDE.md 8절 11개 섹션 전부 + 매매 내역 표 + 한계 고지를 JSON 필드로 매핑. 세 자리 대체는 finding 7(사용자 확인 대기).
- 부호·색: `sign`/`*_sign` 3값, `sign_color`(pos `#1428A0`/neg `#B0472F`), 어두운 배경 `sign_color_dark`, 일별 손익 막대는 조각 색이 곧 부호(gain `#1428A0`, loss `#B0472F`), 알림 색 3단계. 예시 JSON의 부호 플래그는 전부 값과 일치.
- 템플릿 무계산: 좌표·`height_pct`·`bar_pct`·`conic_gradient`·caption·문장이 전부 JSON에 완성값으로 존재. `render()` 금지 항목에 수치 계산 명시. 외부 JS 없음 규칙(`test_render.py`).

### 중점 8 — 과최적화·한계 고지
- 2절 "최근 30일 결과를 보고 값을 바꾸지 않는다", 파라미터마다 사전 근거(비용 허들·관행·운영 상한) 표기, 실데이터 미실행 명시(머리말).
- 13절 한계 고지 9개, `meta.disclaimers` 9개(비용 허들, 30일 표본, 고정 파라미터, 체결 가정, 일별 MDD, 벤치마크 조건 차이, 결제·최소 수수료·하한가 가정, 업종 집중, 투자 권유 아님)와 `meta.slippage_note` 존재.

## 재현 방법
- 손계산·항등식 검증은 `stock-sim/` 상위 워크트리 루트에서 `python -c`(Python 3.11.9)로 실행. 10.2절 13봉을 그대로 입력해 4.1절 정의로 지표·플래그를 다시 계산했고, `result.example.json`은 `json.load` 후 5.7절 항등식 8개·체결별 비용식·사이징식·일별 halted·MDD·승률·손익비·연속 손실·좌표를 재계산해 대조했다(임시 파일 없음).
