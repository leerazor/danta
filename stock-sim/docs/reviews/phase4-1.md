# Phase 4 리뷰 1회차 — 대시보드

검토일 2026-09-30 · 담당: reviewer · 대상: `templates/dashboard.html.j2`, `src/stock_sim/render.py`, `tests/test_render.py`, `output/dashboard.html`(실데이터), `output/dashboard.example.html`
기준: CLAUDE.md 2절·6.6절·8절, `docs/architecture.md` 1.8절·5절, `dashboard-sample.html`

## 판정: **PASS** (High 0 · Med 2 · Low 3)

Med 2건은 Phase 5(최종 검수) 전에 처리할 것을 권고한다. Med 1은 오케스트레이터 결정이 먼저 필요하다.

## Findings

| # | 심각도 | 파일:줄 | 문제 | 근거 | 수정 제안 | 담당 |
|---|---|---|---|---|---|---|
| 1 | Med | `templates/dashboard.html.j2` 전체, `tests/test_render.py:170` | `trades[]`(매매 내역)가 대시보드 어디에도 표시되지 않는다. CLAUDE.md 1절은 대시보드 내용에 "매매 내역"을 명시하고, architecture.md 5.4절 "+" 행은 "매매 내역 표 … 배치는 dashboard-builder가 샘플 카드 스타일 안에서 정한다", 5.6절은 "매매 내역 자리에 '거래 없음'"을 요구한다. | `output/dashboard.html`에서 `"매매 내역"` 0건, `"목표 편입"`(trades[].reason) 0건. 테스트가 `assert "매매 내역" not in html`로 부재를 고정하고 있다. 한편 CLAUDE.md 8절 매핑 표(11개)에는 매매 내역 섹션이 없고 dashboard-builder 정의는 "섹션을 새로 만들지 않는다"라서 문서 간 충돌이다. | 오케스트레이터가 결정: (a) 샘플 카드 스타일의 "매매 내역" 표 카드를 추가(체결일, 종목, 매수/매도, 수량, 체결가, 금액, 비용, 실현손익(sign 색), 사유 — 모두 `trades[]`에 이미 있어 계약 변경 불필요) 또는 (b) 범위에서 빼기로 하고 CLAUDE.md 1절·architecture.md 5.4/5.6절 문구를 정리. (a)면 `test_render.py:170` 단언을 뒤집고 거래 0건일 때 "거래 없음" 표시를 테스트한다. | 오케스트레이터 결정 → dashboard-builder (b면 architect) |
| 2 | Med | `templates/dashboard.html.j2:318` | 종목별 상세 표 "실현손익" 열이 부호 있는 손익인데 중립색(`#4A5568`)이다. 8절 "수익은 블루, 손실은 `#B0472F`. 부호와 색은 항상 일치"에 어긋난다. 반전(손실이 블루)은 아니므로 High는 아니다. | `output/dashboard.html:414` `+1,151,604원`, `:427` `+93,319원`, `:453` `-147,704원`, `:466` `-172,195원`이 모두 `color: #4A5568`. 정규식 집계 결과 `('#4A5568','+'):2, ('#4A5568','-'):2`. `per_stock[].sign`은 `total_pnl`의 부호라 실현손익에 쓸 수 없다(삼성전자: 실현 +1,151,604 / 평가 -855,030). 템플릿은 계산 금지라 계약 추가 없이는 고칠 수 없다. | architect: `per_stock[].realized_pnl_sign`("pos"/"neg"/"zero")을 architecture.md 5.3절과 `result.example.json`에 추가. implementer: `report.py`에서 채우고 `test_report.py` 계약 테스트 갱신. dashboard-builder: 318줄에 `color: {{ r.realized_pnl_sign\|sign_color }}` 적용, `test_render.py`의 부호-색 검사가 중립색 손익도 잡도록 보강. | architect → implementer ∥ dashboard-builder |
| 3 | Low | `templates/dashboard.html.j2:338` | 알림 보조줄에 `a.date`를 항상 덧붙여 날짜가 중복된다. | `output/dashboard.html:531-532`: 제목 "…넘었습니다(2026-09-29)." + 보조줄 "고점 2026-09-09 → 저점 2026-09-29 · 2026-09-29". | `detail`이 있으면 `date`를 덧붙이지 않는다(또는 implementer가 `date`가 있는 알림의 `detail`에서 날짜를 뺀다). | dashboard-builder |
| 4 | Low | `output/result.json:1427,1458,1493,1209` (문장은 report.py 산출, 대시보드에 그대로 노출) | 표시 문장 품질: ① "SK하이닉스이(가)", "POSCO홀딩스이(가)" 조사 미처리 ② "목표 +2.00% 대비 -41.94% 달성" ③ 같은 문장에 하이픈 `-5.14%`와 U+2212 `−5.00%` 혼용 ④ "상위 5종목 손익 합계 …, 손실 5종목 합계 …"(상위 5에 손실 2종목 포함). | `output/dashboard.html:356, 566, 531, 340`. 템플릿은 문장을 그대로 출력하므로 템플릿 결함은 아니다. | strategy.md 10절 문장 틀과 대조해 report.py에서 정리(조사 선택, 음수 진척 문구, 부호 문자 통일). Phase 3 리뷰 범위와 겹치면 그쪽에서 처리. | implementer (틀 자체 문제면 strategy-designer) |
| 5 | Low | `templates/dashboard.html.j2:299-319` | architecture.md 5.4절 9번 행이 나열한 `per_stock[].trade_value`, `trade_volume`이 상세 표에 없다. | 표 열은 종목·거래·총손익·승률·실현손익·수익률 6개. CLAUDE.md 8절 상세 테이블 요구(거래 횟수, 승률, 실현손익, 수익률)는 충족하고, 거래량·거래대금은 합계 수준(KPI 카드 5: 260,908,100원 / 987주)으로 표시된다. | 열 추가가 어렵다면 종목 셀 보조줄에 거래대금을 넣거나, 5.4절 9번 행에서 두 필드를 "선택"으로 표기. | dashboard-builder 또는 architect |

## dashboard-builder가 보고한 예외에 대한 판정
- **헤더 KPI가 흰색 + 부호 문자**: 수용. 샘플도 헤더 주 수치는 흰색(`dashboard-sample.html:44,49,54,59`)이고, 네이비 배경에 `#1428A0`은 읽히지 않는다. 손실이 블루로, 수익이 손실색으로 칠해진 곳은 없다. 같은 수치가 KPI 카드(`-0.84%` → `#B0472F`)와 목표 카드에서 색으로 표시된다. 계약 변경 불필요.
- **상세 표 실현손익 열 중립색**: 수용 불가(finding 2, Med). 계약 변경 필요.
- **샘플 대비 변경점**: 금액 KPI 34→26px(`white-space: nowrap`, 9자리 금액용), 헤더 우측 정적 칩(샘플의 탭·버튼 자리), 0 기준선(`zero_line_top_pct`, 계약에 있음), 예시 데이터 표식(`meta.is_example`일 때만, 실데이터 HTML에는 없음) — 모두 수용. 색·카드·그리드는 유지된다.

## 확인한 항목 (통과)
- **테스트**: `uv run pytest tests/test_render.py` → `13 passed in 0.60s`. 네트워크 미사용.
- **잔여물·태그**: `output/dashboard.html`, `dashboard.example.html` 모두 `{{`, `}}`, `{%`, `%}`, `{#`, `None`, `Undefined`, `nan`, `null` 0건. HTMLParser 스택 검사로 태그 균형 오류 0, 미닫힘 0.
- **KPI 대조(result.json → HTML)**: 누적 수익률 -0.84%(-0.8389), 초과수익 -4.73%p(-4.7283), MDD -5.14%(-5.1446, 2026-09-09 → 2026-09-29), 거래 13회(매수 9·매도 4), 최종 평가 99,161,144원, 실현손익 +925,024원, 평가손익 -1,763,880원, 승률 50.00%(2승 2패, 청산 4건), 보유 5종목, 총 거래대금 260,908,100원·987주, KOSPI +3.89%, 주식 비중 98.28%, 목표 평가금액 102,000,000원, 진척 0.00% — 전부 일치. 원자료 재계산도 일치: `final/initial−1` = -0.8389%, `Σ trades.realized_pnl` = 925,024, `Σ amount` = 260,908,100, `Σ qty` = 987, `min drawdown_pct` = -5.1446.
- **포맷**: 금액 콤마+원, 비율 소수 2자리 %, 날짜 YYYY-MM-DD(다른 날짜 형식 0건).
- **부호·색**: 색이 입혀진 부호 값 25개 — `#B0472F`+음수 15, `#1428A0`+양수 10, 반전 0건. 막대 색도 `sign`과 일치(손실 종목 막대 `#B0472F`). `per_stock` 10행 모두 `sign`·`total_pnl`·`return_pct` 부호 일치.
- **섹션 11개**: 헤더(라벨·제목·구간), 헤더 KPI 4, KPI 카드 5(스파크라인·도넛·막대), 자산 곡선 vs 벤치마크, 포지션 비중 도넛, 주차별 스택 바, 손익 기여 상위 5, 분석 요약 3개+다음 조치, 종목별 상세 표, 점검 필요, 목표 진척 — 전부 있음. 하단 한계 고지 6문장 있음(1개월 표본, 투자 권유 아님 포함).
- **외부 리소스·스타일**: `<script` 0건, 이벤트 핸들러 0건, 외부 URL은 샘플과 같은 폰트 링크 3개뿐. 인라인 스타일. 사용 색은 전부 샘플에 있는 색(8절 토큰 포함; `#C98A2E`는 실데이터에 해당 알림이 없어 미등장, 예시 렌더에는 등장). 폰트(Gothic A1 / Noto Sans KR), 섹션 그리드(`repeat(5,1fr)`, `1.9fr 1fr`, `1.35fr 1fr 1fr`, `1.9fr 1fr`), 카드 스타일 샘플과 동일.
- **템플릿 무계산**: 산술 연산·누적 없음. `{:,}` 포맷, `"%.1f"` 포맷, `meta.universe|length`, `generated_at[:10]`은 표시 변환 수준(5.2절 허용 범위). polyline·path 좌표 전부 viewBox 안, `width/height/left/top` % 52개 모두 0~100. 좌표·conic-gradient 문자열은 result.json 값 그대로.
- **render.py 계약(1.8절)**: 시그니처 `render(result_path, template_path, out_path) -> Path`, 키워드 호출 가능, 부모 폴더 생성, `FileNotFoundError`/`ValueError`(major ≠ 1), `autoescape=True`·`StrictUndefined`, 필터 정확히 5개, `stock_sim` 타 모듈 미import, `print` 없음, 네트워크 없음, `__main__` 블록 있음.
- **R1·R2·R4**: 대상 파일에서 `trading/`, `order-cash`, `inquire-balance`, `APP_KEY`, `APP_SECRET`, `계좌` 검색 0건. 샘플 회사명(`SAMSUNG`, `DS혁신`) 0건. 시뮬레이션 수치만 표시.
- **6.6절**: 실데이터 HTML에 "예시 데이터" 표식 없음, 예시 렌더는 `dashboard.example.html`에만 있고 표식 있음.

## 확인하지 못한 것
- **브라우저 시각 확인(항목 8)**: 수행하지 않았다. 헤드리스 Chrome/Edge는 폰트 링크로 네트워크를 호출하고 프로필 파일을 쓰므로 이번 위임의 제약(네트워크 금지, 쓰기 제한)과 충돌한다. 대신 DOM 정적 검사(태그 균형, 좌표·% 범위, 색 집계)로 대체했다. 따라서 26px 금액이 좁은 화면에서 카드 폭을 넘는지, 상세 표 92px 폭 셀의 줄바꿈 여부는 실측하지 않았다. 최종 검수(Phase 5)에서 사람이 브라우저로 한 번 열어 볼 것을 권한다.
