from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Callable


@dataclass(frozen=True)
class ApprovalRecord:
    id: int
    created_at: str
    updated_at: str
    symbol: str
    name: str
    action: str
    qty: int
    price: int
    reason: str
    source: str
    status: str
    response_msg: str


def _approval_record_from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        symbol=str(row["symbol"]),
        name=str(row["name"]),
        action=str(row["action"]),
        qty=int(row["qty"]),
        price=int(row["price"]),
        reason=str(row["reason"] or ""),
        source=str(row["source"] or ""),
        status=str(row["status"]),
        response_msg=str(row["response_msg"] or ""),
    )


class ApprovalRepository:
    def __init__(self, connect_fn: Callable[[], sqlite3.Connection]) -> None:
        self._connect_fn = connect_fn

    def init_db(self) -> None:
        with self._connect_fn() as conn:
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

    def create_approval(
        self,
        *,
        created_at: str,
        updated_at: str,
        symbol: str,
        name: str,
        action: str,
        qty: int,
        price: int,
        reason: str,
        source: str,
        status: str = "pending",
        response_msg: str = "",
    ) -> int:
        with self._connect_fn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO approvals
                (created_at, updated_at, symbol, name, action, qty, price, reason, source, status, response_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    updated_at,
                    symbol,
                    name,
                    action,
                    qty,
                    price,
                    reason,
                    source,
                    status,
                    response_msg,
                ),
            )
            return int(cursor.lastrowid)

    def get_approval(self, approval_id: int) -> ApprovalRecord | None:
        with self._connect_fn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return _approval_record_from_row(row)

    def list_approvals(self, *, limit: int) -> list[ApprovalRecord]:
        with self._connect_fn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM approvals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_approval_record_from_row(row) for row in rows]

    def update_approval_status(
        self,
        approval_id: int,
        *,
        status: str,
        response_msg: str,
        updated_at: str,
    ) -> bool:
        with self._connect_fn() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET status = ?, response_msg = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, response_msg, updated_at, approval_id),
            )
            return cursor.rowcount > 0
