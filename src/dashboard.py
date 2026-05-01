import json
import hashlib
import concurrent.futures
import os
import sqlite3
import subprocess
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from src import trader  # noqa: E402
from src.trader import KIStockAPI  # noqa: E402
from src.api.kis_api import KISAccountError, KISConfigError, KISRateLimitError  # noqa: E402
from src.notifier.slack import slack_order as _slack_order, slack_error as _slack_error  # noqa: E402
from src.strategy.allocator import PortfolioAllocator  # noqa: E402
from src.strategy.seven_split import adjust_tick_size  # noqa: E402


app = FastAPI(title="Seven Split Dashboard", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
DB_PATH = trader.DB_PATH
FINRL_DIR = BASE_DIR / "vendor" / "FinRL"
BALANCE_CACHE = trader.RUNTIME_DIR / "balance_snapshot.json"
CANDIDATE_CACHE = trader.RUNTIME_DIR / "candidate_snapshot.json"
AUTO_APPROVAL_STATE = trader.RUNTIME_DIR / "auto_approval.json"
ENV_PATH = BASE_DIR / ".env"
CANDIDATE_CACHE_TTL_SECONDS = int(os.environ.get("CANDIDATE_CACHE_TTL_SECONDS", "180"))
BALANCE_CACHE_TTL_SECONDS = int(os.environ.get("BALANCE_CACHE_TTL_SECONDS", "30"))
BALANCE_FETCH_TIMEOUT_SECONDS = float(os.environ.get("BALANCE_FETCH_TIMEOUT_SECONDS", "25"))
GIT_FETCH_TIMEOUT_SECONDS = float(os.environ.get("GIT_FETCH_TIMEOUT_SECONDS", "3"))
_balance_fetch_lock = threading.Lock()
ENV_FIELDS = [
    {"key": "KISTOCK_APP_KEY", "label": "KIS App Key", "type": "secret"},
    {"key": "KISTOCK_APP_SECRET", "label": "KIS App Secret", "type": "secret"},
    {"key": "KISTOCK_ACCOUNT", "label": "KIS Account", "type": "secret", "hint": "계좌번호 8자리 또는 계좌번호 8자리 + 상품코드 2자리, 예: 12345678 또는 1234567801"},
    {"key": "TRADING_ENV", "label": "거래환경", "type": "select", "options": ["demo", "real"], "hint": "demo=모의투자, real=실전투자"},
    {"key": "DRY_RUN", "label": "주문차단", "type": "bool", "hint": "true이면 주문차단 ON 상태로 KIS 주문 API 전송을 막고 기록만 남깁니다."},
    {"key": "ENABLE_LIVE_TRADING", "label": "실전매매 최종허용", "type": "bool", "hint": "실전주문을 허용하는 최종 안전 스위치입니다."},
    {"key": "REQUIRE_APPROVAL", "label": "주문승인 필요", "type": "bool"},
    {"key": "SPLIT_N", "label": "Split N", "type": "int"},
    {"key": "STOP_LOSS_PCT", "label": "Stop Loss %", "type": "float"},
    {"key": "TAKE_PROFIT", "label": "Take Profit %", "type": "float"},
    {"key": "RSI_BUY", "label": "RSI Buy", "type": "int"},
    {"key": "RSI_SELL", "label": "RSI Sell", "type": "int"},
    {"key": "TOTAL_CAPITAL", "label": "Total Capital", "type": "float"},
    {"key": "MAX_POSITIONS", "label": "Max Positions", "type": "int"},
    {"key": "MAX_SINGLE_WEIGHT", "label": "Max Single Weight", "type": "float"},
    {"key": "CASH_BUFFER", "label": "Cash Buffer", "type": "float"},
    {"key": "MAX_DAILY_LOSS_PCT", "label": "Max Daily Loss %", "type": "float"},
    {"key": "SCAN_UNIVERSE_SIZE", "label": "Scan Universe Size", "type": "int"},
    {"key": "KIS_CIRCUIT_COOLDOWN_SECONDS", "label": "KIS API 차단 대기초", "type": "int", "hint": "KIS API 오류 후 재시도까지 기다릴 시간(초)입니다. 저장 후 서버 재시작 시 적용됩니다."},
    {"key": "TRADE_DB_PATH", "label": "Trade DB Path", "type": "text"},
    {"key": "ACTIVE_MODEL_VERSION", "label": "Active Model Version", "type": "text"},
    {"key": "SLACK_WEBHOOK_URL", "label": "Slack Webhook URL", "type": "secret"},
]
ENV_FIELD_MAP = {field["key"]: field for field in ENV_FIELDS}
VENDOR_PROJECTS = {
    "finrl": {
        "name": "FinRL",
        "path": BASE_DIR / "vendor" / "FinRL",
        "package": "finrl",
        "dashboard": "/finrl",
        "license_hint": "MIT",
        "adapter": "Weight-centric allocation for current KIS holdings",
        "entrypoints": [
            "finrl/train.py",
            "finrl/test.py",
            "finrl/trade.py",
            "finrl/meta/env_stock_trading/env_stocktrading.py",
            "finrl/agents/stablebaselines3/models.py",
        ],
    },
    "qlib": {
        "name": "Qlib",
        "path": BASE_DIR / "vendor" / "qlib",
        "package": "qlib",
        "dashboard": "/vendors",
        "license_hint": "MIT",
        "adapter": "AI quant research pipeline map: dataset, feature, model, signal, execution",
        "entrypoints": [
            "qlib/workflow",
            "qlib/model",
            "qlib/contrib",
            "qlib/backtest",
            "examples",
        ],
    },
    "pyportfolioopt": {
        "name": "PyPortfolioOpt",
        "path": BASE_DIR / "vendor" / "PyPortfolioOpt",
        "package": "pypfopt",
        "dashboard": "/vendors",
        "license_hint": "MIT",
        "adapter": "Portfolio target weights and risk-aware rebalance planning",
        "entrypoints": [
            "pypfopt/efficient_frontier",
            "pypfopt/risk_models",
            "pypfopt/expected_returns",
            "pypfopt/objective_functions",
        ],
    },
    "freqtrade": {
        "name": "freqtrade",
        "path": BASE_DIR / "vendor" / "freqtrade",
        "package": "freqtrade",
        "dashboard": "/vendors",
        "license_hint": "GPL-3.0",
        "adapter": "Dry-run, approval workflow, strategy status concepts only; source kept isolated",
        "entrypoints": [
            "freqtrade/strategy",
            "freqtrade/rpc",
            "freqtrade/persistence",
            "freqtrade/freqai",
            "user_data/strategies",
        ],
    },
}

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


def _required_env_missing() -> list[str]:
    required = ["KISTOCK_APP_KEY", "KISTOCK_APP_SECRET", "KISTOCK_ACCOUNT"]
    missing = [name for name in required if not os.environ.get(name)]
    if _account_format_warning(trader.config.kistock_account):
        missing.append("KISTOCK_ACCOUNT_FORMAT")
    return missing


def _account_format_warning(account: str) -> str:
    digits = "".join(char for char in str(account or "") if char.isdigit())
    if not digits:
        return "KISTOCK_ACCOUNT is required"
    if len(digits) not in {8, 10}:
        return "KISTOCK_ACCOUNT must be 8 digits, or 10 digits including 2-digit product code"
    return ""


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summary_item(summary):
    if isinstance(summary, list):
        return summary[0] if summary else {}
    if isinstance(summary, dict):
        return summary
    return {}


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


def _holding_value(stock: dict, qty: int, price: int) -> int:
    broker_value = _to_int(stock.get("evlu_amt"))
    if broker_value > 0:
        return broker_value
    return qty * price


def _portfolio_totals(cash: int, summary_total: int, holdings: list[dict]) -> dict:
    stock_eval = sum(_to_int(holding.get("value")) for holding in holdings)
    broker_total = max(0, summary_total)
    calculated_total = max(0, cash) + stock_eval
    effective_total = broker_total if broker_total >= stock_eval else calculated_total
    if effective_total <= 0:
        effective_total = calculated_total
    return {
        "stock_eval": stock_eval,
        "broker_total_eval": broker_total,
        "calculated_total_eval": calculated_total,
        "total_eval": effective_total,
        "cash_ratio": _clamp_ratio(cash / effective_total) if effective_total > 0 else 0.0,
        "stock_ratio": _clamp_ratio(stock_eval / effective_total) if effective_total > 0 else 0.0,
    }


def _parse_balance(balance_data: dict) -> dict:
    if balance_data.get("_error"):
        raise RuntimeError(balance_data["_error"])

    stocks = balance_data.get("output1", [])
    first_summary = _summary_item(balance_data.get("output2", [{}]))

    holdings = []
    for stock in stocks:
        qty = _to_int(stock.get("hldg_qty"))
        price = _to_int(stock.get("prpr"))
        value = _holding_value(stock, qty, price)
        if price <= 0 and qty > 0:
            price = round(value / qty)
        holdings.append({
            "symbol": stock.get("pdno", ""),
            "name": stock.get("prdt_name", stock.get("pdno", "")),
            "qty": qty,
            "price": price,
            "rt": _to_float(stock.get("evlu_pfls_rt")),
            "pnl": _to_int(stock.get("evlu_pfls_amt")),
            "value": value,
            "_raw": stock,
        })

    summary_total = _to_int(first_summary.get("tot_evlu_amt"))
    summary_stock_eval = _to_int(first_summary.get("scts_evlu_amt"))
    cash = _to_int(first_summary.get("prvs_rcdl_excc_amt"))
    if cash <= 0 and summary_total > 0 and summary_stock_eval > 0:
        cash = max(0, summary_total - summary_stock_eval)
    if cash <= 0:
        cash = _to_int(first_summary.get("dnca_tot_amt"))
    totals = _portfolio_totals(cash, summary_total, holdings)
    return {
        "cash": cash,
        "total_eval": totals["total_eval"],
        "broker_total_eval": totals["broker_total_eval"],
        "calculated_total_eval": totals["calculated_total_eval"],
        "stock_eval": totals["stock_eval"],
        "cash_ratio": totals["cash_ratio"],
        "stock_ratio": totals["stock_ratio"],
        "pnl": _to_int(first_summary.get("evlu_pfls_smtl_amt")),
        "holdings": holdings,
    }


def _get_api() -> KIStockAPI:
    return KIStockAPI(notify_errors=False)


def _account_cache_key() -> str:
    source = f"{trader.TRADING_ENV}:{trader.config.kistock_account}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _save_balance_cache(balance_data: dict) -> None:
    BALANCE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BALANCE_CACHE.write_text(
        json.dumps({
            "cached_at": trader.datetime.now(trader.KST).isoformat(),
            "trading_env": trader.TRADING_ENV,
            "account_key": _account_cache_key(),
            "data": balance_data,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_balance_cache() -> dict | None:
    if not BALANCE_CACHE.exists():
        return None
    try:
        cached = json.loads(BALANCE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if cached.get("trading_env") != trader.TRADING_ENV:
        return None
    if cached.get("account_key") != _account_cache_key():
        return None
    data = cached.get("data")
    if not isinstance(data, dict):
        return None
    data["_cache"] = {"stale": True, "cached_at": cached.get("cached_at", "")}
    return data


def _balance_cache_age_seconds(balance_data: dict) -> float | None:
    cached_at = balance_data.get("_cache", {}).get("cached_at", "")
    if not cached_at:
        return None
    try:
        return (trader.datetime.now(trader.KST) - trader.datetime.fromisoformat(cached_at)).total_seconds()
    except Exception:
        return None


def _run_with_timeout(func, timeout_seconds: float):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _get_balance_data(api: KIStockAPI, allow_cache: bool = True) -> dict:
    cached = _load_balance_cache() if allow_cache else None
    if allow_cache:
        if cached is not None:
            age = _balance_cache_age_seconds(cached)
            if age is not None and age < BALANCE_CACHE_TTL_SECONDS:
                return cached

    with _balance_fetch_lock:
        if allow_cache:
            cached = _load_balance_cache()
            if cached is not None:
                age = _balance_cache_age_seconds(cached)
                if age is not None and age < BALANCE_CACHE_TTL_SECONDS:
                    return cached
        try:
            balance_data = _run_with_timeout(api.get_balance, BALANCE_FETCH_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            if cached is not None:
                return cached
            raise RuntimeError("KIS balance API timed out")
        except KISConfigError:
            if allow_cache:
                cached = _load_balance_cache()
                if cached is not None:
                    return cached
            raise
        except Exception:
            if allow_cache:
                cached = _load_balance_cache()
                if cached is not None:
                    return cached
            raise
        try:
            _parse_balance(balance_data)
        except Exception:
            if allow_cache:
                cached = _load_balance_cache()
                if cached is not None:
                    return cached
            raise
        _save_balance_cache(balance_data)
        return balance_data


def _load_candidate_cache(min_score: int) -> dict | None:
    if not CANDIDATE_CACHE.exists():
        return None
    try:
        cached = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if cached.get("trading_env") != trader.TRADING_ENV or cached.get("min_score") != min_score:
        return None
    cached_at = cached.get("cached_at")
    if not cached_at:
        return None
    try:
        age = (trader.datetime.now(trader.KST) - trader.datetime.fromisoformat(cached_at)).total_seconds()
    except ValueError:
        return None
    if age > CANDIDATE_CACHE_TTL_SECONDS:
        return None
    rows = cached.get("rows")
    if not isinstance(rows, list):
        return None
    return {
        "candidates": rows,
        "scan_summary": cached.get("scan_summary", []),
        "scanned": cached.get("scanned", len(rows)),
        "min_score": min_score,
        "_cache": {"stale": False, "cached_at": cached_at},
    }


def _save_candidate_cache(
    min_score: int, rows: list[dict], scan_summary: list[dict], scanned: int
) -> None:
    CANDIDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_CACHE.write_text(
        json.dumps({
            "cached_at": trader.datetime.now(trader.KST).isoformat(),
            "trading_env": trader.TRADING_ENV,
            "min_score": min_score,
            "rows": rows,
            "scan_summary": scan_summary,
            "scanned": scanned,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_candidate_orders_from_scan(
    candidates: list[dict], held_count: int, cash: int
) -> list[dict]:
    available_slots = trader.MAX_POSITIONS - held_count
    if available_slots <= 0:
        return []

    order_candidates = []
    for candidate in candidates[:available_slots]:
        cloned = dict(candidate)
        cloned["limit_price"] = adjust_tick_size(int(cloned.get("current_price") or 0))
        order_candidates.append(cloned)
    return PortfolioAllocator().allocate(order_candidates, cash, trader.TOTAL_CAPITAL)


def _init_approval_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with trader.connect_db() as conn:
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


def _approval_row(row) -> dict:
    return dict(row)


def _auto_approval_enabled() -> bool:
    if not AUTO_APPROVAL_STATE.exists():
        return False
    try:
        state = json.loads(AUTO_APPROVAL_STATE.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(state.get("enabled"))


def _save_auto_approval(enabled: bool) -> None:
    AUTO_APPROVAL_STATE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_APPROVAL_STATE.write_text(
        json.dumps({
            "enabled": bool(enabled),
            "updated_at": trader.datetime.now(trader.KST).isoformat(),
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_env_values(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = _env_value_without_inline_comment(value.strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def _env_value_without_inline_comment(value: str) -> str:
    quote = None
    for index, char in enumerate(value):
        if char in ("'", '"') and (index == 0 or value[index - 1] != "\\"):
            quote = None if quote == char else (char if quote is None else quote)
        if char == "#" and quote is None and index > 0 and value[index - 1].isspace():
            return value[:index].strip()
    return value.strip()


def _mask_env_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(4, len(value) - 4)}{value[-2:]}"


def _validate_env_value(key: str, value: object) -> str:
    field = ENV_FIELD_MAP[key]
    value_text = _env_value_without_inline_comment(str(value).strip())
    field_type = field["type"]
    if field_type == "bool":
        lowered = value_text.lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise HTTPException(status_code=400, detail=f"{key} must be a boolean")
        return "true" if lowered in {"true", "1", "yes", "on"} else "false"
    if field_type == "int":
        try:
            int(value_text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{key} must be an integer") from exc
        return value_text
    if field_type == "float":
        try:
            float(value_text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{key} must be a number") from exc
        return value_text
    if field_type == "select":
        options = field.get("options", [])
        if value_text not in options:
            raise HTTPException(status_code=400, detail=f"{key} must be one of: {', '.join(options)}")
        return value_text
    if key == "KISTOCK_ACCOUNT":
        digits = "".join(char for char in value_text if char.isdigit())
        warning = _account_format_warning(digits)
        if warning:
            raise HTTPException(status_code=400, detail=warning)
        return digits
    return value_text


def _env_bool_value(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = str(values.get(key, str(default))).strip().lower()
    return raw in {"true", "1", "yes", "on"}


def _virtual_env_value(key: str, values: dict[str, str]) -> str:
    dry_run = _env_bool_value(values, "DRY_RUN", True)
    trading_env = values.get("TRADING_ENV", "demo")
    enable_live = _env_bool_value(values, "ENABLE_LIVE_TRADING", False)
    if key == "ORDER_SUBMISSION_ENABLED":
        return "true" if (not dry_run and (trading_env == "demo" or enable_live)) else "false"
    return ""


def _expand_virtual_env_updates(updates: dict[str, str]) -> dict[str, str]:
    expanded = dict(updates)
    order_submission = expanded.pop("ORDER_SUBMISSION_ENABLED", None)

    if order_submission is not None:
        expanded["DRY_RUN"] = "false" if _env_bool_value({"value": order_submission}, "value") else "true"

    return expanded


def _apply_runtime_env_updates(updates: dict[str, str]) -> None:
    for key, value in updates.items():
        if key == "TRADING_ENV":
            trader.config.trading_env = value
            trader.TRADING_ENV = value
        elif key == "DRY_RUN":
            parsed = _env_bool_value({"value": value}, "value")
            trader.config.dry_run = parsed
            trader.DRY_RUN = parsed
        elif key == "ENABLE_LIVE_TRADING":
            parsed = _env_bool_value({"value": value}, "value")
            trader.config.enable_live_trading = parsed
            trader.ENABLE_LIVE_TRADING = parsed

    trader.REAL_ORDERS_ENABLED = (
        (not trader.DRY_RUN)
        and trader.TRADING_ENV == "real"
        and trader.ENABLE_LIVE_TRADING
    )
    trader.ORDER_SUBMISSION_ENABLED = (
        (not trader.DRY_RUN)
        and (trader.TRADING_ENV == "demo" or trader.REAL_ORDERS_ENABLED)
    )


def _runtime_order_mode_updates(key: str, enabled: bool) -> dict[str, str]:
    normalized = key.upper()
    if normalized == "DRY_RUN":
        return {"DRY_RUN": "true" if enabled else "false"}
    raise HTTPException(status_code=400, detail="key must be DRY_RUN")


def _serialize_env_value(value: str) -> str:
    if not value or any(char.isspace() for char in value) or "#" in value:
        return json.dumps(value, ensure_ascii=False)
    return value


def _write_env_values(updates: dict[str, str], path: Path = ENV_PATH) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            value_part = line.split("=", 1)[1]
            suffix = ""
            comment_index = value_part.find(" #")
            if comment_index >= 0:
                suffix = value_part[comment_index:]
            output.append(f"{key}={_serialize_env_value(updates[key])}{suffix}")
            seen.add(key)
        else:
            output.append(line)
    missing = [key for key in updates if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Dashboard updates")
        output.extend(f"{key}={_serialize_env_value(updates[key])}" for key in missing)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


@app.get("/", response_class=FileResponse)
def read_root():
    return FileResponse(WEB_DIR / "templates" / "index.html")


@app.get("/finrl", response_class=FileResponse)
def read_finrl_dashboard():
    return FileResponse(WEB_DIR / "templates" / "finrl.html")


@app.get("/vendors", response_class=FileResponse)
def read_vendor_dashboard():
    return FileResponse(WEB_DIR / "templates" / "vendors.html")


@app.get("/ai-dashboard", response_class=FileResponse)
def read_ai_dashboard():
    return FileResponse(WEB_DIR / "templates" / "ai_dashboard.html")


@app.get("/env-settings", response_class=FileResponse)
def read_env_settings():
    return FileResponse(WEB_DIR / "templates" / "env_settings.html")


def _license_name(text: str, hint: str) -> str:
    lowered = text.lower()
    if "gnu general public license" in lowered:
        return "GPL-3.0"
    if "mit license" in lowered:
        return "MIT"
    if "apache license" in lowered:
        return "Apache-2.0"
    return hint or "unknown"


def _vendor_status(slug: str, meta: dict) -> dict:
    root = meta["path"]
    exists = root.exists()
    license_path = root / "LICENSE"
    if not license_path.exists():
        license_path = root / "LICENSE.txt"
    license_text = license_path.read_text(encoding="utf-8", errors="replace") if license_path.exists() else ""
    files = list(root.rglob("*")) if exists else []
    pkg = root / meta["package"]
    modules = []
    if pkg.exists():
        modules = [
            child.name
            for child in sorted(pkg.iterdir())
            if child.is_dir() and not child.name.startswith("__")
        ]
    return {
        "slug": slug,
        "name": meta["name"],
        "exists": exists,
        "path": str(root),
        "license": _license_name(license_text, meta["license_hint"]),
        "license_notice": license_text[:500],
        "file_count": len([path for path in files if path.is_file()]),
        "python_file_count": len([path for path in files if path.suffix == ".py"]),
        "notebook_count": len([path for path in files if path.suffix == ".ipynb"]),
        "modules": modules,
        "adapter": meta["adapter"],
        "entrypoints": meta["entrypoints"],
        "dashboard": meta["dashboard"],
    }


@app.get("/api/health")
def health():
    missing = _required_env_missing()
    account_warning = _account_format_warning(trader.config.kistock_account)
    return {
        "ok": not missing and not account_warning,
        "missing": missing,
        "account_warning": account_warning,
        "trading_env": trader.TRADING_ENV,
        "dry_run": trader.DRY_RUN,
        "enable_live_trading": trader.ENABLE_LIVE_TRADING,
        "require_approval": trader.REQUIRE_APPROVAL,
        "order_submission_enabled": trader.ORDER_SUBMISSION_ENABLED,
        "real_orders_enabled": trader.REAL_ORDERS_ENABLED,
        "circuit_breaker": KIStockAPI.circuit_status(),
        "active_model_version": getattr(trader.config, "active_model_version", "v1"),
        "auto_approval_enabled": _auto_approval_enabled(),
        "kill_switch_active": Path(".runtime/kill_switch.json").exists()
    }


@app.get("/api/config")
def get_config():
    return {
        "trading_env": trader.TRADING_ENV,
        "dry_run": trader.DRY_RUN,
        "enable_live_trading": trader.ENABLE_LIVE_TRADING,
        "require_approval": trader.REQUIRE_APPROVAL,
        "order_submission_enabled": trader.ORDER_SUBMISSION_ENABLED,
        "real_orders_enabled": trader.REAL_ORDERS_ENABLED,
        "split_n": trader.SPLIT_N,
        "stop_loss_pct": trader.STOP_LOSS_PCT,
        "take_profit": trader.TAKE_PROFIT,
        "rsi_buy": trader.RSI_BUY,
        "rsi_sell": trader.RSI_SELL,
        "total_capital": trader.TOTAL_CAPITAL,
        "max_positions": trader.MAX_POSITIONS,
        "max_single_weight": trader.MAX_SINGLE_WEIGHT,
        "cash_buffer": trader.CASH_BUFFER,
        "max_daily_loss_pct": trader.MAX_DAILY_LOSS_PCT,
        "watchlist": trader.WATCHLIST,
        "scan_universe_size": trader.SCAN_UNIVERSE_SIZE,
        "kospi_universe_size": len(trader.KOSPI_UNIVERSE),
        "strategy_sources": [
            "RSI recovery + MACD confirmation",
            "Bollinger mean reversion",
            "Trend pullback with short RSI",
            "20-day breakout with volume",
            "FinRL-X inspired weight-centric allocation",
        ],
    }


@app.get("/api/env")
def get_env_settings():
    values = _read_env_values()
    fields = []
    for field in ENV_FIELDS:
        key = field["key"]
        value = _virtual_env_value(key, values) if field.get("virtual") else values.get(key, "")
        item = {
            "key": key,
            "label": field["label"],
            "type": field["type"],
            "options": field.get("options", []),
            "hint": field.get("hint", ""),
            "secret": field["type"] == "secret",
            "virtual": bool(field.get("virtual")),
            "has_value": bool(value),
            "value": value,
            "masked": "",
        }
        fields.append(item)
    return {
        "path": str(ENV_PATH),
        "exists": ENV_PATH.exists(),
        "requires_restart": True,
        "fields": fields,
    }


@app.post("/api/env")
def update_env_settings(payload: dict = Body(...)):
    raw_updates = payload.get("values")
    if not isinstance(raw_updates, dict):
        raise HTTPException(status_code=400, detail="values must be an object")

    updates: dict[str, str] = {}
    for key, value in raw_updates.items():
        if key not in ENV_FIELD_MAP:
            raise HTTPException(status_code=400, detail=f"{key} is not editable")
        field = ENV_FIELD_MAP[key]
        if field["type"] == "secret" and str(value).strip() == "":
            continue
        updates[key] = _validate_env_value(key, value)

    if updates:
        updates = _expand_virtual_env_updates(updates)
        _write_env_values(updates)
    return {
        "ok": True,
        "updated": sorted(updates.keys()),
        "requires_restart": True,
    }


@app.post("/api/circuit-breaker/reset")
def reset_circuit_breaker():
    KIStockAPI.reset_circuit()
    return {"ok": True, "circuit_breaker": KIStockAPI.circuit_status()}


@app.post("/api/auto-approval")
def set_auto_approval(payload: dict = Body(...)):
    enabled = bool(payload.get("enabled"))
    _save_auto_approval(enabled)
    processed = _auto_approve_pending_approvals() if enabled else []
    return {"ok": True, "enabled": enabled, "processed": processed, "processed_count": len(processed)}


@app.post("/api/runtime/order-mode")
def set_runtime_order_mode(payload: dict = Body(...)):
    key = str(payload.get("key", "")).strip()
    enabled = bool(payload.get("enabled"))
    updates = _runtime_order_mode_updates(key, enabled)
    _write_env_values(updates, ENV_PATH)
    _apply_runtime_env_updates(updates)
    return {
        "ok": True,
        "updated": sorted(updates.keys()),
        "trading_env": trader.TRADING_ENV,
        "dry_run": trader.DRY_RUN,
        "enable_live_trading": trader.ENABLE_LIVE_TRADING,
        "order_submission_enabled": trader.ORDER_SUBMISSION_ENABLED,
        "real_orders_enabled": trader.REAL_ORDERS_ENABLED,
        "requires_restart": False,
    }


@app.get("/api/balance")
def get_balance():
    missing = _required_env_missing()
    if missing:
        if "KISTOCK_ACCOUNT_FORMAT" in missing:
            raise HTTPException(status_code=503, detail="KISTOCK_ACCOUNT must be 10 digits: 8-digit account number + 2-digit product code")
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    try:
        api = _get_api()
        balance_data = _get_balance_data(api)
        parsed = _parse_balance(balance_data)
        for holding in parsed["holdings"]:
            holding.pop("_raw", None)
        if balance_data.get("_cache"):
            parsed["_cache"] = balance_data["_cache"]
        return parsed
    except SystemExit as e:
        raise HTTPException(status_code=502, detail=f"KIS API initialization failed: {e}") from e
    except KISAccountError as e:
        raise HTTPException(status_code=503, detail=f"KIS account setting is invalid. Check KISTOCK_ACCOUNT: {e}") from e
    except KISRateLimitError as e:
        raise HTTPException(status_code=429, detail=f"KIS API rate limit exceeded. Retry shortly: {e}") from e
    except RuntimeError as e:
        if "timed out" in str(e):
            raise HTTPException(status_code=504, detail=f"KIS balance API timed out after {BALANCE_FETCH_TIMEOUT_SECONDS:g}s") from e
        raise HTTPException(status_code=502, detail=f"KIS API request failed: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"KIS API request failed: {e}") from e


@app.get("/api/signals")
def get_signals():
    missing = _required_env_missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    try:
        api = _get_api()
        parsed = _parse_balance(_get_balance_data(api))
        signals = []
        for holding in parsed["holdings"]:
            daily = api.get_daily(holding["symbol"], n=60)
            signal = trader.generate_signal(holding["_raw"], daily)
            indicators = signal.get("indicators", {})
            signals.append({
                "symbol": holding["symbol"],
                "name": holding["name"],
                "qty": holding["qty"],
                "price": holding["price"],
                "rt": holding["rt"],
                "action": signal.get("action", "hold"),
                "signal_qty": signal.get("qty", 0),
                "signal_price": signal.get("price", 0),
                "reason": signal.get("reason", ""),
                "rsi": indicators.get("rsi"),
                "rsi2": indicators.get("rsi2"),
                "sma20": indicators.get("sma20"),
                "sma60": indicators.get("sma60"),
                "bb_lo": indicators.get("bb_lo"),
                "bb_hi": indicators.get("bb_hi"),
                "strategy_score": indicators.get("strategy_score"),
                "macd_hist": indicators.get("macd_hist"),
            })
        return {"signals": signals}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Signal analysis failed: {e}") from e


@app.get("/api/candidates")
def get_candidates(min_score: int = 2):
    if min_score < 1:
        raise HTTPException(status_code=400, detail="min_score must be greater than 0")

    missing = _required_env_missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    cached = _load_candidate_cache(min_score)
    if cached is not None:
        return cached

    try:
        api = _get_api()
        parsed = _parse_balance(_get_balance_data(api))
        held_symbols = {holding["symbol"] for holding in parsed["holdings"]}
        universe = trader.build_scan_universe(api, held_symbols)
        result = trader.find_candidates(held_symbols, universe=universe, min_score=min_score)
        candidates = result["candidates"]
        scan_summary = result["scan_summary"]
        orders = _build_candidate_orders_from_scan(candidates, len(held_symbols), parsed["cash"])
        order_by_symbol = {order["ticker"]: order for order in orders}
        rows = []
        for candidate in candidates:
            order = order_by_symbol.get(candidate["ticker"], {})
            rows.append({
                "ticker": candidate["ticker"],
                "name": candidate.get("name", candidate["ticker"]),
                "current_price": candidate["current_price"],
                "score": candidate["score"],
                "reasons": candidate["reasons"],
                "rsi": candidate.get("rsi"),
                "rsi2": candidate.get("rsi2"),
                "macd_hist": candidate.get("macd_hist"),
                "sma20": candidate.get("sma20"),
                "sma60": candidate.get("sma60"),
                "bb_lo": candidate.get("bb_lo"),
                "bb_hi": candidate.get("bb_hi"),
                "planned_qty": order.get("quantity", 0),
                "limit_price": order.get("limit_price", 0),
                "estimated_cost": order.get("estimated_cost", 0),
                "universe_size": len(universe),
            })
        scanned = result["scanned"]
        scan_error = result.get("scan_error")
        # scanned=0 은 yfinance 실패 등 데이터 수신 오류 — 캐시하지 않음
        if scanned > 0:
            _save_candidate_cache(min_score, rows, scan_summary, scanned)
        return {
            "candidates": rows,
            "universe_size": len(universe),
            "scanned": scanned,
            "min_score": min_score,
            "scan_summary": scan_summary,
            "scan_error": scan_error,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Candidate scan failed: {e}") from e


@app.get("/api/ai-allocation")
def get_ai_allocation():
    missing = _required_env_missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    try:
        api = _get_api()
        parsed = _parse_balance(_get_balance_data(api))
        holdings = []
        for holding in parsed["holdings"]:
            daily = api.get_daily(holding["symbol"], n=120)
            prices = [float(row["stck_clpr"]) for row in daily if row.get("stck_clpr")]
            highs = [float(row["stck_hgpr"]) for row in daily if row.get("stck_hgpr")]
            volumes = [float(row["acml_vol"]) for row in daily if row.get("acml_vol")]
            prices.reverse()
            highs.reverse()
            volumes.reverse()
            holdings.append({
                "symbol": holding["symbol"],
                "name": holding["name"],
                "qty": holding["qty"],
                "price": holding["price"],
                "value": holding["value"],
                "prices": prices,
                "highs": highs,
                "volumes": volumes,
            })
        return trader.generate_ai_weight_plan(holdings, parsed["total_eval"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI allocation failed: {e}") from e


def _holding_history(api: KIStockAPI, parsed: dict, n: int = 120) -> list[dict]:
    holdings = []
    for holding in parsed["holdings"]:
        daily = api.get_daily(holding["symbol"], n=n)
        prices = [float(row["stck_clpr"]) for row in daily if row.get("stck_clpr")]
        highs = [float(row["stck_hgpr"]) for row in daily if row.get("stck_hgpr")]
        volumes = [float(row["acml_vol"]) for row in daily if row.get("acml_vol")]
        prices.reverse()
        highs.reverse()
        volumes.reverse()
        holdings.append({
            "symbol": holding["symbol"],
            "name": holding["name"],
            "qty": holding["qty"],
            "price": holding["price"],
            "value": holding["value"],
            "prices": prices,
            "highs": highs,
            "volumes": volumes,
        })
    return holdings


@app.get("/api/portfolio-optimizer")
def get_portfolio_optimizer():
    missing = _required_env_missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    try:
        api = _get_api()
        parsed = _parse_balance(_get_balance_data(api))
        holdings = _holding_history(api, parsed, n=120)
        return trader.generate_portfolio_optimizer_plan(holdings, parsed["total_eval"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Portfolio optimizer failed: {e}") from e


@app.get("/api/finrl/status")
def get_finrl_status():
    return _vendor_status("finrl", VENDOR_PROJECTS["finrl"])


@app.get("/api/vendors")
def get_vendors():
    return {"vendors": [_vendor_status(slug, meta) for slug, meta in VENDOR_PROJECTS.items()]}


@app.get("/api/vendors/{slug}")
def get_vendor(slug: str):
    if slug not in VENDOR_PROJECTS:
        raise HTTPException(status_code=404, detail="vendor not found")
    return _vendor_status(slug, VENDOR_PROJECTS[slug])


@app.get("/api/finrl/pipeline")
def get_finrl_pipeline():
    return {
        "pipeline": [
            {
                "stage": "Data",
                "source": "KIS balance + KIS daily chart",
                "finrl_reference": "meta/data_processor.py",
                "status": "adapted",
            },
            {
                "stage": "Feature Engineering",
                "source": "RSI, RSI2, SMA, Bollinger, MACD, volatility",
                "finrl_reference": "meta/preprocessor/preprocessors.py",
                "status": "adapted",
            },
            {
                "stage": "Environment",
                "source": "current portfolio snapshot",
                "finrl_reference": "meta/env_stock_trading/env_stocktrading.py",
                "status": "dashboard proxy",
            },
            {
                "stage": "Agent Policy",
                "source": "deterministic weight policy inspired by FinRL-X",
                "finrl_reference": "agents/stablebaselines3/models.py",
                "status": "lightweight adapter",
            },
            {
                "stage": "Execution",
                "source": "approval queue + KIS order API",
                "finrl_reference": "trade.py",
                "status": "protected by DRY_RUN and approval",
            },
        ],
    }





@app.get("/api/approvals")
def get_approvals(limit: int = 50):
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be greater than 0")
    limit = min(limit, 200)

    _init_approval_db()
    with trader.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM approvals ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"approvals": [_approval_row(row) for row in rows]}


@app.post("/api/approvals")
def create_approval(payload: dict = Body(...)):
    action = str(payload.get("action", "")).lower()
    if action not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="action must be buy or sell")

    symbol = str(payload.get("symbol", "")).strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    qty = _to_int(payload.get("qty"))
    if qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be greater than 0")

    price = _to_int(payload.get("price"))
    name = str(payload.get("name") or symbol)
    reason = str(payload.get("reason") or "")
    source = str(payload.get("source") or "dashboard")
    now = trader.datetime.now(trader.KST).strftime("%Y-%m-%d %H:%M:%S")

    _init_approval_db()
    with trader.connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO approvals
            (created_at, updated_at, symbol, name, action, qty, price, reason, source, status, response_msg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
            """,
            (now, now, symbol, name, action, qty, price, reason, source),
        )
        approval_id = cursor.lastrowid
    if _auto_approval_enabled():
        result = _approve_pending_approval(approval_id, "자동승인")
        result["auto_approved"] = True
        return result
    return {"id": approval_id, "status": "pending"}


def _load_pending_approval(approval_id: int) -> dict:
    _init_approval_db()
    with trader.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    item = _approval_row(row)
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval is already {item['status']}")
    return item


def _pending_approval_ids(limit: int = 200) -> list[int]:
    _init_approval_db()
    with trader.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id FROM approvals WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [int(row["id"]) for row in rows]


def _auto_approve_pending_approvals(limit: int = 200) -> list[dict]:
    results = []
    for approval_id in _pending_approval_ids(limit):
        try:
            results.append(_approve_pending_approval(approval_id, "자동승인"))
        except HTTPException:
            continue
    return results


def _approve_pending_approval(approval_id: int, approval_label: str = "수동승인") -> dict:
    item = _load_pending_approval(approval_id)
    try:
        api = _get_api()
        result = api.place_order(item["symbol"], item["action"], item["price"], item["qty"])
        ok = result.get("rt_cd") == "0"
        status = "executed" if ok else "failed"
        response_msg = result.get("msg1", "")
        if ok and not trader.DRY_RUN:
            response_msg = f"{response_msg} (주문접수 완료 - 실제 체결 여부는 HTS/MTS에서 확인 요망)"
        trader.save_trade(
            item["symbol"],
            item["name"],
            item["action"],
            item["qty"],
            item["price"],
            item["reason"],
            ok,
            trader.ORDER_SUBMISSION_ENABLED,
        )
    except Exception as e:
        status = "failed"
        response_msg = str(e)

    now = trader.datetime.now(trader.KST).strftime("%Y-%m-%d %H:%M:%S")
    with trader.connect_db() as conn:
        conn.execute(
            "UPDATE approvals SET status = ?, response_msg = ?, updated_at = ? WHERE id = ?",
            (status, response_msg, now, approval_id),
        )

    # Slack 알림
    try:
        indicators = {"rsi": "-", "sma20": 0, "sma60": 0, "rt": 0}
        _slack_order(
            item["name"], item["symbol"], item["action"],
            item["qty"], item["price"],
            f"[대시보드 {approval_label}] {item.get('reason', '')}",
            status == "executed",
            indicators,
        )
    except Exception:
        pass

    return {"id": approval_id, "status": status, "response_msg": response_msg}


@app.post("/api/approvals/{approval_id}/approve")
def approve_order(approval_id: int):
    return _approve_pending_approval(approval_id, "수동승인")


@app.post("/api/approvals/{approval_id}/reject")
def reject_order(approval_id: int):
    _load_pending_approval(approval_id)
    now = trader.datetime.now(trader.KST).strftime("%Y-%m-%d %H:%M:%S")
    with trader.connect_db() as conn:
        conn.execute(
            "UPDATE approvals SET status = 'rejected', response_msg = 'Rejected by dashboard', updated_at = ? WHERE id = ?",
            (now, approval_id),
        )
    return {"id": approval_id, "status": "rejected"}


import time

_cloud_trades_cache = None
_cloud_trades_cache_time = 0

def fetch_cloud_trades():
    global _cloud_trades_cache, _cloud_trades_cache_time
    if _cloud_trades_cache is not None and time.time() - _cloud_trades_cache_time < 10:
        return [dict(t) for t in _cloud_trades_cache]
        
    try:
        subprocess.run(
            ["git", "fetch", "origin", "database:database"],
            check=False,
            capture_output=True,
            timeout=GIT_FETCH_TIMEOUT_SECONDS,
        )
        output = subprocess.check_output(
            ["git", "show", "origin/database:trades.json"],
            stderr=subprocess.STDOUT,
            timeout=GIT_FETCH_TIMEOUT_SECONDS,
        ).decode("utf-8")
        trades = json.loads(output)
        
        _cloud_trades_cache = trades
        _cloud_trades_cache_time = time.time()
        return [dict(t) for t in trades]
    except Exception as e:
        if _cloud_trades_cache is not None:
            return [dict(t) for t in _cloud_trades_cache]
        return []


def _load_merged_trades() -> list[dict]:
    cloud_trades = fetch_cloud_trades() or []
    local_trades = []
    with trader.connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades ORDER BY ts ASC").fetchall()
        local_trades = [dict(row) for row in rows]

    merged_trades = {}
    for t in cloud_trades + local_trades:
        ts = t.get("ts") or t.get("timestamp")
        if not ts:
            continue
        key = f"{ts}_{t.get('symbol')}_{t.get('action')}"
        merged_trades[key] = {
            "ts": ts,
            "symbol": t.get("symbol"),
            "name": t.get("name", t.get("symbol")),
            "action": t.get("action"),
            "qty": _to_int(t.get("qty")),
            "price": _to_int(t.get("price")),
            "reason": t.get("reason", ""),
            "ok": t.get("ok", 1),
            "env": t.get("env", "demo"),
            "dry_run": t.get("dry_run", 0),
        }
    return sorted(merged_trades.values(), key=lambda x: x["ts"])


def _trade_is_ok(trade: dict) -> bool:
    return bool(_to_int(trade.get("ok"), 1))


def _trade_is_dry_run(trade: dict) -> bool:
    return bool(_to_int(trade.get("dry_run"), 0))


def _trade_is_sync_adjustment(trade: dict) -> bool:
    reason = str(trade.get("reason") or "").lower()
    return any(token in reason for token in ("동기화", "보정", "sync", "adjust"))


def _account_trades(trades: list[dict]) -> list[dict]:
    return [
        trade
        for trade in trades
        if _trade_is_ok(trade)
        and not _trade_is_dry_run(trade)
        and not _trade_is_sync_adjustment(trade)
    ]


def _period_bucket() -> dict:
    return {
        "order_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "buy_amount": 0,
        "sell_amount": 0,
        "realized_pnl": 0,
        "net_cashflow": 0,
    }


def _build_periodic_performance(trades: list[dict]) -> dict:
    daily: dict[str, dict] = {}
    monthly: dict[str, dict] = {}
    holdings: dict[str, dict] = {}

    for trade in _account_trades(trades):
        ts = str(trade.get("ts") or "")
        if len(ts) < 10 or ts[0] == "-":
            continue

        day_key = ts[:10]
        month_key = ts[:7]
        action = str(trade.get("action") or "").lower()
        symbol = str(trade.get("symbol") or "")
        qty = _to_int(trade.get("qty"))
        price = _to_int(trade.get("price"))
        amount = qty * price

        if qty <= 0 or price <= 0 or action not in {"buy", "sell"}:
            continue

        day = daily.setdefault(day_key, _period_bucket())
        month = monthly.setdefault(month_key, _period_bucket())
        for bucket in (day, month):
            bucket["order_count"] += 1
            if action == "buy":
                bucket["buy_count"] += 1
                bucket["buy_amount"] += amount
            else:
                bucket["sell_count"] += 1
                bucket["sell_amount"] += amount

        if symbol not in holdings:
            holdings[symbol] = {"qty": 0, "avg_cost": 0.0}
        holding = holdings[symbol]

        if action == "buy":
            total_qty = holding["qty"] + qty
            total_cost = holding["qty"] * holding["avg_cost"] + amount
            holding["qty"] = total_qty
            holding["avg_cost"] = total_cost / total_qty if total_qty > 0 else 0.0
        else:
            sell_qty = min(qty, holding["qty"])
            realized = int((price - holding["avg_cost"]) * sell_qty)
            day["realized_pnl"] += realized
            month["realized_pnl"] += realized
            holding["qty"] = max(0, holding["qty"] - sell_qty)
            if holding["qty"] <= 0:
                holding["avg_cost"] = 0.0

    for rows in (daily, monthly):
        for bucket in rows.values():
            bucket["net_cashflow"] = bucket["sell_amount"] - bucket["buy_amount"]

    return {
        "daily": [{"period": key, **value} for key, value in sorted(daily.items())],
        "monthly": [{"period": key, **value} for key, value in sorted(monthly.items())],
    }


@app.post("/api/trades/sync")
def sync_trades():
    if trader.DRY_RUN:
        raise HTTPException(status_code=400, detail="모의 실행(DRY_RUN) 모드에서는 증권사 계좌 동기화를 사용할 수 없습니다.")
    try:
        api = _get_api()
        balance_data = _get_balance_data(api, allow_cache=False)
        parsed_balance = _parse_balance(balance_data)
        current_holdings = {h['symbol']: h for h in parsed_balance['holdings']}
        
        # Reconstruct current holdings from DB and Cloud
        cloud_trades = fetch_cloud_trades() or []
        local_trades = []
        with trader.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades ORDER BY ts ASC").fetchall()
            local_trades = [dict(row) for row in rows]
            
        merged_trades = {}
        for t in cloud_trades + local_trades:
            ts = t.get("ts") or t.get("timestamp")
            if not ts: continue
            key = f"{ts}_{t.get('symbol')}_{t.get('action')}"
            merged_trades[key] = t
            
        trades = _account_trades(sorted(merged_trades.values(), key=lambda x: x.get("ts", "")))
        
        db_holdings = {}
        names = {}
        for t in trades:
            if not t.get("ok", False): continue
            sym = t["symbol"]
            qty = t["qty"]
            names[sym] = t.get("name", sym)
            if sym not in db_holdings:
                db_holdings[sym] = 0
            if t["action"] == "buy":
                db_holdings[sym] += qty
            elif t["action"] == "sell":
                db_holdings[sym] = max(0, db_holdings[sym] - qty)
                
        synced_count = 0
        
        # 1. Sync missing buys (broker has more)
        for sym, ch in current_holdings.items():
            broker_qty = ch["qty"]
            db_qty = db_holdings.get(sym, 0)
            diff = broker_qty - db_qty
            
            if diff != 0:
                action = "buy" if diff > 0 else "sell"
                raw_stock = ch.get("_raw", {})
                price = int(float(raw_stock.get("pchs_avg_pric", ch["price"])))
                
                trader.save_trade(
                    symbol=sym,
                    name=ch["name"],
                    action=action,
                    qty=abs(diff),
                    price=price,
                    reason="증권사 잔고 강제 동기화 (수동/누락분 보정)",
                    ok=True,
                    order_submission_enabled=True
                )
                synced_count += 1
                
        # Calculate db average costs to use for selling missing items without affecting PnL
        db_costs = {}
        for t in trades:
            if not t.get("ok", False): continue
            sym = t["symbol"]
            qty = t["qty"]
            price = t["price"]
            if sym not in db_costs: db_costs[sym] = {"qty": 0, "cost": 0.0}
            if t["action"] == "buy":
                total_qty = db_costs[sym]["qty"] + qty
                total_cost = (db_costs[sym]["qty"] * db_costs[sym]["cost"]) + (qty * price)
                db_costs[sym]["qty"] = total_qty
                db_costs[sym]["cost"] = total_cost / total_qty if total_qty > 0 else 0
            elif t["action"] == "sell":
                db_costs[sym]["qty"] = max(0, db_costs[sym]["qty"] - qty)
                if db_costs[sym]["qty"] <= 0: db_costs[sym]["cost"] = 0

        # 2. Sync missing sells (broker has less or none)
        for sym, db_qty in db_holdings.items():
            if db_qty > 0 and sym not in current_holdings:
                avg_cost = int(db_costs.get(sym, {}).get("cost", 0))
                trader.save_trade(
                    symbol=sym,
                    name=names.get(sym, sym),
                    action="sell",
                    qty=db_qty,
                    price=avg_cost,  # Use avg_cost to avoid distorting Realized PnL

                    reason="증권사 잔고 강제 동기화 (전량매도 보정)",
                    ok=True,
                    order_submission_enabled=True
                )
                synced_count += 1
                
        return {"ok": True, "synced_count": synced_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trades")
def get_trades(limit: int = 50):
    try:
        cloud_trades = fetch_cloud_trades() or []
        local_trades = []
        with trader.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades ORDER BY ts ASC").fetchall()
            local_trades = [dict(row) for row in rows]
            
        merged_trades = {}
        for t in cloud_trades + local_trades:
            ts = t.get("ts") or t.get("timestamp")
            if not ts: continue
            key = f"{ts}_{t.get('symbol')}_{t.get('action')}"
            merged_trades[key] = {
                "ts": ts,
                "symbol": t.get("symbol"),
                "name": t.get("name", t.get("symbol")),
                "action": t.get("action"),
                "qty": t.get("qty", 0),
                "price": t.get("price", 0),
                "reason": t.get("reason", ""),
                "ok": t.get("ok", 1),
                "env": t.get("env", "demo"),
                "dry_run": t.get("dry_run", 0)
            }
            
        trades = sorted(_account_trades(list(merged_trades.values())), key=lambda x: x["ts"], reverse=True)
        return {"trades": trades[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance/periodic")
def get_periodic_performance():
    try:
        trades = _load_merged_trades()
        return _build_periodic_performance(trades)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance")
def get_performance():
    try:
        cloud_trades = fetch_cloud_trades() or []
        local_trades = []
        with trader.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades ORDER BY ts ASC").fetchall()
            local_trades = [dict(row) for row in rows]
            
        # Merge cloud and local trades
        # Use a dictionary keyed by timestamp and symbol to deduplicate
        merged_trades = {}
        for t in cloud_trades + local_trades:
            ts = t.get("ts") or t.get("timestamp")
            if not ts: continue
            key = f"{ts}_{t.get('symbol')}_{t.get('action')}"
            merged_trades[key] = {
                "ts": ts,
                "symbol": t.get("symbol"),
                "name": t.get("name", t.get("symbol")),
                "action": t.get("action"),
                "qty": t.get("qty", 0),
                "price": t.get("price", 0),
                "reason": t.get("reason", ""),
                "ok": t.get("ok", 1),
                "env": t.get("env", "demo"),
                "dry_run": t.get("dry_run", 0)
            }
            
        trades = _account_trades(sorted(merged_trades.values(), key=lambda x: x["ts"]))
        
        total_trades = len(trades)
        success_count = sum(1 for t in trades if t.get("ok", False))
        success_rate = (success_count / total_trades * 100) if total_trades > 0 else 0
        
        holdings = {}
        realized_pnl = 0
        names = {}
        
        for t in trades:
            if not t.get("ok", False): continue
            sym = t["symbol"]
            qty = t["qty"]
            price = t["price"]
            names[sym] = t.get("name", sym)
            
            if sym not in holdings:
                holdings[sym] = {"qty": 0, "cost": 0.0}
                
            if t["action"] == "buy":
                total_qty = holdings[sym]["qty"] + qty
                total_cost = (holdings[sym]["qty"] * holdings[sym]["cost"]) + (qty * price)
                holdings[sym]["qty"] = total_qty
                holdings[sym]["cost"] = total_cost / total_qty if total_qty > 0 else 0
            elif t["action"] == "sell":
                sell_qty = min(qty, holdings[sym]["qty"])
                profit = (price - holdings[sym]["cost"]) * sell_qty
                realized_pnl += profit
                holdings[sym]["qty"] -= sell_qty
                if holdings[sym]["qty"] <= 0:
                    holdings[sym]["qty"] = 0
                    holdings[sym]["cost"] = 0
                    
        # Fetch current prices to calculate evaluation PnL
        current_holdings = {}
        total_broker_pnl = 0
        try:
            api = _get_api()
            balance_data = _get_balance_data(api)
            parsed_balance = _parse_balance(balance_data)
            current_holdings = {h['symbol']: h for h in parsed_balance['holdings']}
            total_broker_pnl = parsed_balance.get("pnl", 0)
        except Exception:
            pass

        # 사용자 요청: 불일치가 발생하면 증권사 정보로 맞춰서 보정
        # 자동매매 기록(trades.json)으로 추적한 보유량 대신, 증권사 실제 잔고를 강제로 덮어씌움 (단, DRY_RUN일 때는 DB 우선)
        eval_details = []
        total_eval_pnl = total_broker_pnl
        
        if trader.DRY_RUN:
            total_eval_pnl = 0
            for sym, data in holdings.items():
                if data["qty"] > 0:
                    current_price = data["cost"]
                    if sym in current_holdings:
                        current_price = current_holdings[sym]["price"]
                    else:
                        try:
                            q = api.get_quote(sym)
                            current_price = q["current"]
                        except Exception:
                            pass
                    
                    eval_pnl = (current_price - data["cost"]) * data["qty"]
                    return_rate = ((current_price / data["cost"]) - 1) * 100 if data["cost"] > 0 else 0
                    total_eval_pnl += eval_pnl
                    
                    eval_details.append({
                        "symbol": sym,
                        "name": names.get(sym, sym),
                        "qty": data["qty"],
                        "avg_cost": data["cost"],
                        "current_price": current_price,
                        "eval_pnl": int(eval_pnl),
                        "return_rate": round(return_rate, 2),
                        "broker_qty": current_holdings.get(sym, {}).get("qty", 0),
                        "broker_pnl": int(current_holdings.get(sym, {}).get("pnl", 0)),
                        "diff_reason": "모의 실행(DRY_RUN) 중"
                    })
        else:
            for sym, ch in current_holdings.items():
                raw_stock = ch.get("_raw", {})
                avg_cost = float(raw_stock.get("pchs_avg_pric", 0)) if raw_stock.get("pchs_avg_pric") else 0
                
                if avg_cost == 0 and ch["qty"] > 0:
                    avg_cost = ch["price"] - (ch["pnl"] / ch["qty"])
                    
                recorded_qty = holdings.get(sym, {}).get("qty", 0)
                diff_reason = ""
                if recorded_qty == 0:
                    diff_reason = "수동매수/기록누락 보정 완료"
                elif recorded_qty != ch["qty"]:
                    diff_reason = f"수량 불일치({recorded_qty}주->{ch['qty']}주) 보정 완료"
                    
                eval_details.append({
                    "symbol": sym,
                    "name": ch["name"],
                    "qty": ch["qty"],
                    "avg_cost": avg_cost,
                    "current_price": ch["price"],
                    "eval_pnl": int(ch["pnl"]),
                    "return_rate": round(ch["rt"], 2),
                    "broker_qty": ch["qty"],
                    "broker_pnl": int(ch["pnl"]),
                    "diff_reason": diff_reason
                })

        untracked_details = [] # 더 이상 사용하지 않음 (모두 eval_details로 흡수)
                    
        return {
            "total_trades": total_trades,
            "success_rate": round(success_rate, 2),
            "realized_pnl": int(realized_pnl),
            "total_eval_pnl": int(total_eval_pnl),
            "total_broker_pnl": int(total_broker_pnl),
            "eval_details": eval_details,
            "untracked_details": untracked_details
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/risk/status")
def get_risk_status():
    try:
        api = _get_api()
        balance_data = _get_balance_data(api, allow_cache=True)
        parsed = _parse_balance(balance_data)
        
        total_capital = trader.TOTAL_CAPITAL
        pnl = parsed.get("pnl", 0)
        loss_pct = abs(pnl) / total_capital * 100 if total_capital > 0 and pnl < 0 else 0
        max_daily_loss = getattr(trader.config, "max_daily_loss_pct", 3.0)
        
        return {
            "total_capital": total_capital,
            "current_total": parsed.get("total_eval", 0),
            "stock_eval": parsed.get("stock_eval", 0),
            "cash": parsed.get("cash", 0),
            "cash_ratio": parsed.get("cash_ratio", 0),
            "stock_ratio": parsed.get("stock_ratio", 0),
            "daily_pnl": pnl,
            "daily_loss_pct": round(loss_pct, 2),
            "max_daily_loss_pct": max_daily_loss,
            "halted": loss_pct >= max_daily_loss or Path(".runtime/kill_switch.json").exists()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/decisions/history")
def get_decision_history(limit: int = 50):
    try:
        with trader.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM decision_logs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            logs = [dict(row) for row in rows]
            for log in logs:
                if isinstance(log.get("indicators"), str):
                    try:
                        log["indicators"] = json.loads(log["indicators"])
                    except:
                        pass
            return {"decisions": logs}
    except Exception as e:
        return {"decisions": []}

@app.post("/api/system/kill")
def activate_kill_switch():
    kill_file = Path(".runtime/kill_switch.json")
    kill_file.parent.mkdir(parents=True, exist_ok=True)
    with open(kill_file, "w") as f:
        json.dump({"active": True, "ts": trader.datetime.now(trader.KST).isoformat()}, f)
    return {"ok": True, "msg": "Kill switch activated"}

@app.post("/api/system/unkill")
def deactivate_kill_switch():
    kill_file = Path(".runtime/kill_switch.json")
    if kill_file.exists():
        kill_file.unlink()
    return {"ok": True, "msg": "Kill switch deactivated"}

