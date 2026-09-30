# stock-sim 실행 계획 (PLAN)

작성일 2026-09-30 · 현재 상태: **W2(Phase 2) 완료 — reviewer PASS(`docs/reviews/phase2-1.md`, Med·Low 반영), W3(Phase 3 ∥ 4) 진행 중**

## 0. 진행 체크리스트 (오케스트레이터가 갱신)
- [x] Phase 0 지침 수립 — `CLAUDE.md`, `.claude/agents/` 6개, 이 문서
- [x] W1 · Phase 1 조사 — `kis-researcher` ×3 병렬 → `docs/research/{kis-api,market-rules,universe}.md` (결론: DEV 일봉·지수 일봉 지원 추정(샘플 코드 근거, 실호출 미검증 → Phase 3 smoke test에서 확정))
- [x] W2 · Phase 2a 로직 — `strategy-designer` → `docs/strategy.md` → reviewer PASS (확정 전략: 20일 수익률 상위 5종목 주간 리밸런싱 `momentum_topn`)
- [x] W2 · Phase 2b 설계 — `architect` → `docs/architecture.md`, `docs/result.example.json` → reviewer PASS
- [ ] W3 · Phase 3 구현 — `implementer` → `src/`, `tests/`, `config.yaml`, `output/result.json` → reviewer PASS
- [ ] W3 · Phase 4 대시보드 — `dashboard-builder`(Phase 3과 병렬, `result.example.json` 기준) → `templates/`, `render.py`, `output/dashboard.html` → reviewer PASS
- [ ] W4 · Phase 5 최종 실행·검수 — 사용자 확인
- [ ] W5a · Phase 6 개선 루프(탐색) — `alpha-researcher`(Phase 3 PASS 후) ∥ `kis-researcher`(D) ∥ `ux-reviewer` → `docs/alpha/exp-1.md`, `docs/research/volume-data.md`, `docs/reviews/ux-1.md` → 채택안·UX P1을 사용자에게 한 번에 질문
- [ ] W5b · Phase 6 개선 루프(반영) — `strategy-designer` ∥ `dashboard-builder` → `implementer` → `reviewer` ×2 PASS → 통합 실행

> 2026-09-30 agent 흐름 검토: `alpha-researcher`(수익률 담당), `ux-reviewer`(UX 자문) 추가, `kis-researcher`에 조사 항목 D(거래량·추세 데이터) 추가, `reviewer`에 전략 교체 체크리스트 추가. 진행 관리(PM) agent는 추가하지 않고 CLAUDE.md 6.7절 규칙으로 대체. **새 agent는 세션을 재시작해야 로드된다.**

### 진행 회고 (웨이브마다 3줄, CLAUDE.md 6.7)
- W1~W2: (소급 기록 없음)

## 1. MVP 범위
### 포함
- 유니버스: KOSPI 대형주 10종목 고정(`config.yaml`에서 변경 가능).
- 데이터: KIS 일봉(수정주가) + 벤치마크 KOSPI 지수 일봉. CSV 캐시.
- 전략: 단순 규칙 1개 — 20일 수익률 상위 5종목 주간 리밸런싱(`momentum_topn`, strategy-designer 확정. SMA 5/20 크로스는 1개월 구간 거래 0건 위험으로 탈락). 롱 온리, 동일 비중, 최대 5종목.
- 백테스트: 최근 1개월(종료일 = 마지막 완료 거래일, 시작일 = 종료일 − 1개월), T+1 시가 체결, 수수료·세금 반영.
- 산출물: `result.json` + `dashboard.html`(샘플 스타일).

### 제외 (v2 후보)
- 실거래·모의투자 주문, 실시간 시세, 웹소켓, 분봉, 파라미터 최적화, 다중 전략 비교, 공매도, 레버리지, 배당 반영, 서버·스케줄러.

## 2. 기본값 (바꾸려면 오케스트레이터가 사용자에게 확인)
| 항목 | 기본값 | 비고 |
|---|---|---|
| KIS 환경 | DEV(모의투자) | Phase 1 결론: 지원 추정(미검증). smoke test 실패 시 사용자에게 PROD read-only / 대체 소스(FinanceDataReader 1순위) 선택 요청 |
| 유니버스 후보 | 005930 삼성전자, 000660 SK하이닉스, 373220 LG에너지솔루션, 207940 삼성바이오로직스, 005380 현대차, 000270 기아, 068270 셀트리온, 035420 NAVER, 105560 KB금융, 005490 POSCO홀딩스 | 코드는 Phase 1에서 재확인 |
| 백테스트 구간 | 2026-08-29 ~ 2026-09-29 | 첫 거래일 08-31(08-29는 토요일). 구간 내 휴장 09-24, 09-25(추석). 오늘(09-30) 기준 D-1 마감 |
| 데이터 수집 구간 | 2026-06-01 ~ 2026-09-29 | 워밍업(SMA20 + 여유) 포함 |
| 전략 선택용(IS) 데이터 구간 | 백테스트 시작일 이전 12개월(약 2025-08-29 ~ 2026-08-28) + 워밍업 | 사용자 승인(2026-09-30). W5 `alpha-researcher` 실험 전용. `stock_sim.data` 로더로 수집(캐시), v1의 `config.yaml`(`warmup_days: 90`)과 v1 백테스트 구간은 그대로 |
| 파라미터 탐색 | 검증 구간(OOS)을 둔 탐색만 허용 | 사용자 승인(2026-09-30). CLAUDE.md 1절 문구 유지 확정 |
| 초기 자본 | 100,000,000원 (1억원) | 사용자 지정(2026-09-30) |
| 최대 보유 종목 | 5 | 동일 비중 |
| 매수 비용 | 수수료 0.015% | Phase 1 확인(실제 0.0140527%의 반올림) |
| 매도 비용 | 수수료 0.015% + 세금 0.20% = 0.215% | Phase 1 값으로 갱신(증권거래세 0.05% + 농특세 0.15%, `market-rules.md`) |
| 슬리피지 | 0 | 옵션 |
| 벤치마크 | KOSPI 지수 buy&hold | |
| 목표 수익률 | 월 +2% | 대시보드 "목표 진척"용 |

## 3. Phase 상세
### Phase 1 조사 (`kis-researcher` ×3) — 한 메시지에서 동시 위임
- 위임 프롬프트: CLAUDE.md 6.2 템플릿 + agent 정의의 조사 항목을 하나씩 분담(A → `kis-api.md`, B → `market-rules.md`, C → `universe.md`). 각 agent는 자기 문서만 쓴다.
- 완료 기준: 3개 문서, 항목마다 출처·확신도. **DEV 도메인 시세 API 지원 여부**가 결론으로 명시.
- 결과 분기: 지원 → 그대로 진행. 미지원 → 사용자에게 (a) PROD read-only 승인, (b) `pykrx` fallback 중 선택 요청.

### Phase 2a 로직 (`strategy-designer`) ∥ 2b 설계 (`architect`) — 한 메시지에서 동시 위임
- 2a 완료 기준: `strategy.md`에 손계산 예시 포함.
- 2b 완료 기준: `architecture.md` + `result.example.json`, 대시보드 매핑 표.
- 두 결과를 `reviewer`에게 한 번에 검토 요청 → `docs/reviews/phase2-1.md`.
- 사용자 확인 포인트(모아서 한 번에): 확정 전략, 최대 보유 종목 수, 비용 가정.

### Phase 3 구현 (`implementer`) ∥ Phase 4 대시보드 (`dashboard-builder`) — 한 메시지에서 동시 위임
- 파일 소유는 CLAUDE.md 6.6절을 따른다(`cli.py`는 implementer, `render.py`·`templates/`는 dashboard-builder).
- Phase 3 순서: 골격 → `kis_client` + smoke test → `data` → `strategy`/`backtest`/`metrics`(+테스트) → `report` → `cli` → 실데이터 실행.
- smoke test 실패 시 원인 보고 후 대기(PROD 임의 사용 금지). 이 경우에도 dashboard-builder는 계속 진행한다.
- Phase 4 입력: `docs/result.example.json`. 산출: 템플릿 + `render.py` + `output/dashboard.example.html`(검증용).
- 통합: 두 agent 완료 후 오케스트레이터가 `uv run python -m stock_sim run --config config.yaml`로 실데이터 `result.json` + `dashboard.html` 생성.
- 리뷰: `reviewer` 2개 동시 위임 → `docs/reviews/phase3-1.md` ∥ `docs/reviews/phase4-1.md`. FAIL이면 findings를 담당 agent에게 동시에 전달 → 수정 → 재리뷰(Phase별 최대 2회).

### Phase 5 최종 실행·검수 (오케스트레이터)
- `uv run python -m stock_sim run --config config.yaml` 한 번으로 `result.json` + `dashboard.html`이 생성되는지 확인.
- 사용자에게 보고: 대시보드 파일 경로, 요약 KPI(수익률·MDD·거래 횟수), 한계 고지(1개월 표본).
- 이 문서 체크리스트 갱신, v2 후보 정리.

### Phase 6 개선 루프 (W5) — v1 완성 후
- 목표: 비용 차감 후 수익률을 기준 전략(`momentum_topn`)보다 높인다. 입력은 가격·거래량·거래대금뿐(CLAUDE.md 1절 투자 철학).
- 현재 기준 전략은 **거래량을 전혀 쓰지 않는다**(20일 수익률 순위만). 첫 회차의 우선 후보는 거래량 동반 돌파, 거래대금 가중 모멘텀, 지수 추세 필터.
- W5a(동시 위임): `alpha-researcher` → `experiments/`, `docs/alpha/exp-1.md`, `leaderboard.md` ∥ `kis-researcher`(D) → `docs/research/volume-data.md` ∥ `ux-reviewer` → `docs/reviews/ux-1.md`.
- 과최적화 방지: 선택은 IS(백테스트 구간 이전 과거)로만, 최근 1개월은 OOS로 상위 3개만 1회 검증. reviewer가 `docs/reviews/alpha-<회차>.md`로 재현·과최적화·look-ahead를 확인.
- 결정 완료(2026-09-30): IS용 데이터 수집 구간 12개월 확장 승인, 검증 구간을 둔 파라미터 탐색 허용. 12개월치 수집은 W5a에서 `alpha-researcher`가 로더로 수행한다(그 시점에 네트워크를 쓰는 agent는 이것 하나만).
- 사용자 결정 남음(결과가 나온 뒤 모아서 한 번에): ① 채택 전략 교체 여부 ② 유니버스 확장 여부(현재 대형주 10종목 고정, `volume-data.md` 결론 후) ③ UX 규약 변경 제안.
- W5b: 승인된 것만 `strategy-designer`(strategy.md) ∥ `dashboard-builder`(UX P1) → `implementer` → `reviewer` ×2 → 통합 실행.

## 4. 위험과 대응
| 위험 | 대응 |
|---|---|
| DEV(모의) 도메인이 일봉 시세 API를 지원하지 않음 | Phase 1에서 확인. 사용자 승인 하에 PROD read-only, 또는 `pykrx` fallback |
| 토큰 발급 제한(분당 1회)·초당 호출 제한 | 토큰 파일 캐시, 호출 간 대기, 재시도. 캐시로 재실행 시 호출 0건 |
| 1개월 표본에서 거래 0건(신호 미발생) | strategy-designer가 후보 A/B 비교 시 거래 발생 여부 고려. 0건이면 대시보드에 "거래 없음" 명시 |
| 1개월 결과의 통계적 의미 부족 | 대시보드 하단·보고서에 한계 고지. 최근 1개월 수익률을 보고 파라미터를 고르지 않는다 |
| 수익률 극대화가 과최적화로 변질 | `alpha-researcher`는 IS로만 선택·OOS 1회 검증, `reviewer`가 재현·이웃 파라미터·거래수 확인. 계약·코드는 수익률 담당이 직접 못 고침 |
| 실계좌 정보 노출 | R1~R4, reviewer 체크리스트, 계좌 API 코드 자체 부재 |
| 휴장일·결측(추석 등) | 실제 데이터의 날짜를 거래일 달력으로 사용. 결측 종목은 제외 + alert |

## 5. 오케스트레이터 실행 순서 (다음 세션에서 그대로 따라 하기)
1. `CLAUDE.md`, 이 문서를 읽고 현재 Phase 확인. sub agent 정의는 세션 시작 시 로드되므로, `.claude/agents/`를 만든 직후에는 세션을 재시작해 6개 agent가 보이는지 확인한다.
2. W1: `kis-researcher` 3개(A·B·C)를 **한 메시지에서 동시에** 위임 → 결과 요약을 사용자에게 보고, DEV 지원 여부로 분기.
3. W2: `strategy-designer`와 `architect`를 **한 메시지에서 동시에** 위임.
4. `reviewer`로 Phase 2 게이트. PASS 후 사용자 확인 포인트를 한 번에 질문.
5. W3: `implementer`와 `dashboard-builder`를 **한 메시지에서 동시에** 위임.
6. 통합 실행으로 실데이터 `result.json` + `dashboard.html` 생성 → `reviewer` 2개(Phase 3 ∥ Phase 4)를 동시에 위임 → 필요 시 병렬 수정 루프.
7. W4: 최종 실행, 사용자 보고, 체크리스트 갱신.
