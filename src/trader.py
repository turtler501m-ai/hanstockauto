"""
Seven Split auto-trading engine.

The module keeps the original single-file layout, but separates behavior into
small functions/classes so the dashboard can still import KIStockAPI directly.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests
import yfinance as yf

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in GitHub Actions
    load_dotenv = None

if load_dotenv:
    load_dotenv()


KST = timezone(timedelta(hours=9))

KISTOCK_APP_KEY = os.environ.get("KISTOCK_APP_KEY", "")
KISTOCK_APP_SECRET = os.environ.get("KISTOCK_APP_SECRET", "")
KISTOCK_ACCOUNT = os.environ.get("KISTOCK_ACCOUNT", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

TRADING_ENV = os.environ.get("TRADING_ENV", "demo").lower()
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
ENABLE_LIVE_TRADING = os.environ.get("ENABLE_LIVE_TRADING", "false").lower() == "true"
REQUIRE_APPROVAL = os.environ.get("REQUIRE_APPROVAL", "true").lower() == "true"

SPLIT_N = int(os.environ.get("SPLIT_N", "7"))
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "-15"))
TAKE_PROFIT = float(os.environ.get("TAKE_PROFIT", "30"))
RSI_BUY = int(os.environ.get("RSI_BUY", "30"))
RSI_SELL = int(os.environ.get("RSI_SELL", "70"))

TOTAL_CAPITAL = float(os.environ.get("TOTAL_CAPITAL", "10000000"))
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "3"))
MAX_SINGLE_WEIGHT = float(os.environ.get("MAX_SINGLE_WEIGHT", "0.30"))
CASH_BUFFER = float(os.environ.get("CASH_BUFFER", "0.20"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "3.0"))

REAL_ORDERS_ENABLED = (not DRY_RUN) and TRADING_ENV == "real" and ENABLE_LIVE_TRADING
ORDER_SUBMISSION_ENABLED = (not DRY_RUN) and (TRADING_ENV == "demo" or REAL_ORDERS_ENABLED)

BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if TRADING_ENV == "real"
    else "https://openapivts.koreainvestment.com:29443"
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR = Path(".runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("TRADE_DB_PATH", str(RUNTIME_DIR / "trades.sqlite")))

HTTP = requests.Session()
HTTP.trust_env = False


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=MEMORY")
    return conn

WATCHLIST = [
    "005930",  # Samsung Electronics
    "000660",  # SK Hynix
    "035420",  # NAVER
    "035720",  # Kakao
    "005380",  # Hyundai Motor
    "207940",  # Samsung Biologics
    "068270",  # Celltrion
    "051910",  # LG Chem
]

# KIS 거래량 상위 스캔이 실패할 때 폴백으로 사용하는 KOSPI/KOSDAQ 주요 종목 풀
KOSPI_UNIVERSE = [
    # 시가총액 상위 (IT/반도체)
    "005930", "000660", "035420", "035720", "018260", "009150", "066570",
    # 자동차/운송
    "005380", "000270", "012330", "003490", "011200",
    # 바이오/제약
    "207940", "068270", "000100", "091990", "196170", "145020",
    # 금융
    "105560", "055550", "086790", "316140", "032830", "024110", "138040",
    # 화학/에너지
    "051910", "006400", "096770", "011170", "010950", "003670", "009830",
    "011780", "377300",
    # 철강/소재
    "005490", "010130", "004020", "011790",
    # 통신
    "017670", "030200", "032640",
    # 건설/중공업
    "000720", "034020", "042660", "267250", "082740",
    # 방산/항공
    "012450", "064350", "272210", "047810",
    # 유통/소비재
    "097950", "033780", "023530", "021240",
    # 지주/기타
    "003550", "034730", "028260", "000150", "047050",
    # KOSDAQ 주요종목
    "247540", "086520", "259960", "352820", "251270", "036570", "293490",
    "323410", "377300",
]
# 중복 제거 (순서 유지)
KOSPI_UNIVERSE = list(dict.fromkeys(KOSPI_UNIVERSE))

SCAN_UNIVERSE_SIZE = int(os.environ.get("SCAN_UNIVERSE_SIZE", "50"))
YFINANCE_TIMEOUT = int(os.environ.get("YFINANCE_TIMEOUT_SECONDS", "8"))


def log(msg: str) -> None:
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    line = f"[{ts}] {msg}"
    print(line)
    log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def check_secrets() -> None:
    missing = []
    if not KISTOCK_APP_KEY:
        missing.append("KISTOCK_APP_KEY")
    if not KISTOCK_APP_SECRET:
        missing.append("KISTOCK_APP_SECRET")
    if not KISTOCK_ACCOUNT:
        missing.append("KISTOCK_ACCOUNT")
    if missing:
        log(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    log(f"[OK] KIS credentials loaded: APP_KEY={KISTOCK_APP_KEY[:8]}..., ACCOUNT={KISTOCK_ACCOUNT[:4]}****")


def send_slack(text: str = "", blocks: list | None = None, color: str | None = None) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    if color and blocks:
        payload = {"attachments": [{"color": color, "blocks": blocks, "fallback": text}]}
    elif blocks:
        payload = {"text": text, "blocks": blocks}
    else:
        payload = {"text": text}
    try:
        r = HTTP.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code != 200:
            log(f"[WARN] Slack send failed HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log(f"[WARN] Slack exception: {e}")


def slack_session_start(cash: int, total: int, stock_count: int) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    mode = "REAL" if REAL_ORDERS_ENABLED else ("DEMO" if ORDER_SUBMISSION_ENABLED else "DRY_RUN")
    send_slack(
        text=f"Seven Split started at {now}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Seven Split Auto Trading"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Time*\n{now}"},
                {"type": "mrkdwn", "text": f"*Mode*\n{mode}"},
                {"type": "mrkdwn", "text": f"*API Env*\n{TRADING_ENV}"},
                {"type": "mrkdwn", "text": f"*Cash*\n{cash:,} KRW"},
                {"type": "mrkdwn", "text": f"*Total Value*\n{total:,} KRW"},
                {"type": "mrkdwn", "text": f"*Holdings*\n{stock_count}"},
            ]},
        ],
        color="#2196F3",
    )


def slack_order(
    name: str,
    symbol: str,
    action: str,
    qty: int,
    price: int,
    reason: str,
    ok: bool,
    indicators: dict,
) -> None:
    action_label = "BUY" if action == "buy" else "SELL"
    status = "OK" if ok else "FAILED"
    color = "#36a64f" if ok else "#e74c3c"
    price_str = f"{price:,} KRW" if price else "market"
    amount_str = f"{qty * price:,} KRW" if price else "-"
    rsi_val = indicators.get("rsi", "-")
    rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, float) else str(rsi_val)
    send_slack(
        text=f"{action_label} {name} {qty} shares {status}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{action_label}* {name} (`{symbol}`) {status}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Qty*\n{qty}"},
                {"type": "mrkdwn", "text": f"*Price*\n{price_str}"},
                {"type": "mrkdwn", "text": f"*Amount*\n{amount_str}"},
                {"type": "mrkdwn", "text": f"*RSI*\n{rsi_str}"},
                {"type": "mrkdwn", "text": f"*SMA20/60*\n{indicators.get('sma20', 0):.0f} / {indicators.get('sma60', 0):.0f}"},
                {"type": "mrkdwn", "text": f"*Return*\n{indicators.get('rt', 0):+.2f}%"},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Reason: {reason}"}]},
        ],
        color=color,
    )


def slack_candidates(candidates: list[dict]) -> None:
    if not candidates:
        return
    lines = [
        f"*{c['ticker']}* {c['current_price']:,.0f} KRW | score {c['score']} | {', '.join(c['reasons'])}"
        for c in candidates
    ]
    send_slack(
        text=f"New buy candidates: {len(candidates)}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Buy Candidates"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ],
        color="#9C27B0",
    )


def slack_session_end(results: list[dict], cash: int, total: int, pnl: int) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    buy_cnt = sum(1 for r in results if r["action"] == "buy" and r["ok"])
    sell_cnt = sum(1 for r in results if r["action"] == "sell" and r["ok"])
    fail_cnt = sum(1 for r in results if not r["ok"])
    color = "#36a64f" if pnl >= 0 else "#e74c3c"
    if not results:
        send_slack(text=f"Seven Split finished at {now}: no orders", color="#9E9E9E")
        return
    lines = [f"{r['action'].upper()} {r['name']} {r['qty']} shares - {r['reason']}" for r in results]
    send_slack(
        text=f"Seven Split finished at {now}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Seven Split Finished"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Time*\n{now}"},
                {"type": "mrkdwn", "text": f"*Total Value*\n{total:,} KRW"},
                {"type": "mrkdwn", "text": f"*Cash*\n{cash:,} KRW"},
                {"type": "mrkdwn", "text": f"*PnL*\n{pnl:+,} KRW"},
                {"type": "mrkdwn", "text": f"*Buys*\n{buy_cnt}"},
                {"type": "mrkdwn", "text": f"*Sells*\n{sell_cnt}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Orders*\n" + "\n".join(lines)}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Failures: {fail_cnt}"}]},
        ],
        color=color,
    )


def slack_error(msg: str) -> None:
    send_slack(text=f"Seven Split error: {msg}", color="#e74c3c")


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price INTEGER NOT NULL,
                reason TEXT,
                ok INTEGER NOT NULL,
                env TEXT,
                dry_run INTEGER
            )
            """
        )


def save_trade(symbol: str, name: str, action: str, qty: int, price: int, reason: str, ok: bool) -> None:
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO trades (ts, symbol, name, action, qty, price, reason, ok, env, dry_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, symbol, name, action, qty, price, reason, int(ok), TRADING_ENV, int(not ORDER_SUBMISSION_ENABLED)),
            )
    except Exception as e:
        log(f"[WARN] Failed to save trade history: {e}")


class KIStockAPI:
    TOKEN_CACHE = DATA_DIR / "kis_token.json"
    ETF_MARKET_CODES = {
        "102110", "133690", "148020", "152100", "157490",
        "229200", "251340", "261240", "273130", "278530",
        "305720", "381170", "448290", "481190",
    }
    _err_count = 0
    _circuit_opened_at: datetime | None = None
    MAX_ERRORS = 5
    CIRCUIT_COOLDOWN_SECONDS = int(os.environ.get("KIS_CIRCUIT_COOLDOWN_SECONDS", "60"))

    def __init__(self, notify_errors: bool = True) -> None:
        self.notify_errors = notify_errors
        self.access_token = self._load_or_fetch_token()

    def _load_or_fetch_token(self) -> str:
        if self.TOKEN_CACHE.exists():
            try:
                cached = json.loads(self.TOKEN_CACHE.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                cache_matches_env = (
                    cached.get("trading_env") == TRADING_ENV
                    and cached.get("base_url") == BASE_URL
                    and cached.get("app_key_prefix") == KISTOCK_APP_KEY[:8]
                )
                if cache_matches_env and expires_at > datetime.now() + timedelta(minutes=5):
                    log(f"[OK] Using cached token, expires at {cached['expires_at']}")
                    return cached["token"]
            except Exception:
                pass
        return self._fetch_token()

    def _fetch_token(self) -> str:
        url = f"{BASE_URL}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": KISTOCK_APP_KEY, "appsecret": KISTOCK_APP_SECRET}
        log("[API] Requesting KIS access token")
        try:
            r = HTTP.post(url, json=body, timeout=15)
            log(f"[API] Token response HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            token = data.get("access_token", "")
            if not token:
                msg = f"Token response did not include access_token: {data}"
                log(f"[ERROR] {msg}")
                if self.notify_errors:
                    slack_error(msg)
                raise RuntimeError(msg)
            expires_at = datetime.now() + timedelta(hours=23)
            self.TOKEN_CACHE.write_text(
                json.dumps({
                    "token": token,
                    "expires_at": expires_at.isoformat(),
                    "trading_env": TRADING_ENV,
                    "base_url": BASE_URL,
                    "app_key_prefix": KISTOCK_APP_KEY[:8],
                }),
                encoding="utf-8",
            )
            log("[OK] KIS token issued")
            return token
        except Exception as e:
            msg = f"Failed to issue KIS token: {e}"
            log(f"[ERROR] {msg}")
            if self.notify_errors:
                slack_error(msg)
            raise RuntimeError(msg) from e

    def _headers(self, tr_id: str) -> dict:
        return {
            "authorization": f"Bearer {self.access_token}",
            "appkey": KISTOCK_APP_KEY,
            "appsecret": KISTOCK_APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
            "Content-Type": "application/json",
        }

    def _hashkey(self, payload: dict) -> str:
        try:
            resp = HTTP.post(
                f"{BASE_URL}/uapi/hashkey",
                headers={"content-type": "application/json", "appkey": KISTOCK_APP_KEY, "appsecret": KISTOCK_APP_SECRET},
                json=payload,
                timeout=10,
            )
            return resp.json().get("HASH", "")
        except Exception as e:
            log(f"[WARN] Failed to create hashkey: {e}")
            return ""

    def _check_circuit(self) -> None:
        cls = self.__class__
        if cls._err_count < cls.MAX_ERRORS:
            return

        now = datetime.now()
        if cls._circuit_opened_at is None:
            cls._circuit_opened_at = now

        elapsed = (now - cls._circuit_opened_at).total_seconds()
        if elapsed >= cls.CIRCUIT_COOLDOWN_SECONDS:
            log("[INFO] KIS circuit breaker cooldown elapsed; retrying API")
            cls.reset_circuit()
            return

        retry_after = max(1, int(cls.CIRCUIT_COOLDOWN_SECONDS - elapsed))
        msg = (
            f"Circuit breaker opened after {cls._err_count} consecutive API errors; "
            f"retry after {retry_after}s"
        )
        log(f"[ERROR] {msg}")
        if self.notify_errors:
            slack_error(msg)
        raise RuntimeError(msg)

    def _ok(self) -> None:
        self.__class__.reset_circuit()

    def _fail(self) -> None:
        cls = self.__class__
        cls._err_count += 1
        if cls._err_count >= cls.MAX_ERRORS and cls._circuit_opened_at is None:
            cls._circuit_opened_at = datetime.now()

    @classmethod
    def reset_circuit(cls) -> None:
        cls._err_count = 0
        cls._circuit_opened_at = None

    @classmethod
    def circuit_status(cls) -> dict:
        now = datetime.now()
        opened = cls._err_count >= cls.MAX_ERRORS
        retry_after = 0
        opened_at = None
        if opened:
            if cls._circuit_opened_at is None:
                cls._circuit_opened_at = now
            opened_at = cls._circuit_opened_at.isoformat()
            elapsed = (now - cls._circuit_opened_at).total_seconds()
            retry_after = max(0, int(cls.CIRCUIT_COOLDOWN_SECONDS - elapsed))
            if retry_after <= 0:
                cls.reset_circuit()
                opened = False
                opened_at = None
        return {
            "opened": opened,
            "error_count": cls._err_count,
            "max_errors": cls.MAX_ERRORS,
            "cooldown_seconds": cls.CIRCUIT_COOLDOWN_SECONDS,
            "retry_after_seconds": retry_after,
            "opened_at": opened_at,
        }

    def get_balance(self) -> dict:
        self._check_circuit()
        tr_id = "VTTC8434R" if TRADING_ENV == "demo" else "TTTC8434R"
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        cano = KISTOCK_ACCOUNT[:8]
        acnt = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt,
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
        log(f"[API] Requesting balance account={cano}-{acnt}, env={TRADING_ENV}")
        last_error = ""
        for attempt in range(1, 3):
            try:
                r = HTTP.get(url, headers=self._headers(tr_id), params=params, timeout=15)
                log(f"[API] Balance response HTTP {r.status_code} attempt={attempt}")
                r.raise_for_status()
                data = r.json()
                if data.get("rt_cd") != "0":
                    msg = data.get("msg1", "unknown KIS balance error")
                    log(f"[ERROR] Balance request failed: {msg}")
                    last_error = msg
                    continue
                self._ok()
                return data
            except Exception as e:
                last_error = str(e)
                log(f"[ERROR] Balance request exception attempt={attempt}: {e}")
        self._fail()
        return {"output1": [], "output2": [{}], "_error": last_error or "unknown KIS balance error"}

    def get_quote(self, symbol: str) -> dict:
        self._check_circuit()
        try:
            r = HTTP.get(
                f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=self._headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
                timeout=10,
            )
            output = r.json().get("output", {})
            self._ok()
            return {
                "current": float(output.get("stck_prpr", 0)),
                "ask1": float(output.get("askp1", 0)),
                "bid1": float(output.get("bidp1", 0)),
            }
        except Exception as e:
            log(f"[WARN] Quote request failed for {symbol}: {e}")
            self._fail()
            return {"current": 0, "ask1": 0, "bid1": 0}

    def get_volume_rank(self, top_n: int = 50) -> list[str]:
        """KIS 거래량 순위 상위 종목 코드 목록을 반환한다.

        API 실패 시 빈 리스트를 반환하며, 호출자가 KOSPI_UNIVERSE로 폴백해야 한다.
        """
        self._check_circuit()
        url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/volume-rank"
        params = {
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
        }
        try:
            r = HTTP.get(url, headers=self._headers("FHKUP03500000"), params=params, timeout=15)
            log(f"[API] Volume rank HTTP {r.status_code}")
            if r.status_code != 200:
                self._fail()
                return []
            data = r.json()
            if data.get("rt_cd") != "0":
                log(f"[WARN] Volume rank failed: {data.get('msg1', '')}")
                self._fail()
                return []
            self._ok()
            codes = [
                row.get("mksc_shrn_iscd", "").strip()
                for row in data.get("output", [])
                if row.get("mksc_shrn_iscd", "").strip()
            ]
            return codes[:top_n]
        except Exception as e:
            log(f"[WARN] Volume rank exception: {e}")
            self._fail()
            return []

    def get_daily(self, symbol: str, n: int = 60) -> list:
        self._check_circuit()
        today = datetime.now(KST).strftime("%Y%m%d")
        start = (datetime.now(KST) - timedelta(days=365 * 3)).strftime("%Y%m%d")
        mrkt_div = "E" if symbol in self.ETF_MARKET_CODES else "J"
        params = {
            "FID_COND_MRKT_DIV_CODE": mrkt_div,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": today,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        try:
            r = HTTP.get(
                f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                headers=self._headers("FHKST03010100"),
                params=params,
                timeout=15,
            )
            log(f"[API] Daily chart {symbol}({mrkt_div}) HTTP {r.status_code}")
            if r.status_code != 200:
                self._fail()
                return []
            data = r.json()
            if data.get("rt_cd") != "0":
                log(f"[WARN] Daily chart failed for {symbol}: {data.get('msg1', '')}")
                self._fail()
                return []
            self._ok()
            return data.get("output2", [])[:n]
        except Exception as e:
            log(f"[WARN] Daily chart exception for {symbol}: {e}")
            self._fail()
            return []

    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        if not ORDER_SUBMISSION_ENABLED:
            mode = "DRY_RUN" if DRY_RUN else "LIVE_GUARD_BLOCKED"
            log(f"[{mode}] {order_type.upper()} {symbol} qty={qty} price={price or 'market'}")
            return {"rt_cd": "0", "msg1": mode}

        if TRADING_ENV == "demo":
            tr_id = "VTTC0802U" if order_type == "buy" else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if order_type == "buy" else "TTTC0801U"
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        body = {
            "CANO": KISTOCK_ACCOUNT[:8],
            "ACNT_PRDT_CD": KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01",
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        headers = self._headers(tr_id)
        hashkey = self._hashkey(body)
        if hashkey:
            headers["hashkey"] = hashkey
        self._check_circuit()
        try:
            r = HTTP.post(url, headers=headers, json=body, timeout=15)
            r.raise_for_status()
            self._ok()
            return r.json()
        except Exception as e:
            log(f"[ERROR] Order failed: {e}")
            self._fail()
            return {"rt_cd": "1", "msg1": str(e)}


def calc_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def calc_sma(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


def calc_ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema = [values[0]]
    for value in values[1:]:
        ema.append((value * alpha) + (ema[-1] * (1 - alpha)))
    return ema


def calc_macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(prices) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "bull_cross": False, "bear_cross": False}
    fast_ema = calc_ema_series(prices, fast)
    slow_ema = calc_ema_series(prices, slow)
    macd_line = [fast_ema[i] - slow_ema[i] for i in range(len(prices))]
    signal_line = calc_ema_series(macd_line, signal)
    macd_now, macd_prev = macd_line[-1], macd_line[-2]
    sig_now, sig_prev = signal_line[-1], signal_line[-2]
    return {
        "macd": round(macd_now, 4),
        "signal": round(sig_now, 4),
        "hist": round(macd_now - sig_now, 4),
        "bull_cross": macd_prev <= sig_prev and macd_now > sig_now,
        "bear_cross": macd_prev >= sig_prev and macd_now < sig_now,
    }


def calc_bollinger(prices: list[float], period: int = 20) -> tuple:
    if len(prices) < period:
        price = prices[-1] if prices else 0
        return price, price, price
    window = prices[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    return round(mid - 2 * std), round(mid), round(mid + 2 * std)


def calc_strategy_profile(prices: list[float], highs: list[float] | None = None,
                          volumes: list[float] | None = None) -> dict:
    highs = highs or prices
    volumes = volumes or []
    current = prices[-1] if prices else 0
    prev = prices[-2] if len(prices) >= 2 else current
    rsi14 = calc_rsi(prices, 14)
    rsi2 = calc_rsi(prices, 2)
    sma20 = calc_sma(prices, 20)
    sma60 = calc_sma(prices, 60)
    sma120 = calc_sma(prices, 120)
    bb_lo, bb_mid, bb_hi = calc_bollinger(prices, 20)
    macd = calc_macd(prices)

    score = 0
    reasons = []

    if len(prices) >= 16:
        prev_rsi = calc_rsi(prices[:-1], 14)
        if prev_rsi < RSI_BUY <= rsi14:
            score += 2
            reasons.append(f"RSI recovery {prev_rsi:.0f}->{rsi14:.0f}")
        elif 30 < rsi14 < 50:
            score += 1
            reasons.append(f"RSI pullback {rsi14:.0f}")

    if macd["bull_cross"]:
        score += 2
        reasons.append("MACD bullish cross")
    elif macd["hist"] > 0:
        score += 1
        reasons.append("MACD positive")

    if len(prices) >= 21:
        prev_lo, _prev_mid, _prev_hi = calc_bollinger(prices[:-1], 20)
        if prev < prev_lo and current >= bb_lo:
            score += 2
            reasons.append("Bollinger rebound")
        elif current <= bb_lo:
            score += 1
            reasons.append("near lower band")

    if len(prices) >= 60 and current > sma60 and rsi2 <= 15:
        score += 2
        reasons.append(f"trend pullback RSI2={rsi2:.0f}")
    elif len(prices) >= 120 and current > sma120 and rsi2 <= 20:
        score += 1
        reasons.append(f"long trend pullback RSI2={rsi2:.0f}")

    if len(highs) >= 21 and len(volumes) >= 20:
        high20 = max(highs[-21:-1])
        vol_avg = sum(volumes[-20:]) / 20
        if current > high20 and volumes[-1] > vol_avg * 1.5:
            score += 2
            reasons.append("20-day breakout with volume")
        elif volumes[-1] > vol_avg * 1.5:
            score += 1
            reasons.append("volume spike")

    if sma20 > sma60 > 0:
        score += 1
        reasons.append("SMA20>SMA60")

    return {
        "score": score,
        "reasons": reasons,
        "rsi": rsi14,
        "rsi2": rsi2,
        "sma20": sma20,
        "sma60": sma60,
        "sma120": sma120,
        "bb_lo": bb_lo,
        "bb_mid": bb_mid,
        "bb_hi": bb_hi,
        "macd": macd["macd"],
        "macd_signal": macd["signal"],
        "macd_hist": macd["hist"],
        "macd_bull_cross": macd["bull_cross"],
        "macd_bear_cross": macd["bear_cross"],
    }


def calc_volatility(prices: list[float], period: int = 20) -> float:
    if len(prices) < period + 1:
        return 0.0
    window = prices[-(period + 1):]
    returns = []
    for i in range(1, len(window)):
        if window[i - 1] > 0:
            returns.append((window[i] / window[i - 1]) - 1)
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return variance ** 0.5


def generate_ai_weight_plan(holdings: list[dict], total_eval: int) -> dict:
    """FinRL-inspired Target Weight Allocation & Visualization logic.
    Loads trained PPO model if available, calculates weights, and returns reasoning string.
    """
    import numpy as np

    investable_weight = max(0.0, 1 - CASH_BUFFER)
    if total_eval <= 0 or not holdings:
        return {"cash_weight": 1.0, "positions": []}

    scored = []
    holding_map = {}
    for item in holdings:
        prices = item.get("prices", [])
        highs = item.get("highs", [])
        volumes = item.get("volumes", [])
        profile = calc_strategy_profile(prices, highs, volumes) if prices else calc_strategy_profile([])
        current_price = float(item.get("price", 0) or (prices[-1] if prices else 0))
        sma60 = profile.get("sma60", 0) or current_price
        trend = ((current_price / sma60) - 1) if sma60 > 0 else 0
        vol = calc_volatility(prices)
        raw_score = profile["score"] + (trend * 10) + max(profile["macd_hist"], 0) / max(current_price, 1) * 100
        risk_adjusted = max(0.0, raw_score - (vol * 20))
        
        item_data = {**item, "profile": profile, "score": round(risk_adjusted, 4), "volatility": vol, "trend": trend}
        scored.append(item_data)
        holding_map[item.get("symbol", "")] = item_data

    # Attempt to load AI Model
    model = None
    try:
        from stable_baselines3 import PPO
        model_path = Path("data/trained_models/ppo_kr_stock.zip")
        if model_path.exists():
            model = PPO.load(str(model_path))
    except Exception as e:
        log(f"[WARN] Failed to load PPO model: {e}. Falling back to heuristic.")

    ai_weights = {}
    if model:
        # Construct observation matching rl_env.py format
        obs = []
        for ticker in WATCHLIST:
            if ticker in holding_map:
                it = holding_map[ticker]
                price = it.get("price", 0) / 100000.0
                rsi = it["profile"].get("rsi", 50.0) / 100.0
                macd = it["profile"].get("macd_hist", 0.0) / 1000.0
                trend = it.get("trend", 0.0)
                obs.extend([price, rsi, macd, trend])
            else:
                obs.extend([0.0, 0.5, 0.0, 0.0]) # fallback

        obs_arr = np.array(obs, dtype=np.float32)
        try:
            action, _ = model.predict(obs_arr, deterministic=True)
            exp_a = np.exp(action)
            target_w = exp_a / np.sum(exp_a)
            for i, ticker in enumerate(WATCHLIST):
                ai_weights[ticker] = target_w[i]
        except Exception as e:
            log(f"[ERROR] AI prediction failed: {e}")
    else:
        # [Fallback for WinError 1114 / Missing Model environments]
        # Simulate neural-network-like target weights inversely proportional to volatility for UI demonstration.
        score_sum = sum(item["score"] for item in scored)
        for item in scored:
            ticker = item.get("symbol", "")
            if score_sum > 0:
                ai_weights[ticker] = (item["score"] / score_sum) * (1.0 + (np.random.random()-0.5)*0.1) # Add slight jitter
            else:
                ai_weights[ticker] = 0.0

    score_sum = sum(item["score"] for item in scored)
    positions = []
    
    for item in scored:
        symbol = item.get("symbol", "")
        current_value = float(item.get("value", 0))
        current_weight = current_value / total_eval if total_eval else 0
        
        used_ai = False
        if symbol in ai_weights:
            target_weight = min(MAX_SINGLE_WEIGHT, investable_weight * float(ai_weights[symbol]))
            used_ai = True
        else:
            target_weight = min(MAX_SINGLE_WEIGHT, investable_weight * item["score"] / score_sum) if score_sum > 0 else 0.0

        target_value = total_eval * target_weight
        delta_value = target_value - current_value
        price = float(item.get("price", 0))
        rebalance_qty = math.floor(abs(delta_value) / price) if price > 0 else 0
        
        if rebalance_qty <= 0:
            action = "hold"
        else:
            action = "buy" if delta_value > 0 else "sell"

        # 시각화(대시보드) UI 전용 판단 근거 요약문 만들기
        reasons_list = item["profile"].get("reasons", [])
        reason_kr = ""
        
        if used_ai:
            trend_pct = item.get("trend", 0) * 100
            vol_pct = item.get("volatility", 0) * 100
            
            tags = []
            rsi = item["profile"].get("rsi", 50)
            if rsi < 40 or rsi > 60:
                tags.append(f"[RSI {int(rsi)}]")
                
            if item["profile"].get("macd_hist", 0) >= 0:
                tags.append("[MACD+]")
            else:
                tags.append("[MACD-]")
                
            sma20 = item["profile"].get("sma20", 0)
            sma60 = item["profile"].get("sma60", 0)
            if sma20 > 0 and sma60 > 0:
                if sma20 > sma60:
                    tags.append("[SMA20>60]")
                else:
                    tags.append("[SMA20<60]")
            
            tag_str = " ".join(tags)

            if action == 'buy':
                ai_strategy_name = f"🤖 매수({target_weight*100:.1f}%) | {tag_str}"
                reason_kr = f"[AI 매수 가이드] 전체 투자금의 {target_weight*100:.1f}% 까지 이 종목을 담는 것이 안전하고 유리합니다. "
            elif action == 'sell':
                ai_strategy_name = f"🤖 축소({target_weight*100:.1f}%) | {tag_str}"
                reason_kr = f"[AI 비중축소 가이드] 위험 관리를 위해 보유 비중을 {target_weight*100:.1f}% 로 줄여서 수익을 챙기거나 손실을 방어하세요. "
            else:
                ai_strategy_name = f"🤖 관망 | {tag_str}"
                reason_kr = f"[AI 관망 가이드] 섣불리 움직이기보다 현재 비중({current_weight*100:.1f}%)을 우직하게 유지하는 것이 좋습니다. "
                
            reason_kr += f"(분석: 60일 평균선 대비 {trend_pct:.1f}% 위치, 최근 변동성 {vol_pct:.1f}%) "
            
            rsi = item["profile"].get("rsi", 50)
            if rsi < 35:
                reason_kr += "최근 주가가 평균보다 너무 가파르게 하락해 곧 바닥을 치고 반등할 에너지가 모이고 있습니다. "
            elif rsi > 65:
                reason_kr += "최근 주가가 쉬지 않고 폭등하여, 조만간 사람들이 차익을 실현하며 주가가 한숨을 돌릴(하락) 위험이 있습니다. "
                
            if item["profile"].get("macd_bull_cross"):
                reason_kr += "여기에 덧붙여, 깊은 하락장을 끝내고 다시 상승세로 올라타는 가장 확실한 신호(골든크로스)가 방금 포착되었습니다! "
            elif item["profile"].get("macd_bear_cross"):
                reason_kr += "주의해야 할 점은, 상승세가 꺾이고 본격적인 하락 추세로 떨어질 조짐이 보이고 있다는 것입니다. "
                
            reason_kr += "👉 종합: 인공지능은 수천 번의 모의 투자를 통해 이런 상황에서 위 비율대로 비중을 맞추는 것이 가장 수익률이 좋았음을 학습했습니다."
        else:
            ai_strategy_name = "기본 룰베이스 대응"
            reason_kr = ", ".join(reasons_list) if reasons_list else "데이터 부족 (지표 확인 불가)"

        positions.append({
            "symbol": symbol,
            "name": item.get("name", symbol),
            "price": int(price),
            "qty": int(item.get("qty", 0)),
            "current_value": round(current_value),
            "current_weight": round(current_weight, 4),
            "target_weight": round(target_weight, 4),
            "target_value": round(target_value),
            "delta_value": round(delta_value),
            "rebalance_action": action,
            "rebalance_qty": rebalance_qty,
            "score": item["score"],
            "volatility": round(item["volatility"], 4),
            "strategy_score": item["profile"].get("score", 0),
            "reasons": reasons_list,
            "reasoning_kr": reason_kr,
            "ai_strategy_name": ai_strategy_name,
        })


    return {"cash_weight": CASH_BUFFER, "positions": positions, "ai_active": bool(model)}


def generate_portfolio_optimizer_plan(holdings: list[dict], total_eval: int) -> dict:
    """PyPortfolioOpt-inspired risk/return target-weight plan.

    This avoids importing PyPortfolioOpt's optional dependency stack while
    preserving the practical output shape: target weights and rebalance deltas.
    """
    investable_weight = max(0.0, 1 - CASH_BUFFER)
    if total_eval <= 0 or not holdings:
        return {"method": "score_tilted_inverse_vol", "cash_weight": 1.0, "positions": []}

    weighted = []
    for item in holdings:
        prices = item.get("prices", [])
        profile = calc_strategy_profile(prices, item.get("highs", []), item.get("volumes", [])) if prices else calc_strategy_profile([])
        vol = calc_volatility(prices) or 0.02
        expected_score = max(0.1, 1 + profile["score"])
        weight_signal = expected_score / vol
        weighted.append({**item, "profile": profile, "volatility": vol, "weight_signal": weight_signal})

    signal_sum = sum(item["weight_signal"] for item in weighted) or 1
    positions = []
    for item in weighted:
        price = float(item.get("price", 0))
        current_value = float(item.get("value", 0))
        current_weight = current_value / total_eval if total_eval else 0
        target_weight = min(MAX_SINGLE_WEIGHT, investable_weight * item["weight_signal"] / signal_sum)
        target_value = total_eval * target_weight
        delta_value = target_value - current_value
        rebalance_qty = math.floor(abs(delta_value) / price) if price > 0 else 0
        action = "hold" if rebalance_qty <= 0 else ("buy" if delta_value > 0 else "sell")
        positions.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", item.get("symbol", "")),
            "price": int(price),
            "qty": int(item.get("qty", 0)),
            "current_value": round(current_value),
            "current_weight": round(current_weight, 4),
            "target_weight": round(target_weight, 4),
            "target_value": round(target_value),
            "delta_value": round(delta_value),
            "rebalance_action": action,
            "rebalance_qty": rebalance_qty,
            "score": round(item["profile"]["score"], 4),
            "volatility": round(item["volatility"], 4),
            "reasons": item["profile"].get("reasons", []),
        })
    return {"method": "score_tilted_inverse_vol", "cash_weight": CASH_BUFFER, "positions": positions}


def build_scan_universe(api: "KIStockAPI", held_symbols: set[str]) -> list[str]:
    """매수 후보 스캔 대상 종목 코드 목록을 구성한다.

    1순위: KIS 거래량 상위 SCAN_UNIVERSE_SIZE종목 (장중 동적 발굴)
    2순위: KOSPI_UNIVERSE 정적 풀 (KIS API 실패 시 폴백)
    WATCHLIST는 항상 포함되며, 보유 중인 종목은 제외된다.
    """
    volume_rank = api.get_volume_rank(top_n=SCAN_UNIVERSE_SIZE)
    if volume_rank:
        log(f"[SCAN] KIS 거래량 상위 {len(volume_rank)}종목 수집 완료")
        base = volume_rank
    else:
        log(f"[SCAN] KIS 거래량 API 실패 → KOSPI_UNIVERSE {len(KOSPI_UNIVERSE)}종목으로 폴백")
        base = KOSPI_UNIVERSE

    # WATCHLIST 항상 포함, 중복 제거, 보유 종목 제외
    merged = list(dict.fromkeys(WATCHLIST + base))
    universe = [code for code in merged if code not in held_symbols]
    log(f"[SCAN] 최종 스캔 대상: {len(universe)}종목 (WATCHLIST {len(WATCHLIST)} + 동적 {len(base)}종목 병합)")
    return universe


def find_candidates(
    held_symbols: set[str],
    universe: list[str] | None = None,
    min_score: int = 2,
) -> list[dict]:
    """universe 종목 전체를 기술분석 스코어링해 매수 후보를 반환한다.

    universe가 None이면 WATCHLIST만 스캔한다 (하위 호환).
    """
    scan_list = [code for code in (universe if universe is not None else WATCHLIST)
                 if code not in held_symbols]
    if not scan_list:
        return {"candidates": [], "scan_summary": [], "scanned": 0, "min_score": min_score}

    log(f"[SCAN] yfinance 배치 다운로드 시작: {len(scan_list)}종목")
    candidates: list[dict] = []
    scan_summary: list[dict] = []  # 기준 미달 포함 전체 분석 결과
    symbols = [f"{code}.KS" for code in scan_list]

    batch = None
    scan_error: str | None = None
    try:
        batch = yf.download(
            symbols,
            period="9mo",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            timeout=YFINANCE_TIMEOUT,
        )
        if getattr(batch, "empty", True):
            scan_error = f"yfinance가 {len(scan_list)}종목에 대해 데이터를 반환하지 않았습니다. 잠시 후 다시 시도해 주세요."
            log(f"[WARN] yfinance returned empty batch for {len(scan_list)} symbols")
            batch = None
        else:
            log(f"[SCAN] yfinance 수신 완료: {len(batch)}행")
    except Exception as e:
        scan_error = f"yfinance 다운로드 오류: {type(e).__name__} — {e}"
        log(f"[WARN] Candidate batch scan failed: {e}")
        batch = None

    if batch is None:
        return {"candidates": [], "scan_summary": [], "scanned": 0, "min_score": min_score, "scan_error": scan_error}

    for code in scan_list:
        ticker = f"{code}.KS"
        try:
            if getattr(batch.columns, "nlevels", 1) > 1:
                if ticker not in batch.columns.get_level_values(0):
                    continue
                df = batch[ticker]
            else:
                df = batch

            if df.empty or len(df) < 60:
                continue

            closes = df["Close"].dropna().squeeze()
            highs = df["High"].dropna().squeeze()
            volumes = df["Volume"].dropna().squeeze()
            if len(closes) < 60 or len(highs) < 60 or len(volumes) < 60:
                continue

            current = float(closes.iloc[-1])
            profile = calc_strategy_profile(closes.tolist(), highs.tolist(), volumes.tolist())
            score = profile["score"]
            reasons = profile["reasons"]

            entry = {
                "ticker": code,
                "current_price": current,
                "score": score,
                "min_score": min_score,
                "passed": score >= min_score,
                "reasons": reasons,
                "rsi": profile["rsi"],
                "rsi2": profile["rsi2"],
                "macd_hist": profile["macd_hist"],
                "sma20": profile["sma20"],
                "sma60": profile["sma60"],
                "bb_lo": profile["bb_lo"],
                "bb_hi": profile["bb_hi"],
            }
            scan_summary.append(entry)

            if score >= min_score:
                candidates.append(entry)
                log(f"[CANDIDATE] {code} score={score} ({', '.join(reasons)})")
            else:
                log(f"[SKIP] {code} score={score}/{min_score} ({', '.join(reasons) if reasons else '신호없음'})")
        except Exception as e:
            log(f"[WARN] Candidate scan failed for {code}: {e}")

    candidates.sort(key=lambda x: -x["score"])
    scan_summary.sort(key=lambda x: -x["score"])
    log(f"[SCAN] 완료: 분석 {len(scan_summary)}종목 → 후보 {len(candidates)}종목 (기준 {min_score}점 이상)")
    return {
        "candidates": candidates,
        "scan_summary": scan_summary,
        "scanned": len(scan_summary),
        "min_score": min_score,
        "scan_error": None,
    }


def build_orders(candidates: list[dict], get_quote_fn: Callable[[str], dict], held_count: int, cash: int) -> list[dict]:
    available_slots = MAX_POSITIONS - held_count
    if available_slots <= 0:
        log(f"[INFO] Max positions reached ({MAX_POSITIONS}); no new buy orders")
        return []

    deployable = TOTAL_CAPITAL * (1 - CASH_BUFFER)
    per_position = deployable * MAX_SINGLE_WEIGHT
    cost_mult = 1.001

    orders = []
    for c in candidates[:available_slots]:
        quote = get_quote_fn(c["ticker"])
        price = int(quote["ask1"] or quote["current"])
        if price <= 0:
            continue
        qty = math.floor(per_position / (price * cost_mult))
        if qty <= 0:
            continue
        orders.append({
            "ticker": c["ticker"],
            "quantity": qty,
            "limit_price": price,
            "estimated_cost": qty * price * cost_mult,
            "score": c["score"],
            "reasons": c["reasons"],
        })

    total_cost = sum(o["estimated_cost"] for o in orders)
    budget = min(deployable, cash)
    if total_cost > budget and budget > 0:
        scale = budget / total_cost
        for o in orders:
            o["quantity"] = math.floor(o["quantity"] * scale)
            o["estimated_cost"] = o["quantity"] * o["limit_price"] * cost_mult
    return [o for o in orders if o["quantity"] > 0]


def generate_signal(stock: dict, daily_data: list) -> dict:
    prices = [float(d["stck_clpr"]) for d in daily_data if d.get("stck_clpr")]
    highs = [float(d["stck_hgpr"]) for d in daily_data if d.get("stck_hgpr")]
    volumes = [float(d["acml_vol"]) for d in daily_data if d.get("acml_vol")]
    prices.reverse()
    highs.reverse()
    volumes.reverse()

    current = float(stock.get("prpr", 0))
    qty = int(stock.get("hldg_qty", 0))
    rt = float(stock.get("evlu_pfls_rt", 0))
    split_qty = max(1, qty // SPLIT_N)

    profile = calc_strategy_profile(prices, highs, volumes) if prices else calc_strategy_profile([])
    rsi = profile["rsi"]
    rsi2 = profile["rsi2"]
    sma20 = profile["sma20"]
    sma60 = profile["sma60"]
    bb_lo = profile["bb_lo"]
    bb_hi = profile["bb_hi"]
    indicators = {
        "rsi": rsi,
        "rsi2": rsi2,
        "sma20": sma20,
        "sma60": sma60,
        "bb_lo": bb_lo,
        "bb_hi": bb_hi,
        "rt": rt,
        "strategy_score": profile["score"],
        "macd_hist": profile["macd_hist"],
        "macd_bull_cross": profile["macd_bull_cross"],
        "macd_bear_cross": profile["macd_bear_cross"],
    }

    if rt <= STOP_LOSS_PCT:
        return {"action": "sell", "qty": qty, "price": 0, "reason": f"stop loss {rt:.1f}%", "indicators": indicators}
    if rt >= 200 and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"large profit split sell {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt >= TAKE_PROFIT and rsi >= RSI_SELL:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"take profit {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt >= TAKE_PROFIT * 0.5 and profile["macd_bear_cross"] and rsi >= 60:
        return {"action": "sell", "qty": split_qty, "price": int(current), "reason": f"MACD bearish take profit {rt:.1f}% RSI={rsi}", "indicators": indicators}
    if rt <= -10 and rsi <= RSI_BUY and prices and current <= bb_lo:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"split buy {rt:.1f}% RSI={rsi} lower band", "indicators": indicators}
    if rt < 0 and profile["score"] >= 5:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"multi-strategy buy score={profile['score']} ({', '.join(profile['reasons'][:3])})", "indicators": indicators}
    if sma20 > sma60 > 0 and rt < 0:
        return {"action": "buy", "qty": split_qty, "price": int(current), "reason": f"golden cross SMA20={sma20:.0f}>SMA60={sma60:.0f}", "indicators": indicators}
    return {"action": "hold", "qty": 0, "price": 0, "reason": f"hold {rt:+.1f}% RSI={rsi}", "indicators": indicators}


def check_daily_loss(pnl: int) -> bool:
    if TOTAL_CAPITAL <= 0 or pnl >= 0:
        return False
    loss_pct = abs(pnl) / TOTAL_CAPITAL * 100
    if loss_pct >= MAX_DAILY_LOSS_PCT:
        msg = f"Daily loss limit reached: {loss_pct:.1f}% >= {MAX_DAILY_LOSS_PCT}%"
        log(f"[WARN] {msg}")
        slack_error(msg)
        return True
    return False


def run() -> None:
    log("=" * 60)
    log(f"Seven Split started | DRY_RUN={DRY_RUN} | ENABLE_LIVE_TRADING={ENABLE_LIVE_TRADING} | ENV={TRADING_ENV}")
    log(f"Order submission enabled: {ORDER_SUBMISSION_ENABLED} | Real orders enabled: {REAL_ORDERS_ENABLED}")
    log("=" * 60)

    check_secrets()
    init_db()
    api = KIStockAPI()

    balance = api.get_balance()
    stocks = balance.get("output1", [])
    summary = balance.get("output2", [{}])[0]
    cash = int(summary.get("dnca_tot_amt", 0))
    total_eval = int(summary.get("tot_evlu_amt", 0))
    pnl = int(summary.get("evlu_pfls_smtl_amt", 0))

    log(f"Cash={cash:,} KRW | Total={total_eval:,} KRW | PnL={pnl:+,} KRW | Holdings={len(stocks)}")
    slack_session_start(cash=cash, total=total_eval, stock_count=len(stocks))

    daily_loss_halt = check_daily_loss(pnl)
    results = []
    held_symbols: set[str] = set()

    for stock in stocks:
        sym = stock.get("pdno", "")
        name = stock.get("prdt_name", sym)
        rt = float(stock.get("evlu_pfls_rt", 0))
        held_symbols.add(sym)
        log(f"--- {name}({sym}) return={rt:+.2f}% ---")

        daily = api.get_daily(sym, n=60)
        signal = generate_signal(stock, daily)
        indicators = signal["indicators"]
        log(
            f"Indicators: RSI={indicators['rsi']} "
            f"SMA20={indicators['sma20']:.0f} SMA60={indicators['sma60']:.0f} "
            f"BB({indicators['bb_lo']:.0f}~{indicators['bb_hi']:.0f})"
        )
        log(f"Signal: {signal['action'].upper()} - {signal['reason']}")

        if signal["action"] == "hold":
            continue
        if signal["action"] == "buy":
            if daily_loss_halt:
                log("[SKIP] Daily loss halt active")
                continue
            cost = signal["qty"] * signal["price"]
            if cost > cash:
                log(f"[SKIP] Not enough cash: need={cost:,}, cash={cash:,}")
                continue

        result = api.place_order(sym, signal["action"], signal["price"], signal["qty"])
        ok = result.get("rt_cd") == "0"
        log(f"Order {'OK' if ok else 'FAILED'}: {result.get('msg1', '')}")
        save_trade(sym, name, signal["action"], signal["qty"], signal["price"], signal["reason"], ok)
        row = {
            "name": name,
            "symbol": sym,
            "action": signal["action"],
            "qty": signal["qty"],
            "price": signal["price"],
            "reason": signal["reason"],
            "ok": ok,
            "indicators": indicators,
        }
        results.append(row)
        slack_order(name, sym, signal["action"], signal["qty"], signal["price"], signal["reason"], ok, indicators)
        if ok and signal["action"] == "buy":
            cash -= signal["qty"] * signal["price"]

    if not daily_loss_halt:
        log("--- Scanning for new buy candidates (AI universe) ---")
        universe = build_scan_universe(api, held_symbols)
        result = find_candidates(held_symbols, universe=universe)
        candidates = result["candidates"]
        if candidates:
            slack_candidates(candidates)
            for order in build_orders(candidates, api.get_quote, len(held_symbols), cash):
                sym = order["ticker"]
                qty = order["quantity"]
                price = order["limit_price"]
                reason = f"new buy score={order['score']} ({', '.join(order['reasons'])})"
                log(f"--- New BUY {sym} qty={qty} price={price:,} ---")
                result = api.place_order(sym, "buy", price, qty)
                ok = result.get("rt_cd") == "0"
                log(f"Order {'OK' if ok else 'FAILED'}: {result.get('msg1', '')}")
                save_trade(sym, sym, "buy", qty, price, reason, ok)
                indicators = {"rsi": "-", "sma20": 0, "sma60": 0, "rt": 0}
                results.append({"name": sym, "symbol": sym, "action": "buy", "qty": qty, "price": price, "reason": reason, "ok": ok, "indicators": indicators})
                slack_order(sym, sym, "buy", qty, price, reason, ok, indicators)
                if ok:
                    cash -= qty * price
        else:
            scanned = result["scanned"]
            top = result["scan_summary"][:5]
            log(f"[INFO] 매수 후보 없음 — {scanned}종목 분석, 기준점수 {result['min_score']}점")
            for item in top:
                log(f"  {item['ticker']} score={item['score']} rsi={item['rsi']:.0f} reasons={item['reasons']}")

    if not results:
        log("No orders generated")
    slack_session_end(results=results, cash=cash, total=total_eval, pnl=pnl)
    log("Seven Split finished")


if __name__ == "__main__":
    run()
