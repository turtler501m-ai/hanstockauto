import sqlite3
import os
import json
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from datetime import datetime, timedelta, timezone
from src.config import config
from src.utils.logger import logger

KST = timezone(timedelta(hours=9))

class DBWrapper:
    def __init__(self, conn, is_pg=False):
        self.conn = conn
        self.is_pg = is_pg

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.__exit__(exc_type, exc_val, exc_tb)

    def execute(self, sql, params=()):
        if self.is_pg:
            sql = sql.replace("?", "%s")
            if "AUTOINCREMENT" in sql:
                sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            
            cursor = self.conn.cursor(cursor_factory=DictCursor)
        else:
            cursor = self.conn.cursor()
            
        cursor.execute(sql, params)
        return cursor
        
    def commit(self):
        self.conn.commit()
        
    @property
    def row_factory(self):
        if self.is_pg:
            return None
        return self.conn.row_factory
        
    @row_factory.setter
    def row_factory(self, factory):
        if not self.is_pg:
            self.conn.row_factory = factory

def connect_db():
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.startswith("postgres"):
        conn = psycopg2.connect(db_url)
        return DBWrapper(conn, is_pg=True)
    else:
        db_path = Path(config.trade_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=MEMORY")
        return DBWrapper(conn, is_pg=False)

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price INTEGER NOT NULL,
                reason TEXT,
                indicators TEXT,
                approved INTEGER NOT NULL
            )
            """
        )

def save_trade(symbol: str, name: str, action: str, qty: int, price: int, reason: str, ok: bool, order_submission_enabled: bool) -> None:
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO trades (ts, symbol, name, action, qty, price, reason, ok, env, dry_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, symbol, name, action, qty, price, reason, int(ok), config.trading_env, int(not order_submission_enabled)),
            )
            
            # Export to JSON for cloud sync
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT ts, symbol, name, action, qty, price, reason, ok, env, dry_run FROM trades ORDER BY ts ASC").fetchall()
            trades = [dict(row) for row in rows]
            
        # Use data/trades.json for GitHub Actions
        data_json_path = Path("data/trades.json")
        data_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(data_json_path, "w", encoding="utf-8") as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
            
    except Exception as e:
        logger.warning(f"Failed to save trade history: {e}")

def save_decision_log(symbol: str, name: str, action: str, qty: int, price: int, reason: str, indicators: dict, approved: bool) -> None:
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO decision_logs (ts, symbol, name, action, qty, price, reason, indicators, approved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, symbol, name, action, qty, price, reason, json.dumps(indicators, ensure_ascii=False), int(approved))
            )
    except Exception as e:
        logger.warning(f"Failed to save decision log: {e}")
