import json
from src.config import config
from src.utils.logger import logger
from src.db.repository import save_trade, save_decision_log
from src.api.kis_api import KIStockAPI

class OrderRouter:
    def __init__(self, api: KIStockAPI):
        self.api = api
        self.dry_run = config.dry_run
        self.env = config.trading_env
        self.enable_live = config.enable_live_trading
        self.require_approval = config.require_approval
        
        self.real_orders_enabled = (not self.dry_run) and self.env == "real" and self.enable_live
        self.submission_enabled = (not self.dry_run) and (self.env == "demo" or self.real_orders_enabled)

    def route(self, symbol: str, name: str, action: str, qty: int, price: int, reason: str, indicators: dict) -> dict:
        # Decision Log 기록
        save_decision_log(symbol, name, action, qty, price, reason, indicators, True)
        
        if not self.submission_enabled:
            logger.info(f"[ROUTER] Paper Trading: {action} {name} qty={qty}")
            save_trade(symbol, name, action, qty, price, reason, True, False)
            return {"ok": True, "msg": "Paper trading executed", "status": "paper"}

        if self.require_approval:
            # 대기열(approvals)에 넣기
            self._insert_approval(symbol, name, action, qty, price, reason)
            logger.info(f"[ROUTER] Pending Approval: {action} {name} qty={qty}")
            return {"ok": True, "msg": "Added to approval queue", "status": "pending"}
            
        # 직접 KIS API 호출
        result = self.api.place_order(symbol, action, price, qty)
        ok = result.get("rt_cd") == "0"
        logger.info(f"[ROUTER] Live Execution {'OK' if ok else 'FAILED'}: {result.get('msg1', '')}")
        save_trade(symbol, name, action, qty, price, reason, ok, True)
        return {"ok": ok, "msg": result.get("msg1", ""), "status": "live"}

    def _insert_approval(self, symbol: str, name: str, action: str, qty: int, price: int, reason: str) -> None:
        from src.db.repository import connect_db
        from datetime import datetime, timezone, timedelta
        
        KST = timezone(timedelta(hours=9))
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with connect_db() as conn:
                conn.execute("""
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
                """)
                conn.execute(
                    """
                    INSERT INTO approvals
                    (created_at, updated_at, symbol, name, action, qty, price, reason, source, status, response_msg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '')
                    """,
                    (now, now, symbol, name, action, qty, price, reason, 'auto_trader'),
                )
        except Exception as e:
            logger.error(f"[ROUTER] Failed to insert approval: {e}")
