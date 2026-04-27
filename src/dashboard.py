import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from src.approval_service import ApprovalCreateRequest, ApprovalNotFoundError, ApprovalStatusError  # noqa: E402
from src.execution_service import submit_order_request  # noqa: E402
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
    trader.init_approval_db()


def _approval_row(row: object) -> dict:
    return asdict(row)


def _build_signal_row(holding: dict, signal: dict) -> dict:
    indicators = signal.get("indicators", {})
    return {
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
    }


def build_dashboard_signals(api: KIStockAPI, parsed: dict) -> list[dict]:
    rows = []
    for holding in parsed["holdings"]:
        daily = api.get_daily(holding["symbol"], n=60)
        signal = trader.generate_signal(holding["_raw"], daily)
        rows.append(_build_signal_row(holding, signal))
    return rows


def _build_candidate_row(candidate: dict, order: dict, universe_size: int) -> dict:
    return {
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
        "universe_size": universe_size,
    }


def build_dashboard_candidates(api: KIStockAPI, parsed: dict, min_score: int = 2) -> dict:
    held_symbols = {holding["symbol"] for holding in parsed["holdings"]}
    universe = trader.build_scan_universe(api, held_symbols)
    result = trader.find_candidates(held_symbols, universe=universe, min_score=min_score)
    candidates = result["candidates"]
    orders = trader.build_orders(candidates, api.get_quote, len(held_symbols), parsed["cash"])
    order_by_symbol = {order["ticker"]: order for order in orders}
    rows = [
        _build_candidate_row(candidate, order_by_symbol.get(candidate["ticker"], {}), len(universe))
        for candidate in candidates
    ]
    return {
        "candidates": rows,
        "universe_size": len(universe),
        "scanned": result["scanned"],
        "min_score": min_score,
        "scan_summary": result["scan_summary"],
        "scan_error": result.get("scan_error"),
    }


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
        return {"signals": build_dashboard_signals(api, parsed)}
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
        payload = build_dashboard_candidates(api, parsed, min_score=min_score)
        scanned = payload["scanned"]
        # scanned=0 은 yfinance 실패 등 데이터 수신 오류 — 캐시하지 않음
        if scanned > 0:
            _save_candidate_cache(min_score, payload["candidates"], payload["scan_summary"], scanned)
        return payload
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Candidate scan failed: {e}") from e


def build_dashboard_execution_plan() -> dict:
    api = _get_api()
    balance_data = _get_balance_data(api)
    parsed = _parse_balance(balance_data)
    bundle = trader.build_runtime_plan(api, balance_data)
    return {
        "mode": "dashboard",
        "plan": bundle["plan"],
        "cash": parsed["cash"],
        "remaining_cash": bundle["remaining_cash"],
        "total_eval": parsed["total_eval"],
        "pnl": parsed["pnl"],
        "daily_loss_halt": bundle["daily_loss_halt"],
        "scanned": bundle["candidate_scan"]["scanned"],
        "scan_error": bundle["candidate_scan"].get("scan_error"),
    }


@app.get("/api/execution-plan")
async def get_execution_plan():
    missing = _required_env_missing()
    if missing:
        raise HTTPException(status_code=503, detail=f"Missing environment variables: {', '.join(missing)}")

    try:
        return build_dashboard_execution_plan()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Execution plan failed: {e}") from e


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


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be greater than 0")
    limit = min(limit, 200)

    trader.init_db()

    try:
        with trader.connect_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            return {"trades": [dict(row) for row in cursor.fetchall()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trade database query failed: {e}") from e


@app.get("/api/approvals")
async def get_approvals(limit: int = 50):
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be greater than 0")
    limit = min(limit, 200)

    rows = trader.get_approval_service().list_approvals(limit=limit)
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
    approval_id = trader.get_approval_service().create_approval(
        ApprovalCreateRequest(
            symbol=symbol,
            name=name,
            action=action,
            qty=qty,
            price=price,
            reason=reason,
            source=source,
        )
    )
    return {"id": approval_id, "status": "pending"}


def _load_pending_approval(approval_id: int) -> dict:
    service = trader.get_approval_service()
    try:
        row = service.get_pending_approval(approval_id)
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ApprovalStatusError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _approval_row(row)


@app.post("/api/approvals/{approval_id}/approve")
async def approve_order(approval_id: int):
    item = _load_pending_approval(approval_id)
    try:
        api = _get_api()
        execution = submit_order_request(
            context=trader.build_execution_context("execute"),
            symbol=item["symbol"],
            name=item["name"],
            action=item["action"],
            qty=item["qty"],
            price=item["price"],
            reason=item["reason"],
            source=item.get("source") or "dashboard",
            execute_order_fn=api.place_order,
            save_trade_fn=trader.save_trade,
            allow_approval_bypass=True,
        )
        status = "executed" if execution.ok and execution.decision == "execute" else "failed"
        response_msg = execution.response_msg
    except Exception as e:
        status = "failed"
        response_msg = str(e)

    trader.get_approval_service().update_status(
        approval_id,
        status=status,
        response_msg=response_msg,
    )
    return {"id": approval_id, "status": status, "response_msg": response_msg}


@app.post("/api/approvals/{approval_id}/reject")
async def reject_order(approval_id: int):
    try:
        trader.get_approval_service().reject_approval(approval_id)
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ApprovalStatusError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"id": approval_id, "status": "rejected"}
