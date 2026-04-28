"""
Seven Split auto-trading engine (Refactored).
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.config import config
from src.utils.logger import logger
from src.api.kis_api import KIStockAPI
from src.db.repository import init_db, connect_db, save_trade
from src.notifier.slack import slack_session_start, slack_order, slack_candidates, slack_session_end, slack_error
from src.strategy.seven_split import (
    WATCHLIST, KOSPI_UNIVERSE, STOCK_NAMES,
    check_daily_loss, generate_signal, build_scan_universe, find_candidates, build_orders,
    generate_ai_weight_plan, generate_portfolio_optimizer_plan
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

def check_secrets():
    pass

def run() -> None:
    logger.info("=" * 60)
    logger.info(f"Seven Split started | DRY_RUN={DRY_RUN} | ENABLE_LIVE_TRADING={ENABLE_LIVE_TRADING} | ENV={TRADING_ENV}")
    logger.info(f"Order submission enabled: {ORDER_SUBMISSION_ENABLED} | Real orders enabled: {REAL_ORDERS_ENABLED}")
    logger.info("=" * 60)

    init_db()
    api = KIStockAPI()

    balance = api.get_balance()
    stocks = balance.get("output1", [])
    summary = balance.get("output2", [{}])[0]
    cash = int(summary.get("dnca_tot_amt", 0))
    total_eval = int(summary.get("tot_evlu_amt", 0))
    pnl = int(summary.get("evlu_pfls_smtl_amt", 0))

    logger.info(f"Cash={cash:,} KRW | Total={total_eval:,} KRW | PnL={pnl:+,} KRW | Holdings={len(stocks)}")
    slack_session_start(cash=cash, total=total_eval, stock_count=len(stocks), order_submission_enabled=ORDER_SUBMISSION_ENABLED, real_orders_enabled=REAL_ORDERS_ENABLED)

    daily_loss_halt = check_daily_loss(pnl)
    results = []
    held_symbols: set[str] = set()

    for stock in stocks:
        sym = stock.get("pdno", "")
        name = stock.get("prdt_name", sym)
        rt = float(stock.get("evlu_pfls_rt", 0))
        held_symbols.add(sym)
        logger.info(f"--- {name}({sym}) return={rt:+.2f}% ---")

        daily = api.get_daily(sym, n=60)
        signal = generate_signal(stock, daily)
        indicators = signal["indicators"]
        logger.info(
            f"Indicators: RSI={indicators['rsi']} "
            f"SMA20={indicators['sma20']:.0f} SMA60={indicators['sma60']:.0f} "
            f"BB({indicators['bb_lo']:.0f}~{indicators['bb_hi']:.0f})"
        )
        logger.info(f"Signal: {signal['action'].upper()} - {signal['reason']}")

        if signal["action"] == "hold":
            continue
        if signal["action"] == "buy":
            if daily_loss_halt:
                logger.info("[SKIP] Daily loss halt active")
                continue
            cost = signal["qty"] * signal["price"]
            if cost > cash:
                logger.info(f"[SKIP] Not enough cash: need={cost:,}, cash={cash:,}")
                continue

        result = api.place_order(sym, signal["action"], signal["price"], signal["qty"])
        ok = result.get("rt_cd") == "0"
        logger.info(f"Order {'OK' if ok else 'FAILED'}: {result.get('msg1', '')}")
        save_trade(sym, name, signal["action"], signal["qty"], signal["price"], signal["reason"], ok, ORDER_SUBMISSION_ENABLED)
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
        logger.info("--- Scanning for new buy candidates (AI universe) ---")
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
                logger.info(f"--- New BUY {sym} qty={qty} price={price:,} ---")
                result = api.place_order(sym, "buy", price, qty)
                ok = result.get("rt_cd") == "0"
                logger.info(f"Order {'OK' if ok else 'FAILED'}: {result.get('msg1', '')}")
                save_trade(sym, sym, "buy", qty, price, reason, ok, ORDER_SUBMISSION_ENABLED)
                indicators = {"rsi": "-", "sma20": 0, "sma60": 0, "rt": 0}
                results.append({"name": sym, "symbol": sym, "action": "buy", "qty": qty, "price": price, "reason": reason, "ok": ok, "indicators": indicators})
                slack_order(sym, sym, "buy", qty, price, reason, ok, indicators)
                if ok:
                    cash -= qty * price
        else:
            scanned = result["scanned"]
            top = result["scan_summary"][:5]
            logger.info(f"[INFO] 매수 후보 없음 — {scanned}종목 분석, 기준점수 {result['min_score']}점")
            for item in top:
                logger.info(f"  {item['ticker']} score={item['score']} rsi={item['rsi']:.0f} reasons={item['reasons']}")

    if not results:
        logger.info("No orders generated")
    slack_session_end(results=results, cash=cash, total=total_eval, pnl=pnl)
    logger.info("Seven Split finished")

if __name__ == "__main__":
    run()
