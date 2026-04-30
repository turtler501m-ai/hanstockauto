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

    def test_secret_env_values_are_masked_for_response(self):
        self.assertEqual(dashboard._mask_env_value("1234567801"), "12******01")

    def test_kis_account_validation_requires_product_code(self):
        self.assertEqual(dashboard._validate_env_value("KISTOCK_ACCOUNT", "12345678-01"), "1234567801")
        with self.assertRaises(dashboard.HTTPException):
            dashboard._validate_env_value("KISTOCK_ACCOUNT", "12345678")

    def test_required_env_missing_flags_invalid_account_format(self):
        original_account = dashboard.trader.config.kistock_account
        try:
            dashboard.trader.config.kistock_account = "12345678"
            missing = dashboard._required_env_missing()
            self.assertIn("KISTOCK_ACCOUNT_FORMAT", missing)
        finally:
            dashboard.trader.config.kistock_account = original_account


if __name__ == "__main__":
    unittest.main()
