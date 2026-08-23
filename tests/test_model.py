import unittest

import pandas as pd

from gemelo_previsional.__main__ import build_parser
from gemelo_previsional.model import (
    accounting_step,
    generational_fund,
    observed_return,
    simulate_panel,
)


class ModelTests(unittest.TestCase):
    def test_full_run_can_skip_already_completed_one_step_diagnostics(self):
        args = build_parser().parse_args(
            [
                "run",
                "--config",
                "config/experiment.json",
                "--skip-one-step-diagnostics",
            ]
        )
        self.assertTrue(args.skip_one_step_diagnostics)

    def test_generational_rule_boundaries(self):
        cuts = [35, 45, 55, 65]
        expected = {
            20: "A",
            34: "A",
            35: "B",
            44: "B",
            45: "C",
            54: "C",
            55: "D",
            64: "D",
            65: "E",
        }
        self.assertEqual({age: generational_fund(age, cuts) for age in expected}, expected)

    def test_accounting_identity_contribution_at_start(self):
        self.assertAlmostEqual(accounting_step(100.0, 10.0, 0.05), 115.5)
        self.assertAlmostEqual(
            accounting_step(100.0, 10.0, 0.05, contribution_timing="end"), 115.0
        )
        with self.assertRaises(ValueError):
            accounting_step(100.0, 10.0, -1.0)

    def test_weighted_observed_return(self):
        row = type(
            "Row",
            (),
            {
                "observed_fund": "A",
                "saldoA_pesos": 75.0,
                "saldoB_pesos": 25.0,
                "saldoC_pesos": 0.0,
                "saldoD_pesos": 0.0,
                "saldoE_pesos": 0.0,
                "return_A": 0.10,
                "return_B": -0.02,
                "return_C": 0.0,
                "return_D": 0.0,
                "return_E": 0.0,
            },
        )()
        self.assertAlmostEqual(observed_return(row, "dominant"), 0.10)
        self.assertAlmostEqual(observed_return(row, "weighted"), 0.07)

    def test_parallel_simulation_uses_same_contributions(self):
        rows = []
        for index, (period, balance) in enumerate(
            [("2020-01", 100.0), ("2020-02", 110.0), ("2020-03", 120.0)]
        ):
            row = {
                "correl": "00000001",
                "period": period,
                "period_ordinal": pd.Period(period, freq="M").ordinal,
                "observed_fund": "C",
                "balance_uf": balance,
                "contribution_uf": 10.0,
                "age": 30,
                "sexo": "F",
                "afp": "HABITAT",
                "wage_uf": 100.0,
                "transfer_flag": False,
            }
            row.update({"return_A": 0.10, "return_B": 0.05, "return_C": 0.0, "return_D": 0.0, "return_E": 0.0})
            rows.append(row)
        result = simulate_panel(
            pd.DataFrame(rows),
            sensitivity_cuts={"base": [35, 45, 55, 65]},
            minimum_history_months=3,
        )
        individual = result.individual.iloc[0]
        self.assertAlmostEqual(individual["final_reconstructed_observed_uf"], 120.0)
        self.assertAlmostEqual(individual["final_what_if_uf__base"], 144.1)
        self.assertAlmostEqual(individual["delta_uf__base"], 24.1)
        self.assertTrue((result.validation_errors["relative_error"].abs() < 1e-12).all())

    def test_selected_hpa_convention_uses_next_weighted_return_and_end_contribution(self):
        rows = []
        for period, balance, contribution, return_a, return_b in [
            ("2020-01", 100.0, 10.0, 0.00, 0.00),
            ("2020-02", 115.0, 10.0, 0.10, 0.00),
            ("2020-03", 130.75, 10.0, 0.10, 0.00),
        ]:
            row = {
                "correl": "00000001",
                "period": period,
                "period_ordinal": pd.Period(period, freq="M").ordinal,
                "observed_fund": "A",
                "balance_uf": balance,
                "contribution_uf": contribution,
                "age": 30,
                "sexo": "F",
                "afp": "HABITAT",
                "wage_uf": 100.0,
                "transfer_flag": True,
                "saldoA_pesos": 50.0,
                "saldoB_pesos": 50.0,
                "saldoC_pesos": 0.0,
                "saldoD_pesos": 0.0,
                "saldoE_pesos": 0.0,
                "return_A": return_a,
                "return_B": return_b,
                "return_C": 0.0,
                "return_D": 0.0,
                "return_E": 0.0,
            }
            rows.append(row)
        result = simulate_panel(
            pd.DataFrame(rows),
            sensitivity_cuts={"base": [35, 45, 55, 65]},
            minimum_history_months=3,
            contribution_timing="end",
            observed_return_rule="weighted",
            return_month="next",
        )
        individual = result.individual.iloc[0]
        self.assertAlmostEqual(individual["final_reconstructed_observed_uf"], 130.75)
        self.assertTrue((result.validation_errors["relative_error"].abs() < 1e-12).all())

        compact = simulate_panel(
            pd.DataFrame(rows),
            sensitivity_cuts={"base": [35, 45, 55, 65]},
            minimum_history_months=3,
            contribution_timing="end",
            observed_return_rule="weighted",
            return_month="next",
            trajectory_people=set(),
        )
        self.assertFalse(compact.individual.empty)
        self.assertFalse(compact.validation_errors.empty)
        self.assertTrue(compact.trajectories.empty)


if __name__ == "__main__":
    unittest.main()
