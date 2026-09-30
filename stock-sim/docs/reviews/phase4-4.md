# Phase 4 리뷰 4회차 (v2 대시보드 1회차)

- 대상: `templates/dashboard.html.j2`, `src/stock_sim/render.py`, `tests/test_render.py`, 실데이터 `output/result.json` → `output/dashboard.html`
- 기준: CLAUDE.md 2절·8절(v2 매핑 표), architecture.md 1.8·5.1~5.7절, strategy.md 11·12·13절
- 작업 위치: 워크트리 `.claude/worktrees/intraday-scalping` (네트워크 호출 없음, `.env`·토큰 캐시 읽지 않음)

## 판정: **PASS**

High 0 · Med 0 · Low 3

## findings

| # | 심각도 | 파일/섹션 | 문제 | 근거 | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | Low | `dashboard.html.j2:42-62` 헤더 KPI | 1280px에서 헤더 KPI 4개가 한 줄에 다 들어가지 않아 4번째 "거래 횟수 74회"가 둘째 줄로 내려간다(`flex-wrap: wrap`). 값은 모두 보이고 가로 스크롤도 없다 | Chrome headless `--window-size=1280,4000` 스크린샷 `output/review-phase4-3.png` 상단 | `gap: 34px`를 줄이거나 보조 문구(예: "최종 …원")의 글자 크기·폭을 줄여 한 줄에 맞춘다(선택) | dashboard-builder |
| 2 | Low | `dashboard.html.j2:108` KPI ④ 보조줄 | "일평균 청산 1.85건 · 체결 3.7건" — 두 값의 소수 자릿수가 다르다. JSON 값이 `3.7`(float 직렬화에서 끝의 0이 빠짐)이고, 템플릿이 값을 그대로 출력한다. architecture.md 5.3절은 "소수 2자리"라고 정한다 | `summary.avg_fills_per_day = 3.7`, `avg_closed_per_day = 1.85`. 대시보드 텍스트 36번 노드 | 템플릿에서 `"%.2f"\|format(...)`로 표시만 맞춘다(계산이 아니라 표시 형식) | dashboard-builder |
| 3 | Low | `dashboard.html.j2:216-265` 일별 손익 카드 | 같은 행의 다크 패널이 더 길어 카드가 늘어나면서, 막대 라벨과 caption 사이에 큰 빈 공간이 생긴다(caption에 `margin-top: auto`) | 스크린샷 "일별 손익" 카드 | 막대 영역 높이를 늘리거나 caption을 막대 바로 아래에 붙인다(선택, UX) | dashboard-builder |

## 확인한 항목 (통과)

### 실행
- `uv run pytest tests/test_render.py -q` → `18 passed in 1.39s`
- `uv run pytest -q`(전체) → `141 passed, 4 deselected in 6.37s` (network 마커 제외, 네트워크 없이 실행)
- `render(output/result.json, templates/dashboard.html.j2, <임시 경로>)` 재렌더 결과가 `output/dashboard.html`과 **바이트 단위로 같음**(`identical True`). 임시 파일은 삭제함 → 대시보드가 현재 result.json에서 생성된 것임을 확인

### 1. result.json ↔ dashboard.html 값 대조 (HTMLParser로 보이는 텍스트 전체 추출 후 비교)
- 헤더 KPI 4개: 누적 수익률 `-4.75%`(-4.7469), 최종 `95,253,068원`, 초과수익 `-8.64%p`(-8.6364), KOSPI `+3.89%`(3.8894) · "시장 하회", MDD `-5.02%`(-5.0185) · `2026-08-31 → 2026-09-29`, 거래 횟수 `74회` · 매수 37 · 매도 37 — 전부 일치
- KPI 카드 5개: 최종 평가금액 `95,253,068원`/`-4.75%`, 실현 손익 `-4,746,932원`·비용 전 손익 `-626,250원`·총 비용 `4,120,682원`, 승률 `29.73%`(11/37 재계산 29.7297) · 11승 26패 · 청산 37건, 평균 보유 `60.8분`, 총 거래대금 `3,583,744,250원` · `7,380주` — 일치
- 도넛: SK하이닉스 `1,930,135,000원` `53.86%`, 삼성전자 `1,653,609,250원` `46.14%`, 중앙 `74건`, conic `0%–53.86%–100%` — 일치, 마지막 `end_pct = 100.0`
- 일별 손익 막대 20일: 각 날 `height_pct`를 `|pnl| / max_abs(1,126,529) × 100`으로 재계산해 20행 모두 일치(오차 0), gain/loss 색 `#1428A0`/`#B0472F` 고정, `sign` 일치. 매매 중단일 09-01·09-03 `halted=true` = `halt_days 2`, 주황 원 표시. 라벨은 ISO 주 첫 거래일(08-31, 09-07, 09-14, 09-21, 09-28)만. caption "수익 5일, 손실 13일, 손익 없음 2일 …" 일치
- 종목별 기여 상위 5: 삼성전자 `-2,425,377원`(bar 100), SK하이닉스 `-2,321,555원`(bar 95.72) — 절댓값 순, note는 strategy 11.4절 "N=0, M≥1" 틀과 일치
- 종목별 상세: 거래 40/34회, 청산 20/17건, 승률 30.00%/29.41%, 평균 보유 50.2/73.2분, 수익률 -0.24%/-0.29%. 수익률을 `realized_pnl / 종목 매수금액 × 100`으로 재계산(-0.2405 / -0.2933) — 표시값 일치
- 알림 7개: warn 4(MDD_BREACH, LOSS_STREAK, UNDERPERFORM, COST_DRAG) → info 3(DAILY_LOSS_HALT, OVERNIGHT_GAP_NOTE, LOW_SAMPLE) 순서·등급·title/detail이 strategy.md 11.3절 틀과 일치. 색: 앞 3개 `#B0472F`, COST_DRAG `#C98A2E`, info `#1428A0`(architecture 5.3절). `only_baseline_alerts=false`라 "특이 리스크 없음" 미표시가 맞음
- 목표 진척: 진척 0.00%(원값 -237.35 → clip 0), 현재 `-4.75%` 손실색, caption "6.75%p 못 미쳤습니다 … 6,746,932원 부족"(102,000,000 − 95,253,068 = 6,746,932 재계산 일치). 음수 진척률 문구 없음
- 매매 내역: `in_table` 행 = `trades[-20:]`(True), HTML 20행을 JSON과 열 11개(날짜·시각·종목·코드·구분·수량·체결가·금액·비용·실현손익·보유분·사유) 모두 대조해 불일치 0. 헤더 "전체 74건 중 최근 20건 · 비용 합계 4,120,682원", 하단 caption "최근 20건 표시 · 전체 74건은 result.json의 trades[]에 있습니다." 일치
- 분석 요약 3문장·다음 조치: strategy.md 11.1·11.2절 틀과 일치(② 종목 절은 코드 오름차순 000660 → 005930, 다음 조치는 4번 규칙·절댓값 상위 "삼성전자·SK하이닉스")
- 항등식 재계산: `final − initial = total_pnl = realized = gross − cost = -4,746,932`, `Σdaily.pnl = Σclosed.pnl = Σper_stock = -4,746,932`, `Σtrades.amount = total_trade_value = share.total`, `Σtrades.cost = total_cost`, MDD를 equity_curve에서 재계산 -5.0185 일치, 최대 연속 손실 9 일치
- 표기: 금액 원 콤마, 비율 소수 2자리 %, 날짜 `YYYY-MM-DD`(trades 74건 정규식 전부 통과). `-0.00%`·`+0원` 없음 (예외: finding 2)

### 2. 부호와 색
- `color:` 뒤에 부호 있는 수치가 오는 요소 24개 전부 검사: 양수 → `#1428A0`/`#7C9BFF`, 음수 → `#B0472F`/`#E29A80`, 불일치 0. 헤더(어두운 배경)는 `#E29A80` 3개, 흰 배경은 `#B0472F`. 매수 행 실현손익은 `sign=zero` 회색 `–`
- 색 없이 쓰인 음수는 문장(caption·인사이트·알림 detail)뿐이며 중립색이다

### 3. 템플릿 원칙
- 템플릿에 산술 없음(표시·분기·`"{:,}".format`·`[:10]` 슬라이스만). 좌표·비율·height는 모두 JSON 값
- `<script` 0건, `src=` 0건. 외부 리소스는 Google Fonts `<link>` 3줄뿐이며 `dashboard-sample.html` 7~9줄과 같다(JS 아님)
- 스타일은 인라인(기본 리셋 `<style>` 블록은 샘플과 같은 구성)
- SVG: 자산 곡선 viewBox `0 0 720 250` — 전략 점 x 0~720, y 183.9~246.8, 벤치마크 y 99.2~197.1, area path 0~720. 스파크라인 viewBox `0 0 200 44` — 3개 모두 y 3.0~41.0, x 0~200. 모두 viewBox 안. y축 15.0~-5.0이 데이터 범위(전략 -4.75~+0.29, KOSPI -0.77~+7.07)를 덮음
- 잔여물 `{{`, `{%`, `None`, `nan`, `NaN`, `Infinity`, `undefined` 0건

### 4. 섹션
- CLAUDE.md 8절 v2 매핑 12개 + 한계 고지 모두 존재(헤더, KPI 4, 카드 5, 자산 곡선, 거래대금 도넛, 일별 손익, 기여 상위 5, 분석 요약, 종목별 상세, 점검 필요(+진입 차단 집계), 목표 진척, 매매 내역)
- v1 잔재 grep(`포지션 비중|보유 종목|주차별|holding_count|cash_weight`) templates·dashboard.html·result.json·render.py 0건
- `meta.slippage_note` 점검 필요 카드 하단 표시, `meta.disclaimers` 9개 하단 표시

### 5. 보안 (R1·R2·R4)
- dashboard.html·result.json에서 `APP_KEY`, `SECRET`, `token`, `계좌`, `acnt`, `CANO`, `.env`, `C:/`, `C:\`, `Users`, 사용자 이름·이메일 0건 → 키·계좌·개인정보·로컬 절대 경로 노출 없음
- `stock-sim/`(docs 제외)에서 `trading/|order-cash|inquire-balance` 0건
- `meta.env = "DEV"`, `is_example = false`

### 6. 가독성 (1280px, Chrome headless)
- 스크린샷 `output/review-phase4-3.png`(1280×4000): 가로 넘침·잘림 없음, 한글 깨짐 없음, 20행 매매 내역 정상 표시. 헤더 KPI 줄바꿈과 일별 손익 카드 여백은 Low 1·3

### render.py (architecture 1.8절)
- 시그니처 `render(result_path, template_path, out_path) -> Path`, `autoescape=True`, `StrictUndefined`, 필터 6개, schema major `2` 검사, 부모 폴더 생성, UTF-8 쓰기, `print` 없음, 다른 `stock_sim` 모듈 import 없음
