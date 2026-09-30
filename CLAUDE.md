# stock-sim — 주식 자동매매 시뮬레이션 프로젝트 지침

> 메인 세션(오케스트레이터)과 모든 sub agent가 가장 먼저 읽는 규칙서다.
> 세션을 시작하면 이 파일 → `stock-sim/docs/PLAN.md`의 진행 체크리스트 순으로 읽고, 현재 Phase부터 이어간다.

## 1. 프로젝트 요약
- 목적: 한국투자증권(KIS) Open API의 **과거 일봉 데이터**로 간단한 매매 전략을 **백테스트**하고, 결과를 `dashboard-sample.html` 스타일의 **정적 HTML 대시보드**로 출력한다.
- 기간: 최근 **1개월** 백테스트. 지표 워밍업을 위해 그 이전 데이터도 수집한다.
- 산출물: `stock-sim/output/result.json`(수치) + `stock-sim/output/dashboard.html`(대시보드).
- 대시보드 내용: 선정 종목, 매매 내역, 거래량·거래대금, 수익률, MDD, 벤치마크 대비 성과, 리스크 알림.
- 궁극 목표: **개발 효율화**와 **수익률 극대화**. v1(MVP)을 먼저 끝까지 완성한 뒤, W5 개선 루프에서 수익률과 대시보드 사용성을 끌어올린다.
- 투자 철학: 외부 요인(뉴스·공시·금리·실적 등)은 **가격과 거래량에 이미 반영된다**고 본다. 시장을 예측하지 않고 거래량과 추세 흐름만으로 매매한다. 입력 데이터는 일봉 시세·거래량·거래대금과 지수 일봉뿐이다.
- 하지 않는 것: 실거래 주문, 모의투자 주문, 실시간 시세, 실계좌 조회, 웹소켓, 가격·거래량 외 데이터로 하는 예측, 검증 구간 없는 파라미터 최적화(전략 탐색은 `alpha-researcher`가 과최적화 방지 절차 안에서만 한다).

## 2. 절대 규칙 (모든 세션·모든 sub agent 공통)
| # | 규칙 |
|---|---|
| R1 | `.env` 값은 절대 출력·로그·커밋·복사하지 않는다. 키는 **이름**으로만 언급한다(`KIS_DEV_APP_KEY` 등). 로그에는 앞 4자리만 남기고 마스킹한다. |
| R2 | 주문·계좌 API를 호출하지 않는다. `/uapi/domestic-stock/v1/trading/` 하위 경로(`order-cash`, `inquire-balance` 등)는 코드에 문자열로도 등장하면 안 된다. PROD·DEV 모두 해당. |
| R3 | 기본 환경은 **DEV(모의투자)**다. PROD 키는 시세 조회(read-only) 용도로, DEV가 해당 API를 지원하지 않을 때, **사용자가 명시적으로 허용한 경우에만** 쓴다. agent가 임의로 PROD로 전환하지 않는다. |
| R4 | 대시보드·JSON·문서에 계좌번호, 실잔고, 키, 개인정보를 넣지 않는다. 시뮬레이션 수치만 넣는다. |
| R5 | 과거 데이터만 사용한다. 미래 정보 누수(look-ahead) 금지: 신호는 T일 종가까지의 정보로만 계산하고, 체결은 T+1일 시가로 가정한다. |
| R6 | 산출물은 반드시 파일로 남긴다(문서·코드·JSON·HTML). 채팅 답변에만 남기지 않는다. |
| R7 | 작게 시작한다(MVP). 범위 확장·전략 변경·구조 변경은 사용자 승인 후에만 한다. |
| R8 | 이 폴더의 다른 실습 프로젝트(`A2A-MCP-RealEstate/`, `mcp-kr-realestate/`, `real-estate-mcp/`, `.mcp.json`)와 `dashboard-sample.html`은 수정하지 않는다. |

## 3. 환경
- OS Windows 11, PowerShell 기본(Bash 도구도 사용 가능). Python 3.11, uv, Node 24.
- KIS 키는 저장소 루트 `.env`에 있다: `KIS_DEV_APP_KEY` / `KIS_DEV_APP_SECRET`(모의투자), `KIS_PROD_APP_KEY` / `KIS_PROD_APP_SECRET`(실전). 계좌번호는 없고 필요하지도 않다(계좌 API 미사용).
- 실행 환경(DEV/PROD) 선택은 `stock-sim/config.yaml`의 `kis.env` 한 곳에서만 한다.
- 파일 인코딩 UTF-8 명시, 경로는 `pathlib` 사용(Windows 경로 주의).

## 4. 디렉토리 구조 (목표)
```
실습오후mcp/
├── CLAUDE.md                    # 이 파일
├── .claude/agents/              # sub agent 정의 8개
├── dashboard-sample.html        # 대시보드 스타일 원본 (수정 금지)
├── .env                         # 키 (읽기만, 출력 금지)
└── stock-sim/                   # 앱 (Phase 3부터 코드 생성)
    ├── docs/
    │   ├── PLAN.md              # 단계별 계획 + 진행 체크리스트
    │   ├── research/            # Phase 1 산출물 (kis-researcher)
    │   ├── strategy.md          # Phase 2a 산출물 (strategy-designer)
    │   ├── architecture.md      # Phase 2b 산출물 (architect)
    │   ├── result.example.json  # Phase 2b 산출물 (architect)
    │   ├── alpha/               # W5 전략 실험 기록·순위표 (alpha-researcher)
    │   └── reviews/             # Phase별 리뷰 결과 (reviewer), ux-<회차>.md (ux-reviewer)
    ├── experiments/             # W5 전략 실험 스크립트 (alpha-researcher, src/를 import만)
    ├── config.yaml
    ├── pyproject.toml
    ├── src/stock_sim/           # 파이썬 패키지
    ├── templates/dashboard.html.j2
    ├── tests/
    ├── data/cache/              # 일봉 CSV 캐시, 토큰 캐시 (커밋 금지)
    └── output/                  # result.json, dashboard.html
```

## 5. 작업 단계(Phase)와 담당 sub agent
| Phase | 이름 | 담당 agent | 입력 | 산출물 | 완료 조건 |
|---|---|---|---|---|---|
| 0 | 지침 수립 | (메인 세션) | 사용자 요구 | CLAUDE.md, agents, PLAN.md | 사용자 확인 |
| 1 | 조사 | `kis-researcher` ×3 (A·B·C 병렬) | CLAUDE.md, PLAN.md | `docs/research/*.md` | 조사 항목 전부에 출처·확신도 표기 |
| 2a | 로직 | `strategy-designer` | research | `docs/strategy.md` | 손계산 예시 포함, reviewer PASS |
| 2b | 설계 | `architect` | research, (strategy) | `docs/architecture.md`, `docs/result.example.json` | 대시보드 섹션↔JSON 매핑 표 포함, reviewer PASS |
| 3 | 구현 | `implementer` | strategy, architecture | `src/`, `tests/`, `config.yaml`, `output/result.json` | `uv run pytest` 통과, result.json 생성, reviewer PASS |
| 4 | 대시보드 | `dashboard-builder` | result.example.json(병렬 개발용) → result.json(최종 렌더), dashboard-sample.html | `templates/`, `render.py`, `output/dashboard.html` | 렌더 확인, reviewer PASS |
| 5 | 최종 실행·검수 | (메인 세션) + `reviewer` | 전체 | 최종 dashboard.html, PLAN.md 갱신 | 사용자 확인 |
| 6 | 개선 루프 | `alpha-researcher` ∥ `ux-reviewer` ∥ `kis-researcher`(D) | v1 엔진·대시보드 | `docs/alpha/`, `experiments/`, `docs/reviews/ux-*.md`, `docs/research/volume-data.md` | 채택안 사용자 승인 → 계약 갱신 → 재구현 → reviewer PASS |

병렬 실행이 기본이다. 서로 의존하지 않는 위임은 **한 메시지에서 동시에** 보낸다(6.6절).

| 웨이브 | 동시에 위임하는 agent | 다음 웨이브로 넘어가는 조건 |
|---|---|---|
| W1 | `kis-researcher` ×3 (A: kis-api, B: market-rules, C: universe) | 3개 문서 완성, DEV 지원 여부 결론 |
| W2 | `strategy-designer` ∥ `architect` | `reviewer` 1회(두 문서 정합성 포함) PASS |
| W3 | `implementer` ∥ `dashboard-builder`(`result.example.json` 기준) | 통합 실행 후 `reviewer` ×2(Phase 3 ∥ Phase 4) PASS. `ux-reviewer`도 같은 메시지에서 함께 위임(자문, 게이트 아님) |
| W4 | (메인 세션) 최종 실행·검수 | 사용자 확인(v1 완성) |
| W5a | `alpha-researcher` ∥ `kis-researcher`(D) ∥ `ux-reviewer`(W3에서 안 돌렸으면) | 채택 제안 + UX P1 목록을 모아 사용자에게 한 번에 질문 |
| W5b | `strategy-designer`(strategy.md 갱신) ∥ `dashboard-builder`(UX P1 반영) → `implementer` | `reviewer` ×2(전략 교체 `alpha-<회차>.md` ∥ 대시보드) PASS → 통합 실행 |

W5는 반복할 수 있다(회차마다 `docs/alpha/exp-<회차>.md`). 기준 전략 대비 IS·OOS 초과수익이 없으면 "기준 전략 유지"로 끝낸다.

## 6. Sub agent 위임 규칙
### 6.1 역할 분담
- 메인 세션은 **오케스트레이터(PM)**다. 직접 코드를 쓰기보다 위임 → 결과 통합 → 리뷰 게이트 → 사용자 보고를 맡는다. 10줄 이하의 사소한 수정만 직접 한다.
- 각 agent는 **자기 산출물 경로에만** 쓴다. 다른 agent의 산출물을 고쳐야 하면 보고서에 "변경 요청"으로 남기고, 오케스트레이터가 해당 agent에게 전달한다.
- `strategy.md`와 `architecture.md`는 **계약**이다. implementer가 문서와 다르게 구현해야 한다면 먼저 보고하고, 오케스트레이터가 문서를 갱신(담당 agent 재위임)한 뒤 진행한다.
- agent 결과 보고는 사용자에게 보이지 않는다. 오케스트레이터가 핵심(요약 KPI, 결정 필요 사항, 파일 경로)을 골라 사용자에게 전달한다.

### 6.2 위임 프롬프트 템플릿 (Agent 도구 호출 시 반드시 포함)
```
[Phase N · <작업명>]
목표: <한 문장>
읽을 것: CLAUDE.md, stock-sim/docs/PLAN.md, <입력 파일 경로>
쓸 것: <출력 파일 경로> (이 외의 파일은 쓰지 말 것)
제약: CLAUDE.md 2절 절대 규칙. <추가 제약>
완료 보고 형식: (1) 요약 3줄 (2) 작성·수정 파일 목록 (3) 미해결 질문 (4) 다음 단계 제안
```

### 6.3 리뷰 게이트
- Phase 2, 3, 4 산출물은 `reviewer`의 **PASS** 없이 다음 Phase로 넘어가지 않는다.
- FAIL이면 findings를 담당 agent에게 그대로 전달해 수정 → 재리뷰. 같은 Phase에서 재리뷰는 최대 2회. 초과 시 사용자에게 상황을 보고하고 결정을 받는다.
- 리뷰 결과는 `stock-sim/docs/reviews/phase<N>-<회차>.md`로 남긴다.
- Phase 2는 두 문서의 정합성을 봐야 하므로 `reviewer` 1개가 함께 검토한다. Phase 3·4 리뷰는 `reviewer` 2개를 동시에 위임한다(각자 `phase3-<회차>.md`, `phase4-<회차>.md`만 쓴다).
- 여러 agent에 걸친 FAIL findings는 담당 agent들에게 동시에 전달해 병렬로 수정한다.

### 6.4 사용자에게 물어야 하는 결정 (agent가 임의로 정하지 않음)
- PROD 키 사용 여부, 전략 종류·파라미터 변경, 유니버스 변경, 초기 자본·비용 가정 변경, 범위 확장.
- W5에서 `alpha-researcher`의 **실험**은 승인 없이 진행한다(`experiments/` 안에서만). 실험 결과를 **기본 전략으로 채택**하는 것, 데이터 수집 구간·유니버스 확장, 대시보드 규약(8절) 변경은 사용자 승인이 필요하다.
- 오케스트레이터가 질문을 모아 한 번에 묻는다. 답을 기다리는 동안 답에 의존하지 않는 작업은 계속 진행한다.

### 6.5 상태 관리
- Phase가 끝날 때마다 오케스트레이터가 `stock-sim/docs/PLAN.md`의 진행 체크리스트와 기본값 표를 갱신한다.
- 새 세션은 PLAN.md 체크리스트를 보고 이어서 시작한다.

### 6.6 병렬 실행 규칙
- 동시에 도는 agent는 **쓰는 파일이 겹치면 안 된다**. 위임 프롬프트의 "쓸 것"에 파일 단위로 명시한다.
- W1: `kis-researcher` 3개는 각자 조사 항목 하나(A/B/C)와 문서 하나만 맡는다.
- W3 파일 소유: `implementer` = `pyproject.toml`, `config.yaml`, `tests/`, `src/stock_sim/`(단 `render.py` 제외), `output/result.json`. `dashboard-builder` = `templates/`, `src/stock_sim/render.py`, `tests/test_render.py`, `output/dashboard.example.html`. `cli.py`는 implementer만 고치며, architecture.md의 `render()` 시그니처대로 호출한다.
- W3에서 `dashboard-builder`는 `docs/result.example.json`으로 개발하고 `output/dashboard.example.html`로 렌더해 검증한다. 가짜 데이터를 `output/dashboard.html`에 쓰지 않는다. 최종 `dashboard.html`은 두 agent가 끝난 뒤 오케스트레이터가 통합 실행(7절 진입점 명령)으로 실데이터에서 생성한다.
- 병렬 agent끼리는 서로의 진행을 기다리거나 가정하지 않는다. 계약(`architecture.md`, `result.example.json`)만 믿는다. 계약이 부족하면 "변경 요청"으로 보고한다.
- 사용자 결정(6.4)이 필요한 agent만 멈추고, 나머지 병렬 작업은 계속 진행한다.
- W5 파일 소유: `alpha-researcher` = `experiments/`, `docs/alpha/`. `ux-reviewer` = `docs/reviews/ux-<회차>.md`, `output/ux-*.png`. `kis-researcher`(D) = `docs/research/volume-data.md`. 셋 다 `src/`·`templates/`·계약 문서를 고치지 않으므로 W3·W4와도 동시에 돌 수 있다. 단 `alpha-researcher`는 Phase 3 reviewer PASS 뒤에만 시작한다(검증 안 된 엔진 위의 실험은 버려진다).

### 6.7 진행 효율 규칙 (병목·경합 관리 — 별도 PM agent 없이 오케스트레이터가 지킨다)
- **역할 긴장**: `alpha-researcher`는 수익률만 본다. `reviewer`는 그 수익률이 과최적화·look-ahead가 아닌지 의심한다. `strategy-designer`는 채택안을 계약으로 옮긴다. 수익률 담당이 계약·코드를 직접 고치지 않는 것이 안전장치다.
- **위임 프롬프트는 절 단위로**: `architecture.md`·`strategy.md`가 길다. "읽을 것"에 문서 전체가 아니라 필요한 절 번호를 적는다.
- **수정 위임은 findings만**: FAIL 수정·UX 반영은 해당 findings 표와 관련 파일 경로만 전달한다. 전체 재작성 지시 금지.
- **임계 경로 먼저**: 불확실한 외부 의존(DEV 시세 API 실호출 등)은 해당 Phase의 첫 작업으로 검증하고, 실패하면 즉시 보고한다. 나머지 병렬 작업은 멈추지 않는다.
- **API 호출은 한 agent만**: KIS 호출 제한(DEV 초당 2건, 토큰 분당 1회) 때문에 네트워크로 데이터를 받는 agent는 동시에 하나만 돈다. 나머지는 캐시만 읽는다.
- **게이트는 정확성만**: `ux-reviewer`·`alpha-researcher`의 결과는 자문·제안이다. 다음 웨이브를 막지 않는다.
- **웨이브 회고 3줄**: 웨이브가 끝나면 PLAN.md "진행 회고"에 (1) 가장 오래 걸린 agent와 이유 (2) 재작업이 난 원인 (3) 다음 웨이브에서 바꿀 것 하나를 적는다.

## 7. 코딩 규약 (Phase 3 이후)
- Python 3.11, `uv`로 관리(`stock-sim/pyproject.toml`). 의존성은 최소: `requests`, `python-dotenv`, `pandas`, `pyyaml`, `jinja2`, `pytest`. 추가는 보고 후 승인.
- `.env`는 저장소 루트에 있다. `load_dotenv(<루트>/.env)`처럼 경로를 명시해 읽는다.
- 네트워크 호출은 `kis_client.py` 한 곳에서만. 토큰은 `data/cache/token_<env>.json`에 캐시하고 만료 전에는 재발급하지 않는다(KIS는 토큰 재발급 빈도를 제한한다).
- 일봉 데이터는 `data/cache/<종목코드>_<시작>_<종료>.csv`로 캐시한다. 캐시가 있으면 API를 호출하지 않는다.
- 백테스트·지표 계산은 **순수 함수**(DataFrame in → dict/DataFrame out). 네트워크·파일 I/O와 분리해 테스트 가능하게 한다.
- 테스트는 네트워크 없이 실행된다(fixture CSV 사용). 실 API smoke test는 `-m network` 마커로 분리한다.
- 수량은 정수(1주 단위), 현금은 음수가 될 수 없다. 비용은 매수·매도 양쪽에 적용한다.
- 로그에 키·시크릿 마스킹. `print`보다 `logging`.
- 진입점 하나(`stock-sim/`에서 실행): `uv run --directory src python -m stock_sim run --config ../config.yaml` → result.json + dashboard.html 생성. 한글 경로에서 Python 3.11이 편집 가능 설치의 `.pth`를 읽지 못해 패키지를 설치하지 않는 구성(`[tool.uv] package = false`)을 쓴다. 테스트는 `uv run pytest` 그대로다.

## 8. 대시보드 규약 (Phase 4)
- 원본: `dashboard-sample.html`. 구조·색·폰트·카드·그리드를 그대로 따른다. 인라인 스타일, 외부 JS 없음, 차트는 SVG polyline / CSS bar / conic-gradient.
- 색 토큰: 배경 `#EEF0F5`, 네이비 `#0A1547`, 블루 `#1428A0`, 보조 `#4B5CC0` `#7C9BFF` `#C2C8E8`, 손실 `#B0472F`, 주의 `#C98A2E`. 수익은 블루, 손실은 `#B0472F`. 어두운 배경(헤더·다크 패널) 위에서는 수익 `#7C9BFF`, 손실 `#E29A80`(샘플 헤더의 색). 부호와 색은 항상 일치.
- 섹션 매핑:

| 샘플 섹션 | 시뮬레이션 대시보드 |
|---|---|
| 헤더 라벨·제목·기준일 | "STOCK-SIM · 모의투자 백테스트" / "주식 자동매매 시뮬레이션 대시보드" / 백테스트 구간 |
| 헤더 KPI 4개 | 누적 수익률, 벤치마크(KOSPI) 대비 초과수익, MDD, 거래 횟수 |
| KPI 카드 5개 | 최종 평가금액(스파크라인), 실현 손익, 승률(도넛), 보유 종목 수, 총 거래대금(막대) |
| 추이 차트(실적 vs 목표선) | 자산 곡선 vs 벤치마크 buy&hold |
| 도넛(부문별 구성) | 포지션 비중(종목별 + 현금) |
| 스택 바(유형별 추이) | 주차별 매매 구성(매수·매도·보유·현금) |
| 상위 팀 바 | 종목별 손익 기여 상위 5(손익 절댓값 기준 — 이익·손실 종목 모두 포함) |
| 분석 요약(다크 패널) | 규칙 기반 자동 인사이트 3개 + 다음 조치 |
| 상세 테이블 | 종목별 상세(거래 횟수, 승률, 실현손익, 수익률) |
| 점검 필요 | 리스크 알림(MDD 초과, 연속 손실, 데이터 결측 등) |
| 연간 목표 진척 | 목표 수익률 대비 진척 |
| (추가) 상세 테이블과 같은 카드 스타일 | 매매 내역 표(체결일, 종목, 매수/매도, 수량, 체결가, 금액, 비용, 실현손익, 사유) |

- 데이터 흐름: `output/result.json` → `templates/dashboard.html.j2` → `output/dashboard.html`. 템플릿은 JSON 값을 표시만 하고 계산하지 않는다(좌표·비율은 result.json에 미리 계산해 둔다).
- 표기: 한국어, 금액은 원 단위 콤마, 비율은 소수 2자리 `%`, 날짜는 `YYYY-MM-DD`.
