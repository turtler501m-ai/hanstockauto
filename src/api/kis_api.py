import hashlib
import json
import threading
import time
from datetime import datetime, timedelta
import requests
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential
from pathlib import Path

from src.config import config
from src.utils.logger import logger
from src.notifier.slack import slack_error

HTTP = requests.Session()
HTTP.trust_env = False

# KIS API 전역 스로틀: 초당 최대 1회 요청 강제 (EGW00201 방지)
_KIS_THROTTLE_LOCK = threading.Lock()
_KIS_LAST_CALL: float = 0.0
_KIS_MIN_INTERVAL: float = 2.0  # 초 단위 (EGW00201 방지)


def _kis_throttle() -> None:
    """KIS API 호출 전 최소 간격을 보장합니다."""
    global _KIS_LAST_CALL
    with _KIS_THROTTLE_LOCK:
        elapsed = time.monotonic() - _KIS_LAST_CALL
        if elapsed < _KIS_MIN_INTERVAL:
            time.sleep(_KIS_MIN_INTERVAL - elapsed)
        _KIS_LAST_CALL = time.monotonic()


class KISConfigError(RuntimeError):
    """Non-retryable KIS app/environment mismatch."""


class KISRateLimitError(RuntimeError):
    """Non-retryable KIS API rate limit response."""


class KISAccountError(RuntimeError):
    """Non-retryable KIS account number/product code error."""


NON_RETRYABLE_KIS_ERRORS = (KISConfigError, KISRateLimitError, KISAccountError)


class KIStockAPI:
    TOKEN_CACHE = Path("data") / "kis_token.json"
    ETF_MARKET_CODES = {
        "102110", "133690", "148020", "152100", "157490",
        "229200", "251340", "261240", "273130", "278530",
        "305720", "381170", "448290", "481190",
    }
    
    _err_count = 0
    MAX_ERRORS = 5

    @staticmethod
    def _app_key_hash() -> str:
        return hashlib.sha256(config.kistock_app_key.encode("utf-8")).hexdigest()
    
    def __init__(self, notify_errors: bool = True) -> None:
        self.notify_errors = notify_errors
        self.base_url = "https://openapi.koreainvestment.com:9443" if config.trading_env == "real" else "https://openapivts.koreainvestment.com:29443"
        if config.trading_env == "real":
            HTTP.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"})
        else:
            HTTP.headers.update({"User-Agent": "python-requests/2.31.0"})
        self.access_token = self._load_or_fetch_token()

    def _load_or_fetch_token(self) -> str:
        if self.TOKEN_CACHE.exists():
            try:
                cached = json.loads(self.TOKEN_CACHE.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if (
                    cached.get("trading_env") == config.trading_env
                    and cached.get("app_key_hash") == self._app_key_hash()
                    and expires_at > datetime.now() + timedelta(minutes=5)
                ):
                    return cached["token"]
            except Exception:
                pass
        return self._fetch_token()

    def _fetch_token(self) -> str:
        _kis_throttle()
        url = f"{self.base_url}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": config.kistock_app_key, "appsecret": config.kistock_app_secret}
        try:
            r = HTTP.post(url, json=body, timeout=10)
            if r.status_code != 200:
                logger.error(f"Token fetch HTTP {r.status_code}: {r.text}")
                r.raise_for_status()
            data = r.json()
            token = data.get("access_token", "")
            expires_at = datetime.now() + timedelta(hours=23)
            self.TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            self.TOKEN_CACHE.write_text(
                json.dumps({
                    "token": token,
                    "expires_at": expires_at.isoformat(),
                    "trading_env": config.trading_env,
                    "app_key_hash": self._app_key_hash(),
                }),
                encoding="utf-8",
            )
            return token
        except Exception as e:
            logger.error(f"Failed to fetch KIS token: {e}")
            raise

    def _headers(self, tr_id: str) -> dict:
        return {
            "authorization": f"Bearer {self.access_token}",
            "appkey": config.kistock_app_key,
            "appsecret": config.kistock_app_secret,
            "tr_id": tr_id,
            "custtype": "P",
            "Content-Type": "application/json",
        }

    @classmethod
    def circuit_status(cls) -> dict:
        return {
            "opened": cls._err_count >= cls.MAX_ERRORS,
            "error_count": cls._err_count,
            "max_errors": cls.MAX_ERRORS,
        }

    @classmethod
    def reset_circuit(cls) -> None:
        cls._err_count = 0

    @classmethod
    def _fail(cls) -> None:
        cls._err_count = min(cls.MAX_ERRORS, cls._err_count + 1)

    @classmethod
    def _success(cls) -> None:
        cls._err_count = 0

    def _record_result(self, data: dict) -> None:
        if data.get("rt_cd") == "0":
            self._success()
        else:
            self._fail()

    def _kis_error(self, data: dict, fallback: str) -> Exception:
        msg = data.get("msg1", fallback)
        if data.get("msg_cd") == "EGW02004":
            return KISConfigError(msg)
        if data.get("msg_cd") == "EGW00201":
            return KISRateLimitError(msg)
        if "CHECK_ACNO" in msg or "INVALID_CHECK_ACNO" in msg:
            return KISAccountError(msg)
        return Exception(msg)

    def _response_json(self, response: requests.Response, context: str) -> dict:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200:
            msg = data.get("msg1") or response.text
            logger.error(f"{context} HTTP {response.status_code}: {response.text}")
            if data.get("msg_cd") == "EGW02004":
                raise KISConfigError(msg)
            if data.get("msg_cd") == "EGW00201":
                raise KISRateLimitError(msg)
            if "CHECK_ACNO" in msg or "INVALID_CHECK_ACNO" in msg:
                raise KISAccountError(msg)
            response.raise_for_status()
        return data

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    def get_balance(self) -> dict:
        try:
            _kis_throttle()
            tr_id = "VTTC8434R" if config.trading_env == "demo" else "TTTC8434R"
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            cano = config.kistock_account[:8]
            acnt = config.kistock_account[8:] if len(config.kistock_account) > 8 else "01"
            params = {"CANO": cano, "ACNT_PRDT_CD": acnt, "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
            r = HTTP.get(url, headers=self._headers(tr_id), params=params, timeout=15)
            data = self._response_json(r, "Balance")
            if data.get("rt_cd") != "0":
                raise self._kis_error(data, "unknown KIS balance error")
            self._success()
            return data
        except Exception:
            self._fail()
            raise

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_quote(self, symbol: str) -> dict:
        try:
            _kis_throttle()
            r = HTTP.get(f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price", headers=self._headers("FHKST01010100"), params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}, timeout=10)
            data = self._response_json(r, "Quote")
            if data.get("rt_cd") != "0":
                raise self._kis_error(data, "KIS get_quote error")
            self._success()
            output = data.get("output", {})
            return {"current": float(output.get("stck_prpr", 0)), "ask1": float(output.get("askp1", 0)), "bid1": float(output.get("bidp1", 0))}
        except Exception:
            self._fail()
            raise

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_volume_rank(self, top_n: int = 50) -> list[str]:
        try:
            _kis_throttle()
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
            params = {"FID_COND_MRK_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171", "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": "0000000000", "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "", "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""}
            r = HTTP.get(url, headers=self._headers("FHKUP03500000"), params=params, timeout=15)
            data = self._response_json(r, "Volume rank")
            self._record_result(data)
            if data.get("rt_cd") != "0":
                return []
            codes = [row.get("mksc_shrn_iscd", "").strip() for row in data.get("output", []) if row.get("mksc_shrn_iscd", "").strip()]
            return codes[:top_n]
        except Exception:
            self._fail()
            raise

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_daily(self, symbol: str, n: int = 60) -> list:
        try:
            _kis_throttle()
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y%m%d")
            mrkt_div = "E" if symbol in self.ETF_MARKET_CODES else "J"
            params = {"FID_COND_MRKT_DIV_CODE": mrkt_div, "FID_INPUT_ISCD": symbol, "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": today, "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
            r = HTTP.get(f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", headers=self._headers("FHKST03010100"), params=params, timeout=15)
            data = self._response_json(r, "Daily chart")
            self._record_result(data)
            if data.get("rt_cd") != "0":
                return []
            return data.get("output2", [])[:n]
        except Exception:
            self._fail()
            raise

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        real_orders_enabled = (not config.dry_run) and config.trading_env == "real" and config.enable_live_trading
        order_submission_enabled = (not config.dry_run) and (config.trading_env == "demo" or real_orders_enabled)
        if not order_submission_enabled:
            return {"rt_cd": "0", "msg1": "DRY_RUN"}
        _kis_throttle()
        tr_id = ("VTTC0802U" if config.trading_env == "demo" else "TTTC0802U") if order_type == "buy" else ("VTTC0801U" if config.trading_env == "demo" else "TTTC0801U")
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        body = {"CANO": config.kistock_account[:8], "ACNT_PRDT_CD": config.kistock_account[8:] if len(config.kistock_account) > 8 else "01", "PDNO": symbol, "ORD_DVSN": "01" if price == 0 else "00", "ORD_QTY": str(qty), "ORD_UNPR": str(price)}
        try:
            r = HTTP.post(url, headers=self._headers(tr_id), json=body, timeout=15)
            data = self._response_json(r, "Order")
            self._record_result(data)
            return data
        except Exception:
            self._fail()
            raise

    @retry(
        retry=retry_if_not_exception_type(NON_RETRYABLE_KIS_ERRORS),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_trade_history(self, start_date: str, end_date: str) -> list:
        try:
            _kis_throttle()
            tr_id = "VTTC8001R" if config.trading_env == "demo" else "TTTC8001R"
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
            cano = config.kistock_account[:8]
            acnt = config.kistock_account[8:] if len(config.kistock_account) > 8 else "01"
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt,
                "INQR_STRT_DT": start_date,
                "INQR_END_DT": end_date,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "01",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            r = HTTP.get(url, headers=self._headers(tr_id), params=params, timeout=15)
            data = self._response_json(r, "Trade history")
            if data.get("rt_cd") != "0":
                raise self._kis_error(data, "unknown KIS trade history error")
            self._success()
            return data.get("output1", [])
        except Exception:
            self._fail()
            raise
