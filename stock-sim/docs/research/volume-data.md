# 조사 D: 거래량·추세 데이터 확장 (volume-data.md)

조사 일자: 2026-09-30 · 담당: kis-researcher (항목 D) · API 실호출 없음, `.env` 미열람(R1), 주문·계좌 API 미조사(R2). 범위는 가격·거래량·거래대금 계열만이다.

## 다음 단계 agent가 알아야 할 핵심 5줄
1. **거래량순위 API(`volume-rank`, FHPST01710000)는 과거 시점 조회가 안 된다.** 날짜 파라미터가 없고(`FID_INPUT_DATE_1`은 샘플에서 빈 값) 조회 시점의 순위만 준다고 판단한다. 백테스트에 쓰면 look-ahead이므로(R5) **백테스트 신호·유니버스 선정에 쓰지 말 것.** 거래량 계열 실험은 기존 일봉 `acml_vol`·`acml_tr_pbmn`으로 직접 계산한다.
2. volume-rank의 DEV(모의) 지원은 **미확인**이다. 공식 샘플에 `env_dv` 분기가 없어(일봉 샘플과 다름) 지원 근거가 없다. 어차피 백테스트에 못 쓰므로 DEV 지원 확인은 불필요하다.
3. 유니버스 확장용 종목 목록은 KIS 종목 마스터 파일(`kospi_code.mst.zip`, CP949)의 `KOSPI200섹터업종` 등으로 얻는다. 하지만 **현재 시점 스냅샷**이라 과거 구성종목 이력이 없고 상장폐지 종목도 없다. 생존 편향을 없앨 수 없고 "완화하고 고지"만 가능하다.
4. 일봉 1회 100건 기준 종목당 호출 수는 6개월 2회, 12개월 4회, 24개월 6회(워밍업 포함)다. 200종목·24개월이어도 DEV 보수 가정(호출당 약 1.2초)에서 약 24분이다. 유니버스를 넓혀도 수집 비용은 문제가 아니다.
5. 기존 일봉만으로 거래량 동반 돌파·거래대금 가중 모멘텀·거래대금 기반 유동성 필터가 모두 가능하다. 새 API가 꼭 필요한 항목은 없다. 필요한 것은 종목 목록(유니버스 확장 시)뿐이다.

## 1. 거래량·거래대금 순위 API (`volume-rank`)

### 1.1 기본 정보
| 항목 | 내용 | 출처 |
|---|---|---|
| 경로 | `GET /uapi/domestic-stock/v1/quotations/volume-rank` | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/volume_rank/volume_rank.py] |
| tr_id | `FHPST01710000` (거래량순위, 실전) | [확인됨: 같은 파일] |
| 문서명 | "[국내주식] 순위분석 / 순위분석[v1_국내주식-047]" | [확인됨: 같은 파일 docstring] |
| 모의용 tr_id | 문서화 없음. 공식 `kis_auth._url_fetch`는 모의투자일 때 tr_id 첫 글자가 T/J/C이면 V로 치환하는데, `FHPST...`는 F로 시작해 치환 대상이 아니다. 즉 모의에서도 같은 tr_id가 전송된다. | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py 의 치환 코드] |
| 페이지네이션 | 샘플이 `tr_cont == "M"`을 처리하나 1회 최대 건수는 docstring에 없다. (알려진 값은 30건이나) | 최대 건수 미확인. [추정: 순위 API 관행 30건] |

### 1.2 요청 파라미터 (샘플 코드 기준)
| 파라미터 | 값 | 설명 |
|---|---|---|
| `FID_COND_MRKT_DIV_CODE` | `J` 등 (샘플 안내: J, NX, UN, W) | 시장구분 |
| `FID_COND_SCR_DIV_CODE` | `20171` | 화면 구분 코드 |
| `FID_INPUT_ISCD` | `0000`(전체) 또는 업종코드. 샘플 예시는 `0002` | 입력 종목·업종 |
| `FID_DIV_CLS_CODE` | `0` 전체, `1` 보통주, `2` 우선주 | 구분 |
| `FID_BLNG_CLS_CODE` | `0` 평균거래량, `1` 거래증가율, `2` 평균거래회전율, `3` 거래금액순, `4` 평균거래금액회전율 | 소속 구분(순위 기준) |
| `FID_TRGT_CLS_CODE` | 0/1 문자열(예 `111111111`) | 대상 구분(신용 등) |
| `FID_TRGT_EXLS_CLS_CODE` | 0/1 문자열 | 제외 구분(투자위험·경고·관리·ETF 등) |
| `FID_INPUT_PRICE_1`, `FID_INPUT_PRICE_2` | 숫자 문자열, 빈 값이면 전체 | 가격 하한·상한 |
| `FID_VOL_CNT` | 숫자 문자열, 빈 값이면 전체 | 거래량 하한 |
| `FID_INPUT_DATE_1` | 샘플에서 빈 값 | 날짜 입력칸이 있으나 사용하지 않음 |

[확인됨: volume_rank.py 요약 및 https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/volume_rank/chk_volume_rank.py]. 각 코드값의 뜻은 웹 페치 요약 기준이라 문자 그대로의 원문 대조는 못 했다. 사용하지 않을 API이므로 추가 확인은 불필요하다.

### 1.3 응답 필드 (chk 파일의 COLUMN_MAPPING)
| 필드 | 의미 |
|---|---|
| `data_rank` | 데이터 순위 |
| `mksc_shrn_iscd` | 단축 종목코드 |
| `hts_kor_isnm` | 종목명 |
| `stck_prpr`, `prdy_vrss_sign`, `prdy_vrss`, `prdy_ctrt` | 현재가, 전일대비 부호·값·비율 |
| `acml_vol` | 누적 거래량 |
| `prdy_vol` | 전일 거래량 |
| `acml_tr_pbmn` | 누적 거래대금 |
| `lstn_stcn` | 상장 주식수 |
| `avrg_vol` | 평균 거래량 |
| `vol_inrt` | 거래량 증가율 |
| `vol_tnrt`, `nday_vol_tnrt` | 거래량 회전율, N일 거래량 회전율 |
| `avrg_tr_pbmn` | 평균 거래대금 |
| `tr_pbmn_tnrt`, `nday_tr_pbmn_tnrt` | 거래대금 회전율, N일 회전율 |
| `n_befr_clpr_vrss_prpr_rate` | 전일종가대비 현재가(%) |

[확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/volume_rank/chk_volume_rank.py]

### 1.4 과거 시점 조회 여부 (핵심)
- 요청 파라미터 중 기준일을 지정할 수 있는 칸이 없다. `FID_INPUT_DATE_1`이 있으나 샘플은 빈 값으로 두고, 어떤 날짜 형식을 받는지 문서화돼 있지 않다. [확인됨: volume_rank.py] 따라서 **"조회 시점의 순위"만 준다고 판단**한다. [추정: 날짜 파라미터 부재, 순위 API 관행. 실호출로 검증하지 않았다]
- 결론: 이 API는 **실시간·당일(또는 직전 장) 스냅샷**이다. 과거 2025-09 시점의 거래량 상위 종목을 지금 조회해서 알 수 없다. 오늘 받은 순위로 과거 구간의 유니버스를 정하면 미래 정보 누수(look-ahead)이므로 R5 위반이다. **백테스트·IS 실험의 입력으로 쓰지 않는다.**
- 허용되는 용도: (a) 매일 스냅샷을 쌓아 앞으로의 데이터로 삼기(현재 프로젝트 범위 밖, 서버·스케줄러 제외 조건), (b) 사용자가 유니버스 후보를 눈으로 훑는 참고 자료. 어느 쪽도 v1/W5 백테스트에는 해당하지 않는다.

### 1.5 모의투자(DEV) 지원 여부
- **미확인.** 공식 샘플 `volume_rank.py`에는 `env_dv`, `isovrs`, 모의 분기가 전혀 없다. 반면 일봉 샘플은 `env_dv`로 `real`/`demo`를 받는다(kis-api.md 참고). [확인됨: volume_rank.py에 분기 없음]
- 포털(apiportal)의 "모의 TR ID" 칸은 JS 렌더링이라 읽지 못했다. [확인됨: kis-api.md 0절에 기록된 동일 제약]
- 판단: 모의에서 동작하지 않거나 데이터가 비어 있을 가능성이 있다. [추정: 샘플의 모의 분기 부재. 순위 API가 모의에서 미지원인 사례 다수라는 일반 통설이나 근거 URL은 못 찾음]
- 어차피 1.4 때문에 백테스트에 쓰지 않으므로 DEV 지원 확인은 우선순위가 낮다. R3에 따라 PROD로 시험하려면 사용자 승인이 필요하다.

## 2. 유니버스 확장용 종목 목록

### 2.1 방법 비교
| 방법 | 내용 | 시점 | 생존 편향 | 출처 |
|---|---|---|---|---|
| KIS 종목 마스터 파일 | `https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip` 다운로드, CP949 고정폭 텍스트. 컬럼: `단축코드`, `한글명`, `KOSPI200섹터업종`, `지수업종대/중/소분류`, `상장일자`, `거래정지`, `관리종목`, `시가총액`, `그룹코드` 등. 공식 파서 `kis_kospi_code_mst.py` 제공. API 키 불필요한 정적 파일 다운로드. | 다운로드한 날의 현재 상장 종목 | 있음(아래 2.2) | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/stocks_info/kis_kospi_code_mst.py] |
| 마스터 파일 `KOSPI200섹터업종` 컬럼 | 값이 0이 아닌 종목이 KOSPI200 편입이라는 해석이 통용되나, **필드 정의(편입 여부인지 섹터 코드인지)를 공식 문서로 확인하지 못했다.** | 현재 | 있음 | 컬럼 존재 [확인됨: 위 파서]. 값 의미는 미확인 |
| 마스터 헤더 파일 | 필드 정의: `stocks_info/종목마스터정보(코스피).h` | 현재 | 있음 | [확인됨: https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/%EC%A2%85%EB%AA%A9%EB%A7%88%EC%8A%A4%ED%84%B0%EC%A0%95%EB%B3%B4(%EC%BD%94%EC%8A%A4%ED%94%BC).h (검색 결과로 존재 확인, 본문 미열람)] |
| 지수 구성종목 조회 API | KIS에 업종/지수 구성종목을 주는 API가 있는지 확인하지 못했다. | - | - | 미확인 |
| pykrx 지수 구성종목·과거 시점 | pykrx에 특정일 지수 구성종목을 주는 함수가 있는 것으로 알려져 있으나, 2026-09부터 KRX 계정 인증이 필요해 신뢰하기 어렵다(universe.md). 함수명·지원 범위 미확인. | 과거 시점 가능성 | 낮출 수 있음 | 미확인. universe.md 참고 |
| 종목 코드 수동 목록 | 사용자가 정한 코드를 `config.yaml`에 직접 기재 | 임의 | 사용자 책임 | - |

### 2.2 생존 편향 주의점 (핵심)
- 마스터 파일은 **현재 상장 종목**의 스냅샷이다. 공식 파서는 상장폐지 종목 포함 여부를 표시하지 않으며 [확인됨: kis_kospi_code_mst.py 요약], 과거 시점의 KOSPI200 구성 이력은 담겨 있지 않다. [추정: 파일 구조가 현재 값 1행/종목]
- 오늘 기준 KOSPI200이나 시총 상위 N종목을 골라 12~24개월 전 구간을 백테스트하면 (1) 그 기간 상장폐지·관리종목·편출된 부진 종목이 빠지고 (2) 지금 시총이 큰 종목은 과거에 잘 오른 종목이라는 정보가 스며든다. **수익률이 과대평가되는 방향의 편향**이다. 현재 10종목 유니버스도 같은 문제가 있으나 규모가 작다.
- 완화 방법(제거는 불가):
  1. 편향 방향을 대시보드·보고서에 고지한다.
  2. 종목 선정 기준일을 IS 시작 시점 이전으로 못 옮기므로, 최소한 **IS 구간 내내 거래된 종목만** 남기고(상장일자 < IS 시작일 - 워밍업) 신규 상장 종목을 제외한다. 마스터 파일의 `상장일자`로 필터할 수 있다. [확인됨: 컬럼 존재]
  3. 선정을 종목 이름·현재 시총이 아닌 규칙으로 고정한다(예: 마스터의 KOSPI200 편입 전부). 수익률을 보고 종목을 고르지 않는다.
  4. 전략 성과의 **상대 비교**(전략 vs 같은 유니버스 동일비중 buy&hold)로 판단한다. 유니버스 편향은 양쪽에 똑같이 들어가므로 초과성과 해석은 덜 왜곡된다.
- 유니버스 확장은 CLAUDE.md 6.4절상 사용자 결정 사항이다. 이 문서는 가능 여부만 다룬다.

### 2.3 일봉 API에서 종목별 상장폐지·거래정지 처리
- 상장폐지 종목의 일봉을 KIS 일봉 API가 주는지는 미확인이다. 어차피 현재 마스터에 없으므로 코드를 얻을 수 없다.
- 마스터의 `거래정지`, `관리종목` 플래그로 현재 시점 기준 정지·관리종목을 제외할 수 있다. [확인됨: 컬럼 존재]. 값의 인코딩은 미확인.

## 3. 일봉 장기 구간 수집 비용

### 3.1 가정
- 일봉 API 1회 최대 100건, 종료일 기준 과거 방향 [확인됨: kis-api.md 4절, https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py]. 긴 구간은 `FID_INPUT_DATE_2`를 이전 응답의 가장 오래된 날짜 하루 전으로 옮기며 반복 호출하고 날짜로 병합·중복 제거한다. [추정: 페이지 이동 방식. 실호출 미검증]
- 거래일 수: 6개월 약 125일, 12개월 약 250일, 24개월 약 500일. 워밍업 90일(달력, 약 63 거래일)을 더한다: 188 / 313 / 563 거래일. 호출 수 = ceil(거래일 / 100) = 2 / 4 / 6회. (워밍업 제외 시 2 / 3 / 5회)
- 지수(KOSPI) 일봉은 종목과 별개로 +α. 지수 API 1회 최대 건수는 미확인이라 50건이면 종목의 2배 호출이 든다(kis-api.md 5절).
- 호출당 소요 = 대기 + 응답 지연. 대기는 DEV 공식 샘플 0.5초, 보수적으로 1.0초 [확인됨: kis_auth.py `smart_sleep` 실전 0.05 / 모의 0.5, kis-api.md 6절]. 응답 지연은 0.2초로 가정 [추정: 일반적인 REST 지연]. 즉 하한 0.7초/회, 보수 1.2초/회.
- DEV 초당 한도는 자료마다 1건 또는 2건으로 엇갈린다(kis-api.md 6절 미확정). 아래는 두 가정을 모두 병기한다.

### 3.2 시나리오 표 (종목당 호출 수 = 2 / 4 / 6)
| 종목 수 | 6개월 호출 | 12개월 호출 | 24개월 호출 | 6개월 시간 | 12개월 시간 | 24개월 시간 |
|---|---|---|---|---|---|---|
| 10 | 20 | 40 | 60 | 14초 ~ 24초 | 28초 ~ 48초 | 42초 ~ 72초 |
| 50 | 100 | 200 | 300 | 1.2분 ~ 2.0분 | 2.3분 ~ 4.0분 | 3.5분 ~ 6.0분 |
| 100 | 200 | 400 | 600 | 2.3분 ~ 4.0분 | 4.7분 ~ 8.0분 | 7.0분 ~ 12분 |
| 200 (KOSPI200 규모) | 400 | 800 | 1,200 | 4.7분 ~ 8.0분 | 9.3분 ~ 16분 | 14분 ~ 24분 |

- 시간 범위는 (호출 수 × 0.7초) ~ (호출 수 × 1.2초). [추정: 위 가정. 실측 아님]
- 캐시 재사용 시 재실행은 0회다(CLAUDE.md 7절 캐시 규약). 24개월 수집은 최초 1회만 든다.
- PROD 도메인이면 대기 0.05초를 쓰므로 200종목·24개월도 약 5분(1,200 × 0.25초) 내다. 단 R3에 따라 사용자 승인 없이는 쓰지 않는다. [추정: 위 지연 가정]
- 토큰은 24시간 유효하므로 수집 중 재발급은 필요 없다(kis-api.md 2절). 장시간 수집 중 `EGW00201` 발생 시 백오프 후 재시도한다.
- 결론: 수집 비용은 유니버스 확장의 제약이 되지 않는다. 제약은 (a) 종목 목록의 편향, (b) 이벤트(분할·정지) 데이터 품질이다.

## 4. 일봉 응답의 거래대금·수정주가 신뢰성

| 질문 | 답 | 확신도·출처 |
|---|---|---|
| 일봉에 거래대금 필드가 있는가 | 있다: `acml_tr_pbmn`(누적 거래대금, 원), 거래량 `acml_vol` | [확인됨: https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/chk_inquire_daily_itemchartprice.py] |
| `FID_ORG_ADJ_PRC=0`(수정주가)이 거래량에도 적용되는가 | **미확인.** 옵션명이 "수정주가"이고 공식 문서에 거래량 조정 여부 설명이 없다. 거래량은 분할일에 원 단위 그대로일 가능성이 있다. | 미확인 |
| 거래대금은 수정주가 영향을 받는가 | 거래대금은 실제 체결금액이므로 수정되지 않고 원 값일 가능성이 높다. | [추정: 거래대금 정의(체결 금액 합)] |
| 액면분할일의 거래량 표기 | 미확인. 분할 정보를 담은 필드 `prtt_rate`(분할 비율), `mod_yn`(변경 여부), `revl_issu_reas`(재평가사유코드), `flng_cls_code`(락 구분)가 응답에 있으나 값 형식과 의미는 미확인 | 필드 존재 [확인됨: 위 chk 파일]. 동작은 미확인 |
| 거래정지일 행 | 미확인. 정지일에 행이 없거나 거래량 0으로 오는 것이 통상이나 확인하지 못했다. | [추정: 관행] |
| 응답 값 타입 | 문자열로 오는 것이 알려져 있어 숫자 변환이 필요 | [추정: kis-api.md 4절] |

권고(데이터 품질 검사, implementer/alpha-researcher 공통):
1. 종목당 결측 거래일(전체 종목 날짜 합집합 대비), `acml_vol == 0`인 행, 전일 대비 ±30% 초과 등락, `prtt_rate`가 0이 아니거나 `mod_yn == 'Y'`인 행을 리스트업하고 해당 종목·구간을 제외하거나 alert로 표시한다. (KRX 일일 가격제한폭이 ±30%라는 점에 근거한 임계값. [추정: 제도 상식])
2. 거래량 기반 신호는 **비율**(예: 20일 평균 대비 당일 거래량)로 만들고 절대량을 종목 간에 비교하지 않는다. 분할이 거래량에 미반영된 경우에도 분할 구간을 제외하면 영향이 작다.
3. 종목 수를 넓히면 분할·정지 이벤트 확률이 올라간다. 현재 10종목은 2026-06~09에 이벤트가 없었다(universe.md). 확장 종목의 이벤트는 조사하지 못했다. 미확인.
4. 수정주가는 소급 조정이라 수집 시점에 따라 과거 가격이 달라질 수 있다. 캐시 CSV에 수집일을 남기는 편이 안전하다. [추정: 수정주가 일반 성질]

## 5. 결론: 기존 일봉만으로 가능한 것 vs 새 API가 필요한 것

### 5.1 기존 일봉(`FHKST03010100`)만으로 가능 (추가 API 없음)
| 실험 후보 | 필요한 필드 | 비고 |
|---|---|---|
| 거래량 동반 돌파(가격 신고가 + 당일 거래량 / 20일 평균 거래량 ≥ k) | `stck_clpr`, `acml_vol` | 신호는 T일 종가까지, 체결 T+1 시가(R5) |
| 거래대금 가중 모멘텀(수익률 × 거래대금 순위) | `stck_clpr`, `acml_tr_pbmn` | |
| 유동성 필터(20일 평균 거래대금 하한) | `acml_tr_pbmn` | 수량 1주 단위 제약과 함께 보면 고가주·저유동 종목 처리에 유용 |
| 거래량 급증 종목 순위(종목 간 상대) | `acml_vol` | 유니버스 내 종목끼리 비교. **volume-rank API 대체** |
| 지수 추세 필터(KOSPI가 SMA 아래면 현금) | 지수 일봉 `bstp_nmix_prpr` | kis-api.md 5절, 지수 API 최대 건수 미확인이라 분할 호출 |
| 변동성·ATR, 갭(시가 vs 전일 종가) | 시가·고가·저가·종가 | |

- volume-rank의 과거 순위는 일봉으로 **직접 재구성**할 수 있다(각 날짜에 유니버스 내 `acml_tr_pbmn`을 정렬). 이렇게 하면 look-ahead 없이 "당시 시점 순위"를 얻는다. 단 유니버스는 현재 종목 목록 기반이라 생존 편향은 남는다.

### 5.2 새 API·데이터가 필요한 것
| 항목 | 필요한 것 | 상태 |
|---|---|---|
| 유니버스를 10종목 이상으로 확장 | 종목 목록(마스터 파일 다운로드) | 가능. 정적 파일이라 API 키 불필요. 단 새 다운로드 경로 추가(네트워크 호출 위치는 CLAUDE.md 7절대로 한 곳에 모아야 함). 사용자 결정 필요 |
| 과거 시점의 정확한 지수 구성종목 | KRX 이력 데이터 | 미확인. KRX 계정 인증 필요 가능성 |
| 당일·실시간 거래량 순위 | `volume-rank` | 백테스트에 쓸 수 없음(1.4). DEV 지원도 미확인 |
| 분봉·체결강도 등 장중 데이터 | 분봉 API 등 | 범위 밖(CLAUDE.md 1절 "분봉 제외") |
| 투자자별 수급 | - | 범위 밖 |

### 5.3 다음 단계에 영향 주는 결정
- **유니버스 확장은 기술적으로 가능**하다(마스터 파일 + 일봉 반복 호출, 비용 낮음). 결정 사항은 사용자에게 있다: 확장 여부, 크기(예: KOSPI200 전체 vs 시총·거래대금 상위 N), 생존 편향 고지 수용 여부.
- 마스터 파일의 `KOSPI200섹터업종` 값 의미는 미확인이라, KOSPI200 전체 목록을 쓰려면 헤더 파일(`종목마스터정보(코스피).h`)을 읽어 정의를 확인하거나 사용자가 코드 목록을 제공해야 한다.
- 새 파서를 쓰려면 zip 다운로드와 CP949 고정폭 파싱 코드가 필요하다. 의존성은 표준 라이브러리(`zipfile`, `io`)와 기존 `pandas`로 충분하다고 본다. [추정: 파일 형식 요약 기준]. 코드는 implementer 몫이며 이 문서는 작성하지 않는다.
- volume-rank API는 W5에서 쓰지 않는 것으로 결정하는 것을 권고한다.

## 6. 미확인 항목 요약
- volume-rank의 DEV 지원(포털 JS 렌더링, 샘플에 분기 없음), 1회 최대 건수, `FID_INPUT_DATE_1`의 의미. 실호출 금지 조건이라 검증 불가.
- 마스터 파일 `KOSPI200섹터업종` 값의 정의, `거래정지`·`관리종목` 값 인코딩, 상장폐지 종목 포함 여부(공식 파서는 표시 없음).
- KIS에 업종·지수 구성종목 조회 API가 있는지, pykrx의 과거 시점 구성종목 함수.
- 수정주가 옵션이 거래량에 적용되는지, 분할일·거래정지일 일봉 행의 거래량 표기.
- 지수 일봉 1회 최대 건수(kis-api.md와 동일).
- DEV 초당 호출 한도의 정확한 값(1건 vs 2건). 3.2절 시간표는 두 경우를 포괄하는 범위다.
- GitHub API(`api.github.com`) 접근이 403이라 `examples_llm/domestic_stock` 전체 폴더 목록으로 다른 순위·구성종목 API를 훑어보지 못했다.

## 7. 출처 목록
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/volume_rank/volume_rank.py
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/volume_rank/chk_volume_rank.py
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/kis_auth.py
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/stocks_info/kis_kospi_code_mst.py
- https://github.com/koreainvestment/open-trading-api (README, `stocks_info/` 폴더 "종목정보파일 참고 데이터")
- https://raw.githubusercontent.com/koreainvestment/open-trading-api/main/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py 및 `chk_` 파일
- 내부 문서: `stock-sim/docs/research/kis-api.md`, `stock-sim/docs/research/universe.md`
