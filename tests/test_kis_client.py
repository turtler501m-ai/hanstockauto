import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from src.kis_client import CircuitBreakerState, KISClient, KISClientConfig


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, raise_error=None):
        self._payload = payload or {}
        self.status_code = status_code
        self._raise_error = raise_error

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._raise_error is not None:
            raise self._raise_error


class KISClientTests(unittest.TestCase):
    def make_config(self, **overrides):
        config = {
            "base_url": "https://example.test",
            "app_key": "app-key-12345678",
            "app_secret": "secret-value",
            "account_no": "1234567801",
            "trading_env": "demo",
            "circuit_cooldown_seconds": 60,
            "circuit_max_errors": 5,
        }
        config.update(overrides)
        return KISClientConfig(**config)

    def test_headers_include_auth_credentials_and_tr_id(self):
        client = KISClient(
            self.make_config(),
            session=Mock(),
            access_token="token-abc",
        )

        headers = client.headers("VTTC8434R")

        self.assertEqual(headers["authorization"], "Bearer token-abc")
        self.assertEqual(headers["appkey"], "app-key-12345678")
        self.assertEqual(headers["appsecret"], "secret-value")
        self.assertEqual(headers["tr_id"], "VTTC8434R")
        self.assertEqual(headers["custtype"], "P")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_uses_cached_token_when_cache_matches_and_not_near_expiry(self):
        now = datetime(2026, 4, 26, 10, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "kis_token.json"
            cache_path.write_text(
                (
                    '{"token": "cached-token", '
                    '"expires_at": "2026-04-26T11:00:00", '
                    '"trading_env": "demo", '
                    '"base_url": "https://example.test", '
                    '"app_key_prefix": "app-key-"}'
                ),
                encoding="utf-8",
            )
            session = Mock()
            client = KISClient(
                self.make_config(token_cache_path=cache_path),
                session=session,
                clock=lambda: now,
            )

        self.assertEqual(client.access_token, "cached-token")
        session.post.assert_not_called()

    def test_fetches_token_when_cache_is_expiring_soon(self):
        now = datetime(2026, 4, 26, 10, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "kis_token.json"
            cache_path.write_text(
                (
                    '{"token": "stale-token", '
                    '"expires_at": "2026-04-26T10:03:00", '
                    '"trading_env": "demo", '
                    '"base_url": "https://example.test", '
                    '"app_key_prefix": "app-key-"}'
                ),
                encoding="utf-8",
            )
            session = Mock()
            session.post.return_value = _FakeResponse({"access_token": "fresh-token"})
            client = KISClient(
                self.make_config(token_cache_path=cache_path),
                session=session,
                clock=lambda: now,
            )

            rewritten = cache_path.read_text(encoding="utf-8")

        self.assertEqual(client.access_token, "fresh-token")
        self.assertIn('"token": "fresh-token"', rewritten)
        session.post.assert_called_once()

    def test_circuit_breaker_blocks_until_cooldown_then_resets(self):
        state = CircuitBreakerState(error_count=5, opened_at=datetime(2026, 4, 26, 10, 0, 0))

        with self.assertRaisesRegex(RuntimeError, "retry after 30s"):
            state.ensure_can_proceed(
                datetime(2026, 4, 26, 10, 0, 30),
                max_errors=5,
                cooldown_seconds=60,
            )

        state.ensure_can_proceed(
            datetime(2026, 4, 26, 10, 1, 1),
            max_errors=5,
            cooldown_seconds=60,
        )
        self.assertEqual(state.error_count, 0)
        self.assertIsNone(state.opened_at)

    def test_circuit_status_auto_clears_after_cooldown(self):
        client = KISClient(
            self.make_config(),
            session=Mock(),
            clock=lambda: datetime(2026, 4, 26, 10, 2, 0),
            access_token="token",
            circuit=CircuitBreakerState(
                error_count=5,
                opened_at=datetime(2026, 4, 26, 10, 0, 0),
            ),
        )

        status = client.circuit_status()

        self.assertFalse(status["opened"])
        self.assertEqual(status["error_count"], 0)
        self.assertIsNone(status["opened_at"])

    def test_create_hashkey_returns_empty_string_on_failure(self):
        session = Mock()
        session.post.side_effect = RuntimeError("hashkey error")
        client = KISClient(
            self.make_config(),
            session=session,
            access_token="token",
        )

        value = client.create_hashkey({"PDNO": "005930"})

        self.assertEqual(value, "")

    def test_mark_failure_opens_circuit_at_threshold(self):
        timestamps = iter(
            [
                datetime(2026, 4, 26, 9, 0, 0),
                datetime(2026, 4, 26, 9, 0, 1),
                datetime(2026, 4, 26, 9, 0, 2),
                datetime(2026, 4, 26, 9, 0, 3),
                datetime(2026, 4, 26, 9, 0, 4),
            ]
        )
        client = KISClient(
            self.make_config(),
            session=Mock(),
            access_token="token",
            clock=lambda: next(timestamps),
        )

        for _ in range(5):
            client.mark_failure()

        self.assertEqual(client.circuit.error_count, 5)
        self.assertEqual(client.circuit.opened_at, datetime(2026, 4, 26, 9, 0, 4))

    def test_place_order_uses_live_tr_id_for_live_environment(self):
        session = Mock()
        session.post.side_effect = [
            _FakeResponse({"HASH": "hash-value"}),
            _FakeResponse({"rt_cd": "0", "msg1": "ok"}),
        ]
        client = KISClient(
            self.make_config(trading_env="live"),
            session=session,
            access_token="token",
        )

        result = client.place_order("005930", "sell", 70000, 1)

        self.assertEqual(result["rt_cd"], "0")
        order_call = session.post.call_args_list[1]
        self.assertEqual(order_call.kwargs["headers"]["tr_id"], "TTTC0801U")
        self.assertEqual(order_call.kwargs["headers"]["hashkey"], "hash-value")


if __name__ == "__main__":
    unittest.main()
