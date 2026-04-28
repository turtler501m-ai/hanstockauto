import requests
from datetime import datetime, timedelta, timezone
from src.config import config
from src.utils.logger import logger

KST = timezone(timedelta(hours=9))
HTTP = requests.Session()

def send_slack(text: str = "", blocks: list | None = None, color: str | None = None) -> None:
    if not config.slack_webhook_url:
        return
    if color and blocks:
        payload = {"attachments": [{"color": color, "blocks": blocks, "fallback": text}]}
    elif blocks:
        payload = {"text": text, "blocks": blocks}
    else:
        payload = {"text": text}
    try:
        r = HTTP.post(config.slack_webhook_url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(f"Slack send failed HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        logger.warning(f"Slack exception: {e}")

def slack_session_start(cash: int, total: int, stock_count: int, order_submission_enabled: bool, real_orders_enabled: bool) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    mode = "실제매매" if real_orders_enabled else ("모의투자" if order_submission_enabled else "테스트(DRY_RUN)")
    send_slack(
        text=f"세븐 스플릿 자동 매매 시작: {now}",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "세븐 스플릿 자동 매매"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*시간*\n{now}"},
                {"type": "mrkdwn", "text": f"*실행 모드*\n{mode}"},
                {"type": "mrkdwn", "text": f"*API 환경*\n{config.trading_env}"},
                {"type": "mrkdwn", "text": f"*예수금*\n{cash:,} 원"},
                {"type": "mrkdwn", "text": f"*총 평가금액*\n{total:,} 원"},
                {"type": "mrkdwn", "text": f"*보유 종목수*\n{stock_count}개"},
            ]},
        ],
        color="#2196F3",
    )

def slack_order(name: str, symbol: str, action: str, qty: int, price: int, reason: str, ok: bool, indicators: dict) -> None:
    action_label = "매수" if action == "buy" else "매도"
    status = "성공" if ok else "실패"
    color = "#36a64f" if ok else "#e74c3c"
    price_str = f"{price:,} 원" if price else "시장가"
    amount_str = f"{qty * price:,} 원" if price else "-"
    rsi_val = indicators.get("rsi", "-")
    rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, float) else str(rsi_val)
    send_slack(
        text=f"{action_label} {name} {qty}주 {status}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{action_label}* {name} (`{symbol}`) {status}"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*수량*\n{qty}주"},
                {"type": "mrkdwn", "text": f"*단가*\n{price_str}"},
                {"type": "mrkdwn", "text": f"*금액*\n{amount_str}"},
                {"type": "mrkdwn", "text": f"*RSI*\n{rsi_str}"},
                {"type": "mrkdwn", "text": f"*SMA20/60*\n{indicators.get('sma20', 0):.0f} / {indicators.get('sma60', 0):.0f}"},
                {"type": "mrkdwn", "text": f"*수익률*\n{indicators.get('rt', 0):+.2f}%"},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"사유: {reason}"}]},
        ],
        color=color,
    )

def slack_candidates(candidates: list[dict]) -> None:
    if not candidates:
        return
    lines = [
        f"*{c['ticker']}* {c['current_price']:,.0f} 원 | 점수 {c['score']} | {', '.join(c['reasons'])}"
        for c in candidates
    ]
    send_slack(
        text=f"신규 매수 후보: {len(candidates)}종목",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "매수 후보 종목"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ],
        color="#9C27B0",
    )

def slack_session_end(results: list[dict], cash: int, total: int, pnl: int) -> None:
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    buy_cnt = sum(1 for r in results if r["action"] == "buy" and r["ok"])
    sell_cnt = sum(1 for r in results if r["action"] == "sell" and r["ok"])
    fail_cnt = sum(1 for r in results if not r["ok"])
    color = "#36a64f" if pnl >= 0 else "#e74c3c"
    if not results:
        send_slack(text=f"세븐 스플릿 자동 매매 종료: 주문 내역 없음", color="#9E9E9E")
        return
    
    lines = []
    for r in results:
        action_kr = "매수" if r['action'] == "buy" else "매도"
        lines.append(f"{action_kr} {r['name']} {r['qty']}주 - {r['reason']}")

    send_slack(
        text=f"세븐 스플릿 자동 매매 종료",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "매매 세션 종료"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*시간*\n{now}"},
                {"type": "mrkdwn", "text": f"*총 평가금액*\n{total:,} 원"},
                {"type": "mrkdwn", "text": f"*예수금*\n{cash:,} 원"},
                {"type": "mrkdwn", "text": f"*당일 손익*\n{pnl:+,} 원"},
                {"type": "mrkdwn", "text": f"*매수 건수*\n{buy_cnt}건"},
                {"type": "mrkdwn", "text": f"*매도 건수*\n{sell_cnt}건"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*주문 내역*\n" + "\n".join(lines)}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"실패 건수: {fail_cnt}건"}]},
        ],
        color=color,
    )

def slack_error(msg: str) -> None:
    send_slack(text=f"세븐 스플릿 에러: {msg}", color="#e74c3c")
