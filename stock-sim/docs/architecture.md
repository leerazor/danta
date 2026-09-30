# stock-sim 아키텍처 (architecture.md)

작성일 2026-09-30 · 담당: architect (Phase 2b) · 상태: reviewer 검토 대기

이 문서와 `docs/result.example.json`은 implementer와 dashboard-builder 사이의 **계약**이다.
매매 규칙·지표 정의·문장 틀은 `docs/strategy.md`가 정한다. 이 문서는 그것을 **어디에서 계산하고 어떤 모양으로 주고받는지**만 정한다. 두 문서가 어긋나면 규칙은 strategy.md, 구조·스키마는 이 문서가 우선이며, 발견 즉시 "변경 요청"으로 보고한다.

## 0. 설계 원칙
- 모듈 9개, 파일당 200줄 목표. 프레임워크 없음. 클래스는 `KisClient`와 예외 클래스뿐이다.
  - (개정 1.2) 예외 기록: `report.py`는 약 680줄로 목표를 넘는다(result.json 조립·좌표·strategy.md 10절 문장 생성이 한 파일에 있다). 지금은 기록만 하고 분할은 v2 후보로 둔다(모듈 추가는 1.7절대로 보고 후 승인).
- 네트워크는 `kis_client.py` 한 곳. `strategy`·`backtest`·`metrics`는 순수 함수(파일·네트워크·시계 접근 없음).
- 캐시 우선. 캐시가 있으면 API를 호출하지 않는다. 테스트는 fixture CSV만 쓴다.
- R2는 구조로 강제한다: `KisClient`에는 토큰 발급과 시세 조회 2종 외의 메서드·경로 상수가 없다. 주문·계좌 경로 문자열은 코드 어디에도 두지 않는다(테스트로 검사, 8.3절).
- R3도 구조로 강제한다: base URL은 `config.yaml`의 `kis.env` 하나로만 정해지고, 코드에 환경을 바꾸는 분기(fallback)가 없다.

## 1. 패키지 레이아웃과 공개 함수

```
stock-sim/
├── config.yaml
├── pyproject.toml
├── src/stock_sim/
│   ├── __init__.py
│   ├── __main__.py      # cli.main() 호출만
│   ├── config.py
│   ├── kis_client.py
│   ├── data.py
│   ├── strategy.py
│   ├── backtest.py
│   ├── metrics.py
│   ├── report.py
│   ├── render.py        # dashboard-builder 소유
│   └── cli.py
├── templates/dashboard.html.j2   # dashboard-builder 소유
├── tests/  (fixtures/ 포함)
├── data/cache/
└── output/
```

타입 표기에서 `DataFrame = pandas.DataFrame`, `Path = pathlib.Path`, `date = datetime.date`.

### 1.1 `config.py` — 설정 로드·검증, 경로 해석, 자격 증명 읽기
```python
class ConfigError(Exception): ...

def load_config(path: Path) -> dict
    # YAML(UTF-8) 로드 → 3절 기본값 병합 → 검증. 실패 시 ConfigError.
    # 상대 경로는 config 파일이 있는 폴더(stock-sim/) 기준으로 절대 경로화해 cfg["paths"]에 넣는다.
    # cfg["paths"] = {"root", "cache_dir", "result", "dashboard", "template", "env_file"}  (모두 Path)
def load_credentials(env: str, env_file: Path) -> tuple[str, str]
    # load_dotenv(env_file) 후 KIS_<env>_APP_KEY / KIS_<env>_APP_SECRET 반환. 없으면 ConfigError(키 이름만 언급).
def mask(secret: str) -> str
    # 앞 4자리 + "****". 4자 이하면 "****".
def resolve_period(cfg: dict, today: date) -> dict
    # {"fetch_start": date, "requested_start": date, "end": date}  (3.2절 규칙)
```
- `env_file` 기본값은 `<config 폴더>/../.env`(저장소 루트).
- 검증 항목: `kis.env ∈ {"DEV","PROD"}`, `kis.env == "PROD"`이면 `kis.prod_approved_by_user is True`(아니면 ConfigError, R3 안내 포함), `universe` 1개 이상·코드 6자리 문자열·중복 없음, `capital > 0`, `max_positions ≥ 1`, 비용 ≥ 0, `strategy.name`이 `strategy.STRATEGIES`에 존재, `strategy.params.top_n == max_positions`(strategy.md 0절).

### 1.2 `kis_client.py` — 유일한 네트워크 모듈. 토큰 + 시세 조회 2종
```python
class KisError(Exception): ...            # 공통 부모. 메시지에 키·토큰·헤더를 넣지 않는다
class KisAuthError(KisError): ...         # 토큰 발급 실패
class KisRateLimitError(KisError): ...    # 재시도 소진
class KisUnsupportedError(KisError): ...  # 해당 환경에서 API 미지원·빈 응답

class KisClient:
    def __init__(self, env: str, app_key: str, app_secret: str, cache_dir: Path,
                 min_interval_sec: float = 1.0, max_retries: int = 3,
                 backoff_sec: float = 2.0, timeout_sec: float = 10.0) -> None
    def get_token(self) -> str
    def daily_prices(self, code: str, start: date, end: date) -> list[dict]
        # 국내주식 기간별시세 1회 호출. output2 원본 행(문자열 dict) 그대로 반환.
    def index_daily(self, index_code: str, start: date, end: date) -> list[dict]
        # 업종 기간별시세 1회 호출. output2 원본 행 그대로 반환.
    call_count: int   # 실제 HTTP GET 횟수(토큰 제외). meta.data_source.api_calls 용
```
- 모듈 상수: `BASE_URLS = {"PROD": "https://openapi.koreainvestment.com:9443", "DEV": "https://openapivts.koreainvestment.com:29443"}`, `TOKEN_PATH = "/oauth2/tokenP"`, 시세 경로 2개(`.../quotations/inquire-daily-itemchartprice`, `.../quotations/inquire-daily-indexchartprice`), tr_id `FHKST03010100` / `FHKUP03500100`.
- 요청 파라미터: 종목 `FID_COND_MRKT_DIV_CODE="J"`, `FID_PERIOD_DIV_CODE="D"`, **`FID_ORG_ADJ_PRC="0"`(수정주가)**. 지수 `FID_COND_MRKT_DIV_CODE="U"`, `FID_INPUT_ISCD="0001"`. 날짜는 `YYYYMMDD`. 헤더는 kis-api.md 3절(`custtype="P"`, `tr_cont=""`).
- 클라이언트는 **정규화하지 않는다**(문자열 그대로 반환). 구간 분할·병합·형 변환은 `data.py`가 한다. `tr_cont` 연속조회는 구현하지 않는다(구간 분할로 대신한다).
- 모든 GET 직전에 직전 호출로부터 `min_interval_sec`가 지나도록 `time.sleep`한다.

### 1.3 `data.py` — 캐시 I/O, 응답 정규화, 구간 분할, 데이터 검사
```python
def cache_path(cache_dir: Path, code: str, start: date, end: date) -> Path
def split_ranges(start: date, end: date, max_days: int) -> list[tuple[date, date]]      # 순수
def normalize_stock_rows(rows: list[dict]) -> DataFrame                                  # 순수, 4.1절 규격
def normalize_index_rows(rows: list[dict]) -> DataFrame                                  # 순수, 4.1절 규격
def load_daily(code: str, start: date, end: date, cache_dir: Path,
               client: KisClient | None, refresh: bool = False) -> DataFrame
def load_index(index_code: str, start: date, end: date, cache_dir: Path,
               client: KisClient | None, refresh: bool = False) -> DataFrame
def build_calendar(prices: dict[str, DataFrame]) -> list[date]                           # 순수. 종목 날짜 합집합, 오름차순
def check_data(prices: dict[str, DataFrame], calendar: list[date]) -> list[dict]         # 순수. 4.4절 data_issues
def load_all(cfg: dict, period: dict, client: KisClient | None, refresh: bool = False
             ) -> tuple[dict[str, DataFrame], DataFrame, list[dict], dict]
    # (prices{code: df}, benchmark_df, data_issues, source_info{"api_calls","cache_hits"})
def issues_path(path: Path) -> Path                                                      # (개정 1.2) 6.1절 이슈 보조 파일 경로
```
- `client=None`인데 캐시가 없으면 `FileNotFoundError`(테스트·오프라인 실행용).
- 구간 분할: 종목은 `max_days=130`(달력일, 약 90거래일 < 100건), 지수는 `max_days=60`(약 42거래일 < 50건 추정). 조각마다 1회 호출 → 합침 → 날짜 기준 중복 제거 → 오름차순. 기본 구간(05-31~09-29, 122일)은 종목 1회, 지수 3회 = 총 13회 호출.
- 잘림 의심 검사: 한 조각의 응답 건수가 종목 100건 또는 지수 50건 이상이면 경고 로그 + `data_issues`에 `TRUNCATION_SUSPECT`.
  - (개정 1.2) 잘림 의심 데이터는 이번 실행에서는 쓰되 캐시에 저장하지 않는다. 캐시 적중 시 `NON_INTEGER_PRICE`를 복원하는 보조 파일 규칙과 함께 6.1절에 적었다.

### 1.4 `strategy.py` — 신호(목표 종목) 계산. 순수 함수
```python
STRATEGIES: dict[str, dict]   # {"momentum_topn": {"schedule": fn, "targets": fn, "min_warmup": fn}}

def rebalance_schedule(calendar: list[date], start: date, end: date, params: dict
                       ) -> list[tuple[date, date]]
    # [(signal_date, fill_date), ...]. fill_date는 [start, end] 안. signal_date는 그 직전 거래일(워밍업 구간 가능).
def signals(prices: dict[str, DataFrame], calendar: list[date],
            schedule: list[tuple[date, date]], params: dict) -> DataFrame
    # 목표 종목 표. 컬럼: signal_date, fill_date, code, rank(1=최우선), score(float)
    # signal_date까지의 데이터만 사용(R5). 목표가 0개인 신호일은 행이 없다(→ backtest는 schedule로 판단해 전량 매도).
def min_warmup_days(name: str, params: dict) -> int
    # 백테스트 시작 전 필요한 거래일 수. momentum_topn: lookback_days + 10
```
- `signals()`의 반환은 "그 신호일에 보유하고 싶은 종목 집합(순위 포함)"이다. 이 표현은 후보 B(상위 N 주간 교체)를 그대로 담고, 후보 A(SMA 크로스)도 "매 거래일을 schedule로 두고, 크로스 이후 롱 상태인 종목을 목표로" 표현할 수 있다. MVP는 `momentum_topn`만 등록한다. A는 strategy.md 부록 A가 본문으로 승격된 뒤에 추가한다.
- `cli`는 `STRATEGIES[cfg["strategy"]["name"]]`로 함수를 고른다. 없는 이름은 `ConfigError`.

### 1.5 `backtest.py` — 체결 시뮬레이션. 순수 함수
```python
def run_backtest(prices: dict[str, DataFrame], calendar: list[date],
                 schedule: list[tuple[date, date]], targets: DataFrame,
                 start: date, end: date, capital: int, max_positions: int,
                 costs: dict) -> dict
    # costs = {"buy_rate": float, "sell_rate": float, "slippage_rate": float}  (비율, % 아님)
    # 반환 {"trades": DataFrame(4.2절), "snapshots": DataFrame(4.3절),
    #       "positions": DataFrame(4.2절 포지션), "events": list[dict](4.4절)}
```
- 체결 순서, 사이징(`E_ref`, `alloc`), 반올림(half-up, 정수 연산), 거래 불가 판정은 strategy.md 3~5절·8절 그대로 구현한다. 이 문서는 입출력 모양만 정한다.

### 1.6 `metrics.py` — 지표 계산. 순수 함수
```python
def benchmark_curve(benchmark: DataFrame, days: list[date], capital: int) -> tuple[DataFrame, dict]
    # (date, close, value, ret) + {"base_price", "base_kind": "d1_open" | "prev_close"}
def equal_weight_return(prices: dict[str, DataFrame], days: list[date]) -> float | None
def equal_weight_count(prices: dict[str, DataFrame], days: list[date]) -> int
    # (개정 1.2) 동일가중 계산에 들어간 종목 수(d1에 유효 봉이 있고 dn 이하 유효 종가가 있는 종목). strategy.md 10.1절 ①의 n
def summarize(trades: DataFrame, snapshots: DataFrame, positions: DataFrame,
              bench: DataFrame, capital: int) -> dict          # 5.3절 summary의 원값(비율은 소수)
def closed_trades(trades: DataFrame) -> DataFrame              # 매수~매도 한 쌍 단위
def per_stock(trades: DataFrame, positions: DataFrame, universe: list[dict], capital: int) -> list[dict]
def weekly_flow(trades: DataFrame, snapshots: DataFrame) -> list[dict]   # ISO 주 단위
```
- metrics의 비율은 **반올림하지 않은 소수**(0.0186)다(strategy.md 4.2절). `%` 단위 변환과 자리수 맞춤은 `report.py`만 한다.
- (개정 1.2) `equal_weight_return`이 None이 아니면 `equal_weight_count ≥ 1`이고, 두 함수는 같은 종목 집합을 쓴다. `cli`가 두 값을 `bench_info`에 넣어 `report.build_result`로 넘긴다(1.7절 표).

### 1.7 `report.py` — result.json 조립(좌표·비율·문장 포함)과 저장
```python
def sign_of(x: float | int | None) -> str                      # "pos" | "neg" | "zero" (None은 "zero")
def polyline_points(values: list[float], width: float, height: float,
                    y_min: float, y_max: float) -> str         # "x,y x,y ..." 소수 1자리
def nice_axis(v_min: float, v_max: float) -> tuple[float, float, list[float]]   # 5.5절 규칙
def build_alerts(summary: dict, stocks: list[dict], positions: list[dict],
                 issues: list[dict], events: list[dict], period: dict) -> list[dict]
def build_insights(summary: dict, stocks: list[dict], closed: DataFrame, alerts: list[dict],
                   positions: list[dict] | None = None, equal_weight: float | None = None,
                   equal_weight_count: int | None = None
                   ) -> tuple[list[dict], dict]                # (insights 3개, next_action)  (개정 1.2)
def build_result(cfg: dict, period: dict, bt: dict, bench: DataFrame, bench_info: dict,
                 issues: list[dict], source_info: dict, generated_at: str) -> dict   # 순수
def write_result(result: dict, path: Path) -> Path
    # json.dump(ensure_ascii=False, indent=2, allow_nan=False), UTF-8. 폴더 없으면 생성.
```
- 200줄을 넘기면 좌표 계산 함수(`polyline_points`, `nice_axis`)를 `report.py` 안에서만 쓰는 비공개 헬퍼로 정리한다. 모듈을 새로 늘리려면 보고 후 승인을 받는다.
- (개정 1.2) `build_insights`의 뒤 세 인자는 **기본값 있는 키워드 인자**다(기존 위치 인자 4개 호출과 호환). `positions`는 result의 `positions[]` 모양(`code, name, unrealized_pnl` 사용, strategy.md 10.1절 ② 종목 절·10.2절 3번), `equal_weight`는 동일가중 수익률 원값(소수, None이면 ① 뒤 문장 생략), `equal_weight_count`는 ①의 `n`. `equal_weight`가 있는데 `equal_weight_count`가 None이면 `stocks` 중 `status != "excluded"`인 종목 수로 대신한다. `closed`는 시그니처 호환용으로 남아 있고 10절 문장에는 쓰지 않는다. `build_result`는 `positions=positions, equal_weight=bench_info["equal_weight_return"], equal_weight_count=bench_info["equal_weight_count"]`로 부른다.

(개정 1.2, 리뷰 phase3-1 Low 6) **1.1~1.9절 시그니처 밖의 공개 이름과 cli가 넘기는 값.** 아래 이름은 구현에 있고 다른 모듈·테스트가 쓸 수 있다. 계약상 이름·반환 모양을 바꾸려면 보고한다.

| 모듈 | 이름 | 시그니처·값 | 용도 |
|---|---|---|---|
| `config` | `cost_rates` | `(cfg: dict) -> dict` → `{"buy_rate", "sell_rate", "slippage_rate"}` | 3.1절 % → 비율 변환. `cli`가 `run_backtest(costs=...)`에 넘긴다 |
| `data` | `DataError` | `class DataError(Exception)` | 유효 종목 0개·지수 없음·워밍업 부족·거래일 0일. 종료 코드 3 |
| `data` | `make_issue` | `(code, stock=None, day=None, value=None, excluded=False, side=None, extra=None) -> dict` | 4.4절 공통 모양 생성 |
| `data` | `read_cache` | `(path: Path, integer_prices: bool) -> DataFrame \| None` | 6.1절 적중 판정. 없거나 깨졌거나 비었으면 None. `cli`의 "전 파일 캐시 여부" 확인에도 쓴다 |
| `data` | `index_cache_code` | `(index_code: str) -> str` → `"IDX" + 업종코드` | 지수 캐시 파일명·지수 `TRUNCATION_SUSPECT`의 `stock` 값 |
| `data` | `issues_path` | `(path: Path) -> Path` → `<캐시명 stem>.issues.json` | 6.1절 이슈 보조 파일 |
| `kis_client` | `unsupported_message` | `(env, api_name, msg_cd, msg1, http_status=None) -> str` | 7절 DEV 미지원 고정 문안 |
| `backtest` | `rate_to_int` | `(rate: float) -> int` | 비율 → 1억분율 정수(`SCALE = 10**8`, Decimal half-up) |
| `backtest` | `calc_cost` | `(amount: int, rate: float) -> int` | 비용 = 거래대금 × 율, 원 단위 half-up |
| `backtest` | `fill_price` | `(open_price: int, slippage_rate: float, side: str) -> int` | 체결가 = 시가 × (1 ± 슬리피지), half-up |
| `backtest` | `calc_qty` | `(alloc: int, price: int, buy_rate: float) -> int` | 비용 포함 금액이 `alloc`을 넘지 않는 최대 정수 수량 |
| `strategy` | `to_bars` | `(df: DataFrame) -> dict[date, tuple[int, int, int]]` | `{날짜: (시가, 종가, 거래량)}`. metrics 동일가중도 쓴다 |
| `strategy` | `is_valid_bar` | `(bar: tuple \| None) -> bool` | 유효 봉: 행 있음, 시가·종가·거래량 > 0 |
| `strategy` | `STRATEGIES[name]["label"]` | `(params: dict) -> str` | `meta.strategy.label` 문자열(예 "20일 수익률 상위 5종목 · 주간 리밸런싱") |
| `metrics` | `equal_weight_count` | 1.6절 | strategy.md 10.1절 ①의 n |

| cli → `build_result` 인자 | 키 | 출처 |
|---|---|---|
| `period` | `fetch_start`, `requested_start`, `end` | `config.resolve_period` |
| `period` | `rebalances` | `len(schedule)`. cli가 추가한다(없으면 report가 주 수로 대신) |
| `bench` | `date, close, value, ret` | `metrics.benchmark_curve`의 반환 DataFrame(원 지수 DataFrame이 아니다) |
| `bench_info` | `base_price`, `base_kind` | `metrics.benchmark_curve`의 반환 dict |
| `bench_info` | `equal_weight_return` | `metrics.equal_weight_return(prices, days)` (None 가능) |
| `bench_info` | `equal_weight_count` | `metrics.equal_weight_count(prices, days)` |
| `source_info` | `api_calls`, `cache_hits` | `data.load_all` |
| `generated_at` | ISO 8601 초 단위, `+09:00` | `datetime.now(KST).isoformat(timespec="seconds")` |

### 1.8 `render.py` — result.json → HTML (dashboard-builder 소유)
```python
def render(result_path: Path, template_path: Path, out_path: Path) -> Path
```
| 항목 | 계약 |
|---|---|
| 인자 | 세 개 모두 `pathlib.Path`(절대·상대 모두 허용). 키워드로도 호출 가능해야 한다 |
| 동작 | `result_path`를 UTF-8 JSON으로 읽고, `template_path`의 Jinja2 템플릿에 **최상위 키를 그대로 컨텍스트로** 넘겨(`template.render(**result)`) `out_path`에 UTF-8로 쓴다. `out_path`의 부모 폴더가 없으면 만든다 |
| 반환 | 쓴 파일의 경로(`out_path`) |
| 예외 | 파일 없음 → `FileNotFoundError`. `schema_version`의 major가 `1`이 아니면 `ValueError`. 템플릿 오류는 Jinja2 예외를 그대로 올린다 |
| 금지 | 네트워크, 수치 계산(합계·비율·좌표), result.json 수정, `print` |
| 의존 | 표준 라이브러리 + `jinja2`만. **`stock_sim`의 다른 모듈을 import하지 않는다**(병렬 개발 중 단독 실행 가능해야 한다) |
| Jinja2 | `Environment(autoescape=True, undefined=StrictUndefined)`. 필터는 5.2절 표의 6개(개정 1.1: `sign_color_dark` 추가) |

- 단독 실행: `render.py`에 `if __name__ == "__main__":` 블록을 두고 `--result --template --out` 인자를 받는다. W3에서 dashboard-builder는 다음으로 검증한다(패키지 설치·`cli.py` 불필요).
  `uv run --with jinja2 python src/stock_sim/render.py --result docs/result.example.json --template templates/dashboard.html.j2 --out output/dashboard.example.html`

### 1.9 `cli.py` / `__main__.py` — 진입점 (implementer 소유)
```python
def main(argv: list[str] | None = None) -> int     # 종료 코드 반환
```
| 명령 | 동작 |
|---|---|
| `run --config PATH [--refresh] [--no-render]` | 2절 흐름 전체. `--refresh`는 일봉 캐시 무시(토큰 캐시는 유지). `--no-render`는 result.json까지만 |
| `render --config PATH [--result PATH] [--out PATH]` | 기존 result.json으로 HTML만 다시 만든다 |

`cli.py`가 `render`를 부르는 방식(고정):
```python
from stock_sim.render import render      # run/render 명령 함수 안에서 지연 import
render(result_path=cfg["paths"]["result"],
       template_path=cfg["paths"]["template"],
       out_path=cfg["paths"]["dashboard"])
```
- 지연 import인 이유: `render.py`나 템플릿이 아직 없어도 implementer의 나머지 코드와 테스트가 돌아야 한다. `ImportError`·`FileNotFoundError`·Jinja2 예외가 나면 result.json은 이미 저장된 상태로 두고, 오류를 로그로 남긴 뒤 종료 코드 2를 반환한다.
- 종료 코드: 0 성공 / 1 설정 오류(`ConfigError`) / 2 렌더 실패 / 3 KIS·데이터 오류(`KisError`, 워밍업 부족, 유효 종목 0개).

## 2. 데이터 흐름

```
config.yaml ──load_config──▶ cfg ──resolve_period(today)──▶ period{fetch_start, requested_start, end}
                                   │
.env ──load_credentials──▶ KisClient(env)          (캐시가 전부 있으면 HTTP 0회, 토큰도 발급하지 않음)
                                   │
data.load_all ── 캐시 CSV 있음? ─ 예 → CSV 읽기
       │                        └ 아니오 → split_ranges → client.daily_prices / index_daily
       │                                   → normalize_* → 병합·중복 제거·정렬 → CSV 저장
       ▼
prices{code: DataFrame}, benchmark DataFrame, data_issues
       │  build_calendar(prices) → calendar (워밍업 포함)
       ▼
strategy.rebalance_schedule → schedule[(signal_date, fill_date)]
strategy.signals            → targets (signal_date, fill_date, code, rank, score)
       ▼
backtest.run_backtest       → trades, snapshots, positions, events
       ▼
metrics.*                   → summary 원값, per_stock, weekly_flow, benchmark 곡선
       ▼
report.build_result         → result(dict: % 변환, 좌표, 부호 플래그, 알림·인사이트 문장)
report.write_result         → stock-sim/output/result.json
       ▼
render.render               → templates/dashboard.html.j2 → stock-sim/output/dashboard.html
```
- 토큰은 **첫 HTTP 호출이 필요해질 때** 발급한다(`get_token`은 `_get` 안에서 부른다). 캐시만으로 도는 실행은 `.env`에 키가 없어도 끝까지 가야 한다: `cli`는 캐시가 모두 있는지 먼저 보고, 있으면 `client=None`으로 `load_all`을 부른다.

## 3. `config.yaml` 스키마와 기본값

```yaml
kis:
  env: DEV                      # DEV | PROD. base URL을 정하는 유일한 값
  prod_approved_by_user: false  # env가 PROD일 때 true가 아니면 실행 거부(R3). 사용자만 바꾼다
  min_interval_sec: 1.0         # 호출 간 최소 간격
  max_retries: 3                # EGW00201 재시도 횟수
  backoff_sec: 2.0              # 재시도 대기(시도마다 ×1, ×2, ×3)
  timeout_sec: 10
universe:
  - {code: "005930", name: "삼성전자"}
  - {code: "000660", name: "SK하이닉스"}
  - {code: "373220", name: "LG에너지솔루션"}
  - {code: "207940", name: "삼성바이오로직스"}
  - {code: "005380", name: "현대차"}
  - {code: "000270", name: "기아"}
  - {code: "068270", name: "셀트리온"}
  - {code: "035420", name: "NAVER"}
  - {code: "105560", name: "KB금융"}
  - {code: "005490", name: "POSCO홀딩스"}
benchmark: {code: "0001", name: "KOSPI"}
backtest:
  end: auto                     # auto 또는 "YYYY-MM-DD"
  months: 1
  warmup_days: 90               # 달력일. fetch_start = requested_start - warmup_days
strategy:
  name: momentum_topn
  params: {lookback_days: 20, top_n: 5, rebalance: weekly}
capital: 100000000              # 원
max_positions: 5                # strategy.params.top_n과 같아야 한다
costs:                          # 단위 %. 0.015는 0.015%
  buy_fee_pct: 0.015
  sell_fee_pct: 0.015
  sell_tax_pct: 0.20
  slippage_pct: 0.0
target_return: 2.0              # 단위 %. 백테스트 기간 전체에 대한 목표(기본 1개월 +2%)
output:
  result: output/result.json
  dashboard: output/dashboard.html
  template: templates/dashboard.html.j2
  cache_dir: data/cache
```
### 3.1 규칙
- 종목 코드는 **따옴표 문자열**(앞자리 0 보존). 상대 경로는 config 파일 폴더 기준.
- 비용 변환: `buy_rate = buy_fee_pct / 100`, `sell_rate = (sell_fee_pct + sell_tax_pct) / 100`, `slippage_rate = slippage_pct / 100`. 기본값으로 0.00015 / 0.00215 / 0. strategy.md 4.2절의 정수 연산은 1억분율 정수(`backtest.rate_to_int`, `SCALE = 10**8`: 15,000 / 215,000)로 바꿔 쓴다. 결과는 10만분율 식과 같다. (개정 1.2)
- 누락된 키는 위 기본값으로 채운다. 알 수 없는 최상위 키는 경고 로그만 남긴다.
- 알림 임계값(MDD −5% 등)은 strategy.md 10.3절의 고정 표시 규칙이라 config에 두지 않는다.

### 3.2 기간 해석 (`resolve_period`)
| 값 | 규칙 | 기본 실행(오늘 2026-09-30) |
|---|---|---|
| `end` | `auto`면 `today − 1일`(달력일). 당일 미완성 봉을 피한다. 날짜 문자열이면 그 날 | 2026-09-29 |
| `requested_start` | `end − months`개월(달력 월, `pandas.DateOffset`) | 2026-08-29 |
| `fetch_start` | `requested_start − warmup_days`일 | 2026-05-31 |
| 실제 첫 거래일 d1 | 달력에서 `requested_start` 이상인 첫 날짜 | 2026-08-31 |
| 실제 마지막 거래일 dn | 달력에서 `end` 이하인 마지막 날짜 | 2026-09-29 |

- "마지막 완료 거래일"은 휴장일 API 없이 **받은 데이터의 마지막 날짜**로 정한다(chk-holiday 미사용). `end`가 휴장일이어도 그대로 요청하고 dn만 앞당겨진다.
- PLAN.md의 수집 구간 "2026-06-01~"과는 05-31이 일요일이라 같은 데이터다.

## 4. 내부 데이터 모델

### 4.1 일봉 DataFrame (종목·지수 공통, 캐시 CSV와 같은 컬럼)
| 컬럼 | dtype | 종목 (KIS 필드) | 지수 (KIS 필드) |
|---|---|---|---|
| `date` | `datetime64[ns]` | `stck_bsop_date` | `stck_bsop_date` |
| `open` | 종목 int64 / 지수 float64 | `stck_oprc` | `bstp_nmix_oprc` |
| `high` | 같음 | `stck_hgpr` | `bstp_nmix_hgpr` |
| `low` | 같음 | `stck_lwpr` | `bstp_nmix_lwpr` |
| `close` | 같음 | `stck_clpr` | `bstp_nmix_prpr` |
| `volume` | int64 | `acml_vol` | `acml_vol` |
| `value` | int64 (거래대금, 원) | `acml_tr_pbmn` | `acml_tr_pbmn` |

정규화 규칙(`normalize_*`):
1. 응답 값은 전부 문자열로 본다 → `pd.to_numeric(errors="coerce")`.
2. `stck_bsop_date`가 빈 행, 날짜 파싱 실패 행은 버린다.
3. 응답 순서를 믿지 않는다(최신일 우선 추정) → `date` **오름차순 정렬**, 같은 날짜는 마지막 것만 남긴다.
4. 종목 가격이 정수가 아니면 half-up으로 원 단위 반올림하고 `data_issues`에 `NON_INTEGER_PRICE`를 남긴다(strategy.md 2.3절).
5. 요청 구간 `[start, end]` 밖의 행은 버린다. 인덱스는 0부터의 RangeIndex, `date`는 컬럼으로 둔다.
6. 지수 응답에서 일자별 배열이 `output2`가 아닐 수 있다(kis-api.md 5절 미확정). `KisClient.index_daily`는 `output2`를 우선 보고, 없거나 `stck_bsop_date` 키가 없으면 `output1`이 리스트인지 확인한다. 둘 다 아니면 `KisUnsupportedError`.
7. 지수에 `open`이 없거나 0이면 그대로 두고(NaN/0), 벤치마크 기준가 대체는 metrics가 한다(strategy.md 6절).

### 4.2 거래 레코드(`trades`)와 포지션(`positions`)
| trades 컬럼 | 타입 | 뜻 |
|---|---|---|
| `id` | int | 1부터. 날짜 → (매도 먼저, 종목코드순) → (매수, 순위순) |
| `date` | date | 체결일(T+1) |
| `signal_date` | date | 신호일(T) |
| `code` | str | 종목코드 |
| `side` | str | `BUY` / `SELL` |
| `qty` | int | 체결 수량(양의 정수) |
| `price` | int | 체결가(슬리피지 반영 후, 원) |
| `amount` | int | `qty × price` |
| `cost` | int | 매수: 수수료. 매도: 수수료+세금(합친 율로 한 번 반올림) |
| `net_cash` | int | 현금 증감. 매수 `−(amount+cost)`, 매도 `+(amount−cost)` |
| `realized_pnl` | int / None | 매도만. `(amount−cost) − (매수 amount + 매수 cost)` |
| `realized_ret` | float / None | 매도만. `realized_pnl / (매수 amount + 매수 cost)` |
| `holding_days` | int / None | 매도만. 매수 체결일~매도 체결일의 거래일 수(달력 인덱스 차) |
| `reason` | str | `"목표 편입(순위 n)"` / `"목표 이탈"` |

| positions 컬럼(기간 말 미청산) | 타입 |
|---|---|
| `code`, `qty`, `entry_date`, `entry_price`, `buy_amount`, `buy_cost`, `last_price`, `market_value`, `unrealized_pnl`, `unrealized_ret`, `holding_days` | str, int, date, int, int, int, int, int, int, float, int |

### 4.3 일별 포트폴리오 스냅샷(`snapshots`, 백테스트 거래일마다 1행)
| 컬럼 | 타입 | 뜻 |
|---|---|---|
| `date` | date | 거래일 |
| `cash` | int | 종가 시점 현금(≥ 0) |
| `holdings_value` | int | Σ 수량 × 종가(결측은 직전 유효 종가) |
| `equity` | int | `cash + holdings_value` |
| `position_count` | int | 보유 종목 수 |
| `realized_pnl_cum` | int | 그 날까지의 누적 실현 손익 |

### 4.4 데이터 이슈·백테스트 이벤트 (알림의 재료)
`data_issues`와 `events`는 같은 모양의 dict 리스트다: `{"code": 알림코드, "stock": 종목코드 | None, "date": date | None, "value": 수치 | None, "excluded": bool, "side": "BUY" | "SELL" | None, "extra": dict}`.
- `side`는 `UNTRADABLE_SKIP`·`QTY_ZERO_SKIP`에서 매수·매도 구분에 쓴다(그 외는 None). `QTY_ZERO_SKIP`은 `value` = 체결가, `extra = {"alloc": 배분금액}`이다(그 외는 `extra = {}`). (리뷰 phase2-1 Med 1 반영)
- `data.check_data`가 만드는 것: `DATA_MISSING`(조회 0건 → `excluded=True`, 또는 달력 대비 결측일 수), `PRICE_ANOMALY`(전일 종가 대비 ±30% 초과), `NON_INTEGER_PRICE`, `TRUNCATION_SUSPECT`.
- `backtest`가 만드는 것: `UNTRADABLE_SKIP`, `QTY_ZERO_SKIP`. `metrics.benchmark_curve`가 만드는 것: `BENCHMARK_BASE_FALLBACK`.
- 알림 문장·등급·순서는 strategy.md 10.3절이 정하고, `report.build_alerts`가 이 리스트에서 문장을 만든다.

## 5. `result.json` 스키마

### 5.1 공통 규칙
| 항목 | 규칙 |
|---|---|
| 인코딩 | UTF-8, `ensure_ascii=False`, 들여쓰기 2. `NaN`·`Infinity` 금지(값이 없으면 `null`) |
| 금액·수량 | 정수(원, 주). 지수 값만 실수 |
| 비율 | **퍼센트 단위 숫자**, 키 이름이 `_pct`로 끝난다(1.8588은 1.8588%). 데이터 값은 소수 4자리 반올림. 템플릿이 필터로 소수 2자리 표시 |
| 기하 값 | 좌표는 소수 1자리(반올림 방식은 구현 자유이며, 계약 테스트는 좌표 값 자체를 예시와 비교하지 않고 형식·범위만 본다). 폭·높이·도넛 경계 `%`(`width_pct`, `height_pct`, `bar_pct`, `start_pct`, `end_pct`, `x_pct`, `progress_pct`)는 소수 2자리. 템플릿은 그대로 `style`에 넣는다 |
| 부호 | `sign` 또는 `<이름>_sign` = `"pos"`(>0) / `"neg"`(<0) / `"zero"`(0 또는 null). 템플릿은 `sign_color` 필터로 색을 고른다: pos `#1428A0`, neg `#B0472F`, zero `#6E7688`. **어두운 배경(헤더 KPI, 분석 요약 다크 패널) 위의 값은 `sign_color_dark` 필터를 쓴다: pos `#7C9BFF`, neg `#E29A80`, zero `#FFFFFF`**(개정 1.1, CLAUDE.md 8절 색 토큰). 부호 값(`*_sign`)은 배경과 무관하게 하나이고, 배경에 따라 필터만 달리 고른다 |
| 색 | 도넛·스택·막대 조각과 알림 점은 JSON의 `color`(hex)를 그대로 쓴다. 손익에 따라 바뀌는 글자·막대 색은 `sign`으로 고른다 |
| 날짜 | `"YYYY-MM-DD"`. `generated_at`만 ISO 8601(`+09:00`) |
| 문장 | `caption`, `note`, `title`, `detail`, `text`, `disclaimers`, `reason`, `*_label`은 report.py가 완성한 한국어 문자열(숫자 포맷 포함). 템플릿은 그대로 출력한다 |
| 숫자 포맷 | **원시 숫자로 둔다.** 표시 문자열(`"1,234원"`)을 따로 담지 않는다. 포맷은 5.2절 필터가 한다 |
| 배열 | 비어도 키는 항상 있다(`[]`). 빈 경우의 표시는 5.6절 |
| 금지 | 키, 토큰, 계좌번호, 실잔고, 개인정보(R4) |

### 5.2 템플릿 필터 (render.py가 등록, 계산이 아니라 표시 변환)
| 필터 | 입력 → 출력 | null 입력 |
|---|---|---|
| `won` | `101858842` → `101,858,842원` | `–` |
| `signed_won` | `-516743` → `-516,743원`, `906237` → `+906,237원`, `0` → `0원` | `–` |
| `pct` | `33.3333` → `33.33%` | `–` |
| `signed_pct` | `1.8588` → `+1.86%`, `-2.1491` → `-2.15%`, `0` → `0.00%` | `–` |
| `sign_color` | `"pos"` → `#1428A0`, `"neg"` → `#B0472F`, `"zero"` → `#6E7688` | `#6E7688` |
| `sign_color_dark` (개정 1.1) | `"pos"` → `#7C9BFF`, `"neg"` → `#E29A80`, `"zero"` → `#FFFFFF` | `#FFFFFF` |

초과수익은 `signed_pct` 결과 뒤에 템플릿이 `p`를 붙여 `+1.01%p`로 쓴다. 천 단위 콤마만 필요한 수(거래량, 횟수)는 `"{:,}".format` 수준의 표시 변환을 템플릿에서 해도 된다.

- (개정 1.1) 어두운 배경용 색은 기존 `sign_color`에 인자를 주지 않고 **별도 필터 `sign_color_dark`**로 둔다. `sign_color`의 동작은 바뀌지 않는다. 쓰는 곳: 헤더 KPI의 부호 있는 값(5.4절 2번)과, 다크 패널 안에 부호 색을 입힐 값이 있을 때. 흰 배경의 카드·표에서는 쓰지 않는다.

### 5.3 최상위 키와 필드
예시 값은 `docs/result.example.json`과 같다. 그 파일이 **키 구조의 기준**이다(8.3절 계약 테스트).

| 키 | 타입 | 내용 |
|---|---|---|
| `schema_version` | str | `"1.1"` (개정 1.1: 필드 추가만 했으므로 major는 `1` 그대로다. 1.0 대비 추가분은 이 절과 5.5절에 "개정 1.1"로 표시) |
| `meta` | object | 아래 |
| `flags` | object | `no_trades`, `no_closed_trades`, `no_positions`, `only_low_sample_alert` (모두 bool) |
| `summary` | object | KPI. 아래 |
| `equity_curve` | array | 거래일별. `date, equity, cash, holdings_value, return_pct, drawdown_pct, position_count, realized_pnl_cum` |
| `benchmark` | array | 거래일별(equity_curve와 같은 날짜·길이). `date, close, value, return_pct` |
| `charts` | object | 미리 계산한 좌표. 5.5절 |
| `positions` | array | 기간 말 보유. 비중 내림차순. `code, name, qty, avg_price, cost_basis, last_price, market_value, weight_pct, unrealized_pnl, unrealized_pnl_pct, sign, entry_date, holding_days` |
| `allocation` | object | 도넛. `as_of, total, center{label, value_pct}, conic_gradient, segments[]{kind, code, label, value, weight_pct, start_pct, end_pct, color}` |
| `trades` | array | 체결 순. `id, date, signal_date, code, name, side, side_label, qty, price, amount, cost, net_cash, realized_pnl, realized_pnl_pct, sign, holding_days, reason` |
| `per_stock` | array | 유니버스 전 종목(제외 종목 포함). `code, name, status, status_label, trade_count, buy_count, sell_count, closed_count, win_count, win_rate_pct, realized_pnl, realized_pnl_sign, unrealized_pnl, total_pnl, return_pct, contribution_pct, sign, bar_pct, trade_value, trade_volume` (개정 1.1: `realized_pnl_sign` 추가) |
| `top_contributors` | object | `items[]{rank, code, name, pnl, sign, bar_pct}`(최대 5), `note` |
| `weekly_flow` | array | ISO 주별. `label, start, end, trading_days, buy_value, sell_value, buy_count, sell_count, holdings_value, cash, segments[4]{key, label, value, height_pct, color}` |
| `alerts` | array | `level, code, title, detail, date, color` |
| `insights` | array | 항상 3개. `no("01"~"03"), title, detail` |
| `next_action` | object | `label("다음 조치"), text` |
| `target` | object | `target_return_pct, actual_return_pct, sign, current_return_pct, current_return_sign, gap_pct, target_equity, gap_amount, achieved, progress_raw_pct, progress_pct, bar_segments[2]{key, label, width_pct, color}, caption` (개정 1.1: `current_return_pct`, `current_return_sign`, `gap_pct` 추가) |

`meta`
| 필드 | 내용 |
|---|---|
| `is_example` | 예시 파일만 `true`. 실제 결과는 `false` |
| `label`, `title` | 헤더 라벨·제목(고정 문자열) |
| `period` | `requested_start, start(d1), end(dn), trading_days, months` |
| `generated_at` | 생성 시각 |
| `env` | `"DEV"` / `"PROD"` |
| `strategy` | `name, label, params` |
| `data_source` | `provider("KIS"), env, adjusted_price(true), fetch_start, fetch_end, api_calls, cache_hits, excluded[]{code, name, reason}` |
| `universe` | `[{code, name}]` (config 순서) |
| `benchmark` | `code, name, base_price, base_kind` |
| `capital`, `max_positions` | 초기 자본, 최대 보유 종목 수 |
| `costs` | `buy_cost_pct, sell_cost_pct, slippage_pct` (% 단위, 매도는 수수료+세금 합) |
| `disclaimers` | 한계 고지 문장 배열(strategy.md 11절) |

`summary` (정의는 strategy.md 7절)
| 필드 | 뜻 |
|---|---|
| `initial_capital`, `final_equity`, `total_pnl`(+`_sign`) | 초기 자본, 기말 평가액, 그 차이 |
| `total_return_pct`(+`_sign`) | 총수익률 |
| `benchmark_return_pct`(+`_sign`) | KOSPI buy&hold 수익률(기준가 d1 시가) |
| `excess_return_pct`(+`_sign`) | 초과수익(%p) = 총수익률 − 벤치마크 |
| `equal_weight_return_pct`(+`_sign`) | 유니버스 동일가중 buy&hold(보조, null 가능) |
| `excess_vs_equal_weight_pct`, `excess_vs_equal_weight_sign` (개정 1.1) | 동일가중 대비 초과수익(%p) = 총수익률 − 유니버스 동일가중. 반올림 전 원값끼리 뺀 뒤 소수 4자리로 반올림한다. 동일가중이 null이면 값은 null, sign은 `"zero"` |
| `mdd_pct`, `mdd_sign`, `mdd_peak_date`, `mdd_trough_date` | MDD(0 이하). MDD가 0이면 두 날짜는 null. 낙폭의 고점이 초기 자본(E0, 첫 거래일 이전)이면 `mdd_peak_date`만 null이고, 템플릿은 null인 고점 날짜를 "시작"으로 표시한다. `charts.equity.caption` 등 report.py가 만드는 문장에서도 "시작"으로 쓴다 (리뷰 phase2-1 Med 2 반영). (개정 1.2) 표기 통일: `charts.equity.caption`과 템플릿의 null 고점 표시는 **"시작"**, strategy.md 10절 문장(`insights` ③ 리스크, `alerts`의 `MDD_BREACH` detail, `next_action` 5번)은 **"초기 자본"**을 쓴다. 두 표기 모두 허용하며, 위치별로 정해진 쪽만 쓴다 |
| `trade_count`, `buy_count`, `sell_count` | 체결 건수 |
| `closed_count`, `win_count`, `loss_count` | 청산 거래 수, 이익·손실 건수 |
| `win_rate_pct` | 승률. 청산 0건이면 null |
| `payoff_ratio` | 손익비(배수, 소수 4자리). 해당 없으면 null |
| `max_loss_streak` | 최대 연속 손실 |
| `realized_pnl`(+`_sign`), `unrealized_pnl`(+`_sign`) | 실현·평가 손익 합 |
| `total_cost` | 매수·매도 비용 합 |
| `holding_count`, `max_positions` | 기말 보유 종목 수, 상한 |
| `cash`, `cash_weight_pct` | 기말 현금, 비중 |
| `total_trade_value`, `buy_value`, `sell_value`, `total_trade_volume` | 거래대금(비용 제외), 거래량(주) |
| `turnover_pct` | 회전율 |

`per_stock.status`: `held`(기말 보유) / `closed`(거래했고 기말 미보유) / `no_trade` / `excluded`. 정렬: 거래한 종목을 `total_pnl` 내림차순 → `no_trade` → `excluded`(뒤 둘은 config 순서). `return_pct`는 매수가 없으면 null.

- (개정 1.1) `per_stock[].sign`은 **`total_pnl`의 부호**다(총손익 열, 막대 색). `per_stock[].realized_pnl_sign`은 **`realized_pnl`의 부호**다(실현손익 열 색). 두 부호는 다를 수 있다(실현 이익 + 더 큰 평가손실 등). 실현손익이 0이거나 매도가 없으면 `"zero"`.
- (개정 1.1) `return_sign`은 두지 않는다. `return_pct = total_pnl / Σ(매수 거래대금 + 매수 비용)`(strategy.md 7절)이고 분모가 항상 양수라 **`return_pct`의 부호는 `sign`과 항상 같다.** 수익률 열의 색도 `sign`으로 고른다(`return_pct`가 null이면 `total_pnl`도 0이라 `sign`은 `"zero"`).

`alerts.level`: `"warn"` / `"info"`(strategy.md 10.3절). `color`: `MDD_BREACH`·`LOSS_STREAK`·`UNDERPERFORM`은 `#B0472F`, 그 밖의 warn은 `#C98A2E`, info는 `#1428A0`. 정렬은 warn 먼저, 그 안에서 10.3절 표 순서. `title`은 10.3절 메시지 틀, `detail`은 보조 설명(종목코드·날짜 등, 빈 문자열 가능), `date`는 없으면 null.
- (개정 1.1, strategy.md 10.3절) **날짜는 한 알림에서 한 곳에만 쓴다.** `title`에 날짜를 넣지 않는다. 날짜가 하나면 `date`에, 구간(두 날짜)이면 `detail`에 쓰고 `date`는 null로 둔다(예: `MDD_BREACH`는 detail `"고점 2026-09-09 → 저점 2026-09-29"`, date null). `date`를 쓰는 코드는 `PRICE_ANOMALY`(해당일)·`UNTRADABLE_SKIP`·`QTY_ZERO_SKIP`(체결일)뿐이고 나머지는 null이다. 템플릿은 `detail`과 `date`를 그대로 보여 주기만 하며, 이 규칙대로 채우면 같은 날짜가 두 번 나오지 않는다.

### 5.4 대시보드 섹션 ↔ JSON 필드 (CLAUDE.md 8절과 1:1)
| # | 샘플 섹션 | 시뮬레이션 대시보드 | JSON 필드 |
|---|---|---|---|
| 1 | 헤더 라벨·제목·기준일 | 라벨 / 제목 / 백테스트 구간 | `meta.label`, `meta.title`, `meta.period.start`~`meta.period.end`, `meta.period.trading_days`, `meta.generated_at`, `meta.env`, `meta.strategy.label` |
| 2 | 헤더 KPI 4개 | ① 누적 수익률 ② 초과수익 ③ MDD ④ 거래 횟수 | ① `summary.total_return_pct`(+sign), 보조 `summary.final_equity` ② `summary.excess_return_pct`(+sign), 보조 `summary.benchmark_return_pct` ③ `summary.mdd_pct`(+sign), 보조 `mdd_peak_date`→`mdd_trough_date` ④ `summary.trade_count`, 보조 `buy_count`·`sell_count`. (개정 1.1) ①②③의 값 색은 각각 `total_return_sign`·`excess_return_sign`·`mdd_sign`에 **`sign_color_dark`** 필터를 적용한다(수익 `#7C9BFF`, 손실 `#E29A80`, zero 흰색). ④는 부호가 없어 흰색 그대로 |
| 3 | KPI 카드 5개 | ① 최종 평가금액(스파크라인) ② 실현 손익 ③ 승률(도넛) ④ 보유 종목 수 ⑤ 총 거래대금(막대) | ① `summary.final_equity`, `summary.total_return_pct`, `charts.sparklines.equity` ② `summary.realized_pnl`(+sign), `summary.unrealized_pnl`, `charts.sparklines.realized_pnl` ③ `summary.win_rate_pct`, `summary.win_count`·`loss_count`·`closed_count`, `charts.win_donut` ④ `summary.holding_count`, `summary.max_positions`, `charts.sparklines.holdings` ⑤ `summary.total_trade_value`, `summary.total_trade_volume`, `charts.trade_value_bars[]`. (개정 1.1) ②의 보조 문구는 두 줄이다: "보유 종목 평가손익 …원" = `summary.unrealized_pnl`(`signed_won`), "합계 …원" = `summary.total_pnl`(`signed_won`, 색은 `summary.total_pnl_sign`에 `sign_color`, 굵게). 둘 다 기존 필드라 추가 필드는 없다(실현 + 평가 = 합계 항등식은 strategy.md 7.1절) |
| 4 | 추이 차트(실적 vs 목표선) | 자산 곡선 vs 벤치마크 buy&hold | `charts.equity`(`viewbox`, `equity_points`, `equity_area_path`, `benchmark_points`, `y_labels`, `x_labels`, `zero_line_top_pct`, `unit`, `caption`). 원값은 `equity_curve[]`, `benchmark[]` |
| 5 | 도넛(부문별 구성) | 포지션 비중(종목별 + 현금) | `allocation.conic_gradient`, `allocation.center`, `allocation.segments[]`, `allocation.total`. 상세는 `positions[]` |
| 6 | 스택 바(유형별 추이) | 주차별 매매 구성(매수·매도·보유·현금) | `weekly_flow[].segments[]`(`height_pct`, `color`, `label`), `weekly_flow[].label` |
| 7 | 상위 팀 바 | 종목별 손익 기여 상위 5(손익 절댓값 기준 — 이익·손실 종목 모두 포함) | `top_contributors.items[]`(`name`, `pnl`, `sign`, `bar_pct`), `top_contributors.note`. (개정 1.1) 선정·막대·문구 규칙은 5.5절 |
| 8 | 분석 요약(다크 패널) | 자동 인사이트 3개 + 다음 조치 | `insights[]`(`no`, `title`, `detail`), `next_action.label`, `next_action.text`. (개정 1.1) 문장의 재료로 `summary.excess_vs_equal_weight_pct`가 추가됐다. 문장은 strategy.md 10절을 따른다 |
| 9 | 상세 테이블 | 종목별 상세 | `per_stock[]`(`name`, `status_label`, `trade_count`, `win_rate_pct`, `realized_pnl`, `realized_pnl_sign`, `total_pnl`, `return_pct`, `sign`). 색: 실현손익 열은 `realized_pnl_sign`, 총손익·수익률 열과 막대는 `sign`(둘 다 `sign_color`). `bar_pct`는 막대를 그릴 때 쓴다. **선택(종목 셀 보조줄)**: `trade_value`, `trade_volume` — 열로 두지 않고, 표시한다면 종목명 아래 보조줄에 넣는다(개정 1.1, 리뷰 phase4-1 L5) |
| 10 | 점검 필요 | 리스크 알림 | `alerts[]`(`title`, `detail`, `date`, `color`, `level`), `flags.only_low_sample_alert`. (개정 1.1) `date`가 null이 아니면 그대로 표시한다. `title`에는 날짜가 없고 구간 날짜는 `detail`에 있다(5.3절 alerts 규칙) |
| 11 | 연간 목표 진척 | 목표 수익률 대비 진척 | `target`(`target_return_pct`, `actual_return_pct`, `progress_pct`, `bar_segments[]`, `gap_amount`, `caption`). (개정 1.1) 오른쪽 큰 숫자는 진척률이 아니라 **현재 수익률** `target.current_return_pct`(`signed_pct`, 색은 `current_return_sign`에 `sign_color`)다. 보조 수치 `target.gap_pct`(%p), `target.gap_amount`. 문구는 `target.caption`을 그대로 출력한다(규칙은 5.5절) |
| 12 | (추가) 상세 테이블과 같은 카드 스타일 | 매매 내역 표 | `trades[]`, 체결 순(배열 순서 그대로). 열 9개: 체결일 `date` / 종목 `name`(보조 `code`) / 매수·매도 `side_label` / 수량 `qty` / 체결가 `price`(`won`) / 금액 `amount`(`won`) / 비용 `cost`(`won`) / 실현손익 `realized_pnl`(`signed_won`, 색은 `trades[].sign`에 `sign_color`) / 사유 `reason`. 매수 행은 `realized_pnl`이 null이라 필터가 "–"를 내고 `sign`은 `"zero"`다. 전부 기존 `trades[]` 필드이며 추가 필드는 없다. 거래 0건이면 `flags.no_trades`로 "거래 없음"(5.6절). 위치는 종목별 상세 표 아래(개정 1.1, 리뷰 phase4-1 M1·UX C-3) |
| + | (샘플에 없음) | 한계 고지(하단) | `meta.disclaimers[]`. CLAUDE.md 1절이 한계 고지를 요구하므로 데이터는 담는다. 배치는 dashboard-builder가 샘플 카드 스타일 안에서 정한다 |

### 5.5 미리 계산하는 값의 규칙 (report.py가 계산, 템플릿은 표시만)
**시계열 좌표 공통**: 점의 수는 거래일 수 n + 1이다. 맨 앞에 **시작점**(d1 시가 시점: 수익률 0, 누적 실현 손익 0, 보유 0종목)을 붙인다. `x_i = width × i / n` (i = 0..n). 좌표 문자열은 `"x,y x,y ..."`, 소수 1자리.

| 값 | 규칙 |
|---|---|
| `charts.equity` | viewBox `0 0 720 250`. y값은 **누적 수익률(%)**: 전략 `equity_curve[].return_pct`, 벤치마크 `benchmark[].return_pct`. `y = 250 × (y_max − v) / (y_max − y_min)` |
| `y_min`, `y_max`, `y_labels` | 두 계열과 0을 포함한 최솟값·최댓값에 대해, 간격 후보 `[0.5, 1, 2, 5, 10, 20, 50]` 중 `y_min = floor(min / step) × step`, `y_max = y_min + 4 × step ≥ max`를 만족하는 가장 작은 step. `y_labels`는 위에서 아래로 5개 |
| `zero_line_y`, `zero_line_top_pct` | 수익률 0의 y좌표와 그 `%`(`y / 250 × 100`). 0 기준선을 그릴 때 쓴다 |
| `equity_area_path` | `M` + 전략 점들을 `L`로 이은 뒤 `L720.0,250.0 L0.0,250.0 Z` |
| `x_labels[]` | 각 ISO 주의 첫 거래일. `label`은 `MM-DD`, `x_pct = (그 날의 점 번호 i) / n × 100` |
| `charts.sparklines.*` | viewBox `0 0 200 44`. `y = 41 − 38 × (v − min) / (max − min)`(위아래 3 여백). `max == min`이면 전부 `22.0`. `equity`는 누적 수익률, `realized_pnl`은 누적 실현 손익, `holdings`는 보유 종목 수 |
| `charts.win_donut` | `win_pct`(소수 2자리, 청산 0건이면 0), `conic_gradient = "conic-gradient(#1428A0 0% {p}%, #E1E4EC {p}% 100%)"` |
| `charts.trade_value_bars[]` | ISO 주별 거래대금(매수+매도). `height_pct = value / 최댓값 × 100`(최댓값 0이면 전부 0). `color`: 75 이상 `#1428A0`, 50 이상 `#4B5CC0`, 25 이상 `#909BD6`, 그 밖 `#C2C8E8` |
| `allocation.segments[]` | 종목을 평가액 내림차순, 현금을 맨 끝. `weight_pct = value / total × 100`. `end_pct`는 누적 비중(소수 2자리), 마지막은 100.0으로 고정. 종목 색은 순서대로 `#1428A0, #4B5CC0, #7C9BFF, #909BD6, #C2C8E8`, 현금 `#DCE0E9` |
| `allocation.conic_gradient` | `"conic-gradient({color} {start}% {end}%, ...)"` 완성 문자열 |
| `allocation.center` | `label = "주식 비중"`, `value_pct = 100 − 현금 비중` |
| `weekly_flow[].segments[]` | 순서·색 고정: 매수 `#1428A0`, 매도 `#4B5CC0`, 보유 `#7C9BFF`, 현금 `#C2C8E8`. 분모 = 주간 매수 거래대금 + 주간 매도 거래대금 + 주 마지막 거래일 보유 평가액 + 같은 날 현금. 앞의 셋은 소수 2자리 반올림, 현금은 `100 − 앞 셋의 합`(합이 정확히 100) |
| `weekly_flow[].label` | 그 주 첫 거래일 `MM-DD` |
| `per_stock[].bar_pct`, `top_contributors.items[].bar_pct` | `|total_pnl| / max|total_pnl| × 100`(거래한 종목 전체 기준, 최댓값 0이면 0). 막대 색은 `sign`. (개정 1.1) `items[].bar_pct`는 같은 종목의 `per_stock[].bar_pct`와 같은 값이다. 절댓값 순으로 뽑으므로 1위 막대는 항상 100이고 아래로 갈수록 짧아진다 |
| `top_contributors.items[]` | (개정 1.1, UX C-2) 거래한 종목(`status`가 `held` 또는 `closed`. `no_trade`·`excluded`는 제외)을 **`|total_pnl|` 절댓값 내림차순**(동률은 종목코드 오름차순)으로 최대 5개. `rank`는 그 순서 1~5, `pnl = total_pnl`(부호 그대로), `sign`은 `pnl`의 부호. 이익 종목과 손실 종목이 섞여 나온다 |
| `top_contributors.note` | (개정 1.2) **문장 틀은 strategy.md 10.4절을 따른다**(5개 분기: 거래 0건 / 이익·손실 모두 있음 / 손실 종목 없음 / 이익 종목 없음 / 손익 0). 집계는 상위 5가 아니라 `per_stock[]` 전 종목의 `total_pnl` 기준이다(`no_trade`·`excluded`는 0이라 어느 쪽에도 들어가지 않는다). 한 종목은 이익·손실 중 한쪽에만 들어가므로 X − Y = Z(= `summary.total_pnl`)가 성립한다. 부호 표기는 strategy.md 10.0절(ASCII `-`). "상위 5종목 손익 합계 …" 문구는 쓰지 않는다(중복 집계) |
| `per_stock[].contribution_pct` | `total_pnl / 초기 자본 × 100` |
| `per_stock[].realized_pnl_sign` | (개정 1.1) `sign_of(realized_pnl)` |
| `summary.excess_vs_equal_weight_pct` | (개정 1.1) `(total_return − equal_weight_return) × 100`, 소수 4자리. 동일가중이 null이면 null. `excess_vs_equal_weight_sign = sign_of(값)` |
| `target` | `progress_raw_pct = total_return / target_return × 100`. `progress_pct = clip(progress_raw_pct, 0, 100)`. `bar_segments`: 실현 폭 = `clip(실현 손익 / 목표 금액 × 100, 0, progress_pct)`, 미실현 폭 = `progress_pct − 실현 폭`. `target_equity = 초기 자본 × (1 + 목표)`, `gap_amount = max(target_equity − final_equity, 0)`, `achieved = final_equity ≥ target_equity` |
| `target.current_return_pct`, `target.current_return_sign` | (개정 1.1) 현재(기말) 총수익률. `summary.total_return_pct`·`total_return_sign`과 같은 값이며 기존 `target.actual_return_pct`·`target.sign`과도 같다(기존 키는 그대로 둔다) |
| `target.gap_pct` | (개정 1.1) `현재 수익률 − 목표 수익률`(%p, 부호 있음, 소수 4자리). 미달이면 음수, 달성이면 0 이상. 예: −0.84 − 2.00 = −2.84 |
| `target.gap_amount` | 기존 정의 그대로 `max(target_equity − final_equity, 0)`: 목표 평가금액까지 **부족한 금액**(달성하면 0). 초과 금액은 필드로 두지 않고 `caption` 문장 안에만 넣는다(`final_equity − target_equity`) |
| `target.caption` | (개정 1.2) **문장 틀은 strategy.md 10.5절을 따른다**(미달 / 목표 평가금액과 같음 / 초과 달성의 3분기, 판정은 정수 원 `final_equity` 대 `target_equity`). 예(미달): `"목표 +2.00%에 2.84%p 못 미쳤습니다(현재 -0.84%). 목표 평가금액까지 2,838,856원 부족."` **금지: "목표 +2.00% 대비 −41.94% 달성"처럼 진척률(`progress_raw_pct`)을 문장에 넣는 표현.** 음수 진척률은 뜻이 통하지 않으므로 달성률 문구 자체를 쓰지 않는다. `progress_raw_pct`·`progress_pct`는 막대 폭 용도로만 남는다 |
| `insights`, `next_action` | strategy.md 10.1·10.2절 문장 틀. `title`은 고정: `"벤치마크 비교"`, `"손익 분해"`, `"리스크"`(개정 1.1, strategy.md 10.1절. 종전 "벤치마크 대비"/"종목 기여"/"거래·위험"은 쓰지 않는다). `detail`이 10.1절 문장. (개정 1.1) 동일가중 비교 문장에 쓸 수치로 `summary.excess_vs_equal_weight_pct`를 제공한다. 이 문서는 필드만 정하고, 인사이트·다음 조치 문장은 strategy.md 10절을 따른다. (개정 1.2) 문장 재료는 `build_insights`의 키워드 인자 `positions`(② 종목 절, 다음 조치 3번), `equal_weight`, `equal_weight_count`(① 뒤 문장의 `n`)로 받는다(1.7절) |

### 5.6 빈 경우의 표현
| 상황 | JSON | 템플릿 표시 |
|---|---|---|
| 거래 0건 | `trades: []`, `flags.no_trades: true`, `summary.trade_count: 0`, `win_rate_pct: null`, `payoff_ratio: null`, `charts.win_donut.win_pct: 0`, `top_contributors.items: []`, `trade_value_bars`의 `height_pct` 전부 0, `weekly_flow`는 주마다 그대로 있고 매수·매도 0, `alerts`에 `NO_TRADES` | 매매 내역 표(5.4절 12번) 카드는 그대로 두고 행 자리에 "거래 없음". 승률 "–" |
| 청산 0건(매수만) | `flags.no_closed_trades: true`, `closed_count: 0`, `win_rate_pct: null`, `realized_pnl: 0` | 승률 "–", 도넛 회색 |
| 기말 보유 0 | `positions: []`, `flags.no_positions: true`, `allocation.segments`는 현금 1개(0~100%), `center.value_pct: 0` | 도넛 전체 현금색 |
| 알림이 `LOW_SAMPLE`뿐 | `flags.only_low_sample_alert: true` | 알림 목록 위에 "특이 리스크 없음" 함께 표시 |
| 거래 없는 종목 | `per_stock`에 `status: "no_trade"`, 수치 0, `win_rate_pct`·`return_pct` null | null은 "–" |
| 제외 종목 | `per_stock`에 `status: "excluded"`, `meta.data_source.excluded[]`, `alerts`에 `DATA_MISSING` | 상태 라벨만 표시 |
| 값이 null | 필터가 "–"를 낸다 | |
- `equity_curve`, `benchmark`, `weekly_flow`, `per_stock`, `insights`(3개), `allocation.segments`(1개 이상)는 **비지 않는다**. 거래일이 0일이면 result.json을 만들지 않고 종료 코드 3으로 끝낸다.
- `result.example.json`에는 빨간 알림(`#B0472F`)과 빈 배열 사례가 없다. dashboard-builder는 예시를 복사해 값을 바꾼 임시 입력으로 위 경우를 `tests/test_render.py`에서 확인한다.

## 6. 캐시와 토큰

### 6.1 일봉 캐시
| 항목 | 규칙 |
|---|---|
| 위치 | `stock-sim/data/cache/` (커밋 금지) |
| 파일명 | 종목 `<종목코드>_<시작>_<종료>.csv` (예 `005930_20260531_20260929.csv`). 지수 `IDX<업종코드>_<시작>_<종료>.csv` (예 `IDX0001_20260531_20260929.csv`). 날짜는 **요청 구간**(`fetch_start`, `end`)의 `YYYYMMDD` |
| 내용 | 4.1절 컬럼, UTF-8, 헤더 있음, `date`는 `YYYY-MM-DD`, 오름차순 |
| 적중 판정 | 같은 이름의 파일이 있고, 읽었을 때 필수 컬럼이 모두 있고 1행 이상 |
| 적중 시 | API를 호출하지 않는다. 전 파일 적중이면 토큰도 발급하지 않는다. (개정 1.2) 이슈 보조 파일이 있으면 읽어 `NON_INTEGER_PRICE`를 복원한다(아래 행) |
| 무효화 | ① 요청 구간이 바뀌면 파일명이 달라져 자동 미적중 ② `--refresh` ③ 파일 수동 삭제 ④ 파일이 깨졌거나 비었으면 미적중으로 보고 다시 받는다 |
| 저장 조건 | 정규화 결과가 1행 이상일 때만 쓴다. 빈 응답은 캐시하지 않는다. (개정 1.2) 또한 **어느 조각이든 응답 건수가 상한(종목 100건, 지수 50건)에 닿으면**(`TRUNCATION_SUSPECT`) 캐시에 쓰지 않고, 같은 이름의 기존 CSV와 이슈 보조 파일도 지운다. 그 데이터는 이번 실행에만 쓴다. 다음 실행은 캐시 미적중이라 다시 받아 `TRUNCATION_SUSPECT`를 다시 경고한다. `client=None`(오프라인)이면 `FileNotFoundError`(종료 코드 3) |
| 이슈 보조 파일 (개정 1.2) | 파일명 `<캐시명 stem>.issues.json`(예 `005930_20260531_20260929.issues.json`, `data.issues_path`), 내용 `{"non_integer_price": true}`, UTF-8. **비정수 가격이 있던 수집에서만** CSV와 함께 쓴다. 이후 수집(`--refresh` 등)에서 비정수 가격이 없으면 기존 보조 파일을 지운다. 캐시 적중 시 보조 파일이 없거나 깨졌으면(JSON 오류·dict 아님) "이슈 없음"으로 본다(깨진 경우 경고 로그). CSV 컬럼·파일명 규칙은 바뀌지 않는다 |
| 환경 | 파일명에 DEV/PROD를 넣지 않는다(같은 시세로 본다). 실제로 쓴 환경은 `meta.data_source.env`에 남긴다 |
- `end: auto`는 날마다 `end`가 바뀌므로 다음 날 실행하면 새 파일을 받는다. 같은 날 재실행은 호출 0회다. 오래된 파일은 지우지 않는다(수동 관리).
- 동시 실행은 고려하지 않는다(잠금 없음).

### 6.2 토큰 캐시
| 항목 | 규칙 |
|---|---|
| 파일 | `data/cache/token_<env 소문자>.json` (예 `token_dev.json`) |
| 내용 | `{"access_token": str, "expires_at": "YYYY-MM-DDTHH:MM:SS", "issued_at": "...", "env": "DEV"}`. 앱키·시크릿은 저장하지 않는다 |
| 만료 시각 | 응답의 `access_token_token_expired`(`YYYY-MM-DD HH:MM:SS`, 로컬 시각으로 본다). 없으면 `issued_at + expires_in초`, 그것도 없으면 `issued_at + 24시간` |
| 유효 판정 | `now < expires_at − 1시간`이면 재사용. 아니면 재발급 |
| 재발급 제한 | 1분당 1회. 발급 실패 시 같은 실행에서 61초 대기 후 **1회만** 재시도 |
| 서버가 토큰을 거부 | 시세 호출이 HTTP 401 또는 토큰 만료 메시지를 돌려주면 토큰 파일을 지우고 재발급 1회, 같은 요청 1회 재시도 |
| 노출 금지 | 토큰 값은 로그·예외 메시지·result.json에 넣지 않는다 |

## 7. 에러 처리
| 상황 | 감지 | 동작 | 종료 코드 |
|---|---|---|---|
| 설정 오류 | `load_config` 검증 | `ConfigError`, 어떤 키가 왜 틀렸는지 한 줄 | 1 |
| `.env`에 키 없음 | `load_credentials` | `ConfigError`. 키 **이름**만 언급(`KIS_DEV_APP_KEY`) | 1 |
| 토큰 발급 실패 | HTTP 오류, 응답에 `access_token` 없음 | 61초 대기 후 1회 재시도 → 실패면 `KisAuthError`(`msg_cd`·`msg1`만 포함) | 3 |
| 호출 제한 초과 | `msg_cd == "EGW00201"` 또는 HTTP 429 | `backoff_sec × 시도 번호`초 대기 후 재시도, 최대 `max_retries`회 → 소진 시 `KisRateLimitError` | 3 |
| 네트워크 오류·타임아웃 | `requests` 예외 | 같은 재시도 규칙 → 소진 시 `KisError` | 3 |
| DEV 미지원 | 재시도 대상이 아닌 `rt_cd != "0"`, HTTP 4xx/5xx, 또는 지수·전 종목이 빈 응답 | `KisUnsupportedError`. **자동으로 PROD로 바꾸지 않는다.** 아래 메시지 | 3 |
| 종목 데이터 없음 | 한 종목의 조회 결과 0건 | 그 종목만 제외하고 계속. `DATA_MISSING` 알림, `meta.data_source.excluded`, `per_stock.status = "excluded"` | – |
| 종목 일부 결측 | 달력에는 있는데 그 종목 행이 없음 | 제외하지 않는다. `DATA_MISSING`(결측일 수) 알림. 순위·체결 처리는 strategy.md 8절 2번 | – |
| 유효 종목 0개 | 전 종목 제외 | 오류로 중단 | 3 |
| 워밍업 부족 | d1 이전 달력 거래일 수 < `min_warmup_days` | 오류로 중단(strategy.md 2.2절). 필요·확보 일수를 메시지에 적는다 | 3 |
| 지수 데이터 없음 | 벤치마크 조회 실패·0건 | 오류로 중단(벤치마크 없이 대시보드를 만들지 않는다). 대용 지표로 바꾸려면 사용자 결정 | 3 |
| 렌더 실패 | 1.9절 | result.json 유지, 오류 로그 | 2 |

DEV 미지원 시 메시지(고정 문안, 값만 채움):
```
KIS DEV(모의투자) 도메인에서 <API 이름> 조회에 실패했습니다 (msg_cd=<코드>, msg1=<메시지>).
자동으로 PROD로 전환하지 않습니다(CLAUDE.md R3).
다음 중 하나를 사용자가 결정해야 합니다:
 1) PROD 키로 시세 조회(read-only)만 허용: config.yaml의 kis.env를 PROD로, kis.prod_approved_by_user를 true로 설정
 2) 대체 데이터 소스 사용(의존성 추가 승인 필요, docs/research/universe.md 참조)
```
- 일부 종목만 받은 뒤 실패해도 이미 저장한 캐시는 남긴다(다음 실행에서 이어 받는다).
- `cli.main`은 위 예외를 잡아 메시지를 `logging.error`로 남기고 종료 코드를 반환한다. 스택 트레이스는 `--verbose`일 때만.

## 8. 로깅·마스킹·테스트

### 8.1 로깅
- `logging` 사용, `print` 금지. 형식 `%(asctime)s %(levelname)s %(name)s: %(message)s`, 기본 INFO, `--verbose`면 DEBUG. 콘솔(stderr)만.
- 남기는 것: 환경(DEV/PROD), 기간, 종목별 캐시 적중 여부, API 경로·tr_id·종목코드·구간·응답 건수, 재시도 횟수, 제외 종목, 산출물 경로.

### 8.2 마스킹 (R1)
| 대상 | 규칙 |
|---|---|
| 앱키 | `mask()`로 앞 4자리 + `****`만. 초기화 로그 1회 |
| 앱시크릿, 액세스 토큰 | **일부도 남기지 않는다.** "토큰 재사용(만료 <시각>)" 같은 사실만 |
| 요청 헤더·토큰 요청 본문·토큰 응답 본문 | 로그에 통째로 남기지 않는다. DEBUG에서도 같다 |
| 예외 메시지 | `msg_cd`, `msg1`, HTTP 상태, 경로만. `requests` 예외를 그대로 문자열화하지 않는다(URL에 비밀은 없지만 헤더가 섞일 수 있는 repr 금지) |
| result.json·HTML | 키·토큰·계좌 정보 없음(R4) |

### 8.3 테스트
| 파일 | 종류 | 내용 |
|---|---|---|
| `tests/fixtures/` | 데이터 | 가짜 일봉 CSV(캐시와 같은 파일명·컬럼). strategy.md 9절 가격표(AAA, BBB, 지수) 포함. 9절 fixture는 `run_backtest`·`metrics` 직접 호출용이고(코드 6자리·워밍업 검사를 거치지 않음), `test_e2e.py`는 6자리 코드와 충분한 워밍업을 가진 별도 fixture를 쓴다 |
| `test_strategy.py` | 단위 | 스케줄(주 첫 거래일, 휴장 주), 순위·동률, 결측 시 제외, **미래 데이터를 바꿔도 과거 신호 불변** |
| `test_backtest.py` | 단위 | strategy.md 9.4~9.7절 기대값 그대로. 현금 ≥ 0, 정수 수량, T+1 시가 체결, 양쪽 비용, half-up 반올림 |
| `test_metrics.py` | 단위 | 9.6절 지표, 7.1절 항등식, 거래 0건 |
| `test_data.py` | 단위 | 정규화(문자열·내림차순·빈 날짜·중복), `split_ranges`, 캐시 적중 시 클라이언트를 부르지 않음(호출하면 실패하는 가짜 객체) |
| `test_report.py` | 계약 | fixture로 만든 result의 **키 구조가 `docs/result.example.json`과 같음**(재귀 비교, 배열은 첫 원소), `_pct` 자리수, 스택 합 100, 도넛 마지막 `end_pct` 100, `sign`과 값의 부호 일치, NaN 없음, 5.6절 빈 경우 |
| `test_e2e.py` | 통합 | fixture 캐시 폴더 + 임시 config로 `cli.main(["run", ..., "--no-render"])` → result.json 생성, 네트워크 0회 |
| `test_rules.py` | 규칙 | `src/` 전체에서 R2 금지 경로 문자열(주문·계좌 API 경로 조각)이 없음, `kis_client.py` 밖에 `requests` import가 없음 |
| `test_render.py` | 단위(dashboard-builder) | 예시 JSON 렌더 성공, 필터 출력, 부호와 색 일치, 빈 경우, 외부 JS 없음 |
| `test_kis_smoke.py` | `@pytest.mark.network` | DEV에서 종목 1개·지수 1회 실호출, 컬럼·정렬 확인. 기본 실행에서 제외 |
- `pyproject.toml`의 pytest 설정: `markers = ["network: 실 API 호출"]`, `addopts = "-m 'not network'"`. 실행 `uv run pytest`, 스모크 `uv run pytest -m network`.
- R2 검사용 금지 문자열은 테스트 코드 안에서 조각을 이어 붙여 만든다(테스트 파일 자체가 검사에 걸리지 않게, 검사 대상은 `src/`만).

## 9. 실행 명령과 산출물
작업 폴더는 `stock-sim/`이다.

| 목적 | 명령 | 산출물 |
|---|---|---|
| 전체 실행 | `uv run --directory src python -m stock_sim run --config ../config.yaml` | `output/result.json`, `output/dashboard.html`, `data/cache/*.csv`, `data/cache/token_dev.json` |
| 캐시 무시 재수집 | `uv run --directory src python -m stock_sim run --config ../config.yaml --refresh` | 같음 |
| HTML만 다시 | `uv run --directory src python -m stock_sim render --config ../config.yaml` | `output/dashboard.html` |
| 예시 렌더(W3, dashboard-builder) | `uv run --with jinja2 python src/stock_sim/render.py --result docs/result.example.json --template templates/dashboard.html.j2 --out output/dashboard.example.html` | `output/dashboard.example.html` |
| 테스트 | `uv run pytest` | – |
| 실 API 스모크 | `uv run pytest -m network` | – |

- `output/dashboard.html`에는 실데이터 결과만 쓴다. 예시 데이터는 `output/dashboard.example.html`에만 쓴다(CLAUDE.md 6.6절).
- (개정 1.1, CLAUDE.md 7절) 패키지를 설치하지 않는 구성이다: `pyproject.toml`에 `[tool.uv] package = false`. 한글 경로에서 Python 3.11이 편집 가능 설치의 `.pth`를 읽지 못하기 때문이다. 그래서 진입점은 `--directory src`로 `src/`에서 `python -m stock_sim`을 실행하고, `--config`는 `src/` 기준 상대 경로 `../config.yaml`로 준다. `config.yaml` 안의 상대 경로(`output/…`, `data/cache` 등)는 종전대로 config 파일 폴더(`stock-sim/`) 기준이라 산출물 위치는 바뀌지 않는다.
- (개정 1.1) 테스트는 `uv run pytest` 그대로이며, `pyproject.toml`의 pytest 설정에 `pythonpath = ["src"]`를 두어 설치 없이 `stock_sim`을 import한다(8.3절의 `markers`·`addopts`는 그대로).

## 10. strategy.md와 맞춘 점, 남은 확인 사항
| # | 항목 | 이 문서의 처리 |
|---|---|---|
| 1 | 전략 이름 | strategy.md에 코드용 이름이 없어 `momentum_topn`으로 정했다. 파라미터 키는 strategy.md 0절 그대로 |
| 2 | `max_positions`와 `top_n` | 같은 값이어야 한다(다르면 ConfigError). 두 키를 모두 둔 것은 위임 요구(`max_positions` 키)와 strategy.md(`top_n`)를 함께 만족하기 위해서다 |
| 3 | 비용 필드 | strategy.md가 매도 비용을 합친 율로 한 번 반올림하므로 거래 레코드에 수수료·세금을 나누지 않고 `cost` 하나만 둔다 |
| 4 | 비율 저장 | strategy.md 4.2절(내부는 반올림 없는 소수)을 따르고, result.json에서만 % 단위 소수 4자리로 바꾼다. 표시는 필터가 2자리로 만든다 |
| 5 | 거래일 달력 | strategy.md 2.4절대로 종목 날짜의 합집합. 지수는 달력을 만들지 않고 결측일은 직전 값으로 채운다 |
| 6 | 알림 등급 | strategy.md는 `warn`/`info` 두 단계다. 샘플의 빨간 점은 등급이 아니라 `color`로만 구분한다(손실 계열 warn 3종) |
| 7 | 거래 0건 알림 | strategy.md 10.3절에서 `NO_TRADES`는 warn이다. 그대로 따른다 |
| 8 | 인사이트 모양 | 샘플은 제목+설명 2줄, strategy.md는 문장 1개다. 제목은 고정 주제어, 설명에 문장을 넣었다 |
| 9 | 총 거래대금 막대·주차별 스택의 정의 | strategy.md에 없어 5.5절에서 정했다(표시 규칙). 매매에 영향 없음 |
| 10 | 동일가중 벤치마크 | `summary.equal_weight_return_pct` 숫자만 담고 곡선은 그리지 않는다 |
