import copy
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gemelo_previsional.milestone2 import (
    LABOR_STATES,
    load_milestone2_config,
    run_milestone2,
    simulate_milestone2,
    validate_milestone2_config,
)


ROOT = Path(__file__).resolve().parents[1]


class Milestone2Tests(unittest.TestCase):
    def setUp(self):
        self.config = load_milestone2_config(ROOT / "config" / "hito2.json")
        self.config["paths_per_scenario"] = 40

    def test_configuration_has_three_valid_markov_scenarios(self):
        validate_milestone2_config(self.config)
        self.assertEqual(set(self.config["scenarios"]), {"estable", "intermitente", "adversa"})
        for scenario in self.config["scenarios"].values():
            matrix = scenario["transition_matrix"]
            self.assertEqual(set(matrix), set(LABOR_STATES))
            for probabilities in matrix.values():
                self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_rejects_non_stochastic_transition_row(self):
        invalid = copy.deepcopy(self.config)
        invalid["scenarios"]["estable"]["transition_matrix"]["cotizando"]["cotizando"] = 0.5
        with self.assertRaisesRegex(ValueError, "debe sumar 1"):
            validate_milestone2_config(invalid)

    def test_simulation_is_reproducible_and_runs_to_retirement(self):
        first = simulate_milestone2(self.config)
        second = simulate_milestone2(self.config)
        pd.testing.assert_frame_equal(first.path_results, second.path_results)
        pd.testing.assert_frame_equal(first.scenario_summary, second.scenario_summary)
        self.assertEqual(first.metadata["months"], 480)
        self.assertEqual(len(first.path_results), 120)
        self.assertEqual(first.path_results["draw_id"].nunique(), 40)
        self.assertTrue(first.path_results["final_balance_uf"].ge(0).all())
        self.assertTrue(first.path_results["contribution_density"].between(0, 1).all())
        summary = first.scenario_summary.set_index("scenario")
        self.assertGreater(
            summary.loc["estable", "median_final_balance_uf"],
            summary.loc["adversa", "median_final_balance_uf"],
        )
        self.assertTrue(
            first.path_results.loc[
                first.path_results["scenario"].eq("estable"),
                "paired_gap_vs_baseline_uf",
            ].eq(0).all()
        )
        counts = first.representative_trajectories.groupby("scenario").size()
        self.assertTrue((counts == 480).all())

    def test_run_writes_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_milestone2(self.config, directory)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["scenarios"], 3)
            expected = {
                "README.md",
                "hito2-results.svg",
                "hito2_market_returns.csv",
                "hito2_path_results.csv",
                "hito2_person_month_contract.csv",
                "hito2_representative_trajectories.csv",
                "hito2_scenario_summary.csv",
                "hito2_state_occupancy.csv",
                "hito2_summary.json",
                "hito2_transition_matrices.csv",
            }
            self.assertEqual({path.name for path in Path(directory).iterdir()}, expected)


if __name__ == "__main__":
    unittest.main()
