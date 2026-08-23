from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .io import BALANCE_COLUMNS, FUNDS
from .model import longest_valid_segment


CONTRIBUTION_CONVENTIONS = (
    ("current_start", "contribution_current_uf", "start"),
    ("current_end", "contribution_current_uf", "end"),
    ("previous_start", "contribution_previous_uf", "start"),
    ("previous_end", "contribution_previous_uf", "end"),
    ("next_start", "contribution_next_uf", "start"),
    ("next_end", "contribution_next_uf", "end"),
)

RETURN_CONVENTIONS = (
    ("dominant_current", "return_dominant_current"),
    ("dominant_next", "return_dominant_next"),
    ("weighted_current", "return_weighted_current"),
    ("weighted_next", "return_weighted_next"),
)

BASELINE_VARIANT = "current_start__dominant_current"


@dataclass
class OneStepDiagnosticOutputs:
    selection: dict[str, Any]
    variant_summary: pd.DataFrame
    residuals: pd.DataFrame
    stratification: pd.DataFrame


def _stable_score(identifier: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{identifier}".encode("utf-8")).hexdigest()


def _split_people(
    people: list[str], calibration_share: float, seed: int
) -> dict[str, str]:
    ordered = sorted(set(people), key=lambda value: (_stable_score(value, seed), value))
    if len(ordered) < 2:
        return {value: "calibration" for value in ordered}
    calibration_count = round(len(ordered) * calibration_share)
    calibration_count = min(max(int(calibration_count), 1), len(ordered) - 1)
    calibration = set(ordered[:calibration_count])
    return {
        value: "calibration" if value in calibration else "validation"
        for value in ordered
    }


def _dominant_return(row: Any) -> float:
    fund = str(row.observed_fund)
    if fund not in FUNDS:
        return np.nan
    value = getattr(row, f"return_{fund}", np.nan)
    return float(value) if pd.notna(value) else np.nan


def _weighted_return(row: Any) -> float:
    balance_values: list[float] = []
    for column in BALANCE_COLUMNS:
        value = getattr(row, column, 0.0)
        numeric = float(value) if pd.notna(value) else 0.0
        balance_values.append(max(numeric, 0.0))
    balances = np.array(balance_values, dtype=float)
    total = float(balances.sum())
    if not np.isfinite(total) or total <= 0:
        return np.nan
    return_values: list[float] = []
    for fund in FUNDS:
        value = getattr(row, f"return_{fund}", np.nan)
        return_values.append(float(value) if pd.notna(value) else np.nan)
    returns = np.array(return_values, dtype=float)
    positive = balances > 0
    if not np.isfinite(returns[positive]).all():
        return np.nan
    return float(np.dot(balances[positive] / total, returns[positive]))


def _age_band(age: int) -> str:
    if age < 35:
        return "menos_de_35"
    if age < 45:
        return "35_44"
    if age < 55:
        return "45_54"
    if age < 65:
        return "55_64"
    return "65_o_mas"


def _life_stage(age: int) -> str:
    if age < 55:
        return "acumulacion"
    if age < 65:
        return "cercano_a_pension"
    return "edad_de_pension"


def _density_band(value: float) -> str:
    if value == 0:
        return "0"
    if value < 0.5:
        return "mayor_0_menor_0_5"
    if value < 0.8:
        return "0_5_menor_0_8"
    return "0_8_a_1"


def _wage_band(value: float) -> str:
    if value <= 0:
        return "0_uf"
    if value < 20:
        return "mayor_0_menor_20_uf"
    if value < 40:
        return "20_menor_40_uf"
    if value < 60:
        return "40_menor_60_uf"
    return "60_uf_o_mas"


def _fall_ordinal(value: Any) -> int | None:
    text = str(value).strip()
    if len(text) != 6 or not text.isdigit():
        return None
    year = int(text[:4])
    month = int(text[4:])
    if not 1 <= month <= 12:
        return None
    return int(pd.Period(f"{year:04d}-{month:02d}", freq="M").ordinal)


def _candidate_definitions() -> list[dict[str, str]]:
    definitions: list[dict[str, str]] = []
    for contribution_name, contribution_column, contribution_timing in CONTRIBUTION_CONVENTIONS:
        contribution_source = contribution_name.split("_", maxsplit=1)[0]
        for return_name, return_column in RETURN_CONVENTIONS:
            return_rule, fund_month = return_name.split("_", maxsplit=1)
            definitions.append(
                {
                    "variant": f"{contribution_name}__{return_name}",
                    "contribution_convention": contribution_name,
                    "contribution_source": contribution_source,
                    "contribution_timing": contribution_timing,
                    "return_convention": return_name,
                    "return_rule": return_rule,
                    "fund_month": fund_month,
                    "contribution_column": contribution_column,
                    "return_column": return_column,
                }
            )
    return definitions


def _prediction(frame: pd.DataFrame, definition: dict[str, str]) -> pd.Series:
    balance = frame["reported_balance_current_uf"].astype(float)
    contribution = frame[definition["contribution_column"]].astype(float)
    monthly_return = frame[definition["return_column"]].astype(float)
    if definition["contribution_timing"] == "start":
        return (balance + contribution) * (1.0 + monthly_return)
    return balance * (1.0 + monthly_return) + contribution


def _variant_metrics(
    frame: pd.DataFrame,
    prediction: pd.Series,
    definition: dict[str, str],
    split: str,
) -> dict[str, Any]:
    subset = frame if split == "all" else frame[frame["split"].eq(split)]
    predicted = prediction.loc[subset.index]
    finite = np.isfinite(predicted)
    subset = subset.loc[finite]
    predicted = predicted.loc[finite]
    residual = subset["reported_balance_next_uf"] - predicted
    relative = residual / subset["reported_balance_next_uf"]
    absolute_relative = relative.abs()
    return {
        **{key: value for key, value in definition.items() if not key.endswith("_column")},
        "split": split,
        "observations": int(len(subset)),
        "people": int(subset["correl"].nunique()),
        "median_residual_uf": float(residual.median()) if len(subset) else np.nan,
        "median_relative_residual": float(relative.median()) if len(subset) else np.nan,
        "median_absolute_relative_residual": (
            float(absolute_relative.median()) if len(subset) else np.nan
        ),
        "p90_absolute_relative_residual": (
            float(absolute_relative.quantile(0.90)) if len(subset) else np.nan
        ),
        "rmse_uf": (
            float(np.sqrt(np.mean(np.square(residual.to_numpy(dtype=float)))))
            if len(subset)
            else np.nan
        ),
    }


def _build_pair_frame(
    panel: pd.DataFrame,
    minimum_history_months: int,
    calibration_share: float,
    split_seed: int,
    minimum_balance_uf: float,
) -> pd.DataFrame:
    segments: list[tuple[str, pd.DataFrame]] = []
    for correl, complete_group in panel.groupby("correl", sort=False, observed=True):
        group = longest_valid_segment(complete_group).sort_values("period_ordinal")
        if len(group) >= minimum_history_months:
            segments.append((str(correl), group))
    split_by_person = _split_people(
        [correl for correl, _ in segments], calibration_share, split_seed
    )

    records: list[dict[str, Any]] = []
    for correl, group in segments:
        rows = list(group.itertuples(index=False))
        contribution_density = float(group["contribution_uf"].gt(0).mean())
        fall_ordinal = _fall_ordinal(getattr(rows[0], "fecha_fall", None))
        for position in range(len(rows) - 1):
            current = rows[position]
            following = rows[position + 1]
            if int(following.period_ordinal) - int(current.period_ordinal) != 1:
                continue
            previous_contribution = (
                float(rows[position - 1].contribution_uf) if position > 0 else np.nan
            )
            current_ordinal = int(current.period_ordinal)
            age = int(current.age)
            wage = float(current.wage_uf)
            near_death = bool(
                fall_ordinal is not None and 0 <= fall_ordinal - current_ordinal <= 12
            )
            records.append(
                {
                    "correl": correl,
                    "split": split_by_person[correl],
                    "source_period": str(current.period),
                    "target_period": str(following.period),
                    "target_year": str(following.period)[:4],
                    "source_period_ordinal": current_ordinal,
                    "target_period_ordinal": int(following.period_ordinal),
                    "reported_balance_current_uf": float(current.balance_uf),
                    "reported_balance_next_uf": float(following.balance_uf),
                    "contribution_previous_uf": previous_contribution,
                    "contribution_current_uf": float(current.contribution_uf),
                    "contribution_next_uf": float(following.contribution_uf),
                    "return_dominant_current": _dominant_return(current),
                    "return_dominant_next": _dominant_return(following),
                    "return_weighted_current": _weighted_return(current),
                    "return_weighted_next": _weighted_return(following),
                    "observed_fund_current": str(current.observed_fund),
                    "observed_fund_next": str(following.observed_fund),
                    "transfer_flag_current": bool(current.transfer_flag),
                    "transfer_flag_next": bool(following.transfer_flag),
                    "transfer_status": (
                        "mas_de_un_fondo"
                        if bool(current.transfer_flag) or bool(following.transfer_flag)
                        else "un_fondo"
                    ),
                    "age_current": age,
                    "age_band": _age_band(age),
                    "life_stage": _life_stage(age),
                    "near_death_status": "cercano_a_fallecimiento" if near_death else "no_cercano",
                    "sexo": getattr(current, "sexo", pd.NA),
                    "afp": getattr(current, "afp", pd.NA),
                    "wage_current_uf": wage,
                    "wage_band": _wage_band(wage),
                    "income_status": (
                        "sin_fila_remuneracion"
                        if bool(getattr(current, "income_absent_flag", False))
                        else ("remuneracion_positiva" if wage > 0 else "remuneracion_cero")
                    ),
                    "contribution_density": contribution_density,
                    "contribution_density_band": _density_band(contribution_density),
                }
            )
    pairs = pd.DataFrame(records)
    if pairs.empty:
        raise ValueError("No hay transiciones elegibles para el diagnóstico mensual de un paso")
    required_for_comparison = [
        "contribution_previous_uf",
        "contribution_current_uf",
        "contribution_next_uf",
        "return_dominant_current",
        "return_dominant_next",
        "return_weighted_current",
        "return_weighted_next",
    ]
    finite_inputs = np.isfinite(pairs[required_for_comparison]).all(axis=1)
    pairs["eligible_for_variant_comparison"] = (
        pairs["reported_balance_next_uf"].ge(minimum_balance_uf) & finite_inputs
    )
    return pairs


def _stratification(residuals: pd.DataFrame) -> pd.DataFrame:
    eligible = residuals[
        residuals["split"].eq("validation")
        & residuals["eligible_for_variant_comparison"]
        & np.isfinite(residuals["selected_relative_residual"])
    ]
    dimensions = (
        "target_year",
        "age_band",
        "afp",
        "observed_fund_current",
        "transfer_status",
        "life_stage",
        "near_death_status",
        "contribution_density_band",
        "income_status",
        "wage_band",
    )
    records: list[dict[str, Any]] = []
    for dimension in dimensions:
        for value, group in eligible.groupby(dimension, dropna=False, observed=True):
            relative = group["selected_relative_residual"]
            records.append(
                {
                    "evaluation_split": "validation",
                    "dimension": dimension,
                    "group": str(value),
                    "observations": int(len(group)),
                    "people": int(group["correl"].nunique()),
                    "median_residual_uf": float(group["selected_residual_uf"].median()),
                    "median_relative_residual": float(relative.median()),
                    "median_absolute_relative_residual": float(relative.abs().median()),
                    "p90_absolute_relative_residual": float(relative.abs().quantile(0.90)),
                }
            )
    return pd.DataFrame(records)


def run_one_step_diagnostics(
    panel: pd.DataFrame,
    minimum_history_months: int,
    minimum_balance_uf: float,
    calibration_share: float = 0.5,
    split_seed: int = 2030,
    large_relative_residual_threshold: float = 0.10,
) -> OneStepDiagnosticOutputs:
    """Compare one-step accounting conventions without changing the cumulative gate."""
    pairs = _build_pair_frame(
        panel,
        minimum_history_months=minimum_history_months,
        calibration_share=calibration_share,
        split_seed=split_seed,
        minimum_balance_uf=minimum_balance_uf,
    )
    comparison = pairs[pairs["eligible_for_variant_comparison"]].copy()
    if comparison.empty:
        raise ValueError("No hay transiciones comunes para comparar variantes de diagnóstico")

    definitions = _candidate_definitions()
    summary_records: list[dict[str, Any]] = []
    for definition in definitions:
        prediction = _prediction(comparison, definition)
        for split in ("calibration", "validation", "all"):
            summary_records.append(
                _variant_metrics(comparison, prediction, definition, split)
            )
    variant_summary = pd.DataFrame(summary_records)
    calibration = variant_summary[
        variant_summary["split"].eq("calibration")
        & variant_summary["median_absolute_relative_residual"].notna()
    ].copy()
    if calibration.empty:
        raise ValueError("La partición de calibración no contiene residuos comparables")
    definition_order = {
        definition["variant"]: index for index, definition in enumerate(definitions)
    }
    calibration["_order"] = calibration["variant"].map(definition_order)
    calibration = calibration.sort_values(
        ["median_absolute_relative_residual", "_order"], kind="stable"
    )
    rank_by_variant = {
        variant: rank
        for rank, variant in enumerate(calibration["variant"].tolist(), start=1)
    }
    variant_summary["calibration_rank"] = variant_summary["variant"].map(rank_by_variant)
    selected_variant = str(calibration.iloc[0]["variant"])
    selected_definition = next(
        definition for definition in definitions if definition["variant"] == selected_variant
    )

    baseline_definition = next(
        definition for definition in definitions if definition["variant"] == BASELINE_VARIANT
    )
    baseline_prediction = _prediction(pairs, baseline_definition)
    selected_prediction = _prediction(pairs, selected_definition)
    pairs["baseline_predicted_balance_next_uf"] = baseline_prediction
    pairs["baseline_residual_uf"] = pairs["reported_balance_next_uf"] - baseline_prediction
    pairs["baseline_relative_residual"] = (
        pairs["baseline_residual_uf"] / pairs["reported_balance_next_uf"]
    )
    pairs["selected_variant"] = selected_variant
    pairs["selected_predicted_balance_next_uf"] = selected_prediction
    pairs["selected_residual_uf"] = pairs["reported_balance_next_uf"] - selected_prediction
    pairs["selected_relative_residual"] = (
        pairs["selected_residual_uf"] / pairs["reported_balance_next_uf"]
    )
    pairs["large_selected_residual_flag"] = pairs[
        "selected_relative_residual"
    ].abs().ge(large_relative_residual_threshold)
    pairs["first_large_selected_residual_for_person"] = False
    first_large = (
        pairs[pairs["large_selected_residual_flag"]]
        .sort_values(["correl", "source_period_ordinal"])
        .groupby("correl", sort=False)
        .head(1)
        .index
    )
    pairs.loc[first_large, "first_large_selected_residual_for_person"] = True

    selected_rows = variant_summary[variant_summary["variant"].eq(selected_variant)]
    metrics_by_split: dict[str, dict[str, Any]] = {}
    for row in selected_rows.itertuples(index=False):
        split_name = str(row.split)
        split_residuals = pairs[
            pairs["eligible_for_variant_comparison"]
            & (
                pd.Series(True, index=pairs.index)
                if split_name == "all"
                else pairs["split"].eq(split_name)
            )
            & np.isfinite(pairs["selected_relative_residual"])
        ]
        large = split_residuals["selected_relative_residual"].abs().ge(
            large_relative_residual_threshold
        )
        metrics_by_split[split_name] = {
            "observations": int(row.observations),
            "people": int(row.people),
            "median_relative_residual": float(row.median_relative_residual),
            "median_absolute_relative_residual": float(
                row.median_absolute_relative_residual
            ),
            "p90_absolute_relative_residual": float(
                row.p90_absolute_relative_residual
            ),
            "rmse_uf": float(row.rmse_uf),
            "share_at_or_above_large_relative_residual_threshold": (
                float(large.mean()) if len(large) else np.nan
            ),
            "people_with_large_relative_residual": int(
                split_residuals.loc[large, "correl"].nunique()
            ),
        }
    split_people = pairs[["correl", "split"]].drop_duplicates()["split"].value_counts()
    comparison_people = (
        comparison[["correl", "split"]].drop_duplicates()["split"].value_counts()
    )
    selection = {
        "status": (
            "selected_and_validated"
            if int(comparison_people.get("validation", 0)) > 0
            else "selected_without_validation_people"
        ),
        "selection_rule": "minimum calibration median absolute relative one-step residual",
        "selection_does_not_modify_cumulative_gate": True,
        "candidate_variants": len(definitions),
        "baseline_variant": BASELINE_VARIANT,
        "selected_variant": selected_variant,
        "selected_convention": {
            key: value
            for key, value in selected_definition.items()
            if key not in {"contribution_column", "return_column", "variant"}
        },
        "calibration_share_requested": float(calibration_share),
        "split_seed": int(split_seed),
        "people_by_split": {
            "calibration": int(split_people.get("calibration", 0)),
            "validation": int(split_people.get("validation", 0)),
        },
        "common_comparison_people_by_split": {
            "calibration": int(comparison_people.get("calibration", 0)),
            "validation": int(comparison_people.get("validation", 0)),
        },
        "common_comparison_observations": int(len(comparison)),
        "large_relative_residual_threshold": float(large_relative_residual_threshold),
        "selected_metrics_by_split": metrics_by_split,
    }
    return OneStepDiagnosticOutputs(
        selection=selection,
        variant_summary=variant_summary.sort_values(
            ["split", "calibration_rank", "variant"], kind="stable"
        ).reset_index(drop=True),
        residuals=pairs.sort_values(["correl", "source_period_ordinal"]).reset_index(drop=True),
        stratification=_stratification(pairs),
    )
