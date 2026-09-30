# Phase 2 리뷰 — 1회차

작성일 2026-09-30 · 담당: reviewer
대상: `docs/strategy.md`, `docs/architecture.md`, `docs/result.example.json` (두 문서 정합성 포함)

## 판정: **PASS**

High 0 · Med 2 · Low 3. Med 2건은 implementer와 dashboard-builder 사이의 계약에 빈 곳이므로 **W3 위임 전에** architect가 고칠 것을 권고한다.

## Findings

| # | 심각도 | 파일:줄 | 문제 | 근거 | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | Med | architecture.md:341 (4.4절) | 이벤트 dict `{code, stock, date, value, excluded}`로는 `UNTRADABLE_SKIP` 문장을 만들 수 없다. 매수·매도 구분을 담을 필드가 없다 | strategy.md:388 메시지 틀은 "{종목} {날짜} {매수/매도} 불가로 건너뜀."이다. strategy.md:175는 `QTY_ZERO_SKIP`에 (종목, 날짜, 체결가, alloc) 네 값을 남기라고 하는데 수치 필드는 `value` 하나뿐이다. `build_alerts`(architecture.md:150)는 이 리스트만 입력으로 받는다 | 4.4절 dict에 `side`(`"BUY"`/`"SELL"`/None)를 추가하고, `QTY_ZERO_SKIP`의 `value`가 체결가인지 alloc인지 정한다(둘 다 필요하면 `extra` dict 추가) | architect |
| 2 | Med | architecture.md:421 (5.3절 summary) | 낙폭의 고점이 초기 자본(E0, d1 이전)일 때 `mdd_peak_date`에 넣을 값이 정의되지 않았다. "MDD가 0이면 null"만 있다 | strategy.md:204는 고점 후보에 E0를 포함한다. E0에는 날짜가 없다. strategy.md:349(케이스 2)에서 D1 평가액 99,976,023 < E0이므로 첫날부터 낙폭이 생기는 경우가 실제로 나온다. 헤더 KPI ③은 `mdd_peak_date`→`mdd_trough_date`를 표시한다(architecture.md:442). `charts.equity.caption`도 두 날짜를 쓴다 | 고점이 E0인 경우의 값을 명시한다(예: `mdd_peak_date = null`이고 템플릿은 "시작"으로 표시, 또는 `meta.period.start`로 채움). 5.6절 빈 경우 표에도 한 줄 추가 | architect |
| 3 | Low | architecture.md:148, 355 / result.example.json:162 | 좌표 "소수 1자리"의 반올림 방식이 없다. 예시는 half-up인데 Python 기본 포맷과 다르다 | 5.5절 식으로 `benchmark_points`를 `"%.1f"`로 재계산하면 21점 중 3점이 다르다: 점 2 `106.2` vs 예시 `106.3`, 점 9 `131.2` vs `131.3`, 점 19 `81.2` vs `81.3`(원값 106.25, 131.25, 81.25). `equity_points`·스파크라인 3종은 전부 일치 | 반올림 방식을 한 줄로 명시하거나(어느 쪽이든), 계약 테스트는 좌표 값을 비교하지 않는다고 적는다 | architect |
| 4 | Low | architecture.md:563, 569 (8.3절) | strategy.md 9절 fixture(AAA/BBB, 워밍업 2일)는 `cli` 경로로는 돌 수 없다. `test_e2e.py`용 fixture가 따로 필요한데 언급이 없다 | architecture.md:57은 종목 코드 6자리 문자열을 검증한다(`AAA` 불가). architecture.md:114·530은 워밍업 `lookback_days + 10`(9절 설정이면 11거래일)을 요구하는데 9절 달력의 워밍업은 2일이다(strategy.md:258) | 8.3절에 "9절 fixture는 `run_backtest`·`metrics` 직접 호출용, e2e는 6자리 코드·워밍업 충분한 별도 fixture"라고 적는다 | architect |
| 5 | Low | strategy.md:72, 238 | 체결 가능 판정이 체결일 d의 일 거래량(> 0)을 쓴다. 시가 시점에는 확정되지 않은 값이다 | 유효 봉 정의(72줄)와 거래정지 처리(238줄). 신호·순위·`E_ref`·`alloc`에는 쓰이지 않으므로 R5 위반은 아니다(신호는 p 종가까지만 사용, strategy.md:99~100) | 8절 3번에 "체결일 거래량은 체결 가능 여부 판정에만 쓰고 신호에는 쓰지 않는다"를 한 줄 명시 | strategy-designer |

## 오케스트레이터 확인 사항 (문서 결함 아님)
- strategy.md는 후보 B(20일 수익률 상위 5, 주간 리밸런싱)를 기본으로 정했다. PLAN.md 1절은 "기본 후보 SMA 5/20 크로스"다. strategy.md 12절 1번이 사용자 확인을 요청하고 있으므로 W3 전에 사용자 결정을 받고 PLAN.md를 갱신해야 한다(CLAUDE.md 6.4). architecture.md와 예시 JSON은 B(`momentum_topn`)를 전제로 한다.
- DEV 도메인 일봉·지수 지원은 여전히 실호출 미검증이다(kis-api.md 6줄). Phase 3 smoke test에서 확정한다.

## 확인한 항목 (통과)

### 1. strategy.md 손계산 재계산 (Python 정수 연산, 비용 `(거래대금×율+50000)//100000`)
- 9.4절: D1 수량 1,941 / 거래대금 99,961,500 / 비용 14,994 / 현금 23,506. D4 매도 100,932,000 / 비용 217,004 / 현금 100,738,502 / 청산 손익 +738,502(0.00738676). E_ref 101,926,006, alloc 100,738,502, BBB 941주 / 100,687,000 / 비용 15,103 / 현금 36,399. 전부 일치.
- 9.5절: 평가액 100,955,506 / 102,896,506 / 101,926,006 / 101,664,399 / 103,546,399, 일별 수익률 5개, 고점 대비 −0.9432%·−1.1974%. 전부 일치.
- 9.6절: 총수익률 0.03546399, MDD −0.01197424, 평가 손익 2,807,897, 총 거래대금 301,580,500, 총 비용 247,101, 평균 평가액 102,197,763.2, 회전율 1.475475, 동일가중 0.03484572, 목표 진척 1.7732. 전부 일치. 항등식 2개 성립.
- 9.7절: 케이스 2(970주·494주, 비용 7,493·7,484, 현금 136,023, 평가액 99,976,023), 케이스 3(수량 0), 케이스 4(5원, 22원). 전부 일치.
- 9.3절 신호 −0.9434%, +3.9216% 일치.

### 2. look-ahead (R5)
- 신호는 체결일 직전 거래일 p의 종가까지만 사용, 체결은 d 시가(strategy.md:98~116). `E_ref`는 p 종가 평가액, `alloc`은 d 시가 매도 후 현금. 미래 값 없음.
- 추석 주: 09-24·09-25 휴장 → 신호일 09-23, 체결일 09-28(strategy.md:236). ISO 주 정의(74줄)와 맞다. market-rules.md 9줄의 휴장일과 일치. 구간 거래일 20일, 체결일 5회도 달력과 일치.
- 마지막 날 신호 미생성(8절 7번), 기간 초 진입은 워밍업 구간 신호 사용(8절 8번).
- architecture.md: `rebalance_schedule`이 (signal_date, fill_date)를 반환, `signals()`는 signal_date까지만 사용, `test_strategy.py`에 미래 데이터 불변 테스트 포함.

### 3. result.example.json
- JSON 파싱 성공.
- 체결 11건: `amount = qty×price`, 비용 half-up(15/215), `net_cash`, 매도 3건의 `realized_pnl`·`realized_pnl_pct`, `sign` 전부 일치. 현금 음수 없음.
- 매수 수량이 strategy.md 사이징 규칙과 일치(08-31 5건 alloc 20,000,000, 이후 3건 `min(E_ref//5, 매도 후 현금)`으로 재계산한 79·112·67주).
- 실현 −516,743 + 평가 2,375,585 = 1,858,842 = 최종 평가액 − 초기 자본. 최종 현금 38,342 일치. `equity_curve` 20행의 현금·누적 실현·`return_pct`·`drawdown_pct` 일치. MDD −2.1491(09-04 → 09-14) 일치.
- `positions` 5건(원가·평가·비중·수익률·부호·보유일), `per_stock` 10건(건수·거래대금·거래량·합계·기여도·`bar_pct`·부호), 종목별 합계 = summary, 거래대금·비용·거래량·회전율·초과수익·손익비 일치.
- 비중 합 99.9999%(4자리 반올림 오차), 도넛 `end_pct` 누적 일치·마지막 100.0, `conic_gradient` 문자열 일치.
- `equity_points`, `equity_area_path`, 스파크라인 3종, `x_labels`, `weekly_flow` 5주(스택 합 100.0), `trade_value_bars`, `target` 일치. 좌표 전부 viewBox 범위 안. `benchmark_points`는 finding 3의 3점 외 일치.
- `_sign` 플래그 전부 값의 부호와 일치. `benchmark`와 `equity_curve` 날짜·길이 동일.
- 인사이트·다음 조치·알림 문장이 strategy.md 10절 틀과 일치.
- 최상위 키 17개가 architecture.md 5.3절 표와 일치.

### 4. 섹션 매핑
- architecture.md 5.4절이 CLAUDE.md 8절 11개 섹션을 모두 덮는다. 매매 내역·한계 고지도 포함. 좌표·비율·색·문장이 JSON에 미리 들어 있어 템플릿은 필터 5개로 표시만 하면 된다.

### 5. 시그니처·용어 정합성
- 주간 리밸런싱(`rebalance_schedule`), 매도 먼저·매수 순위순(`targets.rank`, trades `id` 순서), 두 벤치마크(`benchmark_curve`, `equal_weight_return`) 표현 가능. 수량 0·거래 불가는 `events`로 전달(단 finding 1).
- `top_n == max_positions` 검증(architecture.md:57), 비용 필드 `cost` 하나(수수료+세금 합, strategy.md 4.1절과 일치), 내부 비율은 소수·JSON은 % 4자리, 거래 횟수 = 매수+매도 체결 수(양쪽 동일).

### 6. W3 병렬 계약
- `render(result_path, template_path, out_path)` 시그니처·호출 방식·예외·필터 5개·null 표시·빈 배열 규칙(5.6절) 명시. `render.py` 단독 실행 명령과 출력 경로 `output/dashboard.example.html` 명시. 파일 소유가 CLAUDE.md 6.6절과 일치(`cli.py` implementer, `render.py`·`templates/`·`tests/test_render.py` dashboard-builder).

### 7. 기본값·절대 규칙
- PLAN.md 2절과 일치: 1억원, 5종목, 매수 0.015% / 매도 0.215%, 슬리피지 0, DEV 기본, 목표 +2%, 유니버스 10종목, 구간.
- R1: `stock-sim/` 전체에서 키·토큰 형태 문자열 검색 0건.
- R2: `stock-sim/`에서 `trading/`, `order-cash`, `inquire-balance` 검색 0건.
- R3: `kis.env` 기본 DEV, PROD는 `prod_approved_by_user: true`일 때만, 자동 전환 없음(architecture.md 7절).
- R4: 계좌번호·잔고·개인정보 없음. 예시는 `is_example: true`의 가짜 수치.
- KIS 경로·tr_id·base URL·`FID_ORG_ADJ_PRC="0"`·지수 필드명이 kis-api.md와 일치.
- 산출물 3개가 지정 경로에 존재.
