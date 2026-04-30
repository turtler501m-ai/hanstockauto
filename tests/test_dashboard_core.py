import tempfile
import unittest

import src.dashboard as dashboard
from src.dashboard import _parse_balance, _portfolio_totals


class MemoryCachePath:
    def __init__(self):
        self.content = None
        self.parent = self

    def mkdir(self, parents=False, exist_ok=False):
        return None

    def exists(self):
        return self.content is not None

    def write_text(self, text, encoding=None):
        self.content = text

    def read_text(self, encoding=None):
        return self.content


class MemoryTextPath:
    def __init__(self, content=""):
        self.content = content

    def exists(self):
        return True

    def read_text(self, encoding=None):
        return self.content

    def write_text(self, text, encoding=None):
        self.content = text


class DashboardCoreTests(unittest.TestCase):
    def test_parse_balance_uses_holding_eval_amount(self):
        parsed = _parse_balance({
            "output1": [{
                "pdno": "005930",
                "prdt_name": "Samsung",
                "hldg_qty": "10",
                "prpr": "0",
                "evlu_amt": "700000",
                "evlu_pfls_amt": "-10000",
                "evlu_pfls_rt": "-1.41",
            }],
            "output2": [{
                "dnca_tot_amt": "1000000",
                "prvs_rcdl_excc_amt": "200000",
                "scts_evlu_amt": "700000",
                "tot_evlu_amt": "900000",
                "evlu_pfls_smtl_amt": "-10000",
            }],
        })

        self.assertEqual(parsed["holdings"][0]["value"], 700000)
        self.assertEqual(parsed["holdings"][0]["price"], 70000)
        self.assertEqual(parsed["stock_eval"], 700000)
        self.assertEqual(parsed["cash"], 200000)
        self.assertEqual(parsed["total_eval"], 900000)
        self.assertLessEqual(parsed["cash_ratio"], 1.0)

    def test_portfolio_totals_clamps_cash_ratio(self):
        totals = _portfolio_totals(
            cash=10_000_000,
            summary_total=9_937_130,
            holdings=[{"value": 2_000_000}],
        )

        self.assertEqual(totals["stock_eval"], 2_000_000)
        self.assertEqual(totals["total_eval"], 9_937_130)
        self.assertGreater(totals["cash_ratio"], 0)
        self.assertLessEqual(totals["cash_ratio"], 1.0)

    def test_balance_cache_is_scoped_to_account(self):
        original_cache = dashboard.BALANCE_CACHE
        original_account = dashboard.trader.config.kistock_account
        try:
            dashboard.BALANCE_CACHE = MemoryCachePath()
            dashboard.trader.config.kistock_account = "1111111101"
            dashboard._save_balance_cache({"output1": [], "output2": []})

            dashboard.trader.config.kistock_account = "2222222201"
            self.assertIsNone(dashboard._load_balance_cache())

            dashboard.trader.config.kistock_account = "1111111101"
            self.assertIsNotNone(dashboard._load_balance_cache())
        finally:
            dashboard.BALANCE_CACHE = original_cache
            dashboard.trader.config.kistock_account = original_account

    def test_env_writer_preserves_comments_and_updates_allowed_keys(self):
        path = MemoryTextPath("# KIS\nTRADING_ENV=demo\nDRY_RUN=true\nMAX_POSITIONS=10 # 최대보유주식종목\n")
        dashboard._write_env_values({"TRADING_ENV": "real", "MAX_POSITIONS": "5"}, path)

        self.assertIn("# KIS", path.content)
        self.assertIn("TRADING_ENV=real", path.content)
        self.assertIn("DRY_RUN=true", path.content)
        self.assertIn("MAX_POSITIONS=5 # 최대보유주식종목", path.content)

    def test_env_reader_strips_inline_comments_from_numbers(self):
        path = MemoryTextPath("MAX_POSITIONS=10 # 최대보유주식종목\nACTIVE_MODEL_VERSION=v1\n")

        values = dashboard._read_env_values(path)

        self.assertEqual(values["MAX_POSITIONS"], "10")
        self.assertEqual(dashboard._validate_env_value("MAX_POSITIONS", "10 # 최대보유주식종목"), "10")

    def test_runtime_order_mode_updates_apply_without_restart(self):
        original_env_path = dashboard.ENV_PATH
        original_trading_env = dashboard.trader.TRADING_ENV
        original_dry_run = dashboard.trader.DRY_RUN
        original_enable_live = dashboard.trader.ENABLE_LIVE_TRADING
        original_order_submission = dashboard.trader.ORDER_SUBMISSION_ENABLED
        original_real_orders = dashboard.trader.REAL_ORDERS_ENABLED
        original_config_values = {
            "trading_env": dashboard.trader.config.trading_env,
            "dry_run": dashboard.trader.config.dry_run,
            "enable_live_trading": dashboard.trader.config.enable_live_trading,
        }
        try:
            path = MemoryTextPath("TRADING_ENV=demo\nDRY_RUN=true\nENABLE_LIVE_TRADING=false\n")
            dashboard.ENV_PATH = path
            dashboard.trader.TRADING_ENV = "demo"
            dashboard.trader.DRY_RUN = True
            dashboard.trader.ENABLE_LIVE_TRADING = False
            dashboard.trader.REAL_ORDERS_ENABLED = False
            dashboard.trader.ORDER_SUBMISSION_ENABLED = False
            dashboard.trader.config.trading_env = "demo"
            dashboard.trader.config.dry_run = True
            dashboard.trader.config.enable_live_trading = False

            result = dashboard.set_runtime_order_mode({"key": "DRY_RUN", "enabled": False})
            self.assertFalse(result["dry_run"])
            self.assertTrue(result["order_submission_enabled"])
            self.assertIn("DRY_RUN=false", path.content)

            with self.assertRaises(dashboard.HTTPException):
                dashboard.set_runtime_order_mode({"key": "REAL_ORDERS_ENABLED", "enabled": True})
        finally:
            dashboard.ENV_PATH = original_env_path
            dashboard.trader.TRADING_ENV = original_trading_env
            dashboard.trader.DRY_RUN = original_dry_run
            dashboard.trader.ENABLE_LIVE_TRADING = original_enable_live
            dashboard.trader.ORDER_SUBMISSION_ENABLED = original_order_submission
            dashboard.trader.REAL_ORDERS_ENABLED = original_real_orders
            dashboard.trader.config.trading_env = original_config_values["trading_env"]
            dashboard.trader.config.dry_run = original_config_values["dry_run"]
            dashboard.trader.config.enable_live_trading = original_config_values["enable_live_trading"]

    def test_secret_env_values_are_masked_for_response(self):
        self.assertEqual(dashboard._mask_env_value("1234567801"), "12******01")

    def test_kis_account_validation_accepts_8_or_10_digits(self):
        self.assertEqual(dashboard._validate_env_value("KISTOCK_ACCOUNT", "12345678"), "12345678")
        self.assertEqual(dashboard._validate_env_value("KISTOCK_ACCOUNT", "12345678-01"), "1234567801")
        with self.assertRaises(dashboard.HTTPException):
            dashboard._validate_env_value("KISTOCK_ACCOUNT", "1234567")

    def test_required_env_missing_accepts_8_digit_account(self):
        original_account = dashboard.trader.config.kistock_account
        try:
            dashboard.trader.config.kistock_account = "12345678"
            missing = dashboard._required_env_missing()
            self.assertNotIn("KISTOCK_ACCOUNT_FORMAT", missing)
        finally:
            dashboard.trader.config.kistock_account = original_account

    def test_auto_approval_state_can_toggle(self):
        original_state = dashboard.AUTO_APPROVAL_STATE
        try:
            dashboard.AUTO_APPROVAL_STATE = MemoryCachePath()
            self.assertFalse(dashboard._auto_approval_enabled())

            dashboard._save_auto_approval(True)
            self.assertTrue(dashboard._auto_approval_enabled())

            dashboard._save_auto_approval(False)
            self.assertFalse(dashboard._auto_approval_enabled())
        finally:
            dashboard.AUTO_APPROVAL_STATE = original_state

    def test_enabling_auto_approval_processes_pending_orders(self):
        original_state = dashboard.AUTO_APPROVAL_STATE
        original_db_path = dashboard.trader.config.trade_db_path
        original_get_api = dashboard._get_api
        original_save_trade = dashboard.trader.save_trade
        original_slack_order = dashboard._slack_order
        original_dry_run = dashboard.trader.DRY_RUN
        original_order_submission = dashboard.trader.ORDER_SUBMISSION_ENABLED

        class _FakeAPI:
            def place_order(self, symbol, order_type, price, qty):
                return {"rt_cd": "0", "msg1": "DRY_RUN"}

        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                dashboard.AUTO_APPROVAL_STATE = MemoryCachePath()
                dashboard.trader.config.trade_db_path = f"{tmpdir}/trades.sqlite"
                dashboard._get_api = lambda: _FakeAPI()
                dashboard.trader.save_trade = lambda *args, **kwargs: None
                dashboard._slack_order = lambda *args, **kwargs: None
                dashboard.trader.DRY_RUN = True
                dashboard.trader.ORDER_SUBMISSION_ENABLED = False

                created = dashboard.create_approval({
                    "symbol": "005930",
                    "name": "Samsung",
                    "action": "buy",
                    "qty": 1,
                    "price": 70000,
                    "reason": "test",
                    "source": "test",
                })
                self.assertEqual(created["status"], "pending")

                result = dashboard.set_auto_approval({"enabled": True})
                self.assertEqual(result["processed_count"], 1)

                approvals = dashboard.get_approvals()["approvals"]
                self.assertEqual(approvals[0]["status"], "executed")
                self.assertEqual(approvals[0]["response_msg"], "DRY_RUN")
        finally:
            dashboard.AUTO_APPROVAL_STATE = original_state
            dashboard.trader.config.trade_db_path = original_db_path
            dashboard._get_api = original_get_api
            dashboard.trader.save_trade = original_save_trade
            dashboard._slack_order = original_slack_order
            dashboard.trader.DRY_RUN = original_dry_run
            dashboard.trader.ORDER_SUBMISSION_ENABLED = original_order_submission

    def test_candidate_orders_use_scan_price_without_quote_lookup(self):
        original_max_positions = dashboard.trader.MAX_POSITIONS
        try:
            dashboard.trader.MAX_POSITIONS = 1
            orders = dashboard._build_candidate_orders_from_scan(
                [
                    {"ticker": "005930", "current_price": 70003, "score": 2, "reasons": ["test"]},
                    {"ticker": "000660", "current_price": 100000, "score": 2, "reasons": ["test"]},
                ],
                held_count=0,
                cash=1_000_000,
            )
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["ticker"], "005930")
            self.assertEqual(orders[0]["limit_price"], 70000)
            self.assertLessEqual(orders[0]["estimated_cost"], 1_000_000)
        finally:
            dashboard.trader.MAX_POSITIONS = original_max_positions


if __name__ == "__main__":
    unittest.main()
