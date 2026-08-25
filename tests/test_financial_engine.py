import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from gemelo_previsional.financial_engine import (
    fund_indices_for_age,
    load_financial_engine_config,
    run_financial_engine,
    simulate_financial_engine,
    validate_financial_engine_config,
)


ROOT = Path(__file__).resolve().parents[1]


class FinancialEngineTests(unittest.TestCase):
    def setUp(self):
        self.config = load_financial_engine_config(ROOT / "config" / "motor_financiero.json")
        self.config["paths"] = 40
        self.config["profile"]["retirement_age"] = 23

    def test_configuration_validates_covariance_and_fully_invested_funds(self):
        validate_financial_engine_config(self.config)
        assets = self.config["market"]["assets"]
        for allocation in self.config["funds"]["weights"].values():
            self.assertAlmostEqual(sum(allocation[asset] for asset in assets), 1.0)
        self.assertEqual(
            self.config["funds"]["weights"]["FG03"]["renta_fija_nacional"], 0.25
        )
        covariance = np.asarray(self.config["market"]["monthly_covariance"], dtype=float)
        self.assertGreaterEqual(float(np.linalg.eigvalsh(covariance).min()), 0.0)

    def test_rejects_original_underinvested_third_fund(self):
        invalid = copy.deepcopy(self.config)
        invalid["funds"]["weights"]["FG03"]["renta_fija_nacional"] = 0.15
        with self.assertRaisesRegex(ValueError, "deben sumar 1"):
            validate_financial_engine_config(invalid)

    def test_rejects_non_positive_semidefinite_covariance(self):
        invalid = copy.deepcopy(self.config)
        invalid["market"]["monthly_covariance"][0][1] = 1.0
        invalid["market"]["monthly_covariance"][1][0] = 1.0
        with self.assertRaisesRegex(ValueError, "semidefinida positiva"):
            validate_financial_engine_config(invalid)

    def test_age_rule_preserves_inclusive_boundaries(self):
        bounds = self.config["funds"]["age_upper_bounds_inclusive"]
        actual = fund_indices_for_age([35.0, 35.01, 40.0, 40.01, 76.0], bounds)
        np.testing.assert_array_equal(actual, [0, 1, 1, 2, 9])

    def test_simulation_is_reproducible_and_accounting_is_auditable(self):
        first = simulate_financial_engine(self.config)
        second = simulate_financial_engine(self.config)
        pd.testing.assert_frame_equal(first.path_results, second.path_results)
        pd.testing.assert_frame_equal(first.return_diagnostics, second.return_diagnostics)
        pd.testing.assert_frame_equal(
            first.representative_trajectories, second.representative_trajectories
        )
        self.assertEqual(first.metadata["months"], 24)
        self.assertEqual(len(first.path_results), 40)
        self.assertTrue(first.path_results["final_balance_uf"].ge(0).all())
        self.assertTrue(first.path_results["contribution_density"].between(0, 1).all())
        self.assertEqual(
            len(first.representative_trajectories),
            24 * len(self.config["reporting"]["representative_quantiles"]),
        )
        self.assertEqual(first.metadata["independent_random_streams"]["labor"], [0])
        self.assertEqual(first.metadata["independent_random_streams"]["market"], [1])
        self.assertEqual(len(first.metadata["config_sha256"]), 64)
        self.assertTrue(all(first.metadata["validation_gates"].values()))

    def test_different_seed_changes_the_simulation(self):
        first = simulate_financial_engine(self.config)
        changed = copy.deepcopy(self.config)
        changed["seed"] += 1
        second = simulate_financial_engine(changed)
        self.assertFalse(
            np.array_equal(
                first.path_results["final_balance_uf"].to_numpy(),
                second.path_results["final_balance_uf"].to_numpy(),
            )
        )

    def test_run_writes_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_financial_engine(self.config, directory)
            self.assertEqual(result["status"], "completed")
            expected = {
                "README.md",
                "motor_financiero_asset_covariance.csv",
                "motor_financiero_asset_parameters.csv",
                "motor_financiero_balance_summary.csv",
                "motor_financiero_fund_parameters.csv",
                "motor_financiero_path_results.csv",
                "motor_financiero_representative_trajectories.csv",
                "motor_financiero_return_diagnostics.csv",
                "motor_financiero_state_occupancy.csv",
                "motor_financiero_summary.json",
                "motor_financiero_transition_matrix.csv",
            }
            self.assertEqual({path.name for path in Path(directory).iterdir()}, expected)


if __name__ == "__main__":
    unittest.main()
