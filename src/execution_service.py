from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExecutionContext:
    dry_run: bool
    trading_env: str
    enable_live_trading: bool
    require_approval: bool
    analysis_only: bool = False


@dataclass(frozen=True)
class ExecutionDecision:
    decision: str
    reason: str


@dataclass(frozen=True)
class ExecutionResult:
    decision: str
    ok: bool
    response_msg: str
    broker_result: dict | None = None
    approval_id: int | None = None


def resolve_execution_decision(
    context: ExecutionContext,
    *,
    allow_approval_bypass: bool = False,
) -> ExecutionDecision:
    if context.analysis_only:
        return ExecutionDecision("queue", "analysis_only mode")
    if context.require_approval and not allow_approval_bypass:
        return ExecutionDecision("queue", "approval required")
    if context.dry_run:
        return ExecutionDecision("execute", "dry_run simulation")
    if context.trading_env == "real" and not context.enable_live_trading:
        return ExecutionDecision("reject", "live trading switch disabled")
    return ExecutionDecision("execute", "execution allowed")


def submit_order_request(
    *,
    context: ExecutionContext,
    symbol: str,
    name: str,
    action: str,
    qty: int,
    price: int,
    reason: str,
    source: str,
    execute_order_fn: Callable[[str, str, int, int], dict],
    save_trade_fn: Callable[[str, str, str, int, int, str, bool], None],
    queue_order_fn: Callable[[str, str, str, int, int, str, str], int] | None = None,
    allow_approval_bypass: bool = False,
) -> ExecutionResult:
    policy = resolve_execution_decision(context, allow_approval_bypass=allow_approval_bypass)
    if policy.decision == "queue":
        if queue_order_fn is None:
            return ExecutionResult("reject", False, "approval queue unavailable")
        approval_id = queue_order_fn(symbol, name, action, qty, price, reason, source)
        return ExecutionResult("queue", True, policy.reason, approval_id=approval_id)
    if policy.decision == "reject":
        return ExecutionResult("reject", False, policy.reason)

    broker_result = execute_order_fn(symbol, action, price, qty)
    ok = broker_result.get("rt_cd") == "0"
    response_msg = str(broker_result.get("msg1", policy.reason))
    save_trade_fn(symbol, name, action, qty, price, reason, ok)
    return ExecutionResult(
        "execute",
        ok,
        response_msg,
        broker_result=broker_result,
    )
