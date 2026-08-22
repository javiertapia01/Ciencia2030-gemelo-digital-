import unittest

import numpy as np
import pandas as pd

from gemelo_previsional.statistics import (
    bootstrap_intervals,
    validation_summary,
    wilcoxon_signed_rank,
)


class StatisticsTests(unittest.TestCase):
    def test_validation_gate_passes_zero_errors(self):
        periods = pd.period_range("2020-01", periods=12, freq="M")
        errors = pd.DataFrame(
            {
                "period_ordinal": [period.ordinal for period in periods],
                "reported_balance_uf": [100.0] * 12,
                "relative_error": [0.0] * 12,
            }
        )
        summary = validation_summary(
            errors,
            {
                "minimum_observations": 10,
                "minimum_observed_balance_uf": 5.0,
                "max_median_absolute_relative_error": 0.01,
                "final_window_months": 12,
                "max_final_window_median_absolute_relative_error": 0.01,
                "max_absolute_annual_drift": 0.01,
            },
        )
        self.assertTrue(summary["gate_passed"])

    def test_validation_gate_rejects_terminal_deterioration(self):
        periods = pd.period_range("2020-01", periods=24, freq="M")
        errors = pd.DataFrame(
            {
                "period_ordinal": [period.ordinal for period in periods],
                "reported_balance_uf": [100.0] * 24,
                "relative_error": [0.0] * 12 + [0.25] * 12,
            }
        )
        summary = validation_summary(
            errors,
            {
                "minimum_observations": 20,
                "minimum_observed_balance_uf": 5.0,
                "max_median_absolute_relative_error": 0.20,
                "final_window_months": 12,
                "max_final_window_median_absolute_relative_error": 0.10,
                "max_absolute_annual_drift": 1.0,
            },
        )
        self.assertFalse(summary["gate_passed"])
        self.assertFalse(summary["checks"]["final_window_median_absolute_relative_error"])

    def test_wilcoxon_and_bootstrap_are_deterministic(self):
        values = np.array([1.0, 2.0, 3.0, -0.5, 4.0])
        test = wilcoxon_signed_rank(values)
        self.assertEqual(test["n_nonzero"], 5)
        first = bootstrap_intervals(values, iterations=100, seed=2030, confidence_level=0.95)
        second = bootstrap_intervals(values, iterations=100, seed=2030, confidence_level=0.95)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
