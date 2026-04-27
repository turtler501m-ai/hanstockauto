from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol


class HTTPSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any:
        ...

    def post(self, url: str, **kwargs: Any) -> Any:
        ...


def _default_session() -> HTTPSession:
    import requests

    return requests.Session()


@dataclass(frozen=True)
class KISClientConfig:
    base_url: str
    app_key: str
    app_secret: str
    account_no: str = ""
    trading_env: str = "demo"
    customer_type: str = "P"
    token_cache_path: Path | None = None
    token_ttl: timedelta = timedelta(hours=23)
    token_refresh_margin: timedelta = timedelta(minutes=5)
    request_timeout_seconds: int = 15
    circuit_cooldown_seconds: int = 60
    circuit_max_errors: int = 5
    etf_market_codes: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "102110",
                "133690",
                "148020",
                "152100",
                "157490",
                "229200",
                "251340",
                "261240",
                "273130",
                "278530",
                "305720",
                "381170",
                "448290",
                "481190",
            }
        )
    )

    @property
    def account_prefix(self) -> str:
        return self.account_no[:8]

    @property
    def account_suffix(self) -> str:
        return self.account_no[8:] if len(self.account_no) > 8 else "01"

    @property
    def is_demo(self) -> bool:
        return self.trading_env == "demo"


@dataclass(frozen=True)
class TokenCacheEntry:
    token: str
    expires_at: datetime
    trading_env: str
    base_url: str
    app_key_prefix: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "TokenCacheEntry":
        return cls(
            token=str(payload["token"]),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            trading_env=str(payload["trading_env"]),
            base_url=str(payload["base_url"]),
            app_key_prefix=str(payload["app_key_prefix"]),
        )

    @classmethod
    def from_file(cls, path: Path) -> "TokenCacheEntry":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")))

    def matches(self, config: KISClientConfig) -> bool:
        return (
            self.trading_env == config.trading_env
            and self.base_url == config.base_url
            and self.app_key_prefix == config.app_key[:8]
        )

    def is_usable(self, now: datetime, refresh_margin: timedelta) -> bool:
        return self.expires_at > now + refresh_margin

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "token": self.token,
                    "expires_at": self.expires_at.isoformat(),
                    "trading_env": self.trading_env,
                    "base_url": self.base_url,
                    "app_key_prefix": self.app_key_prefix,
                }
            ),
            encoding="utf-8",
        )


@dataclass
class CircuitBreakerState:
    error_count: int = 0
    opened_at: datetime | None = None

    def reset(self) -> None:
        self.error_count = 0
        self.opened_at = None

    def record_success(self) -> None:
        self.reset()

    def record_failure(self, now: datetime, max_errors: int) -> None:
        self.error_count += 1
        if self.error_count >= max_errors and self.opened_at is None:
            self.opened_at = now

    def ensure_can_proceed(self, now: datetime, max_errors: int, cooldown_seconds: int) -> None:
        if self.error_count < max_errors:
            return
        if self.opened_at is None:
            self.opened_at = now
        elapsed = (now - self.opened_at).total_seconds()
        if elapsed >= cooldown_seconds:
            self.reset()
            return
        retry_after = max(1, int(cooldown_seconds - elapsed))
        raise RuntimeError(
            f"Circuit breaker opened after {self.error_count} consecutive API errors; "
            f"retry after {retry_after}s"
        )

    def status(self, now: datetime, max_errors: int, cooldown_seconds: int) -> dict[str, Any]:
        opened = self.error_count >= max_errors
        opened_at = None
        retry_after = 0
        if opened:
            if self.opened_at is None:
                self.opened_at = now
            opened_at = self.opened_at.isoformat()
            elapsed = (now - self.opened_at).total_seconds()
            retry_after = max(0, int(cooldown_seconds - elapsed))
            if retry_after <= 0:
                self.reset()
                opened = False
                opened_at = None
        return {
            "opened": opened,
            "error_count": self.error_count,
            "max_errors": max_errors,
            "cooldown_seconds": cooldown_seconds,
            "retry_after_seconds": retry_after,
            "opened_at": opened_at,
        }


class KISClient:
    def __init__(
        self,
        config: KISClientConfig,
        *,
        session: HTTPSession | None = None,
        clock: Callable[[], datetime] | None = None,
        circuit: CircuitBreakerState | None = None,
        access_token: str | None = None,
    ) -> None:
        self.config = config
        self.session = session or _default_session()
        self._clock = clock or datetime.now
        self.circuit = circuit or CircuitBreakerState()
        self.access_token = access_token or self._load_or_fetch_token()

    def now(self) -> datetime:
        return self._clock()

    def _load_or_fetch_token(self) -> str:
        path = self.config.token_cache_path
        if path and path.exists():
            try:
                cached = TokenCacheEntry.from_file(path)
                if cached.matches(self.config) and cached.is_usable(
                    self.now(),
                    self.config.token_refresh_margin,
                ):
                    return cached.token
            except Exception:
                pass
        return self.fetch_token()

    def fetch_token(self) -> str:
        response = self.session.post(
            f"{self.config.base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.config.app_key,
                "appsecret": self.config.app_secret,
            },
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token", "")
        if not token:
            raise RuntimeError(f"Token response did not include access_token: {data}")
        expires_at = self.now() + self.config.token_ttl
        if self.config.token_cache_path:
            TokenCacheEntry(
                token=token,
                expires_at=expires_at,
                trading_env=self.config.trading_env,
                base_url=self.config.base_url,
                app_key_prefix=self.config.app_key[:8],
            ).write(self.config.token_cache_path)
        return token

    def headers(self, tr_id: str, *, include_auth: bool = True, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": self.config.customer_type,
            "Content-Type": "application/json",
        }
        if include_auth:
            headers["authorization"] = f"Bearer {self.access_token}"
        if extra:
            headers.update(extra)
        return headers

    def create_hashkey(self, payload: dict[str, Any]) -> str:
        try:
            response = self.session.post(
                f"{self.config.base_url}/uapi/hashkey",
                headers={
                    "content-type": "application/json",
                    "appkey": self.config.app_key,
                    "appsecret": self.config.app_secret,
                },
                json=payload,
                timeout=self.config.request_timeout_seconds,
            )
            return response.json().get("HASH", "")
        except Exception:
            return ""

    def check_circuit(self) -> None:
        self.circuit.ensure_can_proceed(
            self.now(),
            self.config.circuit_max_errors,
            self.config.circuit_cooldown_seconds,
        )

    def mark_success(self) -> None:
        self.circuit.record_success()

    def mark_failure(self) -> None:
        self.circuit.record_failure(self.now(), self.config.circuit_max_errors)

    def circuit_status(self) -> dict[str, Any]:
        return self.circuit.status(
            self.now(),
            self.config.circuit_max_errors,
            self.config.circuit_cooldown_seconds,
        )

    def get_balance(self) -> dict[str, Any]:
        self.check_circuit()
        tr_id = "VTTC8434R" if self.config.is_demo else "TTTC8434R"
        params = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        last_error = ""
        for _attempt in range(2):
            try:
                response = self.session.get(
                    f"{self.config.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                    headers=self.headers(tr_id),
                    params=params,
                    timeout=self.config.request_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("rt_cd") == "0":
                    self.mark_success()
                    return data
                last_error = str(data.get("msg1", "unknown KIS balance error"))
            except Exception as exc:
                last_error = str(exc)
        self.mark_failure()
        return {"output1": [], "output2": [{}], "_error": last_error or "unknown KIS balance error"}

    def get_quote(self, symbol: str) -> dict[str, float]:
        self.check_circuit()
        try:
            response = self.session.get(
                f"{self.config.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=self.headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
                timeout=self.config.request_timeout_seconds,
            )
            output = response.json().get("output", {})
            self.mark_success()
            return {
                "current": float(output.get("stck_prpr", 0)),
                "ask1": float(output.get("askp1", 0)),
                "bid1": float(output.get("bidp1", 0)),
            }
        except Exception:
            self.mark_failure()
            return {"current": 0.0, "ask1": 0.0, "bid1": 0.0}

    def get_volume_rank(self, top_n: int = 50) -> list[str]:
        self.check_circuit()
        try:
            response = self.session.get(
                f"{self.config.base_url}/uapi/domestic-stock/v1/quotations/volume-rank",
                headers=self.headers("FHKUP03500000"),
                params={
                    "FID_COND_MRK_DIV_CODE": "J",
                    "FID_COND_SCR_DIV_CODE": "20171",
                    "FID_INPUT_ISCD": "0000",
                    "FID_DIV_CLS_CODE": "0",
                    "FID_BLNG_CLS_CODE": "0",
                    "FID_TRGT_CLS_CODE": "111111111",
                    "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                    "FID_INPUT_PRICE_1": "",
                    "FID_INPUT_PRICE_2": "",
                    "FID_VOL_CNT": "",
                    "FID_INPUT_DATE_1": "",
                },
                timeout=self.config.request_timeout_seconds,
            )
            if response.status_code != 200:
                self.mark_failure()
                return []
            data = response.json()
            if data.get("rt_cd") != "0":
                self.mark_failure()
                return []
            self.mark_success()
            return [
                row.get("mksc_shrn_iscd", "").strip()
                for row in data.get("output", [])
                if row.get("mksc_shrn_iscd", "").strip()
            ][:top_n]
        except Exception:
            self.mark_failure()
            return []

    def get_daily(self, symbol: str, n: int = 60) -> list[dict[str, Any]]:
        self.check_circuit()
        now = self.now()
        params = {
            "FID_COND_MRKT_DIV_CODE": "E" if symbol in self.config.etf_market_codes else "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": (now - timedelta(days=365 * 3)).strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": now.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        try:
            response = self.session.get(
                f"{self.config.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                headers=self.headers("FHKST03010100"),
                params=params,
                timeout=self.config.request_timeout_seconds,
            )
            if response.status_code != 200:
                self.mark_failure()
                return []
            data = response.json()
            if data.get("rt_cd") != "0":
                self.mark_failure()
                return []
            self.mark_success()
            return data.get("output2", [])[:n]
        except Exception:
            self.mark_failure()
            return []

    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict[str, Any]:
        if self.config.is_demo:
            tr_id = "VTTC0802U" if order_type == "buy" else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if order_type == "buy" else "TTTC0801U"
        body = {
            "CANO": self.config.account_prefix,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        headers = self.headers(tr_id)
        hashkey = self.create_hashkey(body)
        if hashkey:
            headers["hashkey"] = hashkey
        self.check_circuit()
        try:
            response = self.session.post(
                f"{self.config.base_url}/uapi/domestic-stock/v1/trading/order-cash",
                headers=headers,
                json=body,
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            self.mark_success()
            return response.json()
        except Exception as exc:
            self.mark_failure()
            return {"rt_cd": "1", "msg1": str(exc)}
