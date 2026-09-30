# stock-sim 아키텍처 (architecture.md)

**버전 2.0 · 2026-09-30** · 담당: architect (Phase 2b) · 상태: reviewer 검토 대기
v1(일봉 `momentum_topn`, 스키마 1.1, 개정 1.2)은 git 이력에 있다. v2는 사용자가 승인한 전략 교체(`docs/strategy.md` v2, 분봉 단타 `intraday_breakout`)에 맞춘 개정이다.

이 문서와 `docs/result.example.json`은 implementer와 dashboard-builder 사이의 **계약**이다.
매매 규칙·지표 정의·문장 틀은 `docs/strategy.md`가 정한다. 이 문서는 그것을 **어디에서 계산하고 어떤 모양으로 주고받는지**만 정한다. 두 문서가 어긋나면 규칙은 strategy.md, 구조·스키마는 이 문서가 우선이며, 발견 즉시 "변경 요청"으로 보고한다.

## v1 대비 변경 요약

| 영역 | v1 | v2 |
|---|---|---|
| 입력 데이터 | 종목 일봉 10개 + 지수 일봉 | **종목 1분봉 2개**(신호·체결) + 종목 일봉 2개(전일 종가·동일가중) + 지수 일봉(벤치마크) |
| `kis_client` | 시세 조회 2종 | 시세 조회 3종. `minute_prices`(tr_id `FHKST03010230`) 추가. 기본 호출 간격 1.0초 → 0.5초 |
| `data` | 일봉 캐시 | 일봉 캐시(그대로) + **분봉 캐시 `data/cache/min/<코드>_<YYYYMMDD>.csv`**, 페이지네이션, 시각 정규화 |
| `strategy` | 리밸런싱 스케줄·목표 종목 | 1분봉→5분봉 리샘플, 당일 지표, 봉별 신호 플래그(상태 없는 순수 함수) |
| `backtest` | 일 단위 체결 | 장중 엔진(봉 시가 체결 → 봉 종가 판정), 청산 거래·일별 상태·차단 집계 반환 |
| `metrics` | 주차별 집계, 포지션 | 일별 집계, 평균 보유 시간, G·K, 매매 중단 일수. 포지션·평가 손익 없음 |
| `config.yaml` | `strategy.params`, `capital`, `max_positions`, `costs.*_pct`, `target_return`, `backtest.months/warmup_days` | strategy.md 2절 키 그대로(`strategy.*`, `session.*`, `backtest.days/initial_cash`, `costs.*_rate`, `target.monthly_return`). v1 키 `lookback_days`, `top_n`, `rebalance`, `warmup_days`, `months`, `max_positions`, `capital`, `target_return` **제거** |
| `.env` 위치 | `<config 폴더>/../.env` | 환경변수 `STOCK_SIM_ENV_FILE` 우선 → 없으면 config 폴더에서 상위로 올라가며 `.env` 탐색(git 워크트리 대응) |
| `result.json` | `schema_version` 1.1 | **2.0**. 삭제 `positions`, `allocation`, `weekly_flow`. 추가 `closed_trades`, `daily`, `trade_value_share`, `trade_table`, `blocks`. `trades[]`에 시각·사유 코드 |
| 대시보드 | 포지션 비중 도넛 / 보유 종목 수 / 주차별 스택 바 | 종목별 거래대금 비중 도넛 / 평균 보유 시간 / 일별 손익 막대. 매매 내역 표는 최근 20건 |
| 알림 | – | 추가 7종, 삭제 `CONCENTRATION`(strategy.md 11.3절) |
| `render()` | 시그니처 | **변경 없음**. `schema_version` major 검사만 `2`로 바뀐다 |
| 실행 명령·종료 코드 | – | 변경 없음 |

## 0. 설계 원칙
- 모듈 9개 유지. 프레임워크 없음. 클래스는 `KisClient`와 예외 클래스뿐이다. 파일당 200줄 목표(`report.py`는 v1부터 예외로 기록돼 있다. 분할은 보고 후 승인).
- 네트워크는 `kis_client.py` 한 곳. `strategy`·`backtest`·`metrics`는 순수 함수(파일·네트워크·시계 접근 없음).
- 캐시 우선. 캐시가 있으면 API를 호출하지 않는다. 테스트는 fixture CSV만 쓴다.
- R2는 구조로 강제한다: `KisClient`에는 토큰 발급과 시세 조회 3종 외의 메서드·경로 상수가 없다. 주문·계좌 경로 문자열은 코드 어디에도 두지 않는다(테스트로 검사, 8.3절).
- R3도 구조로 강제한다: base URL은 `config.yaml`의 `kis.env` 하나로만 정해지고, 코드에 환경을 바꾸는 분기(fallback)가 없다.
- **임계 경로**: implementer의 첫 작업은 분봉 smoke test다(8.4절). 통과 전에는 분봉 수집 코드를 확정하지 않는다.

## 1. 패키지 레이아웃과 공개 함수

```
stock-sim/
├── config.yaml
├── pyproject.toml
├── src/stock_sim/
│   ├── __init__.py
│   ├── __main__.py      # cli.main() 호출만
│   ├── config.py        # 설정 로드·검증, .env 탐색
│   ├── kis_client.py    # 유일한 네트워크 모듈
│   ├── data.py          # 캐시 I/O, 정규화, 페이지네이션
│   ├── strategy.py      # 리샘플·지표·신호 플래그 (순수)
│   ├── backtest.py      # 장중 체결 엔진 (순수)
│   ├── metrics.py       # 일별 집계·지표 (순수)
│   ├── report.py        # result.json 조립·좌표·문장
│   ├── render.py        # dashboard-builder 소유
│   └── cli.py
├── templates/dashboard.html.j2   # dashboard-builder 소유
├── tests/  (fixtures/ 포함)
├── data/cache/          # 일봉 CSV, 토큰
│   └── min/             # 1분봉 CSV (삭제 금지, 6.2절)
└── output/
```

타입 표기: `DataFrame = pandas.DataFrame`, `Path = pathlib.Path`, `date = datetime.date`. 시각은 `"HH:MM"` 문자열(봉 시작 시각, KST).

### 1.1 `config.py`
```python
class ConfigError(Exception): ...

def load_config(path: Path) -> dict
    # YAML(UTF-8) 로드 → 3절 기본값 병합 → 검증. 실패 시 ConfigError.
    # cfg["paths"] = {"root", "cache_dir", "minute_cache_dir", "result", "dashboard", "template", "env_file"}
    # env_file은 find_env_file 결과(없으면 None). minute_cache_dir = cache_dir / "min"
def find_env_file(start: Path) -> Path | None
    # ① 환경변수 STOCK_SIM_ENV_FILE이 있으면 그 경로(파일이 없으면 ConfigError)
    # ② 없으면 start(config 폴더)부터 상위 폴더로 올라가며 처음 만나는 ".env"
    # ③ 끝까지 없으면 None
def load_credentials(env: str, env_file: Path | None) -> tuple[str, str]
    # load_dotenv(env_file) 후 KIS_<env>_APP_KEY / KIS_<env>_APP_SECRET. 없으면 ConfigError(키 이름만 언급).
def mask(secret: str) -> str                 # 앞 4자리 + "****". 4자 이하면 "****"
def resolve_period(cfg: dict, today: date) -> dict
    # {"start": date, "end": date, "daily_fetch_start": date}  (3.2절)
def cost_rates(cfg: dict) -> dict            # {"buy_rate", "sell_rate", "slippage_rate"} (cfg["costs"] 그대로)
```
- **`.env` 탐색(git 워크트리)**: 이 작업은 `<저장소 루트>/.claude/worktrees/<이름>/stock-sim/`에서 돈다. 워크트리에는 `.env`가 없으므로 ②가 `stock-sim/` → 워크트리 루트 → `worktrees/` → `.claude/` → 저장소 루트 순으로 올라가 루트의 `.env`를 찾는다. **`.env`를 워크트리로 복사하지 않는다(R1).** 로그에는 찾은 경로만 남기고 내용은 남기지 않는다.
- 검증: `kis.env ∈ {"DEV","PROD"}`, `PROD`면 `kis.prod_approved_by_user is True`(아니면 ConfigError + R3 안내), `universe` 1개 이상·6자리 문자열·중복 없음, `strategy.name ∈ strategy.STRATEGIES`, `bar_minutes ≥ 1`, `entry_lookback ≥ 1`, `exit_lookback ≥ 1`, `0 < position_pct ≤ 1`, `position_pct × len(universe) ≤ 1`, 시각 문자열 `HH:MM` 형식, `session.open < entry_cutoff < force_exit_time < session.continuous_end`, `backtest.days ≥ 1`, `backtest.initial_cash > 0`, 비용률 ≥ 0, `data.minute_time_label ∈ {"start","end"}`.

### 1.2 `kis_client.py` — 토큰 + 시세 조회 3종
```python
class KisError(Exception): ...            # 메시지에 키·토큰·헤더를 넣지 않는다
class KisAuthError(KisError): ...
class KisRateLimitError(KisError): ...
class KisUnsupportedError(KisError): ...

class KisClient:
    def __init__(self, env: str, app_key: str, app_secret: str, cache_dir: Path,
                 min_interval_sec: float = 0.5, max_retries: int = 3,
                 backoff_sec: float = 2.0, timeout_sec: float = 10.0) -> None
    def get_token(self) -> str
    def daily_prices(self, code: str, start: date, end: date) -> list[dict]      # v1 그대로
    def index_daily(self, index_code: str, start: date, end: date) -> list[dict] # v1 그대로
    def minute_prices(self, code: str, day: date, hour: str) -> list[dict]       # v2 추가
        # 주식일별분봉조회 1회 호출(1페이지, 최대 120건). hour는 "HHMMSS".
        # output2 원본 행(문자열 dict)을 그대로 반환. 빈 배열이면 [] (예외 아님).
    call_count: int   # 실제 HTTP GET 횟수(토큰 제외)
```
| 항목 | 값 |
|---|---|
| 분봉 경로 | `/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice` (GET) |
| tr_id | `FHKST03010230` (DEV·PROD 같음) |
| 쿼리 | `FID_COND_MRKT_DIV_CODE="J"`, `FID_INPUT_ISCD=<코드>`, `FID_INPUT_DATE_1=<YYYYMMDD>`, `FID_INPUT_HOUR_1=<HHMMSS>`, `FID_PW_DATA_INCU_YN="N"`, `FID_FAKE_TICK_INCU_YN=""` |
| 헤더 | 일봉과 같다(`custtype="P"`, `tr_cont=""`) |
| 호출 간격 | 모든 GET 직전에 직전 호출로부터 `min_interval_sec`(기본 0.5초 = DEV 초당 2건)가 지나도록 `time.sleep` |
| 재시도 | `msg_cd == "EGW00201"`·HTTP 429·네트워크 예외 → `backoff_sec × 시도 번호`초 대기, 최대 `max_retries`회(7절) |

- 클라이언트는 **정규화도 페이지네이션도 하지 않는다**(한 번 호출, 문자열 그대로). 반복 호출·필터·형 변환은 `data.py`가 한다.
- 일봉 2종의 경로·tr_id·파라미터(`FID_ORG_ADJ_PRC="0"`)는 v1 그대로다.

### 1.3 `data.py`
```python
class DataError(Exception): ...

# 일봉 (v1 그대로 재사용)
def cache_path(cache_dir: Path, code: str, start: date, end: date) -> Path
def split_ranges(start: date, end: date, max_days: int) -> list[tuple[date, date]]
def normalize_stock_rows(rows: list[dict]) -> DataFrame
def normalize_index_rows(rows: list[dict]) -> DataFrame
def load_daily(code, start, end, cache_dir, client, refresh=False) -> DataFrame
def load_index(index_code, start, end, cache_dir, client, refresh=False) -> DataFrame
def read_cache(path: Path, integer_prices: bool) -> DataFrame | None
def issues_path(path: Path) -> Path
def make_issue(code, stock=None, day=None, value=None, excluded=False, side=None, extra=None) -> dict

# 분봉 (v2 추가)
def minute_cache_path(cache_dir: Path, code: str, day: date) -> Path
    # <cache_dir>/min/<code>_<YYYYMMDD>.csv
def normalize_minute_rows(rows: list[dict], day: date, time_label: str = "start") -> DataFrame   # 순수, 4.2절
def next_page_hour(rows: list[dict], day: date) -> str | None                                   # 순수
    # day 일자 행 중 가장 이른 stck_cntg_hour − 1분을 "HHMMSS"로. day 일자 행이 없으면 None.
def fetch_minutes_day(client: KisClient, code: str, day: date,
                      start_hour: str = "160000", max_pages: int = 6) -> tuple[list[dict], bool]
    # (합친 원본 행, truncated). 페이지네이션 규칙은 아래 표.
def read_minute_cache(path: Path) -> DataFrame | None          # 없거나 깨졌으면 None. 0행(헤더만)은 유효
def load_minutes(code: str, days: list[date], cache_dir: Path, client: KisClient | None,
                 time_label: str = "start") -> tuple[DataFrame, list[dict], dict]
    # (여러 날을 이은 1분봉 DataFrame, data_issues, {"api_calls","cache_hits","empty_days"})
def trading_days(daily: dict[str, DataFrame], start: date, end: date) -> list[date]             # 순수
    # 종목 일봉 날짜의 합집합 중 [start, end]. 분봉을 요청할 후보 일자.
def load_all(cfg: dict, period: dict, client: KisClient | None, refresh: bool = False
             ) -> tuple[dict[str, DataFrame], dict[str, DataFrame], DataFrame, list[dict], dict]
    # (minutes{code}, daily{code}, benchmark_df, data_issues, source_info)
    # source_info = {"api_calls", "cache_hits", "minute_files", "minute_rows", "empty_days"}
```
- `client=None`인데 캐시가 없으면 `FileNotFoundError`(테스트·오프라인용).
- **수집 순서**: ① 종목 일봉 2개 + 지수 일봉(구간 `daily_fetch_start`~`end`) → ② `trading_days`로 후보 일자(휴장일 제외, 예상 20일) → ③ 종목 × 후보 일자마다 분봉. 휴장일 API는 쓰지 않는다. 일봉이 먼저 있으므로 휴장일(09-24·09-25)은 분봉을 요청하지 않는다.
- v1의 `build_calendar`, `check_data`는 제거한다(거래일·결측 판정이 분봉 기준으로 바뀌었다. `DATA_MISSING` 판정은 `load_all`이 한다).

**분봉 페이지네이션(`fetch_minutes_day`)**

| 단계 | 규칙 |
|---|---|
| 첫 호출 | `hour = start_hour`(기본 `"160000"`. 장 마감 뒤 시각이라 15:30 봉까지 포함된다) |
| 채택 | 응답 행 중 `stck_bsop_date == day`인 행만. **요청일 외 일자 행은 버린다**(장 초반 시각을 요청하면 전 거래일 행이 섞여 온다) |
| 다음 호출 | `hour = next_page_hour(이번 페이지 행, day)`(가장 이른 시각 − 1분). 응답은 시각 역방향(최신 → 과거)으로 온다고 보되 순서를 믿지 않고 최솟값을 구한다 |
| 종료 | ① 이번 페이지의 `day` 행이 0건 ② 가장 이른 시각이 `090000` 이하 ③ 응답 행 수 < 120 ④ 새로 추가된 `(date, time)`이 없음 — 중 하나 |
| 상한 | `max_pages`(6)에 닿았는데 종료 조건을 만나지 못하면 `truncated = True` → `TRUNCATION_SUSPECT`, 캐시에 쓰지 않는다 |
| 예상 호출 | 종목·일당 약 4회(봉 350~381개 ÷ 120). 20일 × 2종목 ≈ 160회, 0.5초 간격으로 약 1.5~3분 |

### 1.4 `strategy.py` — 순수 함수
```python
STRATEGIES: dict[str, dict]   # {"intraday_breakout": {"signals": signals, "label": label}}

def resample_bars(minutes: DataFrame, bar_minutes: int = 5,
                  session_open: str = "09:00", continuous_end: str = "15:20") -> DataFrame
    # in: 4.2절(한 종목, 여러 날). out: 4.3절 유효 5분봉(date, time, slot, k, open, high, low, close, volume)
    # strategy.md 3.4·3.5절. continuous_end 이후 1분봉은 버린다. 무효 슬롯은 행이 없다.
def add_indicators(bars: DataFrame, entry_lookback: int, exit_lookback: int) -> DataFrame
    # 날짜별로 초기화. 추가 컬럼 hh, ll, sv, xl (정의되지 않으면 NA), pv, cv (strategy.md 4.1절, 전부 정수)
def signals(bars: DataFrame, params: dict) -> DataFrame
    # add_indicators 결과에 bool 컬럼 추가: breakout, cutoff_ok, range_ok, volume_ok, vwap_ok, exit_signal
    # 봉 k의 종가까지 정보만 쓴다(R5). 포지션·쿨다운·횟수·중단 같은 상태 조건은 넣지 않는다(backtest가 본다).
def auction_closes(minutes: DataFrame, at: str = "15:30") -> dict[date, int]
    # 날짜별 at 시각 1분봉의 종가(없는 날은 키 없음). strategy.md 8절 5번 대체 체결가용
def label(params: dict) -> str               # meta.strategy.label. 예 "5분봉 채널 돌파 · 당일 청산"
```
- 비교식은 strategy.md 4.2절의 **정수·유리수 비교**로 한다(`Decimal` 또는 `fractions.Fraction`으로 율을 다뤄 `float` 비교를 피한다).
  - `breakout`: `k ≥ N` 이고 `close > hh` / `cutoff_ok`: 봉 종료 시각 ≤ `entry_cutoff` / `range_ok`: `(hh − ll) ≥ min_range_pct × close` / `volume_ok`: `volume × N ≥ vol_mult × sv` / `vwap_ok`: `3 × close × cv > pv` / `exit_signal`: `k ≥ M` 이고 `close < xl`.
- 위임 요구의 열린 시그니처 `signals(df) -> DataFrame`은 이 함수다(파라미터 dict만 더 받는다).
- v1의 `rebalance_schedule`, `min_warmup_days`, `to_bars`, `is_valid_bar`는 제거한다(워밍업 없음, 스케줄 없음).

### 1.5 `backtest.py` — 장중 체결 엔진. 순수 함수
```python
def rate_to_int(rate: float) -> int                                   # v1 그대로
def calc_cost(amount: int, rate: float) -> int                        # v1 그대로 (half-up)
def fill_price(open_price: int, slippage_rate: float, side: str) -> int   # v1 그대로
def calc_qty(alloc: int, price: int, buy_rate: float) -> int          # v1 그대로

def run_backtest(bars: dict[str, DataFrame], daily: dict[str, DataFrame],
                 auction: dict[str, dict[date, int]], params: dict, costs: dict,
                 initial_cash: int) -> dict
    # bars[code] = strategy.signals() 결과(4.3절 + 지표 + 플래그). daily[code] = 4.1절(전일 종가용)
    # auction[code] = strategy.auction_closes() 결과. params = cfg["strategy"]. costs = config.cost_rates()
    # 반환 {"fills": DataFrame(4.4절), "closed": DataFrame(4.5절), "days": DataFrame(4.6절 상태 컬럼),
    #       "blocks": dict(4.7절), "events": list[dict](4.8절)}
```
- 하루 루프, 봉 시가 체결(매도 먼저 → 매수, 종목코드 오름차순) → 봉 종가 판정, 대기 주문 취소 규칙, `halted`, 쿨다운, 횟수 상한, 강제 청산, 대체가 청산, 상·하한가 처리는 **strategy.md 4.5·4.6절·5절·6절·8절 그대로** 구현한다. 이 문서는 입출력 모양만 정한다.
- 거래일 = `bars`에 봉이 하나라도 있는 날짜의 합집합(strategy.md 3.5절). 종목별 유효 봉 수 < `min_bars_per_day`인 날은 그 종목만 쉰다(`DAY_SKIPPED`).
- 차단 집계는 엔진이 매수 판정 시점에 센다: `breakout`이 참인데 매수 대기로 이어지지 않으면 `halt → max_entries → cooldown → cutoff → range → volume → vwap` 순으로 처음 거짓인 조건에 1.

### 1.6 `metrics.py` — 순수 함수
```python
def benchmark_curve(benchmark: DataFrame, days: list[date], capital: int) -> tuple[DataFrame, dict]   # v1 그대로
def equal_weight_return(prices: dict[str, DataFrame], days: list[date]) -> float | None               # v1 그대로(일봉)
def equal_weight_count(prices: dict[str, DataFrame], days: list[date]) -> int                         # v1 그대로
def daily_table(days: DataFrame, fills: DataFrame, closed: DataFrame, initial_cash: int) -> DataFrame
    # 일별 집계(4.6절 전체 컬럼). 하루 1행.
def summarize(fills: DataFrame, closed: DataFrame, daily: DataFrame, bench: DataFrame,
              initial_cash: int) -> dict          # 5.3절 summary의 원값(비율은 반올림 없는 소수)
def per_stock(fills: DataFrame, closed: DataFrame, universe: list[dict], initial_cash: int) -> list[dict]
def weekly_trade_value(fills: DataFrame) -> list[dict]      # ISO 주별 거래대금(KPI 카드 막대용)
```
- v1의 `closed_trades`(backtest가 직접 만든다), `weekly_flow`(보유·현금이 항상 0·전액이라 뜻이 없다)는 제거한다.
- `%` 변환과 자리수 맞춤은 `report.py`만 한다.

### 1.7 `report.py`
```python
def sign_of(x) -> str                                         # "pos" | "neg" | "zero"
def polyline_points(values, width, height, y_min, y_max) -> str
def nice_axis(v_min: float, v_max: float) -> tuple[float, float, list[float]]
def build_alerts(summary: dict, stocks: list[dict], issues: list[dict], events: list[dict],
                 period: dict, params: dict) -> list[dict]
def build_insights(summary: dict, stocks: list[dict], alerts: list[dict],
                   equal_weight: float | None = None, equal_weight_count: int | None = None
                   ) -> tuple[list[dict], dict]               # (insights 3개, next_action)
def build_result(cfg: dict, period: dict, bt: dict, daily: DataFrame, bench: DataFrame,
                 bench_info: dict, issues: list[dict], source_info: dict, generated_at: str) -> dict   # 순수
def write_result(result: dict, path: Path) -> Path            # v1 그대로
```
- 문장은 strategy.md 11절 틀을 그대로 쓴다(11.6절 기대 문자열이 테스트 기준).
- `cli`가 넘기는 값: `bt` = `run_backtest` 반환, `daily` = `metrics.daily_table`, `bench`·`bench_info` = `metrics.benchmark_curve` 반환(+ `equal_weight_return`, `equal_weight_count`), `generated_at` = `datetime.now(KST).isoformat(timespec="seconds")`.

### 1.8 `render.py` — dashboard-builder 소유. **시그니처 변경 없음**
```python
def render(result_path: Path, template_path: Path, out_path: Path) -> Path
```
| 항목 | 계약 |
|---|---|
| 동작 | `result_path`(UTF-8 JSON)를 읽어 최상위 키를 그대로 컨텍스트로 넘겨(`template.render(**result)`) `out_path`에 UTF-8로 쓴다. 부모 폴더가 없으면 만든다 |
| 예외 | 파일 없음 → `FileNotFoundError`. `schema_version`의 major가 **`2`**가 아니면 `ValueError`. 템플릿 오류는 Jinja2 예외 그대로 |
| 금지 | 네트워크, 수치 계산(합계·비율·좌표), result.json 수정, `print` |
| 의존 | 표준 라이브러리 + `jinja2`만. `stock_sim`의 다른 모듈을 import하지 않는다 |
| Jinja2 | `Environment(autoescape=True, undefined=StrictUndefined)`. 필터 6개(5.2절, v1과 같음) |
| 단독 실행 | `--result --template --out` 인자(9절) |

### 1.9 `cli.py` / `__main__.py` — implementer 소유
```python
def main(argv: list[str] | None = None) -> int
```
| 명령 | 동작 |
|---|---|
| `run --config PATH [--refresh] [--no-render] [--verbose]` | 2절 흐름 전체. `--refresh`는 **일봉 캐시만** 무시한다. 분봉 캐시와 토큰 캐시는 그대로 쓴다(6.2절) |
| `render --config PATH [--result PATH] [--out PATH]` | 기존 result.json으로 HTML만 다시 만든다 |

`render` 호출 방식(v1과 같음, 지연 import):
```python
from stock_sim.render import render
render(result_path=cfg["paths"]["result"],
       template_path=cfg["paths"]["template"],
       out_path=cfg["paths"]["dashboard"])
```
- 종료 코드: 0 성공 / 1 설정 오류 / 2 렌더 실패(result.json은 유지) / 3 KIS·데이터 오류.

## 2. 데이터 흐름

```
config.yaml ──load_config──▶ cfg ──resolve_period──▶ period{start, end, daily_fetch_start}
STOCK_SIM_ENV_FILE 또는 상위 폴더 탐색 ──find_env_file──▶ .env ──load_credentials──▶ KisClient(kis.env)
                                   │      (캐시가 전부 있으면 client=None, HTTP 0회, 토큰도 발급하지 않음)
                                   ▼
data.load_all
   ├─ 일봉: 005930, 000660, IDX0001  (캐시 → 없으면 daily_prices / index_daily)
   ├─ trading_days(일봉) → 후보 일자 20일
   └─ 분봉: 종목 × 일자  data/cache/min/<코드>_<YYYYMMDD>.csv
              └ 없으면 fetch_minutes_day(페이지 반복) → normalize_minute_rows → CSV 저장
   ▼
minutes{code}(1분봉), daily{code}, benchmark, data_issues
   ▼
strategy.resample_bars → add_indicators → signals      (종목별 5분봉 + 지표 + 신호 플래그)
strategy.auction_closes                                 (15:30 종가, 대체 청산가)
   ▼
backtest.run_backtest → fills, closed, days, blocks, events
   ▼
metrics.daily_table / summarize / per_stock / weekly_trade_value / benchmark_curve / equal_weight_*
   ▼
report.build_result → result(dict: % 변환, 좌표, 부호 플래그, 알림·인사이트 문장)
report.write_result → stock-sim/output/result.json
   ▼
render.render → templates/dashboard.html.j2 → stock-sim/output/dashboard.html
```
- `cli`는 먼저 일봉 캐시 3개가 있는지 본다. 있으면 읽어 후보 일자를 구하고, 분봉 파일이 전부 있으면 `client=None`으로 `load_all`을 부른다(`.env` 없이도 끝까지 간다).

## 3. `config.yaml` 스키마 v2와 기본값

```yaml
kis:
  env: DEV                      # DEV | PROD. base URL을 정하는 유일한 값
  prod_approved_by_user: false  # env가 PROD일 때 true가 아니면 실행 거부(R3). 사용자만 바꾼다
  min_interval_sec: 0.5         # 호출 간 최소 간격(DEV 초당 2건)
  max_retries: 3
  backoff_sec: 2.0              # 재시도 대기(시도마다 ×1, ×2, ×3)
  timeout_sec: 10
universe:
  - {code: "005930", name: "삼성전자"}
  - {code: "000660", name: "SK하이닉스"}
benchmark: {code: "0001", name: "KOSPI"}
data:
  minute_time_label: start      # start | end. KIS stck_cntg_hour가 봉의 시작/끝 중 무엇인지(8.4절에서 확정)
  minute_start_hour: "160000"   # 하루치 첫 페이지 요청 시각
  minute_max_pages: 6
session:
  open: "09:00"
  continuous_end: "15:20"
backtest:
  end: "2026-09-29"             # 고정. "auto"도 허용(오늘 − 1일)
  days: 30                      # 달력 일수. start = end − (days − 1)일
  initial_cash: 100000000
strategy:
  name: intraday_breakout
  bar_minutes: 5
  entry_lookback: 6
  exit_lookback: 3
  vol_mult: 1.5
  min_range_pct: 0.005
  entry_cutoff: "14:50"
  force_exit_time: "15:15"
  cooldown_bars: 3
  max_entries_per_symbol_per_day: 4
  daily_loss_limit_pct: 0.01
  position_pct: 0.5
  min_bars_per_day: 60
costs:                          # 비율(0.00015 = 0.015%). v1의 % 단위 키는 없앴다
  buy_rate: 0.00015
  sell_rate: 0.00215
  slippage_rate: 0.0
target:
  monthly_return: 0.02
output:
  result: output/result.json
  dashboard: output/dashboard.html
  template: templates/dashboard.html.j2
  cache_dir: data/cache
```
### 3.1 규칙
- strategy.md 2절 표의 키를 **이름 그대로** 둔다(`strategy.*`는 `params` 아래로 묶지 않는다). `run_backtest`의 `params`는 `cfg["strategy"]` 전체다.
- 종목 코드·시각은 따옴표 문자열. 상대 경로는 config 파일 폴더 기준.
- 누락 키는 위 기본값으로 채운다. **v1 키(`strategy.params`, `lookback_days`, `top_n`, `rebalance`, `backtest.months`, `backtest.warmup_days`, `capital`, `max_positions`, `target_return`, `costs.*_pct`)가 있으면 `ConfigError`**(조용히 무시하면 옛 설정으로 돌린 줄 알게 된다). 그 밖의 알 수 없는 최상위 키는 경고 로그.
- `data.*`와 `kis.*`는 strategy.md에 없는 수집 설정이다. 매매 결과에 영향을 주는 값은 `data.minute_time_label` 하나다.
- 알림 임계값(strategy.md 11.3절)은 표시 규칙이라 config에 두지 않는다.

### 3.2 기간 해석 (`resolve_period`)
| 값 | 규칙 | 기본 실행 |
|---|---|---|
| `end` | 날짜 문자열이면 그 날. `auto`면 `today − 1일` | 2026-09-29 |
| `start` | `end − (days − 1)일` | 2026-08-31 |
| `daily_fetch_start` | `start − 7일`(전일 종가용. strategy.md 3.3절의 08-28을 포함한다) | 2026-08-24 |
| 거래일 `d1..dn` | 분봉이 하나라도 있는 날짜 | 예상 20일(08-31 ~ 09-29) |

- 워밍업 구간은 없다. `end`를 고정값으로 둔 이유: 서버 분봉 보존이 약 250거래일 롤링이고 구간이 사용자 확정값이기 때문이다.

## 4. 내부 데이터 모델

### 4.1 일봉 DataFrame (종목·지수, v1 그대로)
컬럼 `date, open, high, low, close, volume, value`. 정규화 규칙·KIS 필드 대응은 v1과 같다(종목 `stck_*`, 지수 `bstp_nmix_*`, 오름차순, 중복 제거, 비정수 가격 half-up + `NON_INTEGER_PRICE`). 용도: 지수 → 벤치마크, 종목 → 동일가중 벤치마크·가격제한폭 판정용 전일 종가·후보 거래일.

### 4.2 1분봉 DataFrame (캐시 CSV와 같은 컬럼)
| 컬럼 | dtype | KIS 필드 | 비고 |
|---|---|---|---|
| `date` | `datetime64[ns]` (CSV `YYYY-MM-DD`) | `stck_bsop_date` | 요청일과 같은 행만 |
| `time` | str `HH:MM` | `stck_cntg_hour` (`HHMMSS`) | **봉 시작 시각**으로 정규화 |
| `open`, `high`, `low`, `close` | int64 | `stck_oprc`, `stck_hgpr`, `stck_lwpr`, `stck_prpr` | 원 |
| `volume` | int64 | `cntg_vol` | 분 거래량 |

정규화 규칙(`normalize_minute_rows`):
1. 값은 전부 문자열로 본다 → `pd.to_numeric(errors="coerce")`. 날짜·시각 파싱 실패 행은 버린다.
2. `stck_bsop_date != day`인 행은 버린다(전 거래일 혼입).
3. **시각**: `time_label == "start"`면 `HHMMSS`의 `HH:MM`을 그대로 쓴다. `"end"`면 1분을 뺀다(09:01 → 09:00). 초 자리는 버린다.
4. `(date, time)` 오름차순 정렬, 같은 키는 마지막 것만 남긴다.
5. 가격이 정수가 아니면 half-up 반올림 + `NON_INTEGER_PRICE`(strategy.md 3.3절).
6. **체결 없는 분은 행이 없다**(하루 350~381행). 채워 넣지 않는다(forward-fill 금지). 5분봉은 있는 1분봉만으로 만들고(strategy.md 3.4절), 1분봉이 하나도 없는 슬롯은 무효 슬롯이다(8절 3번, `BAR_MISSING`). 유효 5분봉이 `min_bars_per_day` 미만인 날은 그 종목을 쉰다(8절 4번, `DAY_SKIPPED`).
7. **분 거래대금은 저장하지 않는다.** `acml_tr_pbmn`은 누적값이고 페이지 경계·결측 분 때문에 차분이 불안정하다. 전략·대시보드는 시장 거래대금을 쓰지 않는다(대시보드의 "거래대금"은 시뮬레이션 체결 금액 `수량 × 체결가`다). 시장 분 거래대금이 필요해지면 `close × volume` 근사를 쓴다.
8. 분봉은 **수정주가가 아닌 원시 가격**으로 본다(API에 수정주가 파라미터가 없다). 일봉은 수정주가다. 구간 안에 권리락·분할이 있으면 둘이 어긋나므로 smoke test에서 대조한다(8.4절).

### 4.3 5분봉 DataFrame (`resample_bars` → `add_indicators` → `signals`)
| 컬럼 | 타입 | 뜻 |
|---|---|---|
| `date`, `time` | date, str | 슬롯 시작 시각(09:00, 09:05, …, 15:15) |
| `slot` | int | 0~75 (무효 슬롯도 번호는 차지한다) |
| `k` | int | 당일 유효 봉 번호(0부터, 무효 슬롯은 건너뜀) |
| `open, high, low, close, volume` | int | strategy.md 3.4절 |
| `hh, ll, sv, xl` | Int64(NA 가능) | 직전 N봉 최고·최저·거래량 합, 직전 M봉 최저 |
| `pv, cv` | int | 당일 누적 `(H+L+C)×V`, 누적 거래량 |
| `breakout, cutoff_ok, range_ok, volume_ok, vwap_ok, exit_signal` | bool | 1.4절 |

유효 봉만 행으로 둔다. "바로 다음 슬롯이 무효인지"는 `slot` 차이로 판정한다(매수 대기 취소, strategy.md 8절 3번).

### 4.4 체결 레코드 (`fills`, 체결 1건 = 1행)
| 컬럼 | 타입 | 뜻 |
|---|---|---|
| `id` | int | 1부터. 날짜 → 시각 → (매도 먼저, 종목코드순) → (매수, 종목코드순) |
| `date`, `time` | date, str | 체결 봉 시작 시각. 대체가 청산은 `"15:30"` |
| `signal_time` | str / None | 신호 봉 시작 시각. `EXIT_EOD`는 None |
| `code`, `side` | str | `BUY` / `SELL` |
| `qty`, `price`, `amount`, `cost` | int | 수량, 체결가(슬리피지 반영), `qty × price`, 비용 |
| `net_cash` | int | 매수 `−(amount + cost)`, 매도 `+(amount − cost)` |
| `reason` | str | `ENTRY_BREAKOUT` / `EXIT_BREAKDOWN` / `EXIT_EOD` |
| `closed_id` | int | 속한 청산 거래의 `id` |
| `realized_pnl`, `realized_ret`, `hold_minutes` | int / float / int, 매수는 None | 매도 행에만 |

### 4.5 청산 거래 (`closed`, 매수~매도 한 쌍 = 1행)
`id`(매도 체결 일시 → 종목코드 오름차순, 1부터), `code`, `date`, `entry_time`, `exit_time`, `hold_minutes`, `qty`, `entry_price`, `exit_price`, `gross_pnl`(`qty × (매도가 − 매수가)`), `cost`(매수 비용 + 매도 비용), `pnl`(`gross_pnl − cost`), `ret`(`pnl / (매수 amount + 매수 cost)`), `exit_reason`, `buy_fill_id`, `sell_fill_id`.

### 4.6 일별 레코드 (`days` → `daily_table`, 거래일마다 1행)
| 컬럼 | 만드는 곳 | 뜻 |
|---|---|---|
| `date`, `e_start`, `e_end`, `halted`, `skipped_codes` | backtest | 장 시작·마감 평가액(= 현금), 매매 중단 여부, 봉 부족으로 쉰 종목 |
| `pnl`, `ret`, `cum_ret`, `drawdown` | metrics | `e_end − e_start`, 일별 수익률, 누적 수익률, 고점(E0 포함) 대비 낙폭 |
| `buy_count`, `sell_count`, `closed_count`, `trade_value`, `cost` | metrics | 그 날 체결 집계 |

### 4.7 차단 집계 (`blocks`)
`{"breakout": int, "halt": int, "max_entries": int, "cooldown": int, "cutoff": int, "range": int, "volume": int, "vwap": int}` — 기간 합계(strategy.md 4.2절). `breakout` = 돌파가 참이었던 판정 수.

### 4.8 데이터 이슈·이벤트 (알림의 재료)
공통 모양(`data.make_issue`): `{"code", "stock", "date", "value", "excluded", "side", "extra"}`. v2에서 `extra`에 `{"time": "HH:MM"}`(봉 시각), `{"alloc": int}` 등을 담는다.

| 만드는 곳 | 코드 |
|---|---|
| `data` | `DATA_MISSING`(종목 분봉 전체 0행 → `excluded=True`), `NON_INTEGER_PRICE`, `TRUNCATION_SUSPECT` |
| `backtest` | `DAY_SKIPPED`(value = 유효 봉 수), `BAR_MISSING`(종목·날짜별 무효 슬롯 수), `EOD_FALLBACK`(value = 체결가), `PRICE_ANOMALY`(value = 등락률, extra.time), `PRICE_LIMIT_FILL`, `UNTRADABLE_SKIP`, `QTY_ZERO_SKIP` |
| `metrics` | `BENCHMARK_BASE_FALLBACK` |
| `report`(요약값에서 판정) | `MDD_BREACH`, `LOSS_STREAK`, `UNDERPERFORM`, `COST_DRAG`, `NO_TRADES`, `DAILY_LOSS_HALT`, `OVERNIGHT_GAP_NOTE`, `LOW_SAMPLE` |

## 5. `result.json` 스키마 v2

### 5.1 공통 규칙 (v1과 같음)
| 항목 | 규칙 |
|---|---|
| 인코딩 | UTF-8, `ensure_ascii=False`, 들여쓰기 2. `NaN`·`Infinity` 금지(없으면 `null`) |
| 금액·수량 | 정수(원, 주). 지수 값만 실수 |
| 비율 | **퍼센트 단위 숫자**, 키가 `_pct`로 끝난다. 소수 4자리. 표시는 필터가 2자리로 만든다 |
| 기하 값 | 좌표 소수 1자리(계약 테스트는 형식·범위만 본다). `height_pct`, `bar_pct`, `start_pct`, `end_pct`, `x_pct`, `width_pct`, `progress_pct`는 소수 2자리 |
| 부호 | `sign` 또는 `<이름>_sign` = `"pos"` / `"neg"` / `"zero"`. 흰 배경은 `sign_color`, 어두운 배경은 `sign_color_dark` |
| 색 | 도넛·막대 조각·알림 점은 JSON의 `color`(hex)를 그대로 쓴다 |
| 날짜·시각 | `"YYYY-MM-DD"`, `"HH:MM"`. `generated_at`만 ISO 8601(`+09:00`) |
| 분 | `hold_minutes`는 정수, `avg_hold_minutes`는 소수 1자리. 템플릿은 뒤에 `분`만 붙인다 |
| 문장 | `caption`, `note`, `title`, `detail`, `text`, `*_label`, `disclaimers`, `slippage_note`는 report.py가 완성한 한국어 문자열 |
| 배열 | 비어도 키는 항상 있다(`[]`) |
| 금지 | 키, 토큰, 계좌번호, 실잔고, 개인정보(R4) |

### 5.2 템플릿 필터 (v1과 같은 6개, 추가 없음)
`won`, `signed_won`, `pct`, `signed_pct`, `sign_color`(pos `#1428A0` / neg `#B0472F` / zero `#6E7688`), `sign_color_dark`(pos `#7C9BFF` / neg `#E29A80` / zero `#FFFFFF`). null 입력은 `–`. 초과수익은 `signed_pct` 뒤에 `p`를 붙인다. 천 단위 콤마만 필요한 수는 템플릿의 `"{:,}".format`을 써도 된다.

### 5.3 최상위 키와 필드
`docs/result.example.json`이 **키 구조의 기준**이다(8.3절 계약 테스트).

| 키 | 타입 | 내용 |
|---|---|---|
| `schema_version` | str | `"2.0"` |
| `meta` | object | 아래 |
| `flags` | object | `no_trades`, `only_baseline_alerts`, `trades_truncated` (bool) |
| `summary` | object | KPI. 아래 |
| `equity_curve` | array | 거래일별. `date, equity, return_pct(누적), drawdown_pct, realized_pnl_cum` |
| `benchmark` | array | 거래일별(같은 날짜·길이). `date, close, value, return_pct` |
| `daily` | array | 거래일별(같은 날짜·길이). `date, label(MM-DD), show_label, e_start, e_end, pnl, sign, return_pct(일별), buy_count, sell_count, closed_count, trade_value, cost, halted, segments[2]{key, label, value, height_pct, color}` |
| `charts` | object | `equity`, `sparklines`, `win_donut`, `trade_value_bars`, `daily_pnl`. 5.5절 |
| `trade_value_share` | object | 도넛. `total, center{label, value, unit}, conic_gradient, segments[]{code, label, value, share_pct, start_pct, end_pct, color}` |
| `trades` | array | **전체 체결**, 체결 순. `id, date, time, signal_time, code, name, side, side_label, qty, price, amount, cost, net_cash, realized_pnl, realized_pnl_pct, sign, hold_minutes, reason, reason_label, closed_id, in_table` |
| `trade_table` | object | 매매 내역 표 표시 규칙. `limit, total, shown, truncated, caption` |
| `closed_trades` | array | 전체 청산 거래. `id, code, name, date, entry_time, exit_time, hold_minutes, qty, entry_price, exit_price, gross_pnl, cost, pnl, return_pct, sign, exit_reason, exit_reason_label, buy_fill_id, sell_fill_id` |
| `per_stock` | array | 유니버스 전 종목. `code, name, status, status_label, trade_count, buy_count, sell_count, closed_count, win_count, loss_count, win_rate_pct, gross_pnl, cost, realized_pnl, sign, return_pct, contribution_pct, bar_pct, trade_value, trade_value_share_pct, trade_volume, avg_hold_minutes` |
| `top_contributors` | object | `items[]{rank, code, name, pnl, sign, bar_pct}`, `note` |
| `blocks` | object | `breakout, entries, blocked, items[7]{key, label, count, bar_pct}, caption` |
| `alerts` | array | `level, code, title, detail, date, color` |
| `insights` | array | 항상 3개. `no, title, detail` |
| `next_action` | object | `label, text` |
| `target` | object | `target_return_pct, current_return_pct, current_return_sign, gap_pct, target_equity, gap_amount, achieved, progress_raw_pct, progress_pct, bar_segments[1]{key, label, width_pct, color}, caption` |

`meta`
| 필드 | 내용 |
|---|---|
| `is_example` | **예시 파일만 `true`**(가짜 수치 표시). 실제 결과는 `false` |
| `label`, `title` | 헤더 문자열(고정) |
| `period` | `start, end, days, trading_days`. `start`·`end`는 실제 첫·마지막 거래일 |
| `generated_at`, `env` | 생성 시각, `"DEV"` / `"PROD"` |
| `strategy` | `name, label, params`(cfg["strategy"]에서 `name` 제외) |
| `session` | `open, continuous_end` |
| `data_source` | `provider, env, minute_tr_id, minute_time_label, daily_adjusted(true), minute_adjusted(false), daily_fetch_start, fetch_end, minute_files, minute_rows, api_calls, cache_hits, excluded[]{code, name, reason}, empty_days[]{code, date}` |
| `universe`, `benchmark` | `[{code, name}]`, `{code, name, base_price, base_kind}` |
| `capital` | 초기 자본 |
| `costs` | `buy_cost_pct, sell_cost_pct, slippage_pct, round_trip_pct`(% 단위 표시용. 기본 0.015 / 0.215 / 0.0 / 0.2305) |
| `slippage_note` | 슬리피지 0 가정 고지 한 문장(5.5절). 점검 필요 카드 하단에 그대로 출력 |
| `disclaimers` | 한계 고지 배열(strategy.md 13절). 대시보드 하단 |

`summary` (정의는 strategy.md 9절)
| 필드 | 뜻 |
|---|---|
| `initial_capital`, `final_equity`, `total_pnl`(+`_sign`), `total_return_pct`(+`_sign`) | `total_pnl = final_equity − initial_capital = realized_pnl` |
| `benchmark_return_pct`, `excess_return_pct`, `equal_weight_return_pct`, `excess_vs_equal_weight_pct` (각 +`_sign`) | v1과 같음. 동일가중이 null이면 뒤 둘은 null·`"zero"` |
| `mdd_pct`, `mdd_sign`, `mdd_peak_date`, `mdd_trough_date` | 일별 기준. MDD 0이면 두 날짜 null. 고점이 초기 자본이면 `mdd_peak_date`만 null(표시는 v1 규칙: 차트 caption·템플릿은 "시작", strategy.md 11절 문장은 "초기 자본") |
| `trade_count`, `buy_count`, `sell_count` | 체결 건수(헤더 KPI) |
| `closed_count`, `win_count`, `loss_count`, `even_count` | 청산 거래 수와 이익·손실·손익 0 건수 |
| `win_rate_pct`, `payoff_ratio`, `max_loss_streak` | 0건이면 null, null, 0 |
| `realized_pnl`(+`_sign`), `gross_pnl`(+`_sign`), `total_cost`, `buy_cost`, `sell_cost` | **`realized_pnl = gross_pnl − total_cost`** (P = G − K) |
| `cost_to_capital_pct` | `total_cost / initial_capital × 100` |
| `avg_hold_minutes` | 평균 보유 시간(분, 소수 1자리). 0건이면 null |
| `avg_closed_per_day`, `avg_fills_per_day` | `closed_count / trading_days`, `trade_count / trading_days`(소수 2자리) |
| `halt_days` | 매매 중단 일수 |
| `exit_reasons` | `{"breakdown": n, "eod": n}` 청산 사유별 건수 |
| `total_trade_value`, `buy_value`, `sell_value`, `total_trade_volume`, `turnover_pct` | 거래대금(비용 제외), 체결 주식 수, 회전율 |

v1에서 없앤 summary 필드: `unrealized_pnl`, `holding_count`, `max_positions`, `cash`, `cash_weight_pct`(항상 0 또는 전액).

`trades[].reason` → `reason_label`: `ENTRY_BREAKOUT` "돌파 매수" / `EXIT_BREAKDOWN` "하락 이탈 매도" / `EXIT_EOD` "마감 청산". `closed_trades[].exit_reason_label`도 같다.
`per_stock.status`: `traded` "거래" / `no_trade` "거래 없음" / `excluded` "제외(데이터 없음)". 정렬: `traded`를 `realized_pnl` 내림차순 → `no_trade` → `excluded`. `sign`은 `realized_pnl`의 부호이며 `return_pct`의 부호와 항상 같다.
`alerts`: 코드·조건·등급·문장·순서는 strategy.md 11.3절. `color`: `MDD_BREACH`·`LOSS_STREAK`·`UNDERPERFORM`은 `#B0472F`, 그 밖의 warn은 `#C98A2E`, info는 `#1428A0`. 날짜는 한 알림에서 한 곳에만 쓴다(`date`를 쓰는 코드: `DAY_SKIPPED`, `EOD_FALLBACK`, `PRICE_ANOMALY`, `PRICE_LIMIT_FILL`, `UNTRADABLE_SKIP`, `QTY_ZERO_SKIP`).

### 5.4 대시보드 섹션 ↔ JSON 필드
**굵은 글씨**가 v1에서 바뀐 자리다. 세 자리의 대체 내용은 오케스트레이터 결정이며 사용자 최종 확인 전이다(CLAUDE.md 8절 표 갱신은 오케스트레이터 담당).

| # | 샘플 섹션 | 시뮬레이션 대시보드 (v2) | JSON 필드 |
|---|---|---|---|
| 1 | 헤더 라벨·제목·기준일 | 라벨 / 제목 / 백테스트 구간 | `meta.label`, `meta.title`, `meta.period.start`~`end`, `meta.period.trading_days`, `meta.generated_at`, `meta.env`, `meta.strategy.label` |
| 2 | 헤더 KPI 4개 | ① 누적 수익률 ② 초과수익 ③ MDD ④ 거래 횟수 | ① `summary.total_return_pct`, 보조 `final_equity` ② `excess_return_pct`, 보조 `benchmark_return_pct` ③ `mdd_pct`, 보조 `mdd_peak_date`→`mdd_trough_date` ④ `trade_count`, 보조 `buy_count`·`sell_count`. ①②③ 색은 `*_sign`에 `sign_color_dark` |
| 3 | KPI 카드 5개 | ① 최종 평가금액(스파크라인) ② 실현 손익 ③ 승률(도넛) ④ **평균 보유 시간(분)** ⑤ 총 거래대금(막대) | ① `summary.final_equity`, `total_return_pct`, `charts.sparklines.equity` ② `summary.realized_pnl`(+sign), 보조 두 줄 "비용 전 손익" `gross_pnl`(`signed_won`, 색 `gross_pnl_sign`) · "총 비용" `total_cost`(`won`), `charts.sparklines.realized_pnl` ③ `win_rate_pct`, `win_count`·`loss_count`·`closed_count`, `charts.win_donut` ④ **`summary.avg_hold_minutes`, 보조 "일평균 청산 `avg_closed_per_day`건 · 체결 `avg_fills_per_day`건", `charts.sparklines.daily_fills`** ⑤ `total_trade_value`, `total_trade_volume`, `charts.trade_value_bars[]` |
| 4 | 추이 차트 | 자산 곡선 vs KOSPI buy&hold | `charts.equity`(`viewbox`, `equity_points`, `equity_area_path`, `benchmark_points`, `y_labels`, `x_labels`, `zero_line_top_pct`, `unit`, `caption`). 원값 `equity_curve[]`, `benchmark[]` |
| 5 | 도넛 | **종목별 거래대금 비중** | `trade_value_share.conic_gradient`, `.center`(`label`, `value`, `unit`), `.segments[]`(`label`, `value`, `share_pct`, `color`), `.total` |
| 6 | 스택 바 | **일별 손익 막대**(거래일별 실현 손익) | `daily[].segments[]`(`height_pct`, `color`), `daily[].label`, `daily[].show_label`, `daily[].pnl`·`sign`, `daily[].halted`, `charts.daily_pnl.caption`. 그리는 법은 5.5절 |
| 7 | 상위 팀 바 | 종목별 손익 기여 상위 5 | `top_contributors.items[]`, `top_contributors.note` |
| 8 | 분석 요약(다크 패널) | 인사이트 3개 + 다음 조치 | `insights[]`, `next_action.label`, `next_action.text` |
| 9 | 상세 테이블 | 종목별 상세 | `per_stock[]`: `name`(보조 `code`), `status_label`, `trade_count`, `closed_count`, `win_rate_pct`, `realized_pnl`, `return_pct`, `avg_hold_minutes`, `bar_pct`. 색은 `sign`. 선택(보조줄): `gross_pnl`, `cost`, `trade_value` |
| 10 | 점검 필요 | 리스크 알림 + 진입 차단 집계 + 슬리피지 고지 | `alerts[]`, `flags.only_baseline_alerts`, `blocks.caption`(선택: `blocks.items[]` 막대), `meta.slippage_note` |
| 11 | 연간 목표 진척 | 목표 수익률 대비 진척 | `target`(큰 숫자 `current_return_pct`, `progress_pct`, `bar_segments[]`, `gap_pct`, `gap_amount`, `caption`) |
| 12 | (추가) 매매 내역 표 | **최근 20건**, 시각·사유 포함 | `trades[]` 중 `in_table == true`인 행을 배열 순서대로. 열 10개: 체결일 `date` / 시각 `time` / 종목 `name`(보조 `code`) / 구분 `side_label` / 수량 `qty` / 체결가 `price` / 금액 `amount` / 비용 `cost` / 실현손익 `realized_pnl`(`signed_won`, 색 `sign`, 보조 `hold_minutes`분) / 사유 `reason_label`. 표 아래 `trade_table.caption` |
| + | (샘플에 없음) | 한계 고지(하단) | `meta.disclaimers[]` |

### 5.5 미리 계산하는 값의 규칙 (report.py가 계산, 템플릿은 표시만)
**시계열 좌표 공통**(v1과 같음): 점의 수는 거래일 수 n + 1. 맨 앞에 시작점(수익률 0, 누적 손익 0, 체결 0)을 붙인다. `x_i = width × i / n`.

| 값 | 규칙 |
|---|---|
| `charts.equity` | viewBox `0 0 720 250`. y값은 누적 수익률(%). `y = 250 × (y_max − v) / (y_max − y_min)`. 축은 v1 `nice_axis`(간격 후보 `[0.5, 1, 2, 5, 10, 20, 50]`, 눈금 5개). `zero_line_y`, `zero_line_top_pct`, `equity_area_path`, `x_labels[]`(ISO 주 첫 거래일, `x_pct = i / n × 100`)도 v1과 같다 |
| `charts.sparklines.*` | viewBox `0 0 200 44`. `y = 41 − 38 × (v − min) / (max − min)`, `max == min`이면 전부 `22.0`. `equity` = 누적 수익률, `realized_pnl` = 누적 실현 손익, `daily_fills` = 일별 체결 건수. (평가 손익이 없으므로 `equity`와 `realized_pnl`의 모양은 같다) |
| `charts.win_donut` | `win_pct`(소수 2자리, 0건이면 0), `conic_gradient = "conic-gradient(#1428A0 0% {p}%, #E1E4EC {p}% 100%)"` |
| `charts.trade_value_bars[]` | ISO 주별 거래대금(매수 + 매도). `label`(주 첫 거래일 MM-DD), `value`, `height_pct = value / 최댓값 × 100`, `color`: 75 이상 `#1428A0`, 50 이상 `#4B5CC0`, 25 이상 `#909BD6`, 그 밖 `#C2C8E8` |
| `daily[].segments[]` | 길이 2, 순서 고정: `{"key":"gain","label":"수익","color":"#1428A0"}`, `{"key":"loss","label":"손실","color":"#B0472F"}`. `value`는 절댓값(수익일이면 gain에 `pnl`, loss는 0. 손실일은 반대). `height_pct = value / charts.daily_pnl.max_abs × 100`(최댓값 0이면 전부 0). **그리는 법**: 막대 영역을 위·아래 절반으로 나누고 gain은 위 절반에서 아래를 기준으로 `height_pct`%, loss는 아래 절반에서 위를 기준으로 `height_pct`%. 색이 곧 부호다 |
| `daily[].show_label` | ISO 주의 첫 거래일만 `true`(축 라벨이 겹치지 않게). `daily[].halted`가 `true`면 템플릿이 그 날 라벨 옆에 "중단" 표시를 붙일 수 있다 |
| `charts.daily_pnl` | `max_abs`, `win_days`(`pnl > 0`), `loss_days`(`pnl < 0`), `flat_days`(`pnl = 0`), `best{date, pnl}`, `worst{date, pnl}`(거래 0건이면 둘 다 null), `caption`: `"수익 {a}일, 손실 {b}일, 손익 없음 {c}일. 최대 수익 {±금액}원({날짜}), 최대 손실 {±금액}원({날짜})."` 수익일 또는 손실일이 없으면 해당 절을 뺀다. 거래 0건이면 `"거래가 없어 일별 손익이 없습니다."` |
| `trade_value_share` | 종목별 거래대금(매수 + 매도) 내림차순. `share_pct = value / total × 100`, `end_pct`는 누적(소수 2자리), 마지막은 100.0 고정. 색은 순서대로 `#1428A0`, `#4B5CC0`, `#7C9BFF`, `#909BD6`, `#C2C8E8`. `center = {"label": "체결 건수", "value": trade_count, "unit": "건"}`. 거래 0건이면 `segments: []`, `total: 0`, `conic_gradient: "conic-gradient(#DCE0E9 0% 100%)"` |
| `trades[].in_table`, `trade_table` | `limit = 20`(고정). **가장 최근 체결 20건**만 `in_table = true`. `total = len(trades)`, `shown = min(total, limit)`, `truncated = total > limit`(= `flags.trades_truncated`). `caption`: 잘렸으면 `"최근 {shown}건 표시 · 전체 {total}건은 result.json의 trades[]에 있습니다."`, 아니면 `"전체 {total}건"`, 0건이면 `""`. **전체 체결과 청산 거래는 항상 result.json에 남긴다** |
| `per_stock[].bar_pct`, `top_contributors.items[].bar_pct` | `|realized_pnl| / max|realized_pnl| × 100`(거래한 종목 기준). 같은 종목은 두 곳의 값이 같다 |
| `top_contributors.items[]` | `status == "traded"`인 종목을 `|realized_pnl|` 내림차순(동률은 코드 오름차순) 최대 5개. `note`는 strategy.md 11.4절 |
| `per_stock[].trade_value_share_pct` | `trade_value_share.segments[].share_pct`와 같은 값(거래 없으면 0) |
| `blocks` | `entries` = 매수 대기로 이어진 판정 수, `blocked` = 7개 차단 합, `breakout = entries + blocked`. `items`는 strategy.md 4.2절 순서 고정(`halt` "매매 중단", `max_entries` "횟수 상한", `cooldown` "쿨다운", `cutoff` "시간", `range` "변동폭", `volume` "거래량", `vwap` "VWAP"), `bar_pct = count / 최댓값 × 100`. `caption`: `"돌파 {breakout}회 중 {entries}회 매수 신호, {blocked}회 차단(변동폭 {n} · 거래량 {n} · VWAP {n} · 쿨다운 {n} · 시간 {n} · 매매 중단 {n} · 횟수 상한 {n})"` — 괄호 안은 횟수 내림차순(동률은 4.2절 순서) |
| `meta.slippage_note` | `slippage_rate == 0`이면 `"슬리피지 0 가정: 실제 시장가 주문은 호가 차이(보통 1틱, 주가의 0.07~0.17%)만큼 불리하게 체결됩니다. 단타에서는 이 차이가 왕복 비용(0.23%)만큼 커서 실제 성과는 더 나쁠 수 있습니다."` 0이 아니면 `"슬리피지 {x}%를 매수·매도 체결가에 반영했습니다."` |
| `target` | `progress_raw_pct = total_return / target × 100`, `progress_pct = clip(·, 0, 100)`, `bar_segments = [{"key":"realized","label":"실현","width_pct": progress_pct,"color":"#1428A0"}]`, `target_equity`, `gap_amount = max(target_equity − final_equity, 0)`, `gap_pct = 현재 − 목표`(%p), `caption`은 strategy.md 11.5절. 음수 진척률 문구 금지 |
| `insights`, `next_action`, `alerts` | strategy.md 11.1~11.3절 |
| `flags.only_baseline_alerts` | warn이 없고 info가 `OVERNIGHT_GAP_NOTE`·`LOW_SAMPLE`뿐이면 `true` → "특이 리스크 없음" 함께 표시 |

### 5.6 빈 경우의 표현
| 상황 | JSON | 템플릿 표시 |
|---|---|---|
| 거래 0건 | `flags.no_trades: true`, `trades: []`, `closed_trades: []`, `trade_table{total: 0, shown: 0, truncated: false, caption: ""}`, `summary`의 `win_rate_pct`·`payoff_ratio`·`avg_hold_minutes` null, `trade_value_share.segments: []`, `top_contributors.items: []`, `daily[].segments`의 `height_pct` 전부 0, `charts.daily_pnl.best`·`worst` null, `alerts`에 `NO_TRADES`, `blocks`는 그대로 채움 | 매매 내역 "거래 없음", 승률·보유 시간 "–", 도넛 회색, 차단 집계 표시 |
| 거래 없는 날 | `daily[]`에 행은 있고 `pnl: 0`, `sign: "zero"`, 체결 0, 두 조각 `height_pct: 0` | 빈 막대 |
| 매매 중단일 | `daily[].halted: true`, `summary.halt_days ≥ 1`, `alerts`에 `DAILY_LOSS_HALT` | 5.5절 |
| 거래 없는 종목 | `per_stock.status: "no_trade"`, 수치 0, `win_rate_pct`·`return_pct`·`avg_hold_minutes` null | "–" |
| 제외 종목 | `per_stock.status: "excluded"`, `meta.data_source.excluded[]`, `alerts`에 `DATA_MISSING` | 상태 라벨 |
| 제외·무데이터 없음 | `meta.data_source.excluded: []`, `empty_days: []` | 표시 없음 |
| 체결 20건 이하 | `trade_table.truncated: false`, 모든 `in_table: true` | caption "전체 n건" |

- `equity_curve`, `benchmark`, `daily`, `per_stock`, `insights`(3개), `blocks.items`(7개)는 비지 않는다. 거래일이 0일이면 result.json을 만들지 않고 종료 코드 3.
- **예시 파일이 담은 사례**: 손실 청산 거래 7건, 손실일 5일, 매매 중단일 1일(09-08), 거래 없는 날 11일, 빨간 알림 1건(`UNDERPERFORM`), 주황 알림 1건(`COST_DRAG`), 표 잘림(24건 중 20건), 빈 배열(`excluded`, `empty_days`), 목표 미달(진척 막대 0). 거래 0건·제외 종목·`DAY_SKIPPED` 등 예시에 없는 경우는 dashboard-builder가 예시를 복사해 값을 바꾼 임시 입력으로 `tests/test_render.py`에서 확인한다.

### 5.7 예시 파일이 만족하는 항등식 (계약 테스트가 실제 결과에도 검사)
1. `summary.final_equity − initial_capital = total_pnl = realized_pnl = gross_pnl − total_cost`
2. `equity_curve[-1].equity = daily[-1].e_end = summary.final_equity`, `daily[i].e_start = daily[i−1].e_end`, `daily[0].e_start = initial_capital`
3. `Σ daily[].pnl = Σ closed_trades[].pnl = Σ per_stock[].realized_pnl = realized_pnl`
4. `buy_count = sell_count = closed_count`, `trade_count = len(trades)`, `win_count + loss_count + even_count = closed_count`
5. `Σ trades[].amount = total_trade_value = Σ daily[].trade_value = trade_value_share.total`, `Σ trades[].cost = total_cost = Σ daily[].cost`
6. `Σ trades[].net_cash = total_pnl`, `sell_value − buy_value = gross_pnl`
7. `halt_days = daily[].halted가 true인 행 수`, `blocks.breakout = entries + blocked`
8. 부호 플래그와 값의 부호가 일치한다. 도넛 마지막 `end_pct = 100.0`

## 6. 캐시와 토큰

### 6.1 일봉 캐시 (v1 그대로)
`data/cache/<종목코드>_<시작>_<종료>.csv`, 지수는 `IDX<업종코드>_…`. 날짜는 요청 구간(`daily_fetch_start`, `end`)의 `YYYYMMDD`(기본 `005930_20260824_20260929.csv`). 적중 판정·무효화·`--refresh`·잘림 시 미저장·이슈 보조 파일(`.issues.json`) 규칙은 v1과 같다.

### 6.2 분봉 캐시 (v2 추가)
| 항목 | 규칙 |
|---|---|
| 위치·파일명 | `data/cache/min/<종목코드>_<YYYYMMDD>.csv` (예 `005930_20260831.csv`). 종목·일자 단위. 커밋 금지 |
| 내용 | 4.2절 컬럼(`date,time,open,high,low,close,volume`), UTF-8, 헤더 있음, `(date, time)` 오름차순 |
| 적중 판정 | 파일이 있고 필수 컬럼이 모두 있다. **0행(헤더만)도 적중**이다("그 날 무데이터" 표식) |
| 적중 시 | API 호출 0건. 전 파일 적중이면 토큰도 발급하지 않는다 |
| 저장 조건 | 하루치 페이지네이션이 정상 종료했을 때만 쓴다. `truncated`(상한 도달)이면 쓰지 않고 이번 실행에만 쓴다(`TRUNCATION_SUSPECT`) |
| 무데이터 표식 | 후보 일자인데 요청일 행이 0건이면 헤더만 있는 파일을 쓰고 `source_info.empty_days`에 남긴다. **단, 이번 실행에서 받은 분봉 행 합계가 0이면(전 종목·전 일자 빈 응답) 표식을 하나도 쓰지 않고 `KisUnsupportedError`**(DEV 미지원을 "무데이터"로 굳히지 않는다) |
| 무효화 | ① 파일 수동 삭제 ② 파일이 깨졌으면 미적중으로 보고 다시 받는다. **`--refresh`는 분봉에 적용하지 않는다** |
| 삭제 금지 | 프로그램은 분봉 CSV를 지우지 않는다. 서버 보존이 약 250거래일 롤링이라 다시 받지 못할 수 있다 |
| 이슈 보조 파일 | 일봉과 같은 규칙(`<stem>.issues.json`, `{"non_integer_price": true}`) |
| 완결성 로그 | 저장 시 첫 봉·마지막 봉 시각과 행 수를 INFO로 남긴다. 첫 봉이 09:10보다 늦거나 마지막 봉이 15:00보다 이르면 WARNING(봉 수로는 판정하지 않는다. 매매 가능 여부는 `min_bars_per_day`가 정한다) |
| 환경 | 파일명에 DEV/PROD를 넣지 않는다. 쓴 환경은 `meta.data_source.env` |
- 중간에 실패해도 이미 저장한 날짜 파일은 남는다(다음 실행에서 이어 받는다). 동시 실행은 고려하지 않는다.

### 6.3 토큰 캐시 (v1 그대로)
`data/cache/token_<env 소문자>.json`, 만료 1시간 전까지 재사용, 재발급은 1분당 1회, 발급 실패 시 61초 뒤 1회 재시도, 서버가 토큰을 거부하면 파일을 지우고 1회 재발급. 토큰 값은 로그·예외·result.json에 넣지 않는다.

## 7. 에러 처리
| 상황 | 감지 | 동작 | 종료 코드 |
|---|---|---|---|
| 설정 오류·v1 키 사용 | `load_config` | `ConfigError`(어떤 키가 왜 틀렸는지) | 1 |
| `.env` 못 찾음·키 없음 | `find_env_file`, `load_credentials` | `ConfigError`. 키 **이름**과 탐색 방법(`STOCK_SIM_ENV_FILE`)만 안내. 캐시만으로 도는 실행은 `.env`가 없어도 된다 | 1 |
| 토큰 발급 실패 | HTTP 오류, `access_token` 없음 | 61초 뒤 1회 재시도 → `KisAuthError` | 3 |
| 호출 제한 초과 | `msg_cd == "EGW00201"` 또는 HTTP 429 | `backoff_sec × 시도 번호`초 대기 후 재시도, 최대 `max_retries`회 → `KisRateLimitError` | 3 |
| 네트워크 오류·타임아웃 | `requests` 예외 | 같은 재시도 → `KisError` | 3 |
| **DEV가 분봉 미지원** | 재시도 대상이 아닌 `rt_cd != "0"`, HTTP 4xx/5xx, 또는 전 종목·전 일자 빈 `output2` | `KisUnsupportedError`. **자동으로 PROD로 바꾸지 않는다.** 아래 고정 문안 | 3 |
| 페이지 상한 도달 | `truncated` | 그 날 데이터는 쓰되 캐시하지 않음. `TRUNCATION_SUSPECT` 알림 | – |
| 종목 분봉 전체 없음 | 한 종목의 전 일자 0행 | 그 종목 제외. `DATA_MISSING`, `meta.data_source.excluded`, `per_stock.status = "excluded"` | – |
| 하루 봉 부족·무효 슬롯·강제 청산 봉 없음 | backtest | strategy.md 8절 3~5번. `DAY_SKIPPED`, `BAR_MISSING`, `EOD_FALLBACK` | – |
| 유효 종목 0개·거래일 0일 | 전 종목 제외 | `DataError` | 3 |
| 지수 일봉 없음 | 벤치마크 조회 실패·0건 | `DataError`(벤치마크 없이 대시보드를 만들지 않는다) | 3 |
| 종목 일봉 없음 | 0건 | 후보 일자를 다른 종목 일봉으로 정한다. 둘 다 없으면 `DataError`. 동일가중은 있는 종목만, 가격제한폭 판정은 건너뛴다(경고 로그) | –/3 |
| 렌더 실패 | 1.9절 | result.json 유지, 오류 로그 | 2 |

DEV 미지원 시 메시지(고정 문안, 값만 채움):
```
KIS DEV(모의투자) 도메인에서 <API 이름> 조회에 실패했습니다 (msg_cd=<코드>, msg1=<메시지>).
자동으로 PROD로 전환하지 않습니다(CLAUDE.md R3).
다음 중 하나를 사용자가 결정해야 합니다:
 1) PROD 키로 시세 조회(read-only)만 허용: config.yaml의 kis.env를 PROD로, kis.prod_approved_by_user를 true로 설정
 2) 분봉 전략 재검토: 과거 30일 1분봉을 주는 무키 대체 소스는 없습니다(docs/research/intraday-data.md 3절)
```

## 8. 로깅·마스킹·테스트

### 8.1 로깅 · 8.2 마스킹 (v1 그대로)
- `logging`만 쓴다(`print` 금지). 기본 INFO, `--verbose`면 DEBUG. 남기는 것: 환경, 기간, `.env` 경로(내용 아님), 종목·일자별 캐시 적중 여부, API 경로·tr_id·종목코드·일자·요청 시각·응답 건수·페이지 번호, 재시도 횟수, 제외 종목, 산출물 경로.
- 앱키는 `mask()`로 앞 4자리만, 앱시크릿·토큰은 일부도 남기지 않는다. 요청 헤더·토큰 요청/응답 본문은 DEBUG에서도 남기지 않는다. 예외 메시지에는 `msg_cd`, `msg1`, HTTP 상태, 경로만 넣는다.

### 8.3 테스트 (네트워크 없음, `uv run pytest`)
| 파일 | 소유 | 내용 |
|---|---|---|
| `tests/fixtures/bars5_AAA_20260921.csv` | implementer | strategy.md 10.2절 5분봉 13개(date,time,open,high,low,close,volume). `run_backtest` 직접 입력용 |
| `tests/fixtures/cache/min/<코드>_<YYYYMMDD>.csv` | implementer | **가짜 1분봉 CSV**(캐시와 같은 파일명·컬럼). 6자리 코드 2종목 × 2~3일, 결측 분·15:30 봉 포함, 하루 유효 5분봉 60개 이상. e2e용 |
| `tests/fixtures/cache/<코드>_<시작>_<종료>.csv`, `IDX0001_…csv` | implementer | 같은 구간의 가짜 일봉(종목 2 + 지수) |
| `tests/fixtures/minute_page_*.json` | implementer | 가짜 KIS 분봉 응답 페이지(문자열 값, 내림차순, 전 거래일 행 혼입). 페이지네이션 테스트용 |
| `test_strategy.py` | implementer | 리샘플(strategy.md 10.7절 케이스 8, 15:20 이후 제외, 무효 슬롯에 `k` 없음), 지표(10.2절 표 전 행), 신호 플래그(10.3절), 등호 경계(케이스 3), **봉 k+1 이후와 전일 데이터를 바꿔도 봉 k까지 플래그 불변** |
| `test_backtest.py` | implementer | 10.4~10.6절 기대값 그대로, 케이스 2·4·5·6·7, 매도 먼저·코드순 체결, 슬롯 건너뜀 시 매수 취소, 상한가 매수 취소, 9.2절 항등식 1~6(현금 ≥ 0, 장 마감 포지션 없음, look-ahead) |
| `test_metrics.py` | implementer | 10.6절 지표, 일별 집계, MDD(E0 고점), 연속 손실 정렬, 거래 0건(null 규칙) |
| `test_data.py` | implementer | `normalize_minute_rows`(문자열·내림차순·중복·**요청일 외 행 제거**·`end` 라벨 1분 보정), `next_page_hour`, `fetch_minutes_day`(가짜 클라이언트로 종료 조건 4개·상한 도달), 캐시 적중 시 클라이언트를 부르지 않음(호출하면 실패하는 가짜 객체), 0행 표식, 전부 빈 응답이면 `KisUnsupportedError`·표식 없음, 분봉 파일을 지우지 않음 |
| `test_config.py` | implementer | 기본값 병합, v1 키 거부, PROD 미승인 거부, `find_env_file`(환경변수 우선, 상위 탐색, 없음) — 임시 폴더의 가짜 `.env`만 쓴다 |
| `test_report.py` | implementer | fixture로 만든 result의 **키 구조가 `docs/result.example.json`과 같음**(재귀, 배열은 첫 원소), 5.7절 항등식, strategy.md 11.6절 기대 문자열, `in_table` 상한, `segments` 규칙, NaN 없음, 5.6절 빈 경우. **예시 파일 자체도 5.7절 항등식을 통과해야 한다** |
| `test_e2e.py` | implementer | fixture 캐시 폴더 + 임시 config로 `cli.main(["run", …, "--no-render"])` → result.json 생성, 네트워크 0회, `.env` 없이 통과 |
| `test_rules.py` | implementer | `src/` 전체에 R2 금지 경로 조각이 없음(검사 문자열은 테스트 안에서 조각을 이어 만든다), `kis_client.py` 밖에 `requests` import 없음, `KisClient` 공개 메서드가 `get_token`·`daily_prices`·`index_daily`·`minute_prices`뿐 |
| `test_render.py` | dashboard-builder | 예시 JSON 렌더 성공, `schema_version` major 2 검사, 필터, 부호와 색 일치(일별 손익 막대 포함), `in_table == false` 행 미표시, 5.6절 빈 경우, 외부 JS 없음 |
| `test_kis_smoke.py` | implementer, `@pytest.mark.network` | 8.4절 |

### 8.4 임계 경로: 분봉 smoke test (implementer의 **첫 작업**)
실행: `uv run pytest -m network -k minute` (DEV, 기본 실행에서는 제외).

| 단계 | 내용 |
|---|---|
| 1 | DEV로 `minute_prices("005930", 2026-09-29, "160000")` **1페이지만** 호출한다(호출 1건 + 토큰) |
| 2 | 통과 조건: `rt_cd == "0"`, `output2`가 1행 이상, 필드 `stck_bsop_date, stck_cntg_hour, stck_oprc, stck_hgpr, stck_lwpr, stck_prpr, cntg_vol` 존재 |
| 3 | **실패하면 멈추고 보고한다.** PROD로 바꾸지 않는다(R3). 보고 내용: HTTP 상태, `msg_cd`, `msg1`, 응답 행 수. 이후 결정은 사용자(7절 문안) |
| 4 | 통과하면 같은 날 하루치를 `fetch_minutes_day`로 받아(약 4건) 다음을 기록·보고한다: 행 수, 가장 이른·늦은 `stck_cntg_hour`, 15:20~15:30 사이 행의 시각 목록, 페이지 수, 요청일 외 일자 행 수, 응답 정렬 방향 |
| 5 | **시각 라벨 확정**: 가장 이른 시각이 `090000`이면 봉 시작 시각 → `data.minute_time_label: start`(기본값 유지). `090100`이면 봉 종료 시각 → `end`로 바꾼다. 둘 다 아니면 보고 후 결정. 설정 지점은 `config.yaml`의 이 키 하나이고, 적용 지점은 `normalize_minute_rows` 하나다. 캐시 CSV는 정규화 뒤 값이므로 **라벨을 바꾸면 그 전에 받은 분봉 파일을 수동으로 지우고 다시 받는다** |
| 6 | **일봉 대조**: 그 날 1분봉의 첫 시가·15:30 봉 종가(없으면 마지막 봉 종가)가 일봉 시가·종가와 같은지 본다. 다르면 수정주가 차이 또는 단일가 봉 위치 문제이므로 보고한다 |
| 7 | 종가 단일가 봉이 `15:30`이 아닌 시각에 있으면 보고한다(strategy.md 8절 5번 대체가가 `15:30` 봉을 전제한다. `auction_closes(at=…)` 인자로 대응) |

4~7의 결과는 implementer 완료 보고의 "미해결 질문"에 적는다. 이 문서의 가정(시작 시각 라벨, 15:30 단일가 봉, 페이지당 120건, 역방향)이 틀리면 변경 요청으로 올린다.

## 9. 실행 명령과 산출물 (v1과 같음)
작업 폴더는 `stock-sim/`이다.

| 목적 | 명령 | 산출물 |
|---|---|---|
| 분봉 smoke test(첫 작업) | `uv run pytest -m network -k minute` | – |
| 전체 실행 | `uv run --directory src python -m stock_sim run --config ../config.yaml` | `output/result.json`, `output/dashboard.html`, `data/cache/*.csv`, `data/cache/min/*.csv`, `data/cache/token_dev.json` |
| 일봉 재수집 | 위 명령 + `--refresh` | 같음(분봉은 다시 받지 않는다) |
| HTML만 다시 | `uv run --directory src python -m stock_sim render --config ../config.yaml` | `output/dashboard.html` |
| 예시 렌더(W3) | `uv run --with jinja2 python src/stock_sim/render.py --result docs/result.example.json --template templates/dashboard.html.j2 --out output/dashboard.example.html` | `output/dashboard.example.html` |
| 테스트 | `uv run pytest` | – |

- 워크트리에서 `.env`를 못 찾으면: PowerShell `$env:STOCK_SIM_ENV_FILE = "<저장소 루트>\.env"`(경로만 지정, 내용 출력 금지).
- `[tool.uv] package = false`, `pythonpath = ["src"]`, `markers = ["network: 실 API 호출"]`, `addopts = "-m 'not network'"`는 v1 그대로다.
- `output/dashboard.html`에는 실데이터 결과만 쓴다(CLAUDE.md 6.6절).

## 10. W3 파일 소유와 변경 목록 (CLAUDE.md 6.6절)

| 담당 | 파일 | 변경 |
|---|---|---|
| implementer | `config.yaml` | 3절 v2 스키마로 교체 |
| | `src/stock_sim/config.py` | 기본값·검증 교체, `find_env_file` 추가, `resolve_period` 단순화, `cost_rates` 통과 |
| | `src/stock_sim/kis_client.py` | `minute_prices` 추가, 기본 간격 0.5초. 나머지 유지 |
| | `src/stock_sim/data.py` | 분봉 함수 6개 추가, `load_all` 반환 5개로 변경, `build_calendar`·`check_data` 제거 |
| | `src/stock_sim/strategy.py` | 전면 교체(1.4절) |
| | `src/stock_sim/backtest.py` | `run_backtest` 교체. `rate_to_int`·`calc_cost`·`fill_price`·`calc_qty` 유지 |
| | `src/stock_sim/metrics.py` | `daily_table`·`weekly_trade_value` 추가, `summarize`·`per_stock` 교체, `closed_trades`·`weekly_flow` 제거, 벤치마크 3개 유지 |
| | `src/stock_sim/report.py` | 스키마 2.0 조립, 알림·문장(strategy.md 11절) 교체, 좌표 헬퍼 유지 |
| | `src/stock_sim/cli.py` | 2절 흐름, 캐시 전수 확인에 분봉 포함. `render()` 호출부 유지 |
| | `tests/`(`test_render.py` 제외), `tests/fixtures/` | 8.3절. v1 일봉 전략 테스트·fixture는 교체 |
| | `output/result.json` | 실데이터 결과 |
| dashboard-builder | `templates/dashboard.html.j2` | 5.4절 굵은 글씨 자리(도넛, KPI ④, 일별 손익 막대, 매매 내역 표) + KPI ② 보조줄, 점검 필요 카드의 차단 집계·슬리피지 고지, 종목별 상세 열 |
| | `src/stock_sim/render.py` | `schema_version` major 검사 `2`. 시그니처·필터 유지 |
| | `tests/test_render.py` | 8.3절 |
| | `output/dashboard.example.html` | 예시 렌더 결과 |

두 agent 모두 `pyproject.toml` 의존성 추가 없음. `cli.py`는 implementer만 고친다.

## 11. strategy.md와 맞춘 점, 남은 확인 사항
| # | 항목 | 이 문서의 처리 |
|---|---|---|
| 1 | 분봉 컬럼 | strategy.md 3.3절(`date`, `time` 분리)을 따랐다. research의 제안(`datetime` 한 컬럼 + `value`)은 쓰지 않는다(4.2절 7번) |
| 2 | 거래일 | 분봉 요청 대상은 종목 일봉 날짜(휴장일 제외용)이고, 백테스트 거래일은 strategy.md 3.5절대로 분봉이 있는 날이다 |
| 3 | 자산 곡선 시작점 | strategy.md 9절이 architect에게 맡긴 부분. 좌표에만 시작점(E0)을 붙이고 `equity_curve[]`에는 넣지 않는다 |
| 4 | 주차별 집계 | strategy.md 9절의 주별 보유 평가액·현금은 result.json에 담지 않는다(항상 0·전액). 주별 거래대금만 `charts.trade_value_bars`에 쓴다 |
| 5 | 슬리피지 고지 | strategy.md 11.3절에 해당 알림 코드가 없어 알림으로 만들지 않고 `meta.slippage_note`(점검 필요 카드 하단)와 `meta.disclaimers`(13절 4번)에 넣었다 |
| 6 | `BAR_MISSING` 집계 범위 | `DAY_SKIPPED`가 아닌 날의 무효 슬롯만 센다고 해석했다(쉰 날은 `DAY_SKIPPED`가 알린다). strategy.md 8절 3번에 명시가 없다 |
| 7 | `PRICE_ANOMALY` 범위 | 같은 날 안의 직전 유효 봉 대비로 해석했다(밤사이 갭은 대상이 아니다) |
| 8 | 대체 청산가 | strategy.md 8절 5번의 "15:30 1분봉"은 단일가 봉이 `15:30` 라벨로 온다는 가정이다. smoke test 7단계에서 확인한다 |
| 9 | 표시 라벨 | `reason_label`, `status_label`, `blocks.items[].label`, `charts.daily_pnl.caption`, `trade_table.caption`, `blocks.caption`은 strategy.md에 없어 이 문서가 정했다(표시 전용, 매매에 영향 없음) |
| 10 | 대시보드 세 자리 대체 | 오케스트레이터 결정을 반영했다. 사용자 최종 확인과 CLAUDE.md 8절 표 갱신이 남아 있다 |
