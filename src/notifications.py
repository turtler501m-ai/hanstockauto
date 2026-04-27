from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


KST = timezone(timedelta(hours=9))


def format_kst_timestamp(value: datetime | None = None, fmt: str = "%Y-%m-%d %H:%M KST") -> str:
    current = value or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    else:
        current = current.astimezone(KST)
    return current.strftime(fmt)


def build_slack_payload(
    text: str = "",
    blocks: list[dict[str, Any]] | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if text:
        payload["text"] = text
    if color:
        attachment: dict[str, Any] = {"color": color}
        if blocks:
            attachment["blocks"] = blocks
        if text:
            attachment["fallback"] = text
        payload["attachments"] = [attachment]
        return payload
    if blocks:
        payload["blocks"] = blocks
    return payload


def post_slack_payload(
    webhook_url: str,
    payload: dict[str, Any],
    session: Any,
    timeout: int = 10,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    if not webhook_url:
        return False
    try:
        response = session.post(webhook_url, json=payload, timeout=timeout)
        if response.status_code != 200:
            if log_fn:
                log_fn(f"[WARN] Slack send failed HTTP {response.status_code}: {response.text[:100]}")
            return False
        return True
    except Exception as exc:  # pragma: no cover - exercised via tests with a fake session
        if log_fn:
            log_fn(f"[WARN] Slack exception: {exc}")
        return False


def send_slack_message(
    webhook_url: str,
    session: Any,
    text: str = "",
    blocks: list[dict[str, Any]] | None = None,
    color: str | None = None,
    timeout: int = 10,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    payload = build_slack_payload(text=text, blocks=blocks, color=color)
    return post_slack_payload(
        webhook_url=webhook_url,
        payload=payload,
        session=session,
        timeout=timeout,
        log_fn=log_fn,
    )


def build_session_start_payload(
    cash: int,
    total: int,
    stock_count: int,
    *,
    now: datetime | None = None,
    mode: str,
    trading_env: str,
) -> dict[str, Any]:
    ts = format_kst_timestamp(now)
    return build_slack_payload(
        text=f"Seven Split started at {ts}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Seven Split Auto Trading"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Time*\n{ts}"},
                {"type": "mrkdwn", "text": f"*Mode*\n{mode}"},
                {"type": "mrkdwn", "text": f"*API Env*\n{trading_env}"},
                {"type": "mrkdwn", "text": f"*Cash*\n{cash:,} KRW"},
                {"type": "mrkdwn", "text": f"*Total Value*\n{total:,} KRW"},
                {"type": "mrkdwn", "text": f"*Holdings*\n{stock_count}"},
            ]},
        ],
        color="#2196F3",
    )


def build_order_payload(
    name: str,
    symbol: str,
    action: str,
    qty: int,
    price: int,
    reason: str,
    ok: bool,
    indicators: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = indicators or {}
    action_label = "BUY" if action == "buy" else "SELL"
    status = "OK" if ok else "FAILED"
    price_str = f"{price:,} KRW" if price else "market"
    amount_str = f"{qty * price:,} KRW" if price else "-"
    rsi_value = details.get("rsi", "-")
    rsi_str = f"{rsi_value:.1f}" if isinstance(rsi_value, float) else str(rsi_value)
    return build_slack_payload(
        text=f"{action_label} {name} {qty} shares {status}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{action_label}* {name} (`{symbol}`) {status}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Qty*\n{qty}"},
                {"type": "mrkdwn", "text": f"*Price*\n{price_str}"},
                {"type": "mrkdwn", "text": f"*Amount*\n{amount_str}"},
                {"type": "mrkdwn", "text": f"*RSI*\n{rsi_str}"},
                {"type": "mrkdwn", "text": f"*SMA20/60*\n{details.get('sma20', 0):.0f} / {details.get('sma60', 0):.0f}"},
                {"type": "mrkdwn", "text": f"*Return*\n{details.get('rt', 0):+.2f}%"},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Reason: {reason}"}]},
        ],
        color="#36a64f" if ok else "#e74c3c",
    )


def build_candidates_payload(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    lines = [
        f"*{item['ticker']}* {item['current_price']:,.0f} KRW | score {item['score']} | {', '.join(item['reasons'])}"
        for item in candidates
    ]
    return build_slack_payload(
        text=f"New buy candidates: {len(candidates)}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Buy Candidates"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ],
        color="#9C27B0",
    )


def build_session_end_payload(
    results: list[dict[str, Any]],
    cash: int,
    total: int,
    pnl: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    ts = format_kst_timestamp(now)
    if not results:
        return build_slack_payload(
            text=f"Seven Split finished at {ts}: no orders",
            color="#9E9E9E",
        )

    executed = [item for item in results if item.get("decision", "execute") == "execute"]
    queued_count = sum(1 for item in results if item.get("decision") == "queue")
    buy_count = sum(1 for item in executed if item["action"] == "buy" and item["ok"])
    sell_count = sum(1 for item in executed if item["action"] == "sell" and item["ok"])
    fail_count = sum(1 for item in executed if not item["ok"])
    lines = []
    for item in results:
        prefix = "QUEUED" if item.get("decision") == "queue" else item["action"].upper()
        lines.append(f"{prefix} {item['name']} {item['qty']} shares - {item['reason']}")

    return build_slack_payload(
        text=f"Seven Split finished at {ts}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "Seven Split Finished"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Time*\n{ts}"},
                {"type": "mrkdwn", "text": f"*Total Value*\n{total:,} KRW"},
                {"type": "mrkdwn", "text": f"*Cash*\n{cash:,} KRW"},
                {"type": "mrkdwn", "text": f"*PnL*\n{pnl:+,} KRW"},
                {"type": "mrkdwn", "text": f"*Buys*\n{buy_count}"},
                {"type": "mrkdwn", "text": f"*Sells*\n{sell_count}"},
                {"type": "mrkdwn", "text": f"*Queued*\n{queued_count}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Orders*\n" + "\n".join(lines)}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Failures: {fail_count}"}]},
        ],
        color="#36a64f" if pnl >= 0 else "#e74c3c",
    )


def build_error_payload(message: str) -> dict[str, Any]:
    return build_slack_payload(text=f"Seven Split error: {message}", color="#e74c3c")
