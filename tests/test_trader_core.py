import unittest

from src.trader import (
    KOSPI_UNIVERSE,
    WATCHLIST,
    KIStockAPI,
    build_orders,
    build_scan_universe,
    calc_bollinger,
    calc_macd,
    calc_rsi,
    calc_sma,
    calc_strategy_profile,
    find_candidates,
    generate_ai_weight_plan,
    generate_portfolio_optimizer_plan,
    generate_signal,
)


class TraderCoreTests(unittest.TestCase):
    def test_indicators_handle_short_price_history(self):
        self.assertEqual(calc_rsi([1, 2, 3]), 50.0)
        self.assertEqual(calc_sma([1, 2, 3], 5), 3)
        self.assertEqual(calc_bollinger([1, 2, 3], 20), (3, 3, 3))

    def test_build_orders_respects_cash_budget(self):
        orders = build_orders(
            [{"ticker": "005930", "score": 2, "reasons": ["test"]}],
            lambda _symbol: {"ask1": 70000, "current": 70000},
            held_count=0,
            cash=1_000_000,
        )
        self.assertEqual(len(orders), 1)
        self.assertLessEqual(orders[0]["estimated_cost"], 1_000_000)

    def test_generate_signal_stop_loss_sells_all(self):
        signal = generate_signal(
            {"prpr": "10000", "hldg_qty": "7", "evlu_pfls_rt": "-20"},
            [],
        )
        self.assertEqual(signal["action"], "sell")
        self.assertEqual(signal["qty"], 7)
        self.assertEqual(signal["price"], 0)

    def test_strategy_profile_exposes_composite_indicators(self):
        prices = [float(i) for i in range(1, 140)]
        highs = [p + 1 for p in prices]
        volumes = [100.0] * 119 + [200.0] * 20
        profile = calc_strategy_profile(prices, highs, volumes)
        self.assertIn("macd_hist", profile)
        self.assertIn("rsi2", profile)
        self.assertGreaterEqual(profile["score"], 0)

    def test_macd_handles_short_history(self):
        macd = calc_macd([1, 2, 3])
        self.assertFalse(macd["bull_cross"])
        self.assertEqual(macd["hist"], 0.0)

    def test_ai_weight_plan_returns_rebalance_rows(self):
        prices = [float(i) for i in range(100, 220)]
        plan = generate_ai_weight_plan(
            [{
                "symbol": "005930",
                "name": "Samsung",
                "qty": 1,
                "price": 200000,
                "value": 200000,
                "prices": prices,
                "highs": [p + 1 for p in prices],
                "volumes": [100.0] * len(prices),
            }],
            total_eval=1_000_000,
        )
        self.assertEqual(len(plan["positions"]), 1)
        self.assertIn("target_weight", plan["positions"][0])

    def test_portfolio_optimizer_plan_returns_method(self):
        prices = [float(i) for i in range(100, 220)]
        plan = generate_portfolio_optimizer_plan(
            [{
                "symbol": "005930",
                "name": "Samsung",
                "qty": 1,
                "price": 200000,
                "value": 200000,
                "prices": prices,
                "highs": [p + 1 for p in prices],
                "volumes": [100.0] * len(prices),
            }],
            total_eval=1_000_000,
        )
        self.assertEqual(plan["method"], "score_tilted_inverse_vol")
        self.assertEqual(len(plan["positions"]), 1)

    def test_kospi_universe_has_no_duplicates(self):
        self.assertEqual(len(KOSPI_UNIVERSE), len(set(KOSPI_UNIVERSE)))

    def test_build_scan_universe_always_includes_watchlist(self):
        """거래량 API가 빈 결과를 돌려줘도 WATCHLIST는 항상 포함된다."""
        class _FakeAPI:
            def get_volume_rank(self, top_n=50):
                return []  # API 실패 시뮬레이션

        universe = build_scan_universe(_FakeAPI(), held_symbols=set())
        for code in WATCHLIST:
            self.assertIn(code, universe)

    def test_build_scan_universe_excludes_held(self):
        held = {"005930", "000660"}

        class _FakeAPI:
            def get_volume_rank(self, top_n=50):
                return []

        universe = build_scan_universe(_FakeAPI(), held_symbols=held)
        for code in held:
            self.assertNotIn(code, universe)

    def test_build_scan_universe_uses_volume_rank_when_available(self):
        extra = ["000020", "000030", "000040"]

        class _FakeAPI:
            def get_volume_rank(self, top_n=50):
                return extra

        universe = build_scan_universe(_FakeAPI(), held_symbols=set())
        for code in extra:
            self.assertIn(code, universe)

    def test_find_candidates_returns_dict_structure(self):
        """find_candidates는 candidates, scan_summary, scanned, min_score 키를 가진 dict를 반환한다."""
        result = find_candidates(held_symbols=set(), universe=[], min_score=2)
        self.assertIsInstance(result, dict)
        self.assertIn("candidates", result)
        self.assertIn("scan_summary", result)
        self.assertIn("scanned", result)
        self.assertIn("min_score", result)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["min_score"], 2)

    def test_circuit_breaker_can_be_reset(self):
        KIStockAPI.reset_circuit()
        api = KIStockAPI.__new__(KIStockAPI)
        api.notify_errors = False
        for _ in range(KIStockAPI.MAX_ERRORS):
            api._fail()

        status = KIStockAPI.circuit_status()
        self.assertTrue(status["opened"])
        self.assertEqual(status["error_count"], KIStockAPI.MAX_ERRORS)

        KIStockAPI.reset_circuit()
        status = KIStockAPI.circuit_status()
        self.assertFalse(status["opened"])
        self.assertEqual(status["error_count"], 0)

    def test_circuit_breaker_records_api_result(self):
        KIStockAPI.reset_circuit()
        api = KIStockAPI.__new__(KIStockAPI)

        api._record_result({"rt_cd": "1"})
        status = KIStockAPI.circuit_status()
        self.assertEqual(status["error_count"], 1)
        self.assertFalse(status["opened"])

        api._record_result({"rt_cd": "0"})
        status = KIStockAPI.circuit_status()
        self.assertEqual(status["error_count"], 0)
        self.assertFalse(status["opened"])


if __name__ == "__main__":
    unittest.main()
