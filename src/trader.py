"""
Seven Split auto-trading engine (Refactored).
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.config import config
from src.utils.logger import logger
from src.api.kis_api import HTTP
from src.kis_client import KISClient, KISClientConfig
from src.db.repository import init_db, connect_db, save_trade
from src.notifier.slack import slack_session_start, slack_order, slack_candidates, slack_session_end, slack_error
from src.strategy.seven_split import (
    WATCHLIST, KOSPI_UNIVERSE, STOCK_NAMES,
    generate_signal, build_scan_universe, find_candidates, build_orders,
    generate_ai_weight_plan, generate_portfolio_optimizer_plan,
    calc_strategy_profile,
)
from src.strategy.indicators import calc_bollinger, calc_macd, calc_rsi, calc_sma
from src.strategy.risk import RiskEngine
from src.strategy.router import OrderRouter
from src.execution_plan import (
    signal_to_plan_row,
    candidate_order_to_plan_row,
    build_execution_plan,
)

KST = timezone(timedelta(hours=9))

TRADING_ENV = config.trading_env
DRY_RUN = config.dry_run
ENABLE_LIVE_TRADING = config.enable_live_trading
REQUIRE_APPROVAL = config.require_approval

SPLIT_N = config.split_n
STOP_LOSS_PCT = config.stop_loss_pct
TAKE_PROFIT = config.take_profit
RSI_BUY = config.rsi_buy
RSI_SELL = config.rsi_sell

TOTAL_CAPITAL = config.total_capital
MAX_POSITIONS = config.max_positions
MAX_SINGLE_WEIGHT = config.max_single_weight
CASH_BUFFER = config.cash_buffer
MAX_DAILY_LOSS_PCT = config.max_daily_loss_pct
SCAN_UNIVERSE_SIZE = config.scan_universe_size

REAL_ORDERS_ENABLED = (not DRY_RUN) and TRADING_ENV == "real" and ENABLE_LIVE_TRADING
ORDER_SUBMISSION_ENABLED = (not DRY_RUN) and (TRADING_ENV == "demo" or REAL_ORDERS_ENABLED)

RUNTIME_DIR = Path(".runtime")
DB_PATH = Path(config.trade_db_path)

# KIS API module-level constants (patchable in tests)
BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if config.trading_env == "real"
    else "https://openapivts.koreainvestment.com:29443"
)
KISTOCK_APP_KEY = config.kistock_app_key
KISTOCK_APP_SECRET = config.kistock_app_secret
KISTOCK_ACCOUNT = config.kistock_account


def build_kis_client_config() -> KISClientConfig:
    return KISClientConfig(
        base_url=BASE_URL,
        app_key=KISTOCK_APP_KEY,
        app_secret=KISTOCK_APP_SECRET,
        account_no=KISTOCK_ACCOUNT,
        trading_env=TRADING_ENV,
        token_cache_path=Path("data") / "kis_token.json",
    )


class KIStockAPI:
    """KIS API client wired through trader module-level constants for testability."""

    TOKEN_CACHE = Path("data") / "kis_token.json"
    ETF_MARKET_CODES = {
        "102110", "133690", "148020", "152100", "157490",
        "229200", "251340", "261240", "273130", "278530",
        "305720", "381170", "448290", "481190",
    }
    _err_count: int = 0
    _circuit_opened_at: "datetime | None" = None
    MAX_ERRORS: int = 5

    def __init__(self, notify_errors: bool = True) -> None:
        self.notify_errors = notify_errors
        self.client_config = build_kis_client_config()
        self.access_token = self._load_or_fetch_token()
        self._client = KISClient(self.client_config, session=HTTP, access_token=self.access_token)

    def _load_or_fetch_token(self) -> str:
        if self.TOKEN_CACHE.exists():
            try:
                cached = json.loads(self.TOKEN_CACHE.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if (
                    cached.get("trading_env") == TRADING_ENV
                    and cached.get("base_url") == BASE_URL
                    and cached.get("app_key_prefix") == KISTOCK_APP_KEY[:8]
                    and expires_at > datetime.now() + timedelta(minutes=5)
                ):
                    return cached["token"]
            except Exception:
                pass
        return self._fetch_token()

    def _fetch_token(self) -> str:
        r = HTTP.post(
            f"{BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": KISTOCK_APP_KEY,
                "appsecret": KISTOCK_APP_SECRET,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token", "")
        expires_at = datetime.now() + timedelta(hours=23)
        self.TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
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
        return token

    def _headers(self, tr_id: str) -> dict:
        self._client.access_token = self.access_token
        return self._client.headers(tr_id)

    def _hashkey(self, payload: dict) -> str:
        try:
            return self._client.create_hashkey(payload)
        except Exception:
            return ""

    def _fail(self) -> None:
        self.__class__._err_count = min(self.MAX_ERRORS, self.__class__._err_count + 1)

    def _success(self) -> None:
        self.__class__._err_count = 0
        self.__class__._circuit_opened_at = None

    def _record_result(self, data: dict) -> None:
        if data.get("rt_cd") == "0":
            self._success()
        else:
            self._fail()

    def _sync_circuit_to_client(self) -> None:
        self._client.circuit.error_count = self.__class__._err_count
        self._client.circuit.opened_at = self.__class__._circuit_opened_at

    def _sync_circuit_from_client(self) -> None:
        self.__class__._err_count = self._client.circuit.error_count
        self.__class__._circuit_opened_at = self._client.circuit.opened_at

    @classmethod
    def reset_circuit(cls) -> None:
        cls._err_count = 0
        cls._circuit_opened_at = None

    @classmethod
    def circuit_status(cls) -> dict:
        opened = cls._err_count >= cls.MAX_ERRORS
        opened_at = cls._circuit_opened_at.isoformat() if cls._circuit_opened_at else None
        return {
            "opened": opened,
            "error_count": cls._err_count,
            "max_errors": cls.MAX_ERRORS,
            "opened_at": opened_at,
        }

    def get_balance(self) -> dict:
        tr_id = "VTTC8434R" if TRADING_ENV == "demo" else "TTTC8434R"
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        cano = KISTOCK_ACCOUNT[:8]
        acnt = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        r = HTTP.get(url, headers=self._headers(tr_id), params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_quote(self, symbol: str) -> dict:
        r = HTTP.get(
            f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
            timeout=10,
        )
        output = r.json().get("output", {})
        return {
            "current": float(output.get("stck_prpr", 0)),
            "ask1": float(output.get("askp1", 0)),
            "bid1": float(output.get("bidp1", 0)),
        }

    def get_volume_rank(self, top_n: int = 50) -> list:
        self._sync_circuit_to_client()
        result = self._client.get_volume_rank(top_n=top_n)
        self._sync_circuit_from_client()
        return result

    def get_daily(self, symbol: str, n: int = 60) -> list:
        self._sync_circuit_to_client()
        result = self._client.get_daily(symbol, n=n)
        self._sync_circuit_from_client()
        return result

    def place_order(self, symbol: str, order_type: str, price: int, qty: int) -> dict:
        if not ORDER_SUBMISSION_ENABLED:
            return {"rt_cd": "0", "msg1": "DRY_RUN"}
        is_demo = TRADING_ENV == "demo"
        if order_type == "buy":
            tr_id = "VTTC0802U" if is_demo else "TTTC0802U"
        else:
            tr_id = "VTTC0801U" if is_demo else "TTTC0801U"
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        cano = KISTOCK_ACCOUNT[:8]
        acnt = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt,
            "PDNO": symbol,
            "ORD_DVSN": "01" if price == 0 else "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        headers = self._headers(tr_id)
        hashkey = self._hashkey(body)
        if hashkey:
            headers["hashkey"] = hashkey
        r = HTTP.post(url, headers=headers, json=body, timeout=15)
        return r.json()

    def get_trade_history(self, start_date: str, end_date: str) -> list:
        tr_id = "VTTC8001R" if TRADING_ENV == "demo" else "TTTC8001R"
        url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        cano = KISTOCK_ACCOUNT[:8]
        acnt = KISTOCK_ACCOUNT[8:] if len(KISTOCK_ACCOUNT) > 8 else "01"
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt,
            "INQR_STRT_DT": start_date, "INQR_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "",
            "CCLD_DVSN": "01", "ORD_GNO_BRNO": "", "ODNO": "",
            "INQR_DVSN_3": "00", "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        r = HTTP.get(url, headers=self._headers(tr_id), params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("output1", [])


_CANDIDATE_INDICATOR_KEYS = {"rsi", "rsi2", "sma20", "sma60", "bb_lo", "bb_hi", "macd_hist"}

_VALID_RUN_MODES = {"analysis_only", "live", None}


def normalize_run_mode(mode: str | None) -> str | None:
    if mode not in _VALID_RUN_MODES:
        raise ValueError(f"Invalid run mode: {mode!r}. Must be one of {_VALID_RUN_MODES}")
    return mode


def check_secrets():
    pass


def init_approval_db() -> None:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price INTEGER NOT NULL,
                reason TEXT,
                source TEXT,
                status TEXT NOT NULL,
                response_msg TEXT
            )
            """
        )


def daily_loss_halt_triggered(pnl: int) -> bool:
    if TOTAL_CAPITAL <= 0:
        return False
    loss_pct = abs(pnl) / TOTAL_CAPITAL * 100
    return pnl < 0 and loss_pct >= MAX_DAILY_LOSS_PCT


def check_daily_loss(pnl: int) -> bool:
    halted = daily_loss_halt_triggered(pnl)
    if halted:
        logger.warning(f"일일 손실 한도 초과: {pnl:+,} KRW — 신규 매수 및 실행 중단")
    return halted


def queue_approval(
    symbol: str,
    name: str,
    action: str,
    qty: int,
    price: int,
    reason: str = "",
    source: str = "trader",
) -> int:
    init_approval_db()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO approvals
            (created_at, updated_at, symbol, name, action, qty, price, reason, source, status, response_msg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
            """,
            (now, now, symbol, name, action, qty, price, reason, source),
        )
        return cursor.lastrowid


def execute_plan_row(api, context: dict, row: dict) -> dict:
    mode = context.get("mode")
    if mode == "analysis_only":
        approval_id = queue_approval(
            row["symbol"],
            row["name"],
            row["action"],
            row["qty"],
            row["price"],
            row.get("reason", ""),
            source="trader",
        )
        return {**row, "decision": "queue", "ok": True, "approval_id": approval_id}

    router = context.get("router")
    if router is None:
        return {**row, "decision": "skip", "ok": False}

    result = router.route(
        row["symbol"],
        row["name"],
        row["action"],
        row["qty"],
        row["price"],
        row.get("reason", ""),
        row.get("indicators", {}),
    )
    ok = result.get("ok", False)
    decision = "execute" if ok else "failed"
    return {**row, "decision": decision, "ok": ok}


def build_runtime_plan(api, balance_data: dict) -> dict:
    stocks = balance_data.get("output1", [])
    summary = (balance_data.get("output2") or [{}])[0]
    cash = int(summary.get("dnca_tot_amt", 0) or 0)
    pnl = int(summary.get("evlu_pfls_smtl_amt", 0) or 0)

    position_rows = []
    for stock in stocks:
        sym = stock.get("pdno", "")
        name = stock.get("prdt_name", sym)
        rt = float(stock.get("evlu_pfls_rt", 0) or 0)
        daily = api.get_daily(sym, n=60)
        signal = generate_signal(stock, daily)
        row = signal_to_plan_row(
            sym,
            name,
            signal,
            source="holding_signal",
            include_hold=True,
            metadata={"return_pct": rt},
        )
        if row is not None:
            position_rows.append(row)

    halted = daily_loss_halt_triggered(pnl)
    remaining_cash = cash
    candidate_rows = []
    candidate_scan: dict = {"candidates": [], "scan_summary": [], "scanned": 0, "min_score": 2, "scan_error": None}

    if not halted:
        held_symbols = {s.get("pdno", "") for s in stocks}
        universe = build_scan_universe(api, held_symbols)
        scan_result = find_candidates(held_symbols, universe=universe)
        candidates = scan_result.get("candidates", [])
        orders = build_orders(candidates, api.get_quote, len(held_symbols), cash)
        order_by_ticker = {o["ticker"]: o for o in orders}

        for candidate in candidates:
            order = order_by_ticker.get(candidate["ticker"], {})
            row = candidate_order_to_plan_row(candidate, order, source="candidate_order")
            indicators = {
                k: v
                for k, v in candidate.items()
                if k in _CANDIDATE_INDICATOR_KEYS and v is not None
            }
            row = {**row, "indicators": indicators}
            candidate_rows.append(row)
            if order:
                remaining_cash -= int(order.get("estimated_cost", 0) or 0)

        candidate_scan = {
            "candidates": candidates,
            "scan_summary": scan_result.get("scan_summary", []),
            "scanned": scan_result.get("scanned", 0),
            "min_score": scan_result.get("min_score", 2),
            "scan_error": scan_result.get("scan_error"),
        }

    plan = build_execution_plan(position_rows=position_rows, candidate_rows=candidate_rows)

    return {
        "plan": plan,
        "position_plan_rows": position_rows,
        "candidate_plan_rows": candidate_rows,
        "remaining_cash": remaining_cash,
        "daily_loss_halt": halted,
        "candidate_scan": candidate_scan,
        "cash": cash,
        "held_symbols": {s.get("pdno", "") for s in stocks},
    }


def run(mode: str | None = None) -> dict:
    check_secrets()
    init_db()
    init_approval_db()

    api = KIStockAPI()
    balance = api.get_balance()

    stocks = balance.get("output1", [])
    summary = (balance.get("output2") or [{}])[0]
    cash = int(summary.get("dnca_tot_amt", 0) or 0)
    total_eval = int(summary.get("tot_evlu_amt", 0) or 0)
    pnl = int(summary.get("evlu_pfls_smtl_amt", 0) or 0)

    logger.info("=" * 60)
    logger.info(
        f"Seven Split started | DRY_RUN={DRY_RUN} | ENABLE_LIVE_TRADING={ENABLE_LIVE_TRADING} | ENV={TRADING_ENV}"
    )
    logger.info(
        f"Order submission enabled: {ORDER_SUBMISSION_ENABLED} | Real orders enabled: {REAL_ORDERS_ENABLED}"
    )
    logger.info(f"Cash={cash:,} KRW | Total={total_eval:,} KRW | PnL={pnl:+,} KRW | Holdings={len(stocks)}")

    slack_session_start(
        cash=cash,
        total=total_eval,
        stock_count=len(stocks),
        order_submission_enabled=ORDER_SUBMISSION_ENABLED,
        real_orders_enabled=REAL_ORDERS_ENABLED,
    )

    if check_daily_loss(pnl):
        slack_session_end(results=[], cash=cash, total=total_eval, pnl=pnl)
        return {"plan": [], "results": []}

    runtime_bundle = build_runtime_plan(api, balance)

    candidates = runtime_bundle.get("candidate_scan", {}).get("candidates", [])
    if candidates:
        slack_candidates(candidates)

    context: dict = {"mode": mode}
    if mode != "analysis_only":
        context["router"] = OrderRouter(api)

    results = []
    for row in runtime_bundle["plan"]:
        result_row = execute_plan_row(api, context, row)
        results.append(result_row)

    remaining_cash = runtime_bundle.get("remaining_cash", cash)
    slack_session_end(results=results, cash=remaining_cash, total=total_eval, pnl=pnl)

    logger.info("Seven Split finished")
    return {
        "plan": runtime_bundle["plan"],
        "results": results,
        **{k: v for k, v in runtime_bundle.items() if k != "plan"},
    }


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.exception("Critical error in trader:")
        if hasattr(e, "last_attempt") and e.last_attempt.exception():
            original_err = e.last_attempt.exception()
            slack_error(f"실행 중 치명적인 오류가 발생했습니다: {original_err}")
        else:
            slack_error(f"실행 중 치명적인 오류가 발생했습니다: {e}")
        raise
