import json
import os
import sqlite3
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from src import trader  # noqa: E402
from src.trader import KIStockAPI  # noqa: E402


app = FastAPI(title="Seven Split Dashboard", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
DB_PATH = trader.DB_PATH
FINRL_DIR = BASE_DIR / "vendor" / "FinRL"
BALANCE_CACHE = trader.RUNTIME_DIR / "balance_snapshot.json"
CANDIDATE_CACHE = trader.RUNTIME_DIR / "candidate_snapshot.json"
CANDIDATE_CACHE_TTL_SECONDS = int(os.environ.get("CANDIDATE_CACHE_TTL_SECONDS", "180"))
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
    return [name for name in required if not os.environ.get(name)]


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


def _parse_balance(balance_data: dict) -> dict:
    if balance_data.get("_error"):
        raise RuntimeError(balance_data["_error"])

    stocks = balance_data.get("output1", [])
    first_summary = _summary_item(balance_data.get("output2", [{}]))

    holdings = []
    for stock in stocks:
        qty = _to_int(stock.get("hldg_qty"))
        price = _to_int(stock.get("prpr"))
        holdings.append({
            "symbol": stock.get("pdno", ""),
            "name": stock.get("prdt_name", stock.get("pdno", "")),
            "qty": qty,
            "price": price,
            "rt": _to_float(stock.get("evlu_pfls_rt")),
            "pnl": _to_int(stock.get("evlu_pfls_amt")),
            "value": qty * price,
            "_raw": stock,
        })

    return {
        "cash": _to_int(first_summary.get("dnca_tot_amt")),
        "total_eval": _to_int(first_summary.get("tot_evlu_amt")),
        "pnl": _to_int(first_summary.get("evlu_pfls_smtl_amt")),
        "holdings": holdings,
    }


def _get_api() -> KIStockAPI:
    return KIStockAPI(notify_errors=False)


def _save_balance_cache(balance_data: dict) -> None:
    BALANCE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BALANCE_CACHE.write_text(
        json.dumps({
            "cached_at": trader.datetime.now(trader.KST).isoformat(),
            "trading_env": trader.TRADING_ENV,
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
    data = cached.get("data")
    if not isinstance(data, dict):
        return None
    data["_cache"] = {"stale": True, "cached_at": cached.get("cached_at", "")}
    return data


def _get_balance_data(api: KIStockAPI, allow_cache: bool = True) -> dict:
    if allow_cache:
        cached = _load_balance_cache()
        if cached is not None:
            cached_at = cached.get("_cache", {}).get("cached_at", "")
            if cached_at:
                try:
                    age = (trader.datetime.now(trader.KST) - trader.datetime.fromisoformat(cached_at)).total_seconds()
                    if age < 3:
                        return cached
                except Exception:
                    pass
    try:
        balance_data = api.get_balance()
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


def _approval_row(row: sqlite3.Row) -> dict:
    return dict(row)


@app.get("/", response_class=FileResponse)
async def read_root():
    return FileResponse(WEB_DIR / "templates" / "index.html")


@app.get("/finrl", response_class=FileResponse)
async def read_finrl_dashboard():
    return FileResponse(WEB_DIR / "templates" / "finrl.html")


@app.get("/vendors", response_class=FileResponse)
async def read_vendor_dashboard():
    return FileResponse(WEB_DIR / "templates" / "vendors.html")


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
async def health():
    missing = _required_env_missing()
    return {
        "ok": not missing,
        "missing": missing,
        "trading_env": trader.TRADING_ENV,
        "dry_run": trader.DRY_RUN,
        "enable_live_trading": trader.ENABLE_LIVE_TRADING,
        "require_approval": trader.REQUIRE_APPROVAL,
        "order_submission_enabled": trader.ORDER_SUBMISSION_ENABLED,
        "real_orders_enabled": trader.REAL_ORDERS_ENABLED,
        "circuit_breaker": KIStockAPI.circuit_status(),
    }


@app.get("/api/config")
async def get_config():
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


@app.post("/api/circuit-breaker/reset")
async def reset_circuit_breaker():
    KIStockAPI.reset_circuit()
    return {"ok": True, "circuit_breaker": KIStockAPI.circuit_status()}


@app.get("/api/balance")
async def get_balance():
    missing = _required_env_missing()
    if missing:
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
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"KIS API request failed: {e}") from e


@app.get("/api/signals")
async def get_signals():
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
async def get_candidates(min_score: int = 2):
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
        orders = trader.build_orders(candidates, api.get_quote, len(held_symbols), parsed["cash"])
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
async def get_ai_allocation():
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
async def get_portfolio_optimizer():
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
async def get_finrl_status():
    return _vendor_status("finrl", VENDOR_PROJECTS["finrl"])


@app.get("/api/vendors")
async def get_vendors():
    return {"vendors": [_vendor_status(slug, meta) for slug, meta in VENDOR_PROJECTS.items()]}


@app.get("/api/vendors/{slug}")
async def get_vendor(slug: str):
    if slug not in VENDOR_PROJECTS:
        raise HTTPException(status_code=404, detail="vendor not found")
    return _vendor_status(slug, VENDOR_PROJECTS[slug])


@app.get("/api/finrl/pipeline")
async def get_finrl_pipeline():
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
async def get_approvals(limit: int = 50):
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
async def create_approval(payload: dict = Body(...)):
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


@app.post("/api/approvals/{approval_id}/approve")
async def approve_order(approval_id: int):
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
    return {"id": approval_id, "status": status, "response_msg": response_msg}


@app.post("/api/approvals/{approval_id}/reject")
async def reject_order(approval_id: int):
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
        subprocess.run(["git", "fetch", "origin", "database:database"], check=False, capture_output=True)
        output = subprocess.check_output(["git", "show", "origin/database:trades.json"], stderr=subprocess.STDOUT).decode('utf-8')
        trades = json.loads(output)
        
        _cloud_trades_cache = trades
        _cloud_trades_cache_time = time.time()
        return [dict(t) for t in trades]
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        return [{"ts": "-", "symbol": "ERROR", "name": f"ERROR: {err_msg}", "action": "buy", "qty": 0, "price": 0, "reason": str(e), "ok": 0}]

@app.post("/api/trades/sync")
async def sync_trades():
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
            
        trades = sorted(merged_trades.values(), key=lambda x: x.get("ts", ""))
        
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
async def get_trades(limit: int = 50):
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
            
        trades = sorted(merged_trades.values(), key=lambda x: x["ts"], reverse=True)
        return {"trades": trades[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/performance")
async def get_performance():
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
            
        trades = sorted(merged_trades.values(), key=lambda x: x["ts"])
        
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
