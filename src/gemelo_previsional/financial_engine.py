from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import __version__
from .individual_core import accounting_step_vectorized


@dataclass
class FinancialEngineOutputs:
    path_results: pd.DataFrame
    balance_summary: pd.DataFrame
    state_occupancy: pd.DataFrame
    transition_matrix: pd.DataFrame
    asset_parameters: pd.DataFrame
    asset_covariance: pd.DataFrame
    fund_parameters: pd.DataFrame
    return_diagnostics: pd.DataFrame
    representative_trajectories: pd.DataFrame
    metadata: dict[str, Any]


def load_financial_engine_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = str(config_path)
    validate_financial_engine_config(config)
    return config


def _finite_vector(values: Any, name: str, *, expected_length: int | None = None) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or (expected_length is not None and len(vector) != expected_length):
        expected = f" de largo {expected_length}" if expected_length is not None else ""
        raise ValueError(f"{name} debe ser un vector{expected}")
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} debe contener solo valores finitos")
    return vector


def validate_financial_engine_config(config: dict[str, Any]) -> None:
    if not str(config.get("experiment_name", "")).strip():
        raise ValueError("experiment_name no puede estar vacío")
    if int(config.get("paths", 0)) < 20:
        raise ValueError("paths debe ser al menos 20")
    if int(config.get("seed", -1)) < 0:
        raise ValueError("seed no puede ser negativo")

    profile = config.get("profile", {})
    required_profile = (
        "start_age",
        "retirement_age",
        "initial_monthly_wage_uf",
        "initial_balance_uf",
        "annual_real_wage_growth",
        "contribution_rate",
        "contribution_timing",
        "account_unit",
    )
    missing = [key for key in required_profile if key not in profile]
    if missing:
        raise ValueError(f"Faltan parámetros del perfil: {', '.join(missing)}")
    numeric_profile = _finite_vector(
        [
            profile["start_age"],
            profile["retirement_age"],
            profile["initial_monthly_wage_uf"],
            profile["initial_balance_uf"],
            profile["annual_real_wage_growth"],
            profile["contribution_rate"],
        ],
        "profile",
        expected_length=6,
    )
    start_age, retirement_age, wage, balance, wage_growth, contribution_rate = numeric_profile
    if retirement_age <= start_age:
        raise ValueError("retirement_age debe ser mayor que start_age")
    horizon = (retirement_age - start_age) * 12
    if not np.isclose(horizon, round(horizon)):
        raise ValueError("El horizonte debe contener un número entero de meses")
    if wage <= 0 or balance < 0:
        raise ValueError("El salario debe ser positivo y el saldo inicial no negativo")
    if wage_growth <= -1:
        raise ValueError("annual_real_wage_growth debe ser mayor que -100%")
    if not 0 < contribution_rate <= 1:
        raise ValueError("contribution_rate debe estar en (0, 1]")
    if profile["contribution_timing"] not in {"start", "end"}:
        raise ValueError("contribution_timing debe ser 'start' o 'end'")
    if profile["account_unit"] != "UF_real":
        raise ValueError("account_unit debe ser 'UF_real' para evitar mezclar unidades")
    if not str(profile.get("contribution_policy_note", "")).strip():
        raise ValueError("profile.contribution_policy_note debe declarar el alcance de la tasa")

    labor = config.get("labor", {})
    states = labor.get("states", [])
    if not isinstance(states, list) or not states or len(states) != len(set(states)):
        raise ValueError("labor.states debe contener estados únicos")
    if any(not str(state).strip() for state in states):
        raise ValueError("labor.states no puede contener nombres vacíos")
    if labor.get("initial_state") not in states:
        raise ValueError("labor.initial_state debe pertenecer a labor.states")
    contributing_states = labor.get("contributing_states", [])
    if not contributing_states or not set(contributing_states).issubset(states):
        raise ValueError("labor.contributing_states debe ser un subconjunto no vacío")
    matrix = labor.get("transition_matrix", {})
    if set(matrix) != set(states):
        raise ValueError("labor.transition_matrix debe declarar una fila por estado")
    for source in states:
        row = matrix[source]
        if set(row) != set(states):
            raise ValueError(f"La fila laboral {source!r} debe declarar todos los destinos")
        values = _finite_vector([row[target] for target in states], f"fila laboral {source}")
        if bool((values < 0).any()):
            raise ValueError(f"La fila laboral {source!r} contiene probabilidades negativas")
        if not np.isclose(values.sum(), 1.0, atol=1e-12):
            raise ValueError(
                f"La fila laboral {source!r} debe sumar 1; suma {values.sum():.12f}"
            )
    if not str(labor.get("parameter_provenance", "")).strip():
        raise ValueError("labor.parameter_provenance no puede estar vacío")

    market = config.get("market", {})
    if market.get("model") != "gaussian_multivariate_simple_returns":
        raise ValueError("El motor v1 solo admite gaussian_multivariate_simple_returns")
    assets = market.get("assets", [])
    if not isinstance(assets, list) or not assets or len(assets) != len(set(assets)):
        raise ValueError("market.assets debe contener identificadores únicos")
    if any(not str(asset).strip() for asset in assets):
        raise ValueError("market.assets no puede contener identificadores vacíos")
    asset_count = len(assets)
    means = _finite_vector(
        market.get("monthly_mean_simple_returns", []),
        "market.monthly_mean_simple_returns",
        expected_length=asset_count,
    )
    covariance = np.asarray(market.get("monthly_covariance", []), dtype=float)
    if covariance.shape != (asset_count, asset_count):
        raise ValueError(
            f"market.monthly_covariance debe tener forma {(asset_count, asset_count)}"
        )
    if not np.isfinite(covariance).all():
        raise ValueError("market.monthly_covariance debe contener solo valores finitos")
    if not np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-12):
        raise ValueError("market.monthly_covariance debe ser simétrica")
    if bool((np.diag(covariance) <= 0).any()):
        raise ValueError("La diagonal de market.monthly_covariance debe ser positiva")
    minimum_eigenvalue = float(np.linalg.eigvalsh(covariance).min())
    if minimum_eigenvalue < -1e-12:
        raise ValueError(
            "market.monthly_covariance debe ser semidefinida positiva; "
            f"autovalor mínimo {minimum_eigenvalue:.6g}"
        )
    if bool((means <= -1).any()):
        raise ValueError("Las medias de retornos simples deben ser mayores que -100%")
    if not str(market.get("parameter_provenance", "")).strip():
        raise ValueError("market.parameter_provenance no puede estar vacío")

    funds = config.get("funds", {})
    fund_ids = funds.get("ids", [])
    if not isinstance(fund_ids, list) or len(fund_ids) != 10 or len(set(fund_ids)) != 10:
        raise ValueError("funds.ids debe contener diez identificadores únicos")
    upper_bounds = _finite_vector(
        funds.get("age_upper_bounds_inclusive", []),
        "funds.age_upper_bounds_inclusive",
        expected_length=len(fund_ids) - 1,
    )
    if bool((np.diff(upper_bounds) <= 0).any()):
        raise ValueError("Los cortes etarios de funds deben ser estrictamente crecientes")
    weights = funds.get("weights", {})
    if set(weights) != set(fund_ids):
        raise ValueError("funds.weights debe declarar una cartera para cada fondo")
    for fund_id in fund_ids:
        allocation = weights[fund_id]
        if set(allocation) != set(assets):
            raise ValueError(f"El fondo {fund_id!r} debe declarar todos los activos")
        values = _finite_vector(
            [allocation[asset] for asset in assets], f"pesos del fondo {fund_id}"
        )
        if bool((values < 0).any()):
            raise ValueError(f"El fondo {fund_id!r} contiene pesos negativos")
        if not np.isclose(values.sum(), 1.0, atol=1e-12):
            raise ValueError(
                f"Los pesos del fondo {fund_id!r} deben sumar 1; suma {values.sum():.12f}"
            )
    if not str(funds.get("parameter_provenance", "")).strip():
        raise ValueError("funds.parameter_provenance no puede estar vacío")

    quantiles = _finite_vector(
        config.get("reporting", {}).get("representative_quantiles", []),
        "reporting.representative_quantiles",
    )
    if not len(quantiles) or bool(((quantiles <= 0) | (quantiles >= 1)).any()):
        raise ValueError("Los cuantiles representativos deben estar estrictamente entre 0 y 1")
    if len(np.unique(quantiles)) != len(quantiles):
        raise ValueError("Los cuantiles representativos no pueden repetirse")


def _config_arrays(
    config: dict[str, Any],
) -> tuple[list[str], np.ndarray, np.ndarray, list[str], np.ndarray, np.ndarray]:
    assets = list(config["market"]["assets"])
    means = np.asarray(config["market"]["monthly_mean_simple_returns"], dtype=float)
    covariance = np.asarray(config["market"]["monthly_covariance"], dtype=float)
    fund_ids = list(config["funds"]["ids"])
    weights = np.asarray(
        [
            [config["funds"]["weights"][fund_id][asset] for asset in assets]
            for fund_id in fund_ids
        ],
        dtype=float,
    )
    upper_bounds = np.asarray(config["funds"]["age_upper_bounds_inclusive"], dtype=float)
    return assets, means, covariance, fund_ids, weights, upper_bounds


def fund_indices_for_age(age: Any, upper_bounds_inclusive: Any) -> np.ndarray:
    ages = np.asarray(age, dtype=float)
    bounds = np.asarray(upper_bounds_inclusive, dtype=float)
    if not np.isfinite(ages).all():
        raise ValueError("Las edades deben ser finitas")
    return np.searchsorted(bounds, ages, side="left").astype(int)


def _transition_arrays(config: dict[str, Any]) -> tuple[list[str], np.ndarray]:
    states = list(config["labor"]["states"])
    matrix = np.asarray(
        [
            [config["labor"]["transition_matrix"][source][target] for target in states]
            for source in states
        ],
        dtype=float,
    )
    cumulative = np.cumsum(matrix, axis=1)
    cumulative[:, -1] = 1.0
    return states, cumulative


def _asset_parameter_tables(
    assets: list[str], means: np.ndarray, covariance: np.ndarray
) -> tuple[pd.DataFrame, pd.DataFrame]:
    volatility = np.sqrt(np.diag(covariance))
    parameters = pd.DataFrame(
        {
            "asset": assets,
            "monthly_mean_simple_return": means,
            "monthly_volatility": volatility,
            "annualized_arithmetic_mean": 12.0 * means,
            "annualized_volatility": np.sqrt(12.0) * volatility,
        }
    )
    covariance_rows = []
    for row_index, row_asset in enumerate(assets):
        for column_index, column_asset in enumerate(assets):
            covariance_rows.append(
                {
                    "row_asset": row_asset,
                    "column_asset": column_asset,
                    "monthly_covariance": float(covariance[row_index, column_index]),
                    "monthly_correlation": float(
                        covariance[row_index, column_index]
                        / (volatility[row_index] * volatility[column_index])
                    ),
                }
            )
    return parameters, pd.DataFrame(covariance_rows)


def _fund_parameter_table(
    assets: list[str],
    means: np.ndarray,
    covariance: np.ndarray,
    fund_ids: list[str],
    weights: np.ndarray,
    upper_bounds: np.ndarray,
) -> pd.DataFrame:
    fund_means = weights @ means
    fund_covariance = weights @ covariance @ weights.T
    rows = []
    for index, fund_id in enumerate(fund_ids):
        row: dict[str, Any] = {
            "fund_id": fund_id,
            "age_upper_bound_inclusive": (
                float(upper_bounds[index]) if index < len(upper_bounds) else np.nan
            ),
            "weight_sum": float(weights[index].sum()),
            "monthly_mean_simple_return": float(fund_means[index]),
            "monthly_volatility": float(np.sqrt(fund_covariance[index, index])),
            "annualized_arithmetic_mean": float(12.0 * fund_means[index]),
            "annualized_volatility": float(
                np.sqrt(12.0) * np.sqrt(fund_covariance[index, index])
            ),
        }
        for asset_index, asset in enumerate(assets):
            row[f"weight_{asset}"] = float(weights[index, asset_index])
        rows.append(row)
    return pd.DataFrame(rows)


def _transition_table(config: dict[str, Any]) -> pd.DataFrame:
    states = list(config["labor"]["states"])
    return pd.DataFrame(
        [
            {
                "source_state": source,
                "target_state": target,
                "monthly_probability": float(
                    config["labor"]["transition_matrix"][source][target]
                ),
            }
            for source in states
            for target in states
        ]
    )


def _balance_summary(path_results: pd.DataFrame, months: int) -> pd.DataFrame:
    final = path_results["final_balance_uf"]
    return pd.DataFrame(
        [
            {
                "paths": int(len(path_results)),
                "months": int(months),
                "years": float(months / 12.0),
                "mean_final_balance_uf": float(final.mean()),
                "std_final_balance_uf": float(final.std(ddof=1)),
                "min_final_balance_uf": float(final.min()),
                "p10_final_balance_uf": float(final.quantile(0.10)),
                "p25_final_balance_uf": float(final.quantile(0.25)),
                "median_final_balance_uf": float(final.median()),
                "p75_final_balance_uf": float(final.quantile(0.75)),
                "p90_final_balance_uf": float(final.quantile(0.90)),
                "max_final_balance_uf": float(final.max()),
                "mean_total_contributions_uf": float(
                    path_results["total_contributions_uf"].mean()
                ),
                "median_contribution_density": float(
                    path_results["contribution_density"].median()
                ),
            }
        ]
    )


def simulate_financial_engine(config: dict[str, Any]) -> FinancialEngineOutputs:
    validate_financial_engine_config(config)
    clean_config = copy.deepcopy(config)
    clean_config.pop("_config_path", None)

    paths = int(config["paths"])
    seed = int(config["seed"])
    profile = config["profile"]
    months = int(
        round(
            (float(profile["retirement_age"]) - float(profile["start_age"])) * 12
        )
    )
    assets, means, covariance, fund_ids, weights, upper_bounds = _config_arrays(config)
    states, cumulative = _transition_arrays(config)
    initial_state_index = states.index(config["labor"]["initial_state"])
    contributing_indices = np.asarray(
        [states.index(state) for state in config["labor"]["contributing_states"]],
        dtype=int,
    )

    seed_sequence = np.random.SeedSequence(seed)
    labor_seed, market_seed = seed_sequence.spawn(2)
    labor_rng = np.random.default_rng(labor_seed)
    market_rng = np.random.default_rng(market_seed)

    state_indices = np.full(paths, initial_state_index, dtype=np.int16)
    balances = np.full(paths, float(profile["initial_balance_uf"]), dtype=float)
    total_contributions = np.zeros(paths, dtype=float)
    months_by_state = np.zeros((paths, len(states)), dtype=np.int32)
    balance_history = np.empty((paths, months), dtype=float)
    state_history = np.empty((paths, months), dtype=np.int16)
    selected_return_history = np.empty((paths, months), dtype=float)

    return_sum = np.zeros(len(fund_ids), dtype=float)
    return_sum_squares = np.zeros(len(fund_ids), dtype=float)
    return_min = np.full(len(fund_ids), np.inf, dtype=float)
    return_max = np.full(len(fund_ids), -np.inf, dtype=float)

    initial_wage = float(profile["initial_monthly_wage_uf"])
    wage_growth = float(profile["annual_real_wage_growth"])
    contribution_rate = float(profile["contribution_rate"])
    contribution_timing = str(profile["contribution_timing"])
    start_age = float(profile["start_age"])

    for month in range(months):
        state_history[:, month] = state_indices
        for state_index in range(len(states)):
            months_by_state[:, state_index] += state_indices == state_index

        potential_wage = initial_wage * ((1.0 + wage_growth) ** (month / 12.0))
        contributes = np.isin(state_indices, contributing_indices)
        contribution = contribution_rate * potential_wage * contributes
        total_contributions += contribution

        asset_returns = market_rng.multivariate_normal(
            mean=means,
            cov=covariance,
            size=paths,
            check_valid="raise",
            method="svd",
        )
        if not np.isfinite(asset_returns).all() or bool((asset_returns <= -1).any()):
            raise RuntimeError(
                "El mercado produjo retornos de activos no finitos o menores o iguales a -100%; "
                "no se aplicó recorte silencioso"
            )
        fund_returns = asset_returns @ weights.T
        if not np.isfinite(fund_returns).all() or bool((fund_returns <= -1).any()):
            raise RuntimeError(
                "El mercado produjo retornos no finitos o menores o iguales a -100%; "
                "no se aplicó recorte silencioso"
            )
        return_sum += fund_returns.sum(axis=0)
        return_sum_squares += np.square(fund_returns).sum(axis=0)
        return_min = np.minimum(return_min, fund_returns.min(axis=0))
        return_max = np.maximum(return_max, fund_returns.max(axis=0))

        age = start_age + month / 12.0
        fund_index = int(fund_indices_for_age(age, upper_bounds))
        selected_return = fund_returns[:, fund_index]
        selected_return_history[:, month] = selected_return
        balances = accounting_step_vectorized(
            balances,
            contribution,
            selected_return,
            contribution_timing=contribution_timing,
        )
        balance_history[:, month] = balances

        uniforms = labor_rng.random(paths)
        state_indices = (
            uniforms[:, None] > cumulative[state_indices]
        ).sum(axis=1).astype(np.int16)

    path_records: dict[str, Any] = {
        "draw_id": [f"draw_{index + 1:05d}" for index in range(paths)],
        "final_balance_uf": balances,
        "total_contributions_uf": total_contributions,
        "contribution_density": months_by_state[:, contributing_indices].sum(axis=1)
        / months,
    }
    for state_index, state in enumerate(states):
        path_records[f"months_{state}"] = months_by_state[:, state_index]
    path_results = pd.DataFrame(path_records)

    denominator = paths * months
    state_occupancy = pd.DataFrame(
        [
            {
                "state": state,
                "person_months": int(months_by_state[:, index].sum()),
                "share_person_months": float(months_by_state[:, index].sum() / denominator),
            }
            for index, state in enumerate(states)
        ]
    )

    asset_parameters, asset_covariance = _asset_parameter_tables(assets, means, covariance)
    fund_parameters = _fund_parameter_table(
        assets, means, covariance, fund_ids, weights, upper_bounds
    )
    observations_per_fund = paths * months
    empirical_mean = return_sum / observations_per_fund
    empirical_variance = (
        return_sum_squares - observations_per_fund * np.square(empirical_mean)
    ) / (observations_per_fund - 1)
    analytic_by_fund = fund_parameters.set_index("fund_id")
    return_diagnostics = pd.DataFrame(
        [
            {
                "fund_id": fund_id,
                "observations": int(observations_per_fund),
                "analytic_monthly_mean": float(
                    analytic_by_fund.loc[fund_id, "monthly_mean_simple_return"]
                ),
                "empirical_monthly_mean": float(empirical_mean[index]),
                "mean_error": float(
                    empirical_mean[index]
                    - analytic_by_fund.loc[fund_id, "monthly_mean_simple_return"]
                ),
                "analytic_monthly_volatility": float(
                    analytic_by_fund.loc[fund_id, "monthly_volatility"]
                ),
                "empirical_monthly_volatility": float(
                    np.sqrt(max(empirical_variance[index], 0.0))
                ),
                "minimum_simulated_return": float(return_min[index]),
                "maximum_simulated_return": float(return_max[index]),
            }
            for index, fund_id in enumerate(fund_ids)
        ]
    )

    trajectory_frames: list[pd.DataFrame] = []
    representative_paths: dict[str, str] = {}
    representative_quantiles = [
        float(value) for value in config["reporting"]["representative_quantiles"]
    ]
    ages = start_age + np.arange(months, dtype=float) / 12.0
    fund_index_by_month = fund_indices_for_age(ages, upper_bounds)
    wages = initial_wage * ((1.0 + wage_growth) ** (np.arange(months) / 12.0))
    for quantile in representative_quantiles:
        target = float(np.quantile(balances, quantile))
        path_index = int(np.abs(balances - target).argmin())
        label = f"p{int(round(quantile * 100)):02d}"
        path_id = str(path_results.loc[path_index, "draw_id"])
        representative_paths[label] = path_id
        states_for_path = state_history[path_index]
        contributions = (
            contribution_rate
            * wages
            * np.isin(states_for_path, contributing_indices)
        )
        opening = np.concatenate(
            ([float(profile["initial_balance_uf"])], balance_history[path_index, :-1])
        )
        closing = balance_history[path_index]
        expected = accounting_step_vectorized(
            opening,
            contributions,
            selected_return_history[path_index],
            contribution_timing=contribution_timing,
        )
        if not np.allclose(expected, closing, rtol=1e-12, atol=1e-10):
            raise RuntimeError("Una trayectoria representativa no satisface la identidad contable")
        trajectory_frames.append(
            pd.DataFrame(
                {
                    "representative_quantile": label,
                    "path_id": path_id,
                    "month": np.arange(1, months + 1, dtype=int),
                    "age": ages,
                    "labor_state": [states[index] for index in states_for_path],
                    "potential_wage_uf": wages,
                    "contribution_uf": contributions,
                    "fund_id": [fund_ids[index] for index in fund_index_by_month],
                    "monthly_return": selected_return_history[path_index],
                    "opening_balance_uf": opening,
                    "closing_balance_uf": closing,
                }
            )
        )
    representative_trajectories = pd.concat(trajectory_frames, ignore_index=True)

    balance_summary = _balance_summary(path_results, months)
    used_funds = [fund_ids[index] for index in np.unique(fund_index_by_month)]
    canonical_config = json.dumps(
        clean_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    transition_matrix = np.diff(
        np.column_stack([np.zeros(len(states)), cumulative]), axis=1
    )
    metadata = {
        "experiment_name": config["experiment_name"],
        "software_version": __version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "config_sha256": hashlib.sha256(canonical_config).hexdigest(),
        "status": "completed",
        "experiment_type": "synthetic_joint_labor_financial_monte_carlo_v1",
        "methodological_scope": "motor_financiero_reproducible_v1",
        "seed": seed,
        "random_number_generator": "numpy.default_rng.PCG64",
        "independent_random_streams": {
            "labor": list(labor_seed.spawn_key),
            "market": list(market_seed.spawn_key),
        },
        "paths": paths,
        "months": months,
        "years": months / 12.0,
        "market_model": config["market"]["model"],
        "shared_accounting_core": "individual_core.accounting_step_vectorized",
        "contribution_timing": contribution_timing,
        "account_unit": profile["account_unit"],
        "fund_count": len(fund_ids),
        "funds_used_by_profile_horizon": used_funds,
        "representative_paths": representative_paths,
        "minimum_covariance_eigenvalue": float(np.linalg.eigvalsh(covariance).min()),
        "validation_gates": {
            "transition_rows_sum_to_one": bool(
                np.allclose(transition_matrix.sum(axis=1), 1.0, atol=1e-12)
            ),
            "fund_weights_sum_to_one": bool(
                np.allclose(weights.sum(axis=1), 1.0, atol=1e-12)
            ),
            "covariance_positive_semidefinite": bool(
                np.linalg.eigvalsh(covariance).min() >= -1e-12
            ),
            "all_simulated_asset_and_fund_returns_above_minus_one": True,
            "representative_trajectories_pass_accounting_identity": True,
        },
        "corrections_applied": copy.deepcopy(config.get("corrections_applied", [])),
        "warnings": [
            "Las transiciones laborales y los parámetros financieros son supuestos no calibrados con HPA.",
            "Los fondos FG01-FG10 son sintéticos y no representan carteras regulatorias oficiales.",
            "La tasa de cotización es un escenario simplificado constante, no la implementación temporal de la reforma.",
            "Los retornos normales multivariados no reproducen completamente colas, crisis ni cambios de régimen.",
            "Los resultados combinan incertidumbre laboral y financiera y no constituyen una predicción individual o nacional.",
        ],
        "config": clean_config,
    }
    return FinancialEngineOutputs(
        path_results=path_results,
        balance_summary=balance_summary,
        state_occupancy=state_occupancy,
        transition_matrix=_transition_table(config),
        asset_parameters=asset_parameters,
        asset_covariance=asset_covariance,
        fund_parameters=fund_parameters,
        return_diagnostics=return_diagnostics,
        representative_trajectories=representative_trajectories,
        metadata=metadata,
    )


def _write_readme(outputs: FinancialEngineOutputs, path: Path) -> None:
    summary = outputs.balance_summary.iloc[0]
    lines = [
        "# Motor financiero reproducible v1",
        "",
        "Primera adaptación controlada del prototipo recibido por el equipo. Combina una cadena de Markov laboral con retornos simples normales multivariados y diez fondos sintéticos por edad.",
        "",
        "## Resultado de la configuración versionada",
        "",
        f"- Caminos: {int(summary['paths']):,}",
        f"- Horizonte: {int(summary['months'])} meses",
        f"- Saldo final mediano: {summary['median_final_balance_uf']:,.2f} UF",
        f"- P10–P90: {summary['p10_final_balance_uf']:,.2f}–{summary['p90_final_balance_uf']:,.2f} UF",
        f"- Densidad de cotización mediana: {summary['median_contribution_density']:.1%}",
        "",
        "## Interpretación",
        "",
        "Esta corrida estima la distribución conjunta sintética del saldo bajo incertidumbre laboral y financiera. No aísla todavía el efecto de una política de inversión y no reemplaza el Experimento I ni el Hito 2.",
        "",
        "La configuración utiliza UF reales, semilla fija, flujos aleatorios independientes para trabajo y mercado, y el núcleo contable compartido. Los archivos de parámetros y diagnósticos permiten auditar carteras, covarianzas y momentos simulados.",
        "",
        "Los parámetros provienen del script recibido y siguen pendientes de contrastarse con el archivo fuente `preámbulo.py`. Los fondos son sintéticos y la cotización constante es solo un supuesto de escenario.",
        "",
        "## Reproducir",
        "",
        "```powershell",
        "gemelo-previsional motor-financiero --config config/motor_financiero.json --output-dir examples/motor_financiero",
        "```",
        "",
        "Consulte `docs/FINANCIAL_ENGINE.md` para la metodología y `motor_financiero_summary.json` para el manifiesto completo.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_financial_engine(config: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    outputs = simulate_financial_engine(config)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "motor_financiero_path_results.csv": outputs.path_results,
        "motor_financiero_balance_summary.csv": outputs.balance_summary,
        "motor_financiero_state_occupancy.csv": outputs.state_occupancy,
        "motor_financiero_transition_matrix.csv": outputs.transition_matrix,
        "motor_financiero_asset_parameters.csv": outputs.asset_parameters,
        "motor_financiero_asset_covariance.csv": outputs.asset_covariance,
        "motor_financiero_fund_parameters.csv": outputs.fund_parameters,
        "motor_financiero_return_diagnostics.csv": outputs.return_diagnostics,
        "motor_financiero_representative_trajectories.csv": outputs.representative_trajectories,
    }
    for filename, frame in tables.items():
        frame.to_csv(output / filename, index=False, encoding="utf-8")
    with (output / "motor_financiero_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(outputs.metadata, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    _write_readme(outputs, output / "README.md")
    return {
        "status": "completed",
        "experiment_name": outputs.metadata["experiment_name"],
        "paths": outputs.metadata["paths"],
        "months": outputs.metadata["months"],
        "output_directory": str(output),
    }
