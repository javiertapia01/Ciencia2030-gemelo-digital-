import unittest

import pandas as pd

from gemelo_previsional.diagnostics import (
    BASELINE_VARIANT,
    run_one_step_diagnostics,
)


def _row(
    correl: str,
    period: str,
    balance: float,
    contribution: float,
    fund_balances: dict[str, float],
    returns: dict[str, float],
) -> dict:
    row = {
        "correl": correl,
        "period": period,
        "period_ordinal": pd.Period(period, freq="M").ordinal,
        "observed_fund": max(fund_balances, key=fund_balances.get),
        "balance_uf": balance,
        "contribution_uf": contribution,
        "age": 40,
        "sexo": "F",
        "afp": "HABITAT",
        "fecha_fall": pd.NA,
        "wage_uf": contribution * 10,
        "income_absent_flag": False,
        "transfer_flag": sum(value > 0 for value in fund_balances.values()) > 1,
    }
    for fund in "ABCDE":
        row[f"saldo{fund}_pesos"] = fund_balances.get(fund, 0.0)
        row[f"return_{fund}"] = returns.get(fund, 0.0)
    return row


class OneStepDiagnosticTests(unittest.TestCase):
    def test_selects_convention_only_on_calibration_and_reports_validation(self):
        rows = []
        for correl in ("00000001", "00000002"):
            rows.extend(
                [
                    _row(
                        correl,
                        "2020-01",
                        100.0,
                        5.0,
                        {"A": 60.0, "B": 40.0},
                        {"A": 0.10, "B": 0.0},
                    ),
                    _row(
                        correl,
                        "2020-02",
                        111.3,
                        10.0,
                        {"A": 66.78, "B": 44.52},
                        {"A": 0.10, "B": 0.0},
                    ),
                    _row(
                        correl,
                        "2020-03",
                        128.578,
                        20.0,
                        {"A": 128.578},
                        {fund: 0.25 for fund in "ABCDE"},
                    ),
                ]
            )
        result = run_one_step_diagnostics(
            pd.DataFrame(rows),
            minimum_history_months=3,
            minimum_balance_uf=5.0,
            calibration_share=0.5,
            split_seed=2030,
        )
        self.assertEqual(
            result.selection["selected_variant"],
            "current_start__weighted_current",
        )
        self.assertEqual(result.selection["people_by_split"], {"calibration": 1, "validation": 1})
        self.assertEqual(
            result.selection["common_comparison_people_by_split"],
            {"calibration": 1, "validation": 1},
        )
        validation = result.selection["selected_metrics_by_split"]["validation"]
        self.assertAlmostEqual(validation["median_absolute_relative_residual"], 0.0)
        self.assertFalse(result.stratification.empty)

    def test_one_step_residual_restarts_from_each_reported_balance(self):
        rows = []
        for correl in ("00000001", "00000002"):
            rows.extend(
                [
                    _row(correl, "2020-01", 100.0, 10.0, {"C": 100.0}, {}),
                    _row(correl, "2020-02", 120.0, 10.0, {"C": 120.0}, {}),
                    _row(correl, "2020-03", 130.0, 10.0, {"C": 130.0}, {}),
                ]
            )
        result = run_one_step_diagnostics(
            pd.DataFrame(rows),
            minimum_history_months=3,
            minimum_balance_uf=5.0,
            calibration_share=0.5,
            split_seed=2030,
        )
        self.assertEqual(result.selection["selected_variant"], BASELINE_VARIANT)
        person = result.residuals[result.residuals["correl"].eq("00000001")]
        self.assertAlmostEqual(person.iloc[0]["baseline_residual_uf"], 10.0)
        self.assertAlmostEqual(person.iloc[1]["baseline_residual_uf"], 0.0)


if __name__ == "__main__":
    unittest.main()
