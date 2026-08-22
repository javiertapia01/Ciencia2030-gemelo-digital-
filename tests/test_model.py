import unittest

import pandas as pd

from gemelo_previsional.model import accounting_step, generational_fund, simulate_panel


class ModelTests(unittest.TestCase):
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
        with self.assertRaises(ValueError):
            accounting_step(100.0, 10.0, -1.0)

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


if __name__ == "__main__":
    unittest.main()

