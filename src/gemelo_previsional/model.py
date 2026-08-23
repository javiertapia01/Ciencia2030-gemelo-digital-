from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .individual_core import accounting_step_vectorized
from .io import BALANCE_COLUMNS, FUNDS


def generational_fund(age: int | float, cuts: list[int] | tuple[int, int, int, int]) -> str:
    """Assign A–E from age using four ascending cut points."""
    c1, c2, c3, c4 = cuts
    if age < c1:
        return "A"
    if age < c2:
        return "B"
    if age < c3:
        return "C"
    if age < c4:
        return "D"
    return "E"


def accounting_step(
    balance: float,
    contribution: float,
    monthly_return: float,
    *,
    contribution_timing: str = "start",
) -> float:
    """Apply one monthly posting with contribution at the configured boundary."""
    return float(
        accounting_step_vectorized(
            balance,
            contribution,
            monthly_return,
            contribution_timing=contribution_timing,
        )
    )


def observed_return(row: Any, rule: str) -> float:
    """Return the dominant-fund or reported-balance-weighted market return."""
    if rule == "dominant":
        fund = str(row.observed_fund)
        if fund not in FUNDS:
            return np.nan
        value = getattr(row, f"return_{fund}", np.nan)
        return float(value) if pd.notna(value) else np.nan
    if rule != "weighted":
        raise ValueError("observed_return_rule debe ser 'dominant' o 'weighted'")

    balances = np.array(
        [
            max(float(getattr(row, column)), 0.0)
            if pd.notna(getattr(row, column, np.nan))
            else 0.0
            for column in BALANCE_COLUMNS
        ],
        dtype=float,
    )
    total = float(balances.sum())
    if not np.isfinite(total) or total <= 0:
        return np.nan
    returns = np.array(
        [
            float(getattr(row, f"return_{fund}"))
            if pd.notna(getattr(row, f"return_{fund}", np.nan))
            else np.nan
            for fund in FUNDS
        ],
        dtype=float,
    )
    positive = balances > 0
    if not np.isfinite(returns[positive]).all():
        return np.nan
    return float(np.dot(balances[positive] / total, returns[positive]))


def longest_valid_segment(group: pd.DataFrame) -> pd.DataFrame:
    """Return the longest contiguous segment with a usable observed balance and fund."""
    valid = group[
        group["observed_fund"].isin(FUNDS)
        & group["balance_uf"].gt(0)
        & group["balance_uf"].notna()
    ].copy()
    if valid.empty:
        return valid
    gap = valid["period_ordinal"].diff().fillna(1).ne(1)
    valid["_segment"] = gap.cumsum()
    segment_sizes = valid.groupby("_segment", sort=False).size()
    selected = segment_sizes.idxmax()
    return valid[valid["_segment"].eq(selected)].drop(columns="_segment")


@dataclass
class SimulationOutputs:
    individual: pd.DataFrame
    validation_errors: pd.DataFrame
    trajectories: pd.DataFrame
    exclusions: pd.DataFrame


def simulate_panel(
    panel: pd.DataFrame,
    sensitivity_cuts: dict[str, list[int]],
    minimum_history_months: int,
    contribution_timing: str = "start",
    observed_return_rule: str = "dominant",
    return_month: str = "current",
    trajectory_people: set[str] | None = None,
) -> SimulationOutputs:
    if contribution_timing not in {"start", "end"}:
        raise ValueError("contribution_timing debe ser 'start' o 'end'")
    if observed_return_rule not in {"dominant", "weighted"}:
        raise ValueError("observed_return_rule debe ser 'dominant' o 'weighted'")
    if return_month not in {"current", "next"}:
        raise ValueError("return_month debe ser 'current' o 'next'")
    individual_records: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []
    trajectory_records: list[dict[str, Any]] = []
    exclusion_records: list[dict[str, Any]] = []

    scenario_names = list(sensitivity_cuts)
    if "base" not in scenario_names:
        raise ValueError("sensitivity_cuts debe contener un escenario llamado 'base'")

    for correl, complete_group in panel.groupby("correl", sort=False, observed=True):
        retain_trajectory = trajectory_people is None or str(correl) in trajectory_people
        group = longest_valid_segment(complete_group).sort_values("period_ordinal")
        if len(group) < minimum_history_months:
            exclusion_records.append(
                {
                    "correl": correl,
                    "reason": "historia_contigua_insuficiente",
                    "available_contiguous_months": int(len(group)),
                }
            )
            continue

        rows = list(group.itertuples(index=False))
        reconstructed_observed = float(rows[0].balance_uf)
        what_if = {name: reconstructed_observed for name in scenario_names}
        valid_pairs = 0
        if retain_trajectory:
            trajectory_records.append(
                _trajectory_record(
                    rows[0], reconstructed_observed, what_if, sensitivity_cuts, None
                )
            )

        stopped_reason: str | None = None
        for position in range(len(rows) - 1):
            current = rows[position]
            following = rows[position + 1]
            if int(following.period_ordinal) - int(current.period_ordinal) != 1:
                stopped_reason = "brecha_calendario"
                break

            observed_fund = str(current.observed_fund)
            return_row = current if return_month == "current" else following
            observed_return_value = observed_return(return_row, observed_return_rule)
            if pd.isna(observed_return_value):
                stopped_reason = f"retorno_observado_ausente_{observed_fund}"
                break
            contribution = float(current.contribution_uf)
            predicted_observed = accounting_step(
                reconstructed_observed,
                contribution,
                float(observed_return_value),
                contribution_timing=contribution_timing,
            )
            reported_next = float(following.balance_uf)
            relative_error = (
                (predicted_observed - reported_next) / reported_next
                if reported_next > 0
                else np.nan
            )
            error_records.append(
                {
                    "correl": correl,
                    "period": str(following.period),
                    "period_ordinal": int(following.period_ordinal),
                    "reported_balance_uf": reported_next,
                    "reconstructed_balance_uf": predicted_observed,
                    "error_uf": predicted_observed - reported_next,
                    "relative_error": relative_error,
                    "observed_fund_previous_month": observed_fund,
                    "transfer_flag_previous_month": bool(current.transfer_flag),
                }
            )
            reconstructed_observed = predicted_observed
            valid_pairs += 1

            for name, cuts in sensitivity_cuts.items():
                assigned_fund = generational_fund(int(return_row.age), cuts)
                assigned_return = getattr(return_row, f"return_{assigned_fund}")
                if pd.isna(assigned_return):
                    stopped_reason = f"retorno_what_if_ausente_{assigned_fund}"
                    break
                what_if[name] = accounting_step(
                    what_if[name],
                    contribution,
                    float(assigned_return),
                    contribution_timing=contribution_timing,
                )
            if stopped_reason:
                break
            if retain_trajectory:
                trajectory_records.append(
                    _trajectory_record(
                        following,
                        reconstructed_observed,
                        what_if,
                        sensitivity_cuts,
                        relative_error,
                    )
                )

        if stopped_reason:
            exclusion_records.append(
                {
                    "correl": correl,
                    "reason": stopped_reason,
                    "available_contiguous_months": int(valid_pairs + 1),
                }
            )
            continue
        if valid_pairs + 1 < minimum_history_months:
            exclusion_records.append(
                {
                    "correl": correl,
                    "reason": "historia_simulada_insuficiente",
                    "available_contiguous_months": int(valid_pairs + 1),
                }
            )
            continue

        observed_funds = group["observed_fund"].dropna()
        predominant = observed_funds.value_counts().index[0] if not observed_funds.empty else pd.NA
        result: dict[str, Any] = {
            "correl": correl,
            "start_period": str(rows[0].period),
            "end_period": str(rows[-1].period),
            "months": int(valid_pairs + 1),
            "age_start": int(rows[0].age),
            "age_end": int(rows[-1].age),
            "sexo": rows[0].sexo,
            "afp": rows[0].afp,
            "initial_balance_uf": float(rows[0].balance_uf),
            "final_reconstructed_observed_uf": reconstructed_observed,
            "final_reported_balance_uf": float(rows[-1].balance_uf),
            "mean_wage_uf": float(group["wage_uf"].mean()),
            "contribution_density": float(group["contribution_uf"].gt(0).mean()),
            "predominant_observed_fund": predominant,
            "transfer_month_share": float(group["transfer_flag"].mean()),
        }
        for name in scenario_names:
            final_wi = float(what_if[name])
            delta = final_wi - reconstructed_observed
            result[f"final_what_if_uf__{name}"] = final_wi
            result[f"delta_uf__{name}"] = delta
            result[f"delta_relative__{name}"] = (
                final_wi / reconstructed_observed - 1.0
                if reconstructed_observed > 0
                else np.nan
            )
        individual_records.append(result)

    return SimulationOutputs(
        individual=pd.DataFrame(individual_records),
        validation_errors=pd.DataFrame(error_records),
        trajectories=pd.DataFrame(trajectory_records),
        exclusions=pd.DataFrame(exclusion_records),
    )


def _trajectory_record(
    row: Any,
    reconstructed_observed: float,
    what_if: dict[str, float],
    sensitivity_cuts: dict[str, list[int]],
    relative_error: float | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "correl": row.correl,
        "period": str(row.period),
        "age": int(row.age),
        "observed_fund": row.observed_fund,
        "reported_balance_uf": float(row.balance_uf),
        "reconstructed_observed_uf": float(reconstructed_observed),
        "relative_error": relative_error,
        "contribution_uf": float(row.contribution_uf),
        "transfer_flag": bool(row.transfer_flag),
    }
    for name, cuts in sensitivity_cuts.items():
        record[f"what_if_fund__{name}"] = generational_fund(int(row.age), cuts)
        record[f"what_if_balance_uf__{name}"] = float(what_if[name])
        record[f"delta_uf__{name}"] = float(what_if[name] - reconstructed_observed)
    return record
