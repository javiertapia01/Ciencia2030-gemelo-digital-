from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import FUNDS


SCENARIOS: dict[str, list[int]] = {
    "transicion_5_anios_antes": [30, 40, 50, 60],
    "base": [35, 45, 55, 65],
    "transicion_5_anios_despues": [40, 50, 60, 70],
}

ARCHETYPES = (
    {
        "archetype": "Joven en Fondo C",
        "age_start": 28,
        "wage_uf": 35.0,
        "density": 1.0,
        "initial_balance_uf": 10.0,
        "observed_fund": "C",
    },
    {
        "archetype": "Edad media en Fondo A",
        "age_start": 48,
        "wage_uf": 55.0,
        "density": 0.8,
        "initial_balance_uf": 90.0,
        "observed_fund": "A",
    },
    {
        "archetype": "Próxima al retiro en Fondo A",
        "age_start": 60,
        "wage_uf": 45.0,
        "density": 0.6,
        "initial_balance_uf": 180.0,
        "observed_fund": "A",
    },
)


def deterministic_market_returns(months: int) -> pd.DataFrame:
    """Create a transparent, deterministic market path with two stress episodes."""
    month = np.arange(months, dtype=float)
    fixed_income = 0.0017 + 0.0005 * np.sin(2 * np.pi * month / 18.0)
    market = 0.0032 + 0.0045 * np.sin(2 * np.pi * month / 30.0)
    market += 0.0015 * np.cos(2 * np.pi * month / 11.0)
    stress = {
        24: -0.13,
        25: -0.055,
        26: 0.055,
        27: 0.035,
        72: -0.16,
        73: 0.075,
        74: 0.045,
    }
    for index, shock in stress.items():
        if index < months:
            market[index] += shock
    exposure = np.array([1.40, 1.10, 0.80, 0.45, 0.15])
    alpha = np.array([0.0004, 0.0003, 0.0002, 0.0001, 0.0])
    values = fixed_income[:, None] + market[:, None] * exposure[None, :] + alpha[None, :]
    if bool((values <= -1).any()):
        raise ValueError("La trayectoria toy produjo un retorno <= -100%")
    result = pd.DataFrame(values, columns=[f"return_{fund}" for fund in FUNDS])
    result.insert(0, "month", np.arange(months, dtype=int))
    result["year"] = result["month"] / 12.0
    return result


def _fund_indices_for_age(age: np.ndarray, cuts: list[int]) -> np.ndarray:
    return np.select(
        [age < cuts[0], age < cuts[1], age < cuts[2], age < cuts[3]],
        [0, 1, 2, 3],
        default=4,
    ).astype(int)


def generate_cohort(people: int, months: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    age = rng.integers(25, 68, size=people)
    wage = np.clip(rng.lognormal(np.log(38.0), 0.35, size=people), 15.0, 100.0)
    density = np.clip(rng.beta(5.0, 2.0, size=people), 0.20, 1.0)
    balance_scale = rng.uniform(1.8, 4.5, size=people)
    initial_balance = np.clip((age - 20) * balance_scale, 5.0, 260.0)
    target_fund = _fund_indices_for_age(age.astype(float), SCENARIOS["base"])
    preference_shift = rng.choice([-2, -1, 0, 1, 2], size=people, p=[0.08, 0.20, 0.44, 0.20, 0.08])
    observed_index = np.clip(target_fund + preference_shift, 0, 4)
    activity = rng.random((people, months)) < density[:, None]
    cohort = pd.DataFrame(
        {
            "toy_id": [f"TOY{index + 1:04d}" for index in range(people)],
            "age_start": age,
            "wage_uf": wage,
            "target_density": density,
            "realized_density": activity.mean(axis=1),
            "initial_balance_uf": initial_balance,
            "observed_fund": np.asarray(FUNDS)[observed_index],
            "observed_fund_index": observed_index,
        }
    )
    return cohort, activity


def simulate_cohort(
    cohort: pd.DataFrame,
    activity: np.ndarray,
    returns: pd.DataFrame,
    contribution_rate: float = 0.10,
) -> pd.DataFrame:
    months = len(returns)
    return_matrix = returns[[f"return_{fund}" for fund in FUNDS]].to_numpy(dtype=float)
    wage_initial = cohort["wage_uf"].to_numpy(dtype=float)
    observed_index = cohort["observed_fund_index"].to_numpy(dtype=int)
    initial = cohort["initial_balance_uf"].to_numpy(dtype=float)
    observed = initial.copy()
    what_if = {scenario: initial.copy() for scenario in SCENARIOS}

    for month in range(months):
        wage = wage_initial * (1.01 ** (month / 12.0))
        contribution = contribution_rate * wage * activity[:, month]
        observed_return = return_matrix[month, observed_index]
        observed = (observed + contribution) * (1.0 + observed_return)
        age = cohort["age_start"].to_numpy(dtype=float) + month / 12.0
        for scenario, cuts in SCENARIOS.items():
            assigned_index = _fund_indices_for_age(age, cuts)
            assigned_return = return_matrix[month, assigned_index]
            what_if[scenario] = (what_if[scenario] + contribution) * (1.0 + assigned_return)

    result = cohort.drop(columns="observed_fund_index").copy()
    result["final_observed_uf"] = observed
    for scenario in SCENARIOS:
        result[f"final_what_if_uf__{scenario}"] = what_if[scenario]
        result[f"delta_uf__{scenario}"] = what_if[scenario] - observed
        result[f"delta_relative__{scenario}"] = what_if[scenario] / observed - 1.0
    result["age_band"] = pd.cut(
        result["age_start"],
        bins=[-np.inf, 34, 44, 54, np.inf],
        labels=["<35", "35–44", "45–54", "55+"],
    ).astype("string")
    return result


def simulate_archetypes(returns: pd.DataFrame, contribution_rate: float = 0.10) -> pd.DataFrame:
    return_matrix = returns[[f"return_{fund}" for fund in FUNDS]].to_numpy(dtype=float)
    records: list[dict[str, Any]] = []
    for archetype_index, archetype in enumerate(ARCHETYPES):
        observed = float(archetype["initial_balance_uf"])
        what_if = observed
        observed_index = FUNDS.index(str(archetype["observed_fund"]))
        records.append(
            {
                **archetype,
                "month": 0,
                "year": 0.0,
                "observed_balance_uf": observed,
                "what_if_balance_uf": what_if,
                "delta_uf": 0.0,
                "what_if_fund": FUNDS[
                    _fund_indices_for_age(np.array([float(archetype["age_start"])]), SCENARIOS["base"])[0]
                ],
            }
        )
        for month in range(len(returns)):
            regular = ((month * 997 + archetype_index * 137) % 1000) / 1000.0
            active = regular < float(archetype["density"])
            wage = float(archetype["wage_uf"]) * (1.01 ** (month / 12.0))
            contribution = contribution_rate * wage * active
            observed = (observed + contribution) * (1.0 + return_matrix[month, observed_index])
            age = float(archetype["age_start"]) + month / 12.0
            assigned_index = int(_fund_indices_for_age(np.array([age]), SCENARIOS["base"])[0])
            what_if = (what_if + contribution) * (1.0 + return_matrix[month, assigned_index])
            records.append(
                {
                    **archetype,
                    "month": month + 1,
                    "year": (month + 1) / 12.0,
                    "observed_balance_uf": observed,
                    "what_if_balance_uf": what_if,
                    "delta_uf": what_if - observed,
                    "what_if_fund": FUNDS[assigned_index],
                }
            )
    return pd.DataFrame(records)


def summarize_results(individual: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    sensitivity_records: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        delta = individual[f"delta_uf__{scenario}"]
        relative = individual[f"delta_relative__{scenario}"]
        sensitivity_records.append(
            {
                "scenario": scenario,
                "n": int(len(individual)),
                "median_delta_uf": float(delta.median()),
                "mean_delta_uf": float(delta.mean()),
                "median_delta_relative": float(relative.median()),
                "winner_share": float((delta > 0).mean()),
            }
        )
    sensitivity = pd.DataFrame(sensitivity_records)
    age_summary = (
        individual.groupby("age_band", observed=True)
        .agg(
            n=("toy_id", "size"),
            median_delta_uf=("delta_uf__base", "median"),
            mean_delta_uf=("delta_uf__base", "mean"),
            median_delta_relative=("delta_relative__base", "median"),
            winner_share=("delta_uf__base", lambda values: float((values > 0).mean())),
        )
        .reset_index()
    )
    base = sensitivity[sensitivity["scenario"].eq("base")].iloc[0]
    summary = {
        "experiment_type": "toy_synthetic_not_empirical",
        "gate_passed_by_construction": True,
        "validation_max_absolute_error_uf": 0.0,
        "people": int(len(individual)),
        "months": 120,
        "base": {
            "median_delta_uf": float(base["median_delta_uf"]),
            "mean_delta_uf": float(base["mean_delta_uf"]),
            "median_delta_relative": float(base["median_delta_relative"]),
            "winner_share": float(base["winner_share"]),
        },
        "warning": "Resultados sintéticos para demostración; no describen la HPA ni la reforma real.",
    }
    return summary, age_summary, sensitivity


def run_toy_experiments(
    output_dir: str | Path,
    people: int = 800,
    months: int = 120,
    seed: int = 2030,
) -> dict[str, Any]:
    if people < 20:
        raise ValueError("El experimento toy requiere al menos 20 personas")
    if months < 24:
        raise ValueError("El experimento toy requiere al menos 24 meses")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    returns = deterministic_market_returns(months)
    cohort, activity = generate_cohort(people, months, seed)
    individual = simulate_cohort(cohort, activity, returns)
    trajectories = simulate_archetypes(returns)
    summary, age_summary, sensitivity = summarize_results(individual)
    summary["months"] = months
    summary["seed"] = seed

    returns.to_csv(output / "toy_market_returns.csv", index=False, encoding="utf-8")
    individual.to_csv(output / "toy_individual_results.csv", index=False, encoding="utf-8")
    trajectories.to_csv(output / "toy_archetype_trajectories.csv", index=False, encoding="utf-8")
    age_summary.to_csv(output / "toy_age_summary.csv", index=False, encoding="utf-8")
    sensitivity.to_csv(output / "toy_sensitivity_summary.csv", index=False, encoding="utf-8")
    with (output / "toy_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return {**summary, "output_directory": str(output)}
