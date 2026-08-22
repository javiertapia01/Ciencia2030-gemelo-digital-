import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gemelo_previsional.toy import deterministic_market_returns, run_toy_experiments


class ToyExperimentTests(unittest.TestCase):
    def test_market_path_is_deterministic_and_finite(self):
        first = deterministic_market_returns(120)
        second = deterministic_market_returns(120)
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue((first.filter(like="return_") > -1).all(axis=None))

    def test_toy_run_writes_non_confidential_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_toy_experiments(directory, people=40, months=24, seed=2030)
            self.assertEqual(result["experiment_type"], "toy_synthetic_not_empirical")
            self.assertTrue(result["gate_passed_by_construction"])
            self.assertEqual(result["people"], 40)
            expected = {
                "toy_market_returns.csv",
                "toy_individual_results.csv",
                "toy_archetype_trajectories.csv",
                "toy_age_summary.csv",
                "toy_sensitivity_summary.csv",
                "toy_summary.json",
            }
            self.assertEqual({path.name for path in Path(directory).iterdir()}, expected)


if __name__ == "__main__":
    unittest.main()
