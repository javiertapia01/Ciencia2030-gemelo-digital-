import unittest

import pandas as pd

from gemelo_previsional.io import build_panel


class IoTests(unittest.TestCase):
    def test_panel_units_age_and_tope(self):
        balances = pd.DataFrame(
            [
                {
                    "correl": "00000001",
                    "period": "2020-01",
                    "balance_clp": 2_000_000.0,
                    "observed_fund": "C",
                    "transfer_flag": False,
                    "no_balance_flag": False,
                    "balance_source_rows": 1,
                    "positive_fund_count": 1,
                }
            ]
        )
        income = pd.DataFrame(
            [
                {
                    "correl": "00000001",
                    "period": "2020-01",
                    "wage_clp": 1_000_000.0,
                    "source_tope_flag": 1,
                    "payer_count": 1,
                    "income_source_rows": 1,
                }
            ]
        )
        characteristics = pd.DataFrame(
            [
                {
                    "correl": "00000001",
                    "fecha_nac": "199001",
                    "sexo": "F",
                    "fecha_afil": "201001",
                    "fecha_fall": pd.NA,
                    "afp": "HABITAT",
                    "region": "13",
                }
            ]
        )
        returns = pd.DataFrame(
            [{"period": "2020-01", **{f"return_{fund}": 0.0 for fund in "ABCDE"}}]
        )
        parameters = pd.DataFrame([{"period": "2020-01", "uf_clp": 20_000.0, "tope_uf": 40.0}])
        panel = build_panel(balances, income, characteristics, returns, parameters, 0.10)
        row = panel.iloc[0]
        self.assertEqual(row["age"], 30)
        self.assertAlmostEqual(row["wage_uf"], 50.0)
        self.assertAlmostEqual(row["contribution_uf"], 4.0)
        self.assertAlmostEqual(row["balance_uf"], 100.0)
        self.assertTrue(row["calculated_tope_flag"])


if __name__ == "__main__":
    unittest.main()

