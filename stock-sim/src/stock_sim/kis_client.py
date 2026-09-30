"""KIS Open API 클라이언트. 이 프로젝트에서 유일한 네트워크 모듈이다.

토큰 발급과 시세 조회 2종(종목 일봉, 업종 일봉)만 있다. 그 외 API의 경로·메서드는 두지 않는다(R2).
base URL은 생성자의 env 하나로만 정해지고, 환경을 바꾸는 분기는 없다(R3).
키·시크릿·토큰은 로그와 예외 메시지에 넣지 않는다(R1).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

BASE_URLS = {
    "PROD": "https://openapi.koreainvestment.com:9443",
    "DEV": "https://openapivts.koreainvestment.com:29443",
}
TOKEN_PATH = "/oauth2/tokenP"
DAILY_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
INDEX_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
DAILY_PRICE_TR_ID = "FHKST03010100"
INDEX_DAILY_TR_ID = "FHKUP03500100"
RATE_LIMIT_CODE = "EGW00201"
TOKEN_REJECT_CODES = ("EGW00121", "EGW00123")
TOKEN_RETRY_WAIT_SEC = 61
ENV_LABELS = {"DEV": "DEV(모의투자)", "PROD": "PROD(실전)"}


class KisError(Exception):
    """공통 부모. 메시지에 키·토큰·헤더를 넣지 않는다."""


class KisAuthError(KisError):
    """토큰 발급 실패."""


class KisRateLimitError(KisError):
    """재시도 소진."""


class KisUnsupportedError(KisError):
    """해당 환경에서 API 미지원·빈 응답."""


def unsupported_message(env: str, api_name: str, msg_cd: str | None, msg1: str | None,
                        http_status: int | None = None) -> str:
    """미지원 시 고정 문안(architecture.md 7절). 자동 전환은 하지 않는다."""
    status = f"HTTP={http_status}, " if http_status is not None else ""
    return (
        f"KIS {ENV_LABELS.get(env, env)} 도메인에서 {api_name} 조회에 실패했습니다 "
        f"({status}msg_cd={msg_cd}, msg1={msg1}).\n"
        "자동으로 PROD로 전환하지 않습니다(CLAUDE.md R3).\n"
        "다음 중 하나를 사용자가 결정해야 합니다:\n"
        " 1) PROD 키로 시세 조회(read-only)만 허용: config.yaml의 kis.env를 PROD로, "
        "kis.prod_approved_by_user를 true로 설정\n"
        " 2) 대체 데이터 소스 사용(의존성 추가 승인 필요, docs/research/universe.md 참조)"
    )


def _mask(secret: str) -> str:
    return secret[:4] + "****" if secret and len(secret) > 4 else "****"


class KisClient:
    def __init__(self, env: str, app_key: str, app_secret: str, cache_dir: Path,
                 min_interval_sec: float = 1.0, max_retries: int = 3,
                 backoff_sec: float = 2.0, timeout_sec: float = 10.0) -> None:
        if env not in BASE_URLS:
            raise KisError(f"알 수 없는 KIS 환경: {env}")
        self.env = env
        self._base = BASE_URLS[env]
        self._key = app_key
        self._secret = app_secret
        self._cache_dir = Path(cache_dir)
        self._min_interval = float(min_interval_sec)
        self._max_retries = int(max_retries)
        self._backoff = float(backoff_sec)
        self._timeout = float(timeout_sec)
        self._token: str | None = None
        self._last_call = 0.0
        self.call_count = 0
        log.info("KIS 클라이언트 초기화: env=%s, app_key=%s", env, _mask(app_key))

    # ---- 토큰 -------------------------------------------------------------
    def _token_file(self) -> Path:
        return self._cache_dir / f"token_{self.env.lower()}.json"

    def _scrub(self, text) -> str:
        out = "" if text is None else str(text)
        for secret in (self._key, self._secret, self._token):
            if secret:
                out = out.replace(secret, "****")
        return out

    def _read_cached_token(self) -> str | None:
        path = self._token_file()
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            expires_at = datetime.fromisoformat(data["expires_at"])
            token = data["access_token"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if token and data.get("env") == self.env and datetime.now() < expires_at - timedelta(hours=1):
            log.info("토큰 재사용(만료 %s)", expires_at.isoformat(timespec="seconds"))
            return token
        return None

    def _issue_token(self) -> str:
        url = self._base + TOKEN_PATH
        body = {"grant_type": "client_credentials", "appkey": self._key, "appsecret": self._secret}
        detail = ""
        for attempt in (1, 2):
            status, data = None, {}
            try:
                resp = requests.post(url, json=body, timeout=self._timeout,
                                     headers={"Content-Type": "application/json"})
                status = resp.status_code
                try:
                    data = resp.json()
                except ValueError:
                    data = {}
            except requests.RequestException as exc:
                detail = f"네트워크 오류 {type(exc).__name__}"
            if not isinstance(data, dict):
                data = {}
            token = data.get("access_token")
            if status == 200 and token:
                self._save_token(token, data)
                return token
            if status is not None:
                msg_cd = data.get("msg_cd") or data.get("error_code")
                msg1 = data.get("msg1") or data.get("error_description")
                detail = f"HTTP={status}, msg_cd={self._scrub(msg_cd)}, msg1={self._scrub(msg1)}"
            if attempt == 1:
                log.warning("토큰 발급 실패(%s). %d초 후 1회 재시도합니다.", detail, TOKEN_RETRY_WAIT_SEC)
                time.sleep(TOKEN_RETRY_WAIT_SEC)
        raise KisAuthError(f"KIS {self.env} 토큰 발급에 실패했습니다 ({detail}).")

    def _save_token(self, token: str, data: dict) -> None:
        issued = datetime.now()
        expires = None
        raw = data.get("access_token_token_expired")
        if raw:
            try:
                expires = datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expires = None
        if expires is None:
            try:
                expires = issued + timedelta(seconds=int(data["expires_in"]))
            except (KeyError, TypeError, ValueError):
                expires = issued + timedelta(hours=24)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {"access_token": token, "expires_at": expires.isoformat(timespec="seconds"),
                   "issued_at": issued.isoformat(timespec="seconds"), "env": self.env}
        with self._token_file().open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        log.info("토큰 발급 완료(만료 %s)", payload["expires_at"])

    def get_token(self) -> str:
        if self._token is None:
            self._token = self._read_cached_token() or self._issue_token()
        return self._token

    def _drop_token(self) -> None:
        self._token = None
        try:
            self._token_file().unlink()
        except OSError:
            pass

    # ---- 시세 GET ---------------------------------------------------------
    def _wait(self) -> None:
        remain = self._min_interval - (time.monotonic() - self._last_call)
        if self._last_call and remain > 0:
            time.sleep(remain)

    def _get(self, path: str, tr_id: str, params: dict, api_name: str) -> dict:
        url = self._base + path
        attempt, token_retried = 0, False
        while True:
            attempt += 1
            token = self.get_token()
            headers = {"Content-Type": "application/json", "Accept": "text/plain",
                       "authorization": f"Bearer {token}", "appkey": self._key,
                       "appsecret": self._secret, "tr_id": tr_id, "custtype": "P", "tr_cont": ""}
            self._wait()
            status, data, net_err = None, {}, None
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=self._timeout)
                status = resp.status_code
                try:
                    data = resp.json()
                except ValueError:
                    data = {}
            except requests.RequestException as exc:
                net_err = type(exc).__name__
            finally:
                self._last_call = time.monotonic()
                self.call_count += 1
            if not isinstance(data, dict):
                data = {}
            msg_cd, msg1 = self._scrub(data.get("msg_cd")), self._scrub(data.get("msg1"))
            if net_err is not None or status == 429 or data.get("msg_cd") == RATE_LIMIT_CODE:
                why = net_err or f"HTTP={status}, msg_cd={msg_cd}"
                if attempt > self._max_retries:
                    if net_err is not None:
                        raise KisError(f"{api_name} 네트워크 오류로 재시도를 소진했습니다 ({why}, 경로 {path}).")
                    raise KisRateLimitError(f"{api_name} 호출 제한으로 재시도를 소진했습니다 ({why}, 경로 {path}).")
                wait = self._backoff * attempt
                log.warning("%s 재시도 %d/%d (%s), %.1f초 대기", api_name, attempt, self._max_retries, why, wait)
                time.sleep(wait)
                continue
            if status == 401 or data.get("msg_cd") in TOKEN_REJECT_CODES:
                if token_retried:
                    raise KisAuthError(f"{api_name}: 서버가 토큰을 거부했습니다 (HTTP={status}, msg_cd={msg_cd}, msg1={msg1}).")
                log.warning("%s: 서버가 토큰을 거부해 재발급합니다 (HTTP=%s, msg_cd=%s)", api_name, status, msg_cd)
                token_retried = True
                self._drop_token()
                continue
            if status >= 400 or str(data.get("rt_cd")) != "0":
                raise KisUnsupportedError(unsupported_message(self.env, api_name, msg_cd, msg1, status))
            return data

    def daily_prices(self, code: str, start: date, end: date) -> list[dict]:
        """국내주식 기간별시세(일봉, 수정주가) 1회 호출. output2 원본 행을 그대로 반환."""
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                  "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                  "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                  "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
        data = self._get(DAILY_PRICE_PATH, DAILY_PRICE_TR_ID, params, "국내주식 기간별시세(일봉)")
        rows = data.get("output2")
        rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        log.info("GET %s tr_id=%s code=%s %s~%s → %d건", DAILY_PRICE_PATH, DAILY_PRICE_TR_ID,
                 code, start, end, len(rows))
        return rows

    def index_daily(self, index_code: str, start: date, end: date) -> list[dict]:
        """업종 기간별시세(지수 일봉) 1회 호출. output2(없으면 리스트형 output1) 원본 행 반환."""
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": index_code,
                  "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                  "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                  "FID_PERIOD_DIV_CODE": "D"}
        api_name = "업종 기간별시세(지수 일봉)"
        data = self._get(INDEX_DAILY_PATH, INDEX_DAILY_TR_ID, params, api_name)
        rows = None
        for key in ("output2", "output1"):
            cand = data.get(key)
            if isinstance(cand, list) and any(isinstance(r, dict) and "stck_bsop_date" in r for r in cand):
                rows = [r for r in cand if isinstance(r, dict)]
                break
        if rows is None:
            raise KisUnsupportedError(unsupported_message(
                self.env, api_name, self._scrub(data.get("msg_cd")), "응답에 일자별 배열이 없습니다"))
        log.info("GET %s tr_id=%s index=%s %s~%s → %d건", INDEX_DAILY_PATH, INDEX_DAILY_TR_ID,
                 index_code, start, end, len(rows))
        return rows
