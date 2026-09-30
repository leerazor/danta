# KIS Open API 조사 (항목 A)

조사 일자: 2026-09-30. 작성: kis-researcher. API 실호출 없음(R1, R2 준수). 계좌·주문 API는 조사하지 않았다.

## 다음 단계 agent가 알아야 할 핵심 5줄
1. **DEV(모의) 도메인에서 일봉(FHKST03010100)과 KOSPI 지수 일봉(FHKUP03500100)은 지원되는 것으로 판단**한다. 공식 샘플이 `env_dv="demo"`를 오류 없이 받고, 실전·모의에 같은 tr_id를 쓴다. 다만 실호출로 검증한 것은 아니므로 implementer smoke test에서 확정한다.
2. Base URL: 실전 `https://openapi.koreainvestment.com:9443`, 모의 `https://openapivts.koreainvestment.com:29443`. 토큰은 `POST {base}/oauth2/tokenP`, 유효 24시간, 재발급은 1분당 1회이므로 파일 캐시가 필수다.
3. 일봉은 1회 최대 100건. 수집 구간 2026-06-01~09-29는 약 85 거래일이라 1회로 충분하다. `FID_ORG_ADJ_PRC` 0=수정주가, 1=원주가이므로 수정주가는 `"0"`을 쓴다.
4. 호출 제한은 실전 초당 20건, 모의는 자료마다 초당 1건 또는 2건으로 엇갈린다. 모의에서는 호출 간 0.5초 이상(안전하게 1초) 대기하고 `EGW00201`이면 백오프 재시도한다.
5. 국내휴장일조회(chk-holiday, CTCA0903R)는 모의 미지원으로 추정하고 1일 1회 권장이다. 쓰지 말고 일봉 데이터의 날짜를 거래일 달력으로 쓴다(PLAN.md 4절과 일치).

## 0. 결론: DEV 지원 여부 (가장 중요)
| API | DEV(모의) 지원 | 근거 | 확신도 |
|---|---|---|---|
| 국내주식 기간별시세 `inquire-daily-itemchartprice` | 지원(판단) | 공식 샘플 함수가 `env_dv`를 `real`/`demo`로 받고 둘 다 tr_id `FHKST03010100`을 쓴다. docstring에 "실전계좌/모의계좌의 경우, 한 번의 호출에 최대 100건까지 확인 가능"이라고 명시. [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py] | 높음. 실호출 미검증 |
| 업종 기간별시세 `inquire-daily-indexchartprice` | 지원(판단) | 공식 샘플이 `env_dv` `real`/`demo`를 모두 허용하고, 모의에서 예외를 내지 않으며 tr_id `FHKUP03500100`을 공통 사용. [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py] | 중상. docstring에 모의 지원 문구는 없고 코드 분기만 근거. 실호출 미검증 |
| 국내휴장일조회 `chk-holiday` | 미지원 가능성 높음 | 샘플에 `env_dv` 인자가 없고 tr_id `CTCA0903R` 하나뿐이다. 공식 `kis_auth._url_fetch`는 모의투자일 때 tr_id 첫 글자가 T/J/C이면 V로 바꾸는데, `CTCA0903R`은 C로 시작해 `VTCA0903R`로 바뀔 것이다. 모의용 tr_id가 문서화돼 있지 않다. [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/chk_holiday/chk_holiday.py] [추정: tr_id 치환 동작과 모의용 tr_id 부재] | 낮음 |

- 미지원으로 드러날 경우의 대안(R3): (a) PROD 키로 시세 조회만 하는 read-only 사용. **사용자의 명시적 승인이 있어야 한다.** agent가 임의로 전환하지 않는다. (b) `pykrx` 등 키 불필요 소스로 fallback(상세는 universe.md). 어느 쪽이든 PLAN.md 4절대로 사용자에게 선택을 요청한다.
- 모의투자 시세가 실전과 같은 데이터인지는 미확인이다. 일봉 과거 데이터는 같은 원장을 쓸 가능성이 높다는 추정일 뿐이다. [추정: 같은 tr_id·같은 응답 구조]
- 포털(apiportal)은 JS 렌더링이라 API별 "모의 TR ID" 칸의 값을 읽지 못했다. 포털 표 확인은 미완료다. [확인됨: https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice 는 "실전 TR ID"·"모의 TR ID" 컬럼 구조만 보였고 값은 미노출]

## 1. Base URL
| 환경 | URL | 출처 |
|---|---|---|
| 실전(PROD) | `https://openapi.koreainvestment.com:9443` | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py] |
| 모의(DEV) | `https://openapivts.koreainvestment.com:29443` | [확인됨: 같은 파일] |

## 2. 토큰 발급
| 항목 | 내용 | 출처 |
|---|---|---|
| 메서드·경로 | `POST {base}/oauth2/tokenP` | [확인됨: kis_auth.py] |
| 헤더 | `Content-Type: application/json` | [확인됨: kis_auth.py] |
| 요청 본문 | `grant_type`="client_credentials", `appkey`, `appsecret` | [확인됨: kis_auth.py] |
| 응답 필드(확인분) | `access_token`, `access_token_token_expired`(만료 시각 문자열) | [확인됨: kis_auth.py] |
| 그 외 응답 필드 | `token_type`, `expires_in` 이 있는 것으로 알려져 있으나 이번에 확인하지 못했다. | 미확인 |
| 유효기간 | 발급 후 24시간. 샘플은 만료 전이면 캐시된 토큰을 재사용한다. | [확인됨: kis_auth.py 요약, https://algolab.co.kr/blog/kis-api-key-guide-30min] |
| 재발급 제한 | 1분당 1회. 초과 시 차단(EGW00133 에러로 보고됨). 약 23시간 캐시 후 갱신을 권장한다. | [확인됨: https://github.com/koreainvestment/open-trading-api (README "1분당 1회 발급됩니다"), https://algolab.co.kr/blog/kis-api-key-guide-30min] |
| 웹소켓 접속키 | `/oauth2/Approval`. 본 프로젝트는 사용하지 않는다. | [확인됨: kis_auth.py] |

구현 지침: 토큰은 `data/cache/token_<env>.json`에 만료 시각과 함께 저장하고, 만료 전에는 재발급하지 않는다(CLAUDE.md 7절). 로그에는 키를 앞 4자리만 남긴다(R1).

## 3. 공통 헤더 (시세 GET 요청)
| 키 | 값 | 출처 |
|---|---|---|
| `Content-Type` | `application/json` | [확인됨: kis_auth.py] |
| `Accept` | `text/plain` | [확인됨: kis_auth.py] |
| `authorization` | `Bearer {access_token}` | [확인됨: kis_auth.py] |
| `appkey` | 앱키(환경별). 값은 `.env`의 `KIS_DEV_APP_KEY` 등에서 읽는다 | [확인됨: kis_auth.py] |
| `appsecret` | 앱시크릿(`KIS_DEV_APP_SECRET` 등) | [확인됨: kis_auth.py] |
| `tr_id` | API별 거래ID. 일봉 `FHKST03010100`, 지수 `FHKUP03500100` | [확인됨: 각 샘플] |
| `custtype` | 개인 `P`, 제휴사 `B`. 본 프로젝트는 `P` | [확인됨: kis_auth.py] |
| `tr_cont` | 연속조회 여부. 최초 호출은 빈 문자열, 응답 헤더 `tr_cont`가 `M` 또는 `F`이면 다음 페이지가 있다 | [확인됨: 각 샘플의 페이지네이션 코드, kis_auth.py] |
| `User-Agent` | 샘플이 설정. 필수 여부는 미확인 | [확인됨: kis_auth.py] |

## 4. 국내주식 기간별시세 (일봉)
- 경로: `GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, tr_id `FHKST03010100` (실전·모의 동일) [확인됨: inquire_daily_itemchartprice.py]
- 설명: 일/주/월/년 기간별 시세. 실전·모의 모두 1회 호출 최대 100건 [확인됨: 같은 파일 docstring]

### 요청 파라미터 (쿼리스트링)
| 파라미터 | 값 | 설명 | 출처 |
|---|---|---|---|
| `FID_COND_MRKT_DIV_CODE` | `J` | 시장구분. 샘플이 J(KRX), NX(NXT), UN(통합)을 안내한다. 본 프로젝트는 `J` | [확인됨: inquire_daily_itemchartprice.py] |
| `FID_INPUT_ISCD` | 종목코드 6자리(예 `005930`) | | [확인됨: 같은 파일] |
| `FID_INPUT_DATE_1` | 조회 시작일 `YYYYMMDD` | | [확인됨: 샘플 예시 `20220101`] |
| `FID_INPUT_DATE_2` | 조회 종료일 `YYYYMMDD` | 종료일 기준 과거 방향 최대 100건 | [확인됨: 샘플 예시 `20220809`, 최대 100건 표기] |
| `FID_PERIOD_DIV_CODE` | `D` | D 일봉, W 주봉, M 월봉, Y 년봉 | [확인됨: 같은 파일] |
| `FID_ORG_ADJ_PRC` | `0` 수정주가, `1` 원주가 | 수정주가는 `"0"`. 샘플 예시는 `"1"`을 쓴다 | [확인됨: 같은 파일 요약]. 값 의미는 샘플 요약 기준이며 포털 표로 재확인하지 못했다 |

### 응답
- 최상위: `rt_cd`(성공 `"0"`), `msg_cd`, `msg1`, `output1`(종목 요약 단일 객체), `output2`(일봉 배열). `rt_cd`·`msg_cd`·`msg1`은 KIS 공통 응답 형식으로 알려져 있으나 이번 조사에서 직접 확인하지 못했다. [추정: KIS 공통 응답 형식]
- 샘플은 output1을 1행 DataFrame, output2를 배열 DataFrame으로 변환한다. [확인됨: inquire_daily_itemchartprice.py]

`output2[]` 필드 (공식 샘플 `chk_inquire_daily_itemchartprice.py`의 컬럼 매핑에서 확인) [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/chk_inquire_daily_itemchartprice.py]
| 필드 | 의미 |
|---|---|
| `stck_bsop_date` | 영업일자 `YYYYMMDD` |
| `stck_clpr` | 종가 |
| `stck_oprc` | 시가 |
| `stck_hgpr` | 최고가 |
| `stck_lwpr` | 최저가 |
| `acml_vol` | 누적 거래량 |
| `acml_tr_pbmn` | 누적 거래대금(원) |
| `flng_cls_code` | 락 구분 코드 |
| `prtt_rate` | 분할 비율 |
| `mod_yn` | 변경 여부 |
| `prdy_vrss_sign` | 전일 대비 부호 |
| `prdy_vrss` | 전일 대비 |
| `revl_issu_reas` | 재평가사유코드 |

- 모든 값은 문자열로 온다는 점이 알려져 있어 `float`/`int` 변환이 필요하다. [추정: KIS 응답 관행. 샘플의 NUMERIC_COLUMNS는 비어 있어 확인 불가]
- 정렬은 최신일이 먼저(내림차순)라고 알려져 있다. [추정: 미확인. implementer가 날짜로 정렬할 것]
- 휴장일·거래정지 등으로 빈 행이 섞일 수 있어 `stck_bsop_date`가 빈 값인 행은 버려야 할 수 있다. [추정: 관행]
- `output1` 필드 목록은 미확인이다(본 프로젝트는 output2만 사용).

수집 계획 참고: 2026-06-01~2026-09-29는 약 85 거래일이라 1회 호출(100건 이내)로 충분하다. 종목 10개 + 지수 1개이면 11회 호출이다.

## 5. KOSPI 지수 일봉 (벤치마크)
- 경로: `GET /uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice`, tr_id `FHKUP03500100`, 모의 지원(코드 분기상, 0절 참고) [확인됨: inquire_daily_indexchartprice.py]
- 문서명: "[국내주식] 업종/기타 국내주식업종기간별시세(일_주_월_년)[v1_국내주식-021]" [확인됨: 같은 파일]
- 한 페이지 최대 건수: 문서화된 값을 확인하지 못했다(미확인). 샘플은 `tr_cont` M/F로 재귀 조회한다(깊이 10). 알려진 값은 일봉 50건이나 [추정: 미확인], 구간이 짧으면 나눠 호출하거나 tr_cont 처리를 구현한다. 본 프로젝트 구간(약 85 거래일)은 2페이지가 필요할 수 있으니 **구간을 분할해서 호출하고 날짜로 병합·중복 제거**하도록 한다.

### 요청 파라미터
| 파라미터 | 값 | 출처 |
|---|---|---|
| `FID_COND_MRKT_DIV_CODE` | `U`(업종) | [확인됨: 샘플] |
| `FID_INPUT_ISCD` | `0001`(코스피 종합). 코스닥은 `1001`, 코스피200은 `2001`로 알려져 있다 [추정: 관행] | [확인됨: 샘플 예시 `0001`] |
| `FID_INPUT_DATE_1` | 시작일 `YYYYMMDD` | [확인됨: 샘플 예시 `20250101`] |
| `FID_INPUT_DATE_2` | 종료일 `YYYYMMDD` | [확인됨: 샘플 예시 `20250131`] |
| `FID_PERIOD_DIV_CODE` | `D` | [확인됨: 샘플] |

### 응답 필드 (샘플의 컬럼 매핑, 신뢰 가능) [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_indexchartprice/chk_inquire_daily_indexchartprice.py]
| 필드 | 의미 | 소속 |
|---|---|---|
| `stck_bsop_date` | 영업일자 | output2로 추정 |
| `bstp_nmix_prpr` | 지수 종가(현재가) | output2로 추정 |
| `bstp_nmix_oprc` | 지수 시가 | output2로 추정 |
| `bstp_nmix_hgpr` | 지수 최고가 | output2로 추정 |
| `bstp_nmix_lwpr` | 지수 최저가 | output2로 추정 |
| `acml_vol` | 누적 거래량 | output2로 추정 |
| `acml_tr_pbmn` | 누적 거래대금 | output2로 추정 |
| `mod_yn` | 변경 여부 | output2로 추정 |
| `bstp_nmix_prdy_vrss`, `prdy_vrss_sign`, `bstp_nmix_prdy_ctrt`, `prdy_nmix`, `prdy_vol`, `bstp_cls_code`, `hts_kor_isnm`, `futs_prdy_oprc/hgpr/lwpr` | 전일 대비, 전일 지수 등 | output1(요약)으로 추정 |

- 필드가 output1과 output2 중 어디에 속하는지는 샘플 매핑이 두 DataFrame에 같이 적용돼 있어 확정하지 못했다. 일자별 배열(`stck_bsop_date`, `bstp_nmix_prpr` 등)이 output2라는 것은 [추정: 지수 차트 API 관행]. implementer는 응답을 받아 실제 키를 확인할 것.
- 벤치마크는 종가(`bstp_nmix_prpr`) 기준 buy&hold로 계산한다. 시작 기준가는 전략 시작일(체결일) 시가 또는 종가 중 strategy-designer가 정한다.
- 대안: 지수 API가 막히면 지수 ETF(KODEX 200 `069500`)를 일봉 API로 받아 대용하는 방법이 있다. [추정: 같은 일봉 API 사용 가능]

## 6. 호출 제한
| 항목 | 값 | 출처 |
|---|---|---|
| 실전 초당 건수 | 20건 | [확인됨: https://algolab.co.kr/blog/kis-api-key-guide-30min] (공식 문서로는 미확인) |
| 모의 초당 건수 | 1건(알고랩) 또는 2건(일반 통설). 자료가 엇갈려 **미확정** | [확인됨: 알고랩 1건] / [추정: 2건, 이번 조사에서 근거 URL 미확보] |
| 초과 에러 | `msg_cd` `EGW00201`, 메시지 "초당 거래건수를 초과하였습니다" | [확인됨: https://algolab.co.kr/blog/kis-api-key-guide-30min, 검색 결과 요약] |
| 공식 샘플의 대기 | `smart_sleep()`: 실전 0.05초, 모의 0.5초, 기본 0.1초 | [확인됨: kis_auth.py] |
| 공식 README 주의 | "모의투자 계좌는 REST API 호출 제한이 낮습니다. 단일 조회에는 문제없으나 연속 호출이 많으면 실전투자 계좌를 권장" | [확인됨: https://github.com/koreainvestment/open-trading-api] |

권장: 모의 환경에서는 호출 사이 **1.0초 대기**(안전 마진), `EGW00201`이 오면 1~2초 백오프 후 최대 3회 재시도. 본 프로젝트는 11회 호출 정도라 약 15초면 끝나고, 캐시가 있으면 0회다.

## 7. 국내휴장일조회
- 경로: `GET /uapi/domestic-stock/v1/quotations/chk-holiday`, tr_id `CTCA0903R` [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/chk_holiday/chk_holiday.py]
- 요청: `BASS_DT`(기준일자 `YYYYMMDD`), `CTX_AREA_FK`, `CTX_AREA_NK`(연속조회키, 최초 빈 값) [확인됨: 같은 파일]
- 응답: `output` 배열. 영업일·거래일·개장일·결제일 여부를 조회하며 "주문 가능 여부는 개장일여부(`opnd_yn`)를 쓰라"고 안내한다. [확인됨: 같은 파일 docstring] 개별 필드(`bass_dt`, `wday_dvsn_cd`, `bzdy_yn`, `tr_day_yn`, `opnd_yn`, `sttl_day_yn`)는 이번에 직접 확인하지 못했다. [추정: 관행]
- 주의: "원장서비스와 연관되어 단시간 다수 호출 시 서비스에 영향, 가급적 1일 1회 호출" [확인됨: 같은 파일]
- 모의 지원: 위 0절대로 미지원 가능성이 높다 [추정].
- 권고: 본 프로젝트에서는 호출하지 않는다. 거래일 달력은 실제 일봉 데이터의 날짜 집합으로 만들고, 휴장일 목록은 market-rules.md를 참고한다.

## 8. 미확인 항목 요약
- DEV에서의 실동작(실호출 미수행, 금지 사항). smoke test에서 확인할 것.
- 포털의 API별 "모의 TR ID"·모의 지원 표시(JS 렌더링으로 미노출).
- 모의 초당 호출 한도의 정확한 값(1건 vs 2건).
- 토큰 응답의 `token_type`, `expires_in`, 지수 API 1회 최대 건수, 지수 응답의 output1/output2 필드 소속, 휴장일 응답 필드명.
- 이 문서의 샘플 코드 내용 일부는 웹 페치 요약을 통해 확인한 것이라 문자 그대로의 원문이 아닐 수 있다. 예시 JSON은 공식 샘플에 없어 싣지 않았다.

## 9. 출처 목록
- https://github.com/koreainvestment/open-trading-api (공식 샘플 저장소, README)
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py (및 `chk_` 파일)
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_indexchartprice/inquire_daily_indexchartprice.py (및 `chk_` 파일)
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/chk_holiday/chk_holiday.py
- https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice (구조만 확인)
- https://algolab.co.kr/blog/kis-api-key-guide-30min (제3자 블로그: 호출 한도·토큰 제한, 공식 아님)
