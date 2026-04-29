import unittest

from src.dashboard import _parse_balance, _portfolio_totals


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
                "tot_evlu_amt": "900000",
                "evlu_pfls_smtl_amt": "-10000",
            }],
        })

        self.assertEqual(parsed["holdings"][0]["value"], 700000)
        self.assertEqual(parsed["holdings"][0]["price"], 70000)
        self.assertEqual(parsed["stock_eval"], 700000)
        self.assertEqual(parsed["total_eval"], 1700000)
        self.assertLessEqual(parsed["cash_ratio"], 1.0)

    def test_portfolio_totals_clamps_cash_ratio(self):
        totals = _portfolio_totals(
            cash=10_000_000,
            summary_total=9_937_130,
            holdings=[{"value": 2_000_000}],
        )

        self.assertEqual(totals["stock_eval"], 2_000_000)
        self.assertEqual(totals["total_eval"], 12_000_000)
        self.assertGreater(totals["cash_ratio"], 0)
        self.assertLessEqual(totals["cash_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
