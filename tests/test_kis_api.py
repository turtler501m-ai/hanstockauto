import unittest
from unittest.mock import Mock, patch

import src.api.kis_api as kis_api
from src.api.kis_api import KIStockAPI, KISAccountError, KISRateLimitError


class KIStockAPITests(unittest.TestCase):
    def test_balance_rate_limit_does_not_retry(self):
        api = KIStockAPI.__new__(KIStockAPI)
        api.base_url = "https://example.test"
        api.access_token = "token"

        response = Mock()
        response.status_code = 500
        response.text = '{"msg_cd":"EGW00201","msg1":"rate limit"}'
        response.json.return_value = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"}

        original_interval = kis_api._KIS_MIN_INTERVAL
        try:
            kis_api._KIS_MIN_INTERVAL = 0
            with patch.object(kis_api.config, "kistock_account", "1234567801"), \
                    patch.object(kis_api.config, "trading_env", "demo"), \
                    patch.object(kis_api.config, "kistock_app_key", "key"), \
                    patch.object(kis_api.config, "kistock_app_secret", "secret"), \
                    patch.object(kis_api.logger, "error"), \
                    patch.object(kis_api.HTTP, "get", return_value=response) as get:
                with self.assertRaises(KISRateLimitError):
                    api.get_balance()

                self.assertEqual(get.call_count, 1)
        finally:
            kis_api._KIS_MIN_INTERVAL = original_interval

    def test_balance_invalid_account_does_not_retry(self):
        api = KIStockAPI.__new__(KIStockAPI)
        api.base_url = "https://example.test"
        api.access_token = "token"

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "rt_cd": "1",
            "msg_cd": "APBK0917",
            "msg1": "ERROR : INPUT INVALID_CHECK_ACNO",
        }

        original_interval = kis_api._KIS_MIN_INTERVAL
        try:
            kis_api._KIS_MIN_INTERVAL = 0
            with patch.object(kis_api.config, "kistock_account", "1234567801"), \
                    patch.object(kis_api.config, "trading_env", "demo"), \
                    patch.object(kis_api.config, "kistock_app_key", "key"), \
                    patch.object(kis_api.config, "kistock_app_secret", "secret"), \
                    patch.object(kis_api.HTTP, "get", return_value=response) as get:
                with self.assertRaises(KISAccountError):
                    api.get_balance()

                self.assertEqual(get.call_count, 1)
        finally:
            kis_api._KIS_MIN_INTERVAL = original_interval


if __name__ == "__main__":
    unittest.main()
