import unittest
from datetime import datetime, timezone

from src.notifications import (
    build_candidates_payload,
    build_error_payload,
    build_order_payload,
    build_session_end_payload,
    build_session_start_payload,
    build_slack_payload,
    format_kst_timestamp,
    post_slack_payload,
    send_slack_message,
)


class _FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or _FakeResponse()
        self.error = error
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


class NotificationTests(unittest.TestCase):
    def test_format_kst_timestamp_converts_timezone(self):
        value = datetime(2026, 4, 26, 3, 15, tzinfo=timezone.utc)
        self.assertEqual(format_kst_timestamp(value), "2026-04-26 12:15 KST")

    def test_build_slack_payload_wraps_color_in_attachment(self):
        payload = build_slack_payload(
            text="hello",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "body"}}],
            color="#123456",
        )
        self.assertEqual(payload["text"], "hello")
        self.assertNotIn("blocks", payload)
        self.assertEqual(payload["attachments"][0]["color"], "#123456")
        self.assertEqual(payload["attachments"][0]["fallback"], "hello")

    def test_build_session_start_payload_matches_expected_fields(self):
        payload = build_session_start_payload(
            cash=1_500_000,
            total=2_000_000,
            stock_count=3,
            now=datetime(2026, 4, 26, 9, 30, tzinfo=timezone.utc),
            mode="DRY_RUN",
            trading_env="demo",
        )
        fields = payload["attachments"][0]["blocks"][1]["fields"]
        self.assertEqual(payload["text"], "Seven Split started at 2026-04-26 18:30 KST")
        self.assertEqual(fields[1]["text"], "*Mode*\nDRY_RUN")
        self.assertEqual(fields[4]["text"], "*Total Value*\n2,000,000 KRW")

    def test_build_order_payload_formats_market_sell_and_failure_color(self):
        payload = build_order_payload(
            name="Samsung",
            symbol="005930",
            action="sell",
            qty=7,
            price=0,
            reason="stop loss",
            ok=False,
            indicators={"rsi": 31.25, "sma20": 71000, "sma60": 68000, "rt": -15.34},
        )
        fields = payload["attachments"][0]["blocks"][1]["fields"]
        self.assertEqual(payload["attachments"][0]["color"], "#e74c3c")
        self.assertEqual(fields[1]["text"], "*Price*\nmarket")
        self.assertEqual(fields[3]["text"], "*RSI*\n31.2")
        self.assertEqual(fields[5]["text"], "*Return*\n-15.34%")

    def test_build_candidates_payload_returns_none_for_empty_candidates(self):
        self.assertIsNone(build_candidates_payload([]))

    def test_build_candidates_payload_renders_candidate_lines(self):
        payload = build_candidates_payload([
            {"ticker": "005930", "current_price": 70123, "score": 4, "reasons": ["rsi", "macd"]},
        ])
        text = payload["attachments"][0]["blocks"][1]["text"]["text"]
        self.assertIn("*005930* 70,123 KRW | score 4 | rsi, macd", text)

    def test_build_session_end_payload_summarizes_results(self):
        payload = build_session_end_payload(
            results=[
                {"name": "Samsung", "action": "buy", "qty": 2, "reason": "score", "ok": True, "decision": "execute"},
                {"name": "SK", "action": "sell", "qty": 1, "reason": "tp", "ok": False, "decision": "execute"},
                {"name": "Naver", "action": "buy", "qty": 3, "reason": "queue", "ok": False, "decision": "queue"},
            ],
            cash=100_000,
            total=500_000,
            pnl=-25_000,
            now=datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc),
        )
        attachment = payload["attachments"][0]
        fields = attachment["blocks"][1]["fields"]
        orders = attachment["blocks"][2]["text"]["text"]
        self.assertEqual(attachment["color"], "#e74c3c")
        self.assertEqual(fields[4]["text"], "*Buys*\n1")
        self.assertEqual(fields[6]["text"], "*Queued*\n1")
        self.assertIn("QUEUED Naver 3 shares - queue", orders)

    def test_build_session_end_payload_handles_empty_results(self):
        payload = build_session_end_payload(results=[], cash=1, total=2, pnl=3)
        self.assertEqual(payload["attachments"][0]["color"], "#9E9E9E")
        self.assertIn("no orders", payload["text"])

    def test_build_error_payload_uses_error_color(self):
        payload = build_error_payload("boom")
        self.assertEqual(payload["text"], "Seven Split error: boom")
        self.assertEqual(payload["attachments"][0]["color"], "#e74c3c")

    def test_post_slack_payload_returns_true_on_success(self):
        session = _FakeSession()
        payload = {"text": "hello"}
        self.assertTrue(post_slack_payload("https://example.test", payload, session))
        self.assertEqual(session.calls[0]["json"], payload)

    def test_post_slack_payload_logs_failures_and_returns_false(self):
        logs = []
        session = _FakeSession(response=_FakeResponse(status_code=500, text="server error"))
        ok = post_slack_payload("https://example.test", {"text": "hello"}, session, log_fn=logs.append)
        self.assertFalse(ok)
        self.assertIn("HTTP 500", logs[0])

    def test_send_slack_message_builds_and_posts_payload(self):
        session = _FakeSession()
        ok = send_slack_message(
            webhook_url="https://example.test",
            session=session,
            text="hello",
            color="#abcdef",
        )
        self.assertTrue(ok)
        sent = session.calls[0]["json"]
        self.assertEqual(sent["text"], "hello")
        self.assertEqual(sent["attachments"][0]["color"], "#abcdef")


if __name__ == "__main__":
    unittest.main()
