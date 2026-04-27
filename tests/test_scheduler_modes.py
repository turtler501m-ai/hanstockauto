import sys
import unittest
from unittest.mock import patch

from src import scheduler


class SchedulerModeTests(unittest.TestCase):
    def test_run_scheduled_cycle_delegates_execute_mode(self):
        expected = {"mode": "execute", "results": []}

        with patch.object(scheduler.trader, "run", return_value=expected) as run_mock:
            result = scheduler.run_scheduled_cycle(mode="execute")

        self.assertEqual(result, expected)
        run_mock.assert_called_once_with(mode="execute")

    def test_run_scheduled_cycle_delegates_analysis_only_mode(self):
        expected = {"mode": "analysis_only", "results": []}

        with patch.object(scheduler.trader, "run", return_value=expected) as run_mock:
            result = scheduler.run_scheduled_cycle(mode="analysis_only")

        self.assertEqual(result, expected)
        run_mock.assert_called_once_with(mode="analysis_only")

    def test_main_uses_default_execute_mode(self):
        with patch.object(sys, "argv", ["scheduler"]), patch.object(
            scheduler, "run_scheduled_cycle"
        ) as cycle_mock:
            exit_code = scheduler.main()

        self.assertEqual(exit_code, 0)
        cycle_mock.assert_called_once_with(mode="execute")

    def test_main_accepts_execute_mode_argument(self):
        with patch.object(sys, "argv", ["scheduler", "--mode", "execute"]), patch.object(
            scheduler, "run_scheduled_cycle"
        ) as cycle_mock:
            exit_code = scheduler.main()

        self.assertEqual(exit_code, 0)
        cycle_mock.assert_called_once_with(mode="execute")

    def test_main_accepts_analysis_only_mode_argument(self):
        with patch.object(
            sys, "argv", ["scheduler", "--mode", "analysis_only"]
        ), patch.object(scheduler, "run_scheduled_cycle") as cycle_mock:
            exit_code = scheduler.main()

        self.assertEqual(exit_code, 0)
        cycle_mock.assert_called_once_with(mode="analysis_only")

    def test_main_rejects_invalid_mode(self):
        with patch.object(sys, "argv", ["scheduler", "--mode", "invalid"]), patch.object(
            scheduler, "run_scheduled_cycle"
        ) as cycle_mock:
            with self.assertRaises(SystemExit) as exc:
                scheduler.main()

        self.assertEqual(exc.exception.code, 2)
        cycle_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
