# 과거 분봉 데이터 조사 (항목 E)

조사 일자: 2026-09-30. 작성: kis-researcher. API 실호출 없음(R1, R2 준수). 주문·계좌 API는 조사하지 않았다.

## 결론
1. **DEV(모의)로 가능한가: 가능성 높음, 단 실호출 미검증.** 공식 샘플의 `inquire_time_dailychartprice`는 모의 제한 코드가 없고(`env_dv` 분기·예외 없음), 제3자 프로젝트(trading-engine PR #174)가 "live paper host"에서 같은 엔드포인트를 실측했다고 적었다. 그러나 "paper host"가 `openapivts`인지 명시되지 않았고, 공식 docstring에는 "실전계좌의 경우 최대 120건"만 있고 모의 언급이 없다. 확정은 implementer smoke test(DEV, 1종목 1일 1페이지)에서 한다.
2. 서버 보존 기간은 약 250 거래일(약 1년)이라 2026-08-31~09-29 30일은 범위 안이다. 당일분봉 API(`FHKST03010200`)는 당일만 주므로 과거 30일에는 못 쓴다.
3. 사용자에게 물을 결정: (a) smoke test에서 DEV가 빈 output2나 오류를 내면 PROD 키 read-only 시세 조회를 허용할지(R3, 사용자 승인 필요). (b) PROD도 막히면 외부 소스는 30일 1분봉을 못 주므로(아래 표) 분봉 전략 자체를 재검토할지. 1순위 fallback은 PROD read-only, 외부 무키 소스는 실질 대안이 못 된다.

## 다음 단계 agent가 알아야 할 핵심 5줄
1. 경로 `GET /uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice`, tr_id `FHKST03010230`. 1회 최대 120건, 서버 보존 약 1년(약 250 거래일).
2. 요청은 `FID_INPUT_DATE_1`(YYYYMMDD)과 `FID_INPUT_HOUR_1`(HHMMSS)로 "그 날짜 그 시각 이전" 120건을 받는다. 다음 페이지는 마지막 행의 `stck_cntg_hour`에서 1분 뺀 값으로 재호출한다. 응답에 이전 거래일 행이 섞이므로 `stck_bsop_date`로 필터한다.
3. 응답 필드: `stck_bsop_date`, `stck_cntg_hour`, `stck_oprc`, `stck_hgpr`, `stck_lwpr`, `stck_prpr`(종가 역할), `cntg_vol`(분 거래량), `acml_tr_pbmn`(누적 거래대금, 차분 필요).
4. 하루 정규장은 종목별로 약 350~381개 분봉(체결 없는 분은 봉이 없음)이라 종목·일당 4페이지 안팎. 30일 x 2종목 = 약 160~200회 호출, DEV에서 5분 이내.
5. 무키 외부 소스(yfinance 1분봉 7일, 네이버 등)는 과거 30일 1분봉을 주지 못하거나 약관 위험이 있어 대체 불가에 가깝다. 일봉 합성은 분봉 전략에 쓸 수 없다.

## 1. 주식일별분봉조회 (핵심)
| 항목 | 내용 | 출처·확신도 |
|---|---|---|
| 경로 | `/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice` (GET) | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_time_dailychartprice/inquire_time_dailychartprice.py] |
| tr_id | `FHKST03010230` (샘플에 하드코딩, 실전/모의 분기 없음) | [확인됨: 같은 파일] |
| 함수 시그니처 | `inquire_time_dailychartprice(fid_cond_mrkt_div_code, fid_input_iscd, fid_input_hour_1, fid_input_date_1, fid_pw_data_incu_yn="N", fid_fake_tick_incu_yn="")` | [확인됨: 같은 파일] |
| 1회 최대 건수 | 120건 ("실전계좌의 경우, 한 번의 호출에 최대 120건") | [확인됨: 같은 파일 docstring] |
| 과거 조회 기간 | 최대 1년치 분봉 보관. 별도 실측 보고는 "rolling ~250 trading days" | [확인됨: 같은 파일 요약] [확인됨: https://github.com/ckrhehfl/trading-engine/pull/174 (제3자)] |
| 페이지네이션 | 샘플은 `tr_cont` 처리 없음(단일 호출). 한 날짜 전체는 `FID_INPUT_HOUR_1`을 마지막 행의 시각으로 바꿔 반복 호출한다. | [확인됨: 샘플에 tr_cont 없음] [확인됨: https://www.inflearn.com/en/community/questions/1606220 (당일분봉 API에 대한 설명이나 같은 방식), trading-engine PR #174] |
| 샘플의 모의 제한 코드 | 없음. `env_dv` 인자 자체가 없다. docstring에 모의 언급 없음. | [확인됨: 같은 파일] |
| 모의 tr_id 치환 | 공식 `kis_auth._url_fetch`는 tr_id 첫 글자가 T/J/C이면 모의에서 `V`로 치환한다. `FHKST03010230`은 F로 시작하므로 치환 없이 그대로 나간다(다른 시세 API와 같은 동작). | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py] |
| DEV 지원 | **가능성 높음, 미검증.** 근거: 위 코드 무제한 + trading-engine PR #174가 "live paper host"에서 이 엔드포인트를 120건/페이지, 0.57초/호출로 실측(단 host가 `openapivts`인지 미명시). 포털 표(모의 TR ID 칸)는 JS 렌더링이라 읽지 못했다. | [추정: 위 근거] |

### 요청 파라미터 (쿼리스트링)
| 파라미터 | 값 | 설명 | 출처 |
|---|---|---|---|
| `FID_COND_MRKT_DIV_CODE` | `J` | J(KRX), NX(NXT), UN(통합). 본 프로젝트는 `J` | [확인됨: 샘플] |
| `FID_INPUT_ISCD` | `005930` 등 | 종목코드 | [확인됨: 샘플] |
| `FID_INPUT_DATE_1` | `YYYYMMDD` (샘플 `20241023`) | 조회 일자 | [확인됨: chk 샘플 `chk_inquire_time_dailychartprice.py`] |
| `FID_INPUT_HOUR_1` | `HHMMSS` (샘플 `130000`) | 이 시각 이전 데이터부터 과거 방향으로 반환 | [확인됨: chk 샘플] [추정: 방향은 PR #174의 "각 요청은 이전 페이지 최초 행 1분 전을 끝으로" 서술] |
| `FID_PW_DATA_INCU_YN` | 기본 `"N"` | "과거 데이터 포함 여부"로 알려짐. `Y`일 때 동작은 미확인 | [확인됨: 기본값] / 의미 [추정] |
| `FID_FAKE_TICK_INCU_YN` | 기본 `""` | 허봉(가짜 틱) 포함 여부로 알려짐. 미확인. 빈 값 사용 | [확인됨: 기본값] / 의미 [추정] |

### 응답
- 최상위 `output1`(요약 단일 객체, 현재가 등, 요청 일자와 무관), `output2`(분봉 배열). 범위 밖 일자는 `output2`가 빈 배열 `[]`로 온다. [확인됨: 샘플 요약, https://github.com/ckrhehfl/trading-engine/pull/174]
- `output2[]` 필드(공식 chk 샘플 COLUMN_MAPPING, output1·output2 공용 매핑이라 소속은 분리 확정 못함) [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_time_dailychartprice/chk_inquire_time_dailychartprice.py]

| 필드 | 의미 | 비고 |
|---|---|---|
| `stck_bsop_date` | 영업일자 YYYYMMDD | |
| `stck_cntg_hour` | 체결(분) 시각 HHMMSS | 분봉 기준 시각 |
| `stck_oprc` | 시가 | |
| `stck_hgpr` | 고가 | |
| `stck_lwpr` | 저가 | |
| `stck_prpr` | 현재가(분봉에서는 종가) | [추정: 분봉 마감가] |
| `cntg_vol` | 체결 거래량(분 단위) | |
| `acml_tr_pbmn` | 누적 거래대금 | 누적값이라 분 거래대금은 차분 필요. 출처 PR #174도 동일 지적 |
| `acml_vol` | 누적 거래량 | output1 소속으로 추정 |
| `prdy_vrss`, `prdy_vrss_sign`, `prdy_ctrt`, `stck_prdy_clpr`, `hts_kor_isnm` | 전일 대비류, 종목명 | output1(요약)으로 추정 |

- 값은 문자열로 온다고 보고 형 변환한다. [추정: KIS 관행]
- 정렬은 최신이 먼저(내림차순)로 추정. 날짜·시각으로 정렬할 것. [추정]

### 페이지네이션 절차 (제안)
1. 하루치: `DATE_1=D`, `HOUR_1=153000`(또는 조금 더 큰 값)으로 첫 호출 → 120행.
2. 받은 행 중 가장 이른 `stck_cntg_hour`에서 1분 뺀 값을 다음 `HOUR_1`로 설정해 반복. 요청 `HOUR_1`이 09:20이면 전 거래일 행이 섞여 오므로 `stck_bsop_date == D`만 채택한다. [확인됨: https://github.com/ckrhehfl/trading-engine/pull/174]
3. 새로 추가되는 D 일자 행이 없거나 가장 이른 시각이 09:01 이하이면 종료. 무한루프 방지 상한(예: 6페이지)을 둔다.
4. 제3자 실측: 종목·일당 약 4페이지(마지막 페이지는 약 21행). 처음 호출은 16:30처럼 장 마감 이후 시각에서 시작했다. [확인됨: 같은 PR]

## 2. 주식당일분봉조회
| 항목 | 내용 | 출처 |
|---|---|---|
| 경로·tr_id | `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice`, `FHKST03010200` (실전·모의 동일) | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py] |
| 파라미터 | `FID_COND_MRKT_DIV_CODE`, `FID_INPUT_ISCD`, `FID_INPUT_HOUR_1`, `FID_PW_DATA_INCU_YN`, `FID_ETC_CLS_CODE`(선택) | [확인됨: 같은 파일] |
| 1회 최대 | 30건 | [확인됨: 같은 파일] |
| DEV 지원 | 지원(샘플이 `env_dv` real/demo를 받고 같은 tr_id 사용) | [확인됨: 같은 파일] |
| 과거 일자 | **불가**. 당일 분봉만 제공 ("Only intraday minute-candle data provided") | [확인됨: 같은 파일 docstring 요약] [확인됨: 인프런 Q&A, 대부분 증권사 API는 당일만 제공] |
| 용도 | 과거 30일에는 쓸 수 없다. 실시간 수집기를 매일 돌려 쌓는 방식만 가능하나 본 프로젝트 범위(과거 백테스트) 밖이다. | |

## 3. DEV 미지원 시 대안 비교 (30일 x 2종목 1분봉 확보 여부)
| 대안 | 30일 1분봉 확보 | 보존·간격·신뢰도 | 위험 | 판정 |
|---|---|---|---|---|
| (0) KIS DEV `FHKST03010230` | 가능(미검증) | 약 1년, 1분, 거래소 원천 | 모의 서버 호출 제한(초당 1~2건) | **1순위: 먼저 시도** |
| (a) KIS PROD 키 read-only | 가능(같은 API, 실전 서버는 샘플 docstring이 명시적으로 지원) | 약 1년, 1분, 초당 20건 | **R3: 사용자 명시 승인 필수.** 주문·계좌 경로 금지(R2). | DEV 실패 시 **권장 1순위 대안** |
| (b1) yfinance `.KS` | **불가** | 1분봉은 최근 7일, 인트라데이 전체 60일. 30일 전 1분봉 요청은 오류 | 비공식 스크랩, 약관·안정성 위험. 5분봉 이상이면 60일 가능(추정) | 불가(1분봉 기준) [확인됨: 검색 결과 https://algotrading101.com/learn/yfinance-guide/ 등이 언급하는 yfinance 제한] |
| (b2) 네이버 금융 분봉 | 사실상 불가 | 공개 페이지·비공식 엔드포인트는 당일 또는 최근 며칠 위주로 알려짐. 이번 조사에서 웹 페치가 도메인 차단으로 실패해 확인하지 못함 | 스크래핑 약관 위험, 비공식 | 미확인, 비권장 |
| (b3) pykrx / FinanceDataReader | 불가 | 일봉 중심. 분봉 미제공으로 알려짐 [추정] | | 분봉에는 무의미 |
| (c) 일봉 합성(가짜 분봉) | 기술적으로 생성은 가능하나 무의미 | OHLC 4개 값으로 장중 경로를 알 수 없음. 장중 신호·체결 시뮬레이션이 임의 가정에 좌우되어 백테스트가 성립하지 않음 | 신뢰 불가 결과가 실제 성과처럼 보임 | **비권장** |
| (d) 상용 데이터 구매 | 가능 | 유료 | 범위·비용 결정 필요 | 범위 밖 |

## 4. 호출 수·소요 시간·캐시 설계
백테스트 구간 2026-08-31 ~ 09-29 거래일: 8/31(1) + 9/1~4(4) + 9/7~11(5) + 9/14~18(5) + 9/21~23(3) + 9/28~29(2) = **20일** (09-24, 09-25 추석 휴장, 대체공휴일 없음). [확인됨: stock-sim/docs/research/market-rules.md의 휴장일 절]

| 항목 | 값 | 근거 |
|---|---|---|
| 종목·일당 페이지 | 약 4 (분봉 350~381개 / 120) | [확인됨: trading-engine PR #174 (005930 381개)] |
| 총 호출 | 20일 x 2종목 x 4 = **약 160회**, 여유 포함 200회 | 계산 |
| DEV 소요 (0.5~1.0초 간격) | 약 1.5~3.5분 (429급 오류·백오프 포함해도 5분 이내) | [추정: kis-api.md 6절 DEV 호출 제한, 초당 1~2건] |
| PROD 소요 (초당 20건 상한, 0.1초 간격 사용) | 약 20~30초 | [추정] |
| 지연 | 호출당 평균 0.57초 실측(제3자) | [확인됨: 같은 PR] |
| 워밍업 추가 | 지표 워밍업으로 이전 거래일이 더 필요하면 일수를 더해 선형 증가(하루 약 8회) | 계산 |

캐시 설계 제안(CLAUDE.md 7절 캐시 규약 확장):
- 경로 `data/cache/min/<종목코드>_<YYYYMMDD>.csv`, 종목·일자 단위. 캐시가 있으면 호출 0회.
- 컬럼: `datetime`(KST, `YYYY-MM-DD HH:MM:00`), `open`, `high`, `low`, `close`, `volume`, `value`(분 거래대금, 누적 차분). 오름차순 저장.
- 완결성 검증은 봉 개수가 아닌 시간 범위로 한다(체결 없는 분에는 봉이 없으므로 종목마다 개수가 다름). 예: 첫 봉 10:05 이내 & 마지막 봉 15:00 이후. [확인됨: trading-engine PR #174가 같은 방식]
- 휴장일은 `output2`가 비거나 요청일 행이 0건이면 "휴장/무데이터"로 기록해 재호출을 막는다. 휴장 판정에 `chk-holiday`는 쓰지 않는다(kis-api.md 7절).
- 서버 보존이 약 250 거래일 롤링이므로 수집한 CSV는 삭제하지 않는다(재수집 불가할 수 있음). [확인됨: 같은 PR]

## 5. 국내 정규장 분봉 특성
| 항목 | 내용 | 확신도 |
|---|---|---|
| 정규장 | 09:00~15:30. 09:00 시가는 동시호가(단일가)로 결정, 15:20~15:30은 종가 단일가 | 시간대 [추정: KRX 일반 규정, market-rules.md 참고 가능]. 이번 조사에서 KRX 공식 URL은 미확인 |
| 09:00 봉 | 시가 단일가 체결이 09:00 봉의 시가·거래량에 포함될 가능성이 높음 | [추정] 미확인 |
| 15:20~15:30 봉 | 종가 단일가 구간은 체결이 15:30에 몰려 나오므로 15:30 봉(또는 15:29 이후 봉)에 큰 거래량이 실릴 수 있음. 공식 문서에 표기 없음. 제3자 실측은 005930이 09:00대~15:30 마지막 봉까지 381개, 다른 종목 351개라고만 보고 | 미확인. 추정. 실 데이터로 확인 필요 |
| 하루 봉 개수 | 종목별 350~381개(체결 없는 분은 봉 없음). 이론 최대 09:00~15:30 = 391개 | [확인됨: PR #174의 381/351] |
| 체결 없는 분 | 봉이 생략됨(전 봉 종가로 채운 가짜 봉 아님). 지표 계산 전 forward-fill 여부를 strategy-designer가 정해야 한다. `FID_FAKE_TICK_INCU_YN` 의미와 관련 있을 수 있으나 미확인 | [확인됨: PR #174 "A minute with no trade has no bar"] |
| 특수 일정 | 수능일처럼 개장·폐장이 1시간 늦는 날이 있다(2025-11-13은 09:59~16:29 거래). 2026-08-31~09-29에는 해당 일정이 없을 것으로 보이나 미확인 | [확인됨: PR #174 사례] / 본 구간 [추정] |
| 휴장일 | 2026-09-24, 09-25는 추석 휴장이므로 거래 없음(요청 시 빈 `output2` 또는 전 거래일 행이 반환될 수 있음. 요청일 `stck_bsop_date` 필터로 제거). 9/23 다음 거래일은 9/28 | [확인됨: market-rules.md] 응답 동작은 [추정] |
| 수정주가 여부 | 분봉 API에는 수정주가 파라미터(`FID_ORG_ADJ_PRC`)가 없다. 원시(당시 체결) 가격으로 추정. 30일 내 삼성전자·SK하이닉스 액면분할·권리락 여부는 미확인이므로 smoke test에서 일간 시가·종가와 일봉 API 값 대조 필요 | [확인됨: 요청 파라미터에 없음] / 나머지 [추정] |
| 시간대 | 응답 시각은 KST(HHMMSS) | [추정] |

## 6. 미확인 항목
- DEV(`openapivts`) 실동작. 포털 "모의 TR ID"·"모의 지원" 표시는 JS 렌더링으로 읽지 못함. 실호출 금지라 smoke test에서 확인.
- `FID_PW_DATA_INCU_YN`(과거 데이터 포함), `FID_FAKE_TICK_INCU_YN`의 `Y`/`N` 동작. 기본값만 확인.
- 종가 단일가(15:20~15:30)와 시가 단일가(09:00)가 분봉에 어떻게 반영되는지. 일 첫·마지막 봉의 시각.
- `output1`/`output2` 필드 소속 분리, 모의 호출 제한의 정확한 값(kis-api.md와 동일 이슈).
- 네이버 금융 분봉의 보존 기간(웹 페치 차단으로 확인 못함).
- 분봉이 수정주가인지 여부(공식 명시 없음).
- 제3자 자료(trading-engine PR #174)는 개인 저장소 서술이라 참고 확신도 중간. "paper host"의 정확한 도메인 미확인.

## 7. 출처 목록
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_time_dailychartprice/inquire_time_dailychartprice.py (및 `chk_` 파일)
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_time_itemchartprice/inquire_time_itemchartprice.py
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py
- https://github.com/ckrhehfl/trading-engine/pull/174 (제3자, 실측 서술)
- https://www.inflearn.com/en/community/questions/1606220 (제3자 Q&A, 당일분봉 API)
- https://algotrading101.com/learn/yfinance-guide/ (yfinance 1분봉 7일 제한 서술, 웹 검색 요약)
- stock-sim/docs/research/kis-api.md, stock-sim/docs/research/market-rules.md (내부 문서)
