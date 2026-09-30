# 조사 C: 유니버스 · 대체 데이터 소스 (universe.md)

조사 일자: 2026-09-30 · 담당: kis-researcher (항목 C) · API 호출·.env 읽기 없음(R1)

## 다음 단계 agent가 알아야 할 핵심 5줄
1. 후보 10종목 코드는 모두 KOSPI 종목 코드로 유효하다고 판단한다. 6개는 웹 출처로 확인했고 4개(000270, 068270, 035420, 005490)는 [추정]이다. 실행 시 KIS 응답으로 최종 검증한다.
2. 2026-06~09 일봉에 영향을 줄 액면분할·분할·거래정지·코드변경 이벤트는 10종목 모두 발견되지 않았다(다만 "미확인 = 없음"이 아니라 검색 한계). 삼성바이오로직스 인적분할은 2025-11-24 재상장으로 끝났고 수집 구간(2026-06-01~) 밖이다.
3. pykrx는 KRX 데이터포털이 2026-09부터 계정 인증(KRX_ID/KRX_PW)을 요구해 익명 사용이 불안정하다(일봉이 FDR로 폴백되는 사례 보고). 키 없이 쓰는 fallback 1순위는 FinanceDataReader(Naver 소스)다.
4. korean-stock-search skill은 "특정일 1건 스냅샷"만 반환하고 기간 조회·지수 조회가 없다. 종목 코드·시장 검증용이지 일봉 수집용이 아니다.
5. 새 패키지(pykrx, finance-datareader) 추가는 CLAUDE.md 7절상 사용자 승인 사항이다. 승인 전에는 의존성에 넣지 말 것.

## (a) 유니버스 10종목 검증

| 코드 | 종목명 | 시장 | 확인 근거 | 2026-06~09 일봉 영향 이벤트 |
|---|---|---|---|---|
| 005930 | 삼성전자 | KOSPI | [확인됨: skill 문서 예시 `market=KOSPI, code=005930` (C:\Users\User\.claude\skills\korean-stock-search\instruction.md), 시총 순위 https://www.seoul.co.kr/news/economy/securities/2026/09/28/20260928500115 검색 결과 요약] | 미발견 |
| 000660 | SK하이닉스 | KOSPI | [확인됨: 시총 상위 목록에 코드 000660 표기(검색 결과 요약, 위 서울신문 기사 포함 검색)] | 미발견 |
| 373220 | LG에너지솔루션 | KOSPI | [확인됨: 위와 동일 시총 상위 목록] | 미발견 |
| 207940 | 삼성바이오로직스 | KOSPI | [확인됨: 위와 동일 시총 상위 목록] | 인적분할(삼성에피스홀딩스 신설)은 2025-11-24 재상장으로 완료. 수집 구간 밖이라 영향 없음 [확인됨: https://pharm.edaily.co.kr/news/read?newsId=03234086642171544 , https://www.mt.co.kr/thebio/2025/11/03/2025110315073044179] |
| 005380 | 현대차 | KOSPI | [확인됨: 위와 동일 시총 상위 목록] | 미발견 |
| 000270 | 기아 | KOSPI | [추정: 널리 알려진 코드. 이번 조사에서 웹 출처로 코드 매칭은 못 함] | 미발견 |
| 068270 | 셀트리온 | KOSPI | [추정: 위와 동일] | 미발견 |
| 035420 | NAVER | KOSPI | [추정: 위와 동일] | 미발견 |
| 105560 | KB금융 | KOSPI | [확인됨: 위와 동일 시총 상위 목록] | 미발견 |
| 005490 | POSCO홀딩스 | KOSPI | [추정: 종목명은 KIND 공시(https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno=20260515001084&docno=&viewerhost=)로 확인되나 코드 표기는 미확인] | 미발견 |

- 이벤트 검색 결과: 2026년 9월 액면병합·분할 거래정지 사례는 코스닥 소형주(빌리언스, 랩지노믹스 등)뿐이었다 [확인됨: https://www.datatooza.com/article/20260907171026994852ef3a9d0e_80]. 위 10종목의 이벤트는 찾지 못했다. **미확인**: KIND 거래정지·공시 페이지는 동적이라 직접 열람하지 못했다.
- 권고: 수집 시 각 종목 일봉에서 (1) 결측일, (2) 전일 대비 ±30% 초과 등락(분할 징후), (3) 거래량 0을 검사하고 이상 시 alert. KIS 일봉은 수정주가 옵션 사용(상세는 kis-api.md 참조).
- 참고(범위 밖 발견): 시총 순위는 삼성전자 1,616조원, SK하이닉스 1,344조원 등으로 가격 수준이 매우 높다. 1억원 자본·최대 5종목(종목당 약 2천만원)에서는 고가주 1주 단위 수량이 문제될 수 있다. 종목 주가는 미확인이므로 strategy-designer가 수량 계산 시 확인할 것. [추정: 시총 규모에서 유추]

## (b) 대체 소스 비교

| 항목 | pykrx (1.2.9) | FinanceDataReader (0.9.202) | korean-stock-search skill |
|---|---|---|---|
| 일봉 OHLCV(기간) | 가능. `get_market_ohlcv(시작, 종료, 종목)` [확인됨: https://github.com/sharebook-kr/pykrx] | 가능. `DataReader('005930', 시작, 종료)` [확인됨: https://github.com/FinanceData/FinanceDataReader] | 불가. 기준일 1일 스냅샷(`trade-info`)만. 종목 1건×1일 호출 [확인됨: instruction.md] |
| 수정주가 | `adjusted` 파라미터, 기본은 최근 요청일 기준 수정 [확인됨: https://raw.githubusercontent.com/sharebook-kr/pykrx/master/README.md] | 문서에 명시 없음. 미확인 [확인됨: 명시 없음을 확인] | 해당 없음(원자료 스냅샷) |
| KOSPI 지수 | 가능. `get_index_ohlcv`, KOSPI 티커 "1001" [확인됨: 위 README] | 가능. `DataReader('KS11', ...)` [확인됨: https://github.com/FinanceData/FinanceDataReader] | 불가(종목 전용) |
| 거래대금 컬럼 | 미확인(KRX 소스 기준 제공되는 것으로 보이나 확인 못함) | 미확인(Naver 소스는 통상 종가·거래량 중심) [추정] | `trading_value` 제공 [확인됨: instruction.md] |
| 키 필요 | KRX 회원 ID/PW(`KRX_ID`, `KRX_PW`) 필요한 API가 있음 [확인됨: https://pypi.org/project/pykrx/] | 불필요 [확인됨: https://github.com/FinanceData/FinanceDataReader] | 불필요(프록시가 KRX 키 보유) [확인됨: instruction.md] |
| 제약 | KRX 포털이 2026-09부터 계정 인증 요구. 익명 시 일부 함수가 0행 반환, 일봉은 FDR로 폴백된 사례 [확인됨: https://github.com/kwondoyun07/K-PaperTrade/pull/44]. Naver/KRX 스크래핑, 과도한 호출 시 차단, 공식과 다를 수 있음 | 스크래핑 기반. 소스(Naver 기본/KRX/Yahoo)에 따라 이력·필드 상이 [확인됨: 위 GitHub] | 제3자 프록시(k-skill-proxy.nomadamas.org) 의존. 벌크 수집 금지 면책 조항(SKILL.md의 Legal disclaimer). 개인 조회용 |
| 새 의존성 | 필요(승인 사항) | 필요(승인 사항) | 파이썬 의존성 없음. 단 프로젝트 코드가 제3자 프록시를 호출하면 네트워크 호출 경로 추가 |

## (c) KIS 차단 시 fallback 우선순위 제안

전제: R3에 따라 PROD read-only는 사용자 승인 시에만. 아래는 "KIS DEV 미지원 + PROD 미승인" 또는 KIS 전체 장애 때의 순서다.

1. **FinanceDataReader** — 키 불필요, 종목·KOSPI 지수(KS11) 모두 기간 조회 가능. 수정주가 여부와 거래대금 컬럼은 **구현 단계 smoke test에서 확인 필요**(미확인). 수정주가가 없으면 수집 구간에 분할 이벤트가 없다는 (a)의 결과에 기대 되 이상치 검사를 넣는다.
2. **pykrx** — 기능은 가장 풍부(수정주가 옵션, 지수)하나, 2026-09부터 KRX 로그인이 필요해 `KRX_ID`/`KRX_PW`가 없으면 신뢰할 수 없다. 이 값들은 `.env`에 없으므로(CLAUDE.md 3절 목록에 없음) 사용자가 별도 발급해야 한다. 일봉이 내부적으로 FDR로 폴백된다는 보고가 있어 1순위와 사실상 같은 경로일 수 있다.
3. **korean-stock-search skill** — 기간 조회 불가. 종목코드·시장 검증과, 결과 CSV의 특정일 종가·거래대금 교차 검증 용도로만 사용한다(약 20거래일×종목 수 호출이 필요해 수집용으로는 부적합, 벌크 금지 면책 조항 저촉 소지).

제안 순서 요약: KIS DEV → (사용자 승인 시) KIS PROD read-only → FDR → pykrx(KRX 계정 확보 시). 어느 경로든 결과는 동일 스키마 CSV(`data/cache/<종목코드>_<시작>_<종료>.csv`)로 정규화해 이후 로직이 소스와 무관하도록 한다.

## 사용자 결정 필요
- 의존성 추가 승인: `finance-datareader`(권고), `pykrx`(선택). 미승인 시 fallback은 사실상 없다.
- (참고) 종목당 예산 약 2천만원 대비 고가주 1주 단위 수량 문제는 가격 확인 후 strategy-designer가 판단.

## 미확인 항목
- 기아·셀트리온·NAVER·POSCO홀딩스 코드의 웹 출처 매칭(검색 결과에 코드 미표기).
- 10종목의 2026-06~09 기업 이벤트 전수 확인(KIND 동적 페이지 미열람).
- FDR의 수정주가 처리, 거래대금 컬럼 유무, pykrx의 KRX 익명 접근 가능 범위(호출 금지 조건으로 검증 불가).
