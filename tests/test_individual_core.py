import unittest

import numpy as np
import pandas as pd

import gemelo_previsional.milestone2 as milestone2_module
import gemelo_previsional.model as model_module
from gemelo_previsional.hpa_adapter import adapt_hpa_panel_to_person_month
from gemelo_previsional.individual_core import (
    PERSON_MONTH_OUTPUT_COLUMNS,
    accounting_step_vectorized,
    post_person_month,
    validate_person_month_contract,
)
from gemelo_previsional.markov_adapter import adapt_markov_trajectories_to_person_month


class IndividualCoreTests(unittest.TestCase):
    def test_scalar_and_vector_inputs_share_the_same_identity(self):
        scalar = accounting_step_vectorized(100.0, 10.0, 0.05)
        vector = accounting_step_vectorized(
            np.array([100.0, 200.0]),
            np.array([10.0, 0.0]),
            np.array([0.05, -0.10]),
        )
        self.assertAlmostEqual(float(scalar), 115.5)
        np.testing.assert_allclose(vector, [115.5, 180.0])
        with self.assertRaisesRegex(ValueError, "mayor que -100%"):
            accounting_step_vectorized([100.0], [10.0], [-1.0])

    def test_hpa_and_markov_engines_import_the_same_kernel(self):
        self.assertIs(
            model_module.accounting_step_vectorized,
            milestone2_module.accounting_step_vectorized,
        )

    def test_person_month_contract_posts_and_validates(self):
        inputs = pd.DataFrame(
            {
                "source": ["test"],
                "person_id": ["P1"],
                "period": ["2020-01"],
                "age": [30.0],
                "labor_state": ["cotizando"],
                "potential_wage_uf": [100.0],
                "contribution_uf": [10.0],
                "fund": ["C"],
                "monthly_return": [0.05],
                "opening_balance_uf": [100.0],
            }
        )
        posted = post_person_month(inputs)
        self.assertEqual(tuple(posted.columns), PERSON_MONTH_OUTPUT_COLUMNS)
        self.assertAlmostEqual(posted.loc[0, "closing_balance_uf"], 115.5)
        validate_person_month_contract(posted)
        broken = posted.copy()
        broken.loc[0, "closing_balance_uf"] = 999.0
        with self.assertRaisesRegex(ValueError, "identidad contable"):
            validate_person_month_contract(broken)

    def test_hpa_and_markov_adapters_agree_for_identical_person_month(self):
        hpa = pd.DataFrame(
            {
                "correl": ["P1"],
                "period": ["2020-01"],
                "age": [30.0],
                "wage_uf": [100.0],
                "contribution_uf": [10.0],
                "observed_fund": ["C"],
                "balance_uf": [100.0],
                "return_A": [0.08],
                "return_B": [0.06],
                "return_C": [0.05],
                "return_D": [0.03],
                "return_E": [0.02],
            }
        )
        markov = pd.DataFrame(
            {
                "scenario": ["equivalencia"],
                "scenario_label": ["Equivalencia"],
                "representative_path_id": ["P1"],
                "month": [1],
                "age": [30.0],
                "state": ["cotizando"],
                "potential_wage_uf": [100.0],
                "contribution_uf": [10.0],
                "fund_proxy": ["C"],
                "monthly_return": [0.05],
                "opening_balance_uf": [100.0],
                "closing_balance_uf": [115.5],
            }
        )
        historical = adapt_hpa_panel_to_person_month(hpa)
        synthetic = adapt_markov_trajectories_to_person_month(markov)
        comparable = [
            "age",
            "potential_wage_uf",
            "contribution_uf",
            "fund",
            "monthly_return",
            "opening_balance_uf",
            "closing_balance_uf",
        ]
        pd.testing.assert_series_equal(
            historical.loc[0, comparable],
            synthetic.loc[0, comparable],
            check_names=False,
        )


if __name__ == "__main__":
    unittest.main()
