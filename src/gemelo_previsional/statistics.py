from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def validation_summary(errors: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    minimum_balance = float(config["minimum_observed_balance_uf"])
    eligible = errors[
        errors["reported_balance_uf"].ge(minimum_balance)
        & errors["relative_error"].notna()
        & np.isfinite(errors["relative_error"])
    ].copy()
    observations = int(len(eligible))
    if observations:
        median_abs = float(eligible["relative_error"].abs().median())
        median_signed = float(eligible["relative_error"].median())
        monthly = eligible.groupby("period_ordinal")["relative_error"].median().sort_index()
        final_window_months = int(config.get("final_window_months", 12))
        final_start = int(eligible["period_ordinal"].max()) - final_window_months + 1
        final_window = eligible[eligible["period_ordinal"].ge(final_start)]
        final_window_median_abs = float(final_window["relative_error"].abs().median())
        final_window_median_signed = float(final_window["relative_error"].median())
        if len(monthly) >= 2:
            x = monthly.index.to_numpy(dtype=float)
            x -= x.min()
            slope = float(np.polyfit(x, monthly.to_numpy(dtype=float), 1)[0])
            annual_drift = slope * 12.0
        else:
            annual_drift = math.nan
    else:
        median_abs = math.nan
        median_signed = math.nan
        annual_drift = math.nan
        final_window_months = int(config.get("final_window_months", 12))
        final_window = eligible
        final_window_median_abs = math.nan
        final_window_median_signed = math.nan

    checks = {
        "minimum_observations": observations >= int(config["minimum_observations"]),
        "median_absolute_relative_error": bool(
            np.isfinite(median_abs)
            and median_abs <= float(config["max_median_absolute_relative_error"])
        ),
        "final_window_median_absolute_relative_error": bool(
            np.isfinite(final_window_median_abs)
            and final_window_median_abs
            <= float(config["max_final_window_median_absolute_relative_error"])
        ),
        "absolute_annual_drift": bool(
            np.isfinite(annual_drift)
            and abs(annual_drift) <= float(config["max_absolute_annual_drift"])
        ),
    }
    return {
        "gate_passed": bool(all(checks.values())),
        "checks": checks,
        "observations": observations,
        "minimum_observed_balance_uf": minimum_balance,
        "median_absolute_relative_error": _finite_or_none(median_abs),
        "median_signed_relative_error": _finite_or_none(median_signed),
        "final_window_months": final_window_months,
        "final_window_observations": int(len(final_window)),
        "final_window_median_absolute_relative_error": _finite_or_none(
            final_window_median_abs
        ),
        "final_window_median_signed_relative_error": _finite_or_none(
            final_window_median_signed
        ),
        "annual_drift_of_monthly_median_error": _finite_or_none(annual_drift),
        "thresholds": {
            "minimum_observations": int(config["minimum_observations"]),
            "max_median_absolute_relative_error": float(
                config["max_median_absolute_relative_error"]
            ),
            "max_final_window_median_absolute_relative_error": float(
                config["max_final_window_median_absolute_relative_error"]
            ),
            "max_absolute_annual_drift": float(config["max_absolute_annual_drift"]),
        },
    }


def wilcoxon_signed_rank(values: np.ndarray | pd.Series) -> dict[str, Any]:
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data) & (data != 0)]
    n = int(data.size)
    if n == 0:
        return {"n_nonzero": 0, "w_plus": 0.0, "z": 0.0, "p_value_two_sided": 1.0}
    absolute = pd.Series(np.abs(data))
    ranks = absolute.rank(method="average").to_numpy(dtype=float)
    w_plus = float(ranks[data > 0].sum())
    mean = n * (n + 1) / 4.0
    tie_counts = absolute.value_counts().to_numpy(dtype=float)
    tie_term = float(np.sum(tie_counts * (tie_counts**2 - 1)))
    variance = (n * (n + 1) * (2 * n + 1) - tie_term) / 24.0
    if variance <= 0:
        z = 0.0
        p_value = 1.0
    else:
        continuity = 0.5 * np.sign(w_plus - mean)
        z = float((w_plus - mean - continuity) / math.sqrt(variance))
        p_value = float(math.erfc(abs(z) / math.sqrt(2.0)))
    return {"n_nonzero": n, "w_plus": w_plus, "z": z, "p_value_two_sided": p_value}


def bootstrap_intervals(
    deltas: np.ndarray | pd.Series,
    iterations: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    values = np.asarray(deltas, dtype=float)
    values = values[np.isfinite(values)]
    n = int(values.size)
    if n == 0:
        raise ValueError("Bootstrap requiere al menos una diferencia finita")
    rng = np.random.default_rng(seed)
    medians = np.empty(iterations, dtype=float)
    winner_shares = np.empty(iterations, dtype=float)
    for index in range(iterations):
        sample = values[rng.integers(0, n, size=n)]
        medians[index] = np.median(sample)
        winner_shares[index] = np.mean(sample > 0)
    alpha = 1.0 - confidence_level
    low, high = alpha / 2.0, 1.0 - alpha / 2.0
    return {
        "iterations": int(iterations),
        "seed": int(seed),
        "confidence_level": float(confidence_level),
        "median_delta_uf": {
            "estimate": float(np.median(values)),
            "lower": float(np.quantile(medians, low)),
            "upper": float(np.quantile(medians, high)),
        },
        "winner_share": {
            "estimate": float(np.mean(values > 0)),
            "lower": float(np.quantile(winner_shares, low)),
            "upper": float(np.quantile(winner_shares, high)),
        },
    }


def population_summary(
    individual: pd.DataFrame,
    scenario: str,
    inference: dict[str, Any],
) -> dict[str, Any]:
    delta = individual[f"delta_uf__{scenario}"].to_numpy(dtype=float)
    relative = individual[f"delta_relative__{scenario}"].to_numpy(dtype=float)
    finite_delta = delta[np.isfinite(delta)]
    finite_relative = relative[np.isfinite(relative)]
    return {
        "scenario": scenario,
        "n": int(len(individual)),
        "winner_share": float(np.mean(finite_delta > 0)),
        "median_delta_uf": float(np.median(finite_delta)),
        "mean_delta_uf": float(np.mean(finite_delta)),
        "median_delta_relative": float(np.median(finite_relative)),
        "mean_delta_relative": float(np.mean(finite_relative)),
        "wilcoxon_signed_rank_normal_approximation": wilcoxon_signed_rank(finite_delta),
        "bootstrap_person_level": bootstrap_intervals(
            finite_delta,
            iterations=int(inference["bootstrap_iterations"]),
            seed=int(inference["bootstrap_seed"]),
            confidence_level=float(inference["confidence_level"]),
        ),
    }


def sensitivity_summary(individual: pd.DataFrame, scenarios: list[str]) -> pd.DataFrame:
    base_sign = np.sign(individual["delta_uf__base"].to_numpy(dtype=float))
    records: list[dict[str, Any]] = []
    for scenario in scenarios:
        delta = individual[f"delta_uf__{scenario}"].to_numpy(dtype=float)
        relative = individual[f"delta_relative__{scenario}"].to_numpy(dtype=float)
        sign = np.sign(delta)
        records.append(
            {
                "scenario": scenario,
                "n": int(np.isfinite(delta).sum()),
                "median_delta_uf": float(np.nanmedian(delta)),
                "median_delta_relative": float(np.nanmedian(relative)),
                "winner_share": float(np.nanmean(delta > 0)),
                "share_sign_changed_vs_base": float(np.mean(sign != base_sign)),
            }
        )
    return pd.DataFrame(records)


def stratification_table(individual: pd.DataFrame, scenario: str = "base") -> pd.DataFrame:
    frame = individual.copy()
    frame["age_group"] = pd.cut(
        frame["age_start"],
        bins=[-np.inf, 34, 54, np.inf],
        labels=["Jóvenes (<35)", "Edad media (35–54)", "Mayores (55+)"],
    ).astype("string")
    income_percentile = frame["mean_wage_uf"].rank(method="average", pct=True)
    frame["income_group"] = np.select(
        [income_percentile <= 0.25, income_percentile <= 0.75],
        ["Q1 ingreso", "Q2–Q3 ingreso"],
        default="Q4 ingreso",
    )
    density_median = float(frame["contribution_density"].median())
    frame["density_group"] = np.where(
        frame["contribution_density"] < density_median,
        "Densidad baja",
        "Densidad alta",
    )
    delta_column = f"delta_uf__{scenario}"
    relative_column = f"delta_relative__{scenario}"
    parts: list[pd.DataFrame] = []
    for dimension, column in (
        ("tramo_etario", "age_group"),
        ("ingreso_promedio", "income_group"),
        ("densidad", "density_group"),
        ("sexo", "sexo"),
        ("afp", "afp"),
        ("fondo_observado_predominante", "predominant_observed_fund"),
    ):
        grouped = (
            frame.groupby(column, dropna=False, observed=True)
            .agg(
                n=("correl", "size"),
                median_delta_uf=(delta_column, "median"),
                median_delta_relative=(relative_column, "median"),
                winner_share=(delta_column, lambda values: float((values > 0).mean())),
            )
            .reset_index()
            .rename(columns={column: "group"})
        )
        grouped.insert(0, "dimension", dimension)
        parts.append(grouped)
    return pd.concat(parts, ignore_index=True)


def ols_hc3(individual: pd.DataFrame, scenario: str = "base") -> pd.DataFrame:
    frame = individual[
        [
            f"delta_relative__{scenario}",
            "age_start",
            "mean_wage_uf",
            "contribution_density",
            "predominant_observed_fund",
        ]
    ].dropna()
    if len(frame) < 10:
        return pd.DataFrame(
            [{"term": "model", "estimate": np.nan, "robust_se_hc3": np.nan, "note": "n<10"}]
        )
    dummies = pd.get_dummies(
        frame["predominant_observed_fund"], prefix="fund", drop_first=True, dtype=float
    )
    numeric = frame[["age_start", "mean_wage_uf", "contribution_density"]].astype(float)
    design_frame = pd.concat(
        [pd.Series(1.0, index=frame.index, name="intercept"), numeric, dummies], axis=1
    )
    x = design_frame.to_numpy(dtype=float)
    y = frame[f"delta_relative__{scenario}"].to_numpy(dtype=float)
    inverse = np.linalg.pinv(x.T @ x)
    beta = inverse @ x.T @ y
    residual = y - x @ beta
    leverage = np.sum((x @ inverse) * x, axis=1)
    adjusted = residual / np.clip(1.0 - leverage, 1e-8, None)
    meat = x.T @ (x * (adjusted**2)[:, None])
    covariance = inverse @ meat @ inverse
    standard_error = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    z = np.divide(beta, standard_error, out=np.full_like(beta, np.nan), where=standard_error > 0)
    p_value = np.array(
        [math.erfc(abs(value) / math.sqrt(2.0)) if np.isfinite(value) else np.nan for value in z]
    )
    return pd.DataFrame(
        {
            "term": design_frame.columns,
            "estimate": beta,
            "robust_se_hc3": standard_error,
            "z_normal_approximation": z,
            "p_value_two_sided": p_value,
            "n": len(frame),
        }
    )


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None
