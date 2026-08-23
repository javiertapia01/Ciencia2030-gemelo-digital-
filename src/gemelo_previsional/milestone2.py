from __future__ import annotations

import copy
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .model import generational_fund
from .toy import deterministic_market_returns


LABOR_STATES = ("cotizando", "desempleado", "informal", "licencia", "invalidez")
CONTRIBUTING_STATE = "cotizando"
ABSORBING_STATE = "invalidez"


@dataclass
class Milestone2Outputs:
    path_results: pd.DataFrame
    scenario_summary: pd.DataFrame
    state_occupancy: pd.DataFrame
    transition_matrices: pd.DataFrame
    representative_trajectories: pd.DataFrame
    market_returns: pd.DataFrame
    metadata: dict[str, Any]


def load_milestone2_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = str(config_path)
    validate_milestone2_config(config)
    return config


def validate_milestone2_config(config: dict[str, Any]) -> None:
    if not str(config.get("experiment_name", "")).strip():
        raise ValueError("experiment_name no puede estar vacío")
    if int(config.get("paths_per_scenario", 0)) < 20:
        raise ValueError("paths_per_scenario debe ser al menos 20")
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
        "initial_state",
    )
    missing_profile = [name for name in required_profile if name not in profile]
    if missing_profile:
        raise ValueError(f"Faltan parámetros del perfil: {', '.join(missing_profile)}")
    numeric_profile = np.asarray(
        [
            profile["start_age"],
            profile["retirement_age"],
            profile["initial_monthly_wage_uf"],
            profile["initial_balance_uf"],
            profile["annual_real_wage_growth"],
            profile["contribution_rate"],
        ],
        dtype=float,
    )
    if not np.isfinite(numeric_profile).all():
        raise ValueError("Los parámetros numéricos del perfil deben ser finitos")
    if float(profile["retirement_age"]) <= float(profile["start_age"]):
        raise ValueError("retirement_age debe ser mayor que start_age")
    horizon = (float(profile["retirement_age"]) - float(profile["start_age"])) * 12
    if not np.isclose(horizon, round(horizon)):
        raise ValueError("El horizonte entre start_age y retirement_age debe ser un número entero de meses")
    if float(profile["initial_monthly_wage_uf"]) <= 0:
        raise ValueError("initial_monthly_wage_uf debe ser positivo")
    if float(profile["initial_balance_uf"]) < 0:
        raise ValueError("initial_balance_uf no puede ser negativo")
    if float(profile["annual_real_wage_growth"]) <= -1:
        raise ValueError("annual_real_wage_growth debe ser mayor que -100%")
    rate = float(profile["contribution_rate"])
    if not 0 < rate <= 1:
        raise ValueError("contribution_rate debe estar en (0, 1]")
    if profile["initial_state"] not in LABOR_STATES:
        raise ValueError(f"initial_state debe pertenecer a {LABOR_STATES}")

    fund_proxy = config.get("fund_proxy", {})
    cuts = np.asarray(fund_proxy.get("cuts", []), dtype=float)
    if len(cuts) != 4 or not np.isfinite(cuts).all() or bool((np.diff(cuts) <= 0).any()):
        raise ValueError("fund_proxy.cuts debe contener cuatro edades crecientes")

    scenarios = config.get("scenarios", {})
    if len(scenarios) < 3:
        raise ValueError("Se requieren al menos tres escenarios laborales")
    baseline = config.get("baseline_scenario")
    if baseline not in scenarios:
        raise ValueError("baseline_scenario debe identificar uno de los escenarios")

    expected_states = set(LABOR_STATES)
    for scenario_name, scenario in scenarios.items():
        if not str(scenario.get("label", "")).strip() or not str(
            scenario.get("description", "")
        ).strip():
            raise ValueError(f"El escenario {scenario_name!r} requiere label y description")
        matrix = scenario.get("transition_matrix", {})
        if set(matrix) != expected_states:
            raise ValueError(
                f"La matriz de {scenario_name!r} debe tener una fila para cada estado laboral"
            )
        for source_state, probabilities in matrix.items():
            if set(probabilities) != expected_states:
                raise ValueError(
                    f"La fila {scenario_name}.{source_state} debe declarar todos los destinos"
                )
            values = np.asarray(list(probabilities.values()), dtype=float)
            if not np.isfinite(values).all() or bool((values < 0).any()):
                raise ValueError(
                    f"La fila {scenario_name}.{source_state} contiene probabilidades inválidas"
                )
            if not np.isclose(values.sum(), 1.0, atol=1e-10):
                raise ValueError(
                    f"La fila {scenario_name}.{source_state} debe sumar 1; suma {values.sum():.12f}"
                )
        absorbing = matrix[ABSORBING_STATE]
        if not np.isclose(absorbing[ABSORBING_STATE], 1.0) or any(
            not np.isclose(probability, 0.0)
            for state, probability in absorbing.items()
            if state != ABSORBING_STATE
        ):
            raise ValueError(f"{ABSORBING_STATE} debe ser un estado absorbente")


def _matrix_array(scenario: dict[str, Any]) -> np.ndarray:
    matrix = scenario["transition_matrix"]
    return np.asarray(
        [[float(matrix[source][target]) for target in LABOR_STATES] for source in LABOR_STATES],
        dtype=float,
    )


def _simulate_scenario(
    scenario_name: str,
    scenario: dict[str, Any],
    profile: dict[str, Any],
    cuts: list[int],
    returns: pd.DataFrame,
    uniforms: np.ndarray,
) -> tuple[pd.DataFrame, np.ndarray]:
    paths, months = uniforms.shape
    matrix = _matrix_array(scenario)
    cumulative = np.cumsum(matrix, axis=1)
    cumulative[:, -1] = 1.0
    state_indices = np.full(paths, LABOR_STATES.index(profile["initial_state"]), dtype=np.int8)
    balances = np.full(paths, float(profile["initial_balance_uf"]), dtype=float)
    total_contributions = np.zeros(paths, dtype=float)
    months_by_state = np.zeros((paths, len(LABOR_STATES)), dtype=np.int32)
    balance_history = np.empty((paths, months), dtype=float)

    start_age = float(profile["start_age"])
    initial_wage = float(profile["initial_monthly_wage_uf"])
    wage_growth = float(profile["annual_real_wage_growth"])
    contribution_rate = float(profile["contribution_rate"])
    return_matrix = returns[[f"return_{fund}" for fund in ("A", "B", "C", "D", "E")]]
    fund_to_index = {fund: index for index, fund in enumerate(("A", "B", "C", "D", "E"))}

    for month in range(months):
        for state_index in range(len(LABOR_STATES)):
            months_by_state[:, state_index] += state_indices == state_index

        potential_wage = initial_wage * ((1.0 + wage_growth) ** (month / 12.0))
        contributing = state_indices == LABOR_STATES.index(CONTRIBUTING_STATE)
        contribution = contribution_rate * potential_wage * contributing
        total_contributions += contribution

        age = start_age + month / 12.0
        fund = generational_fund(age, cuts)
        monthly_return = float(return_matrix.iloc[month, fund_to_index[fund]])
        balances = (balances + contribution) * (1.0 + monthly_return)
        if not np.isfinite(balances).all() or bool((balances < 0).any()):
            raise RuntimeError(f"La simulación de {scenario_name} produjo saldos inválidos")
        balance_history[:, month] = balances

        thresholds = cumulative[state_indices]
        state_indices = (uniforms[:, month, None] > thresholds).sum(axis=1).astype(np.int8)

    records: dict[str, Any] = {
        "scenario": scenario_name,
        "scenario_label": scenario["label"],
        "draw_id": [f"draw_{index + 1:05d}" for index in range(paths)],
        "path_id": [f"{scenario_name}_{index + 1:05d}" for index in range(paths)],
        "final_balance_uf": balances,
        "total_contributions_uf": total_contributions,
        "contribution_density": months_by_state[:, LABOR_STATES.index(CONTRIBUTING_STATE)] / months,
    }
    for state_index, state in enumerate(LABOR_STATES):
        records[f"months_{state}"] = months_by_state[:, state_index]
    return pd.DataFrame(records), balance_history


def _representative_trajectory(
    scenario_name: str,
    scenario: dict[str, Any],
    profile: dict[str, Any],
    cuts: list[int],
    returns: pd.DataFrame,
    uniforms: np.ndarray,
    representative_index: int,
) -> pd.DataFrame:
    months = uniforms.shape[1]
    matrix = _matrix_array(scenario)
    cumulative = np.cumsum(matrix, axis=1)
    cumulative[:, -1] = 1.0
    state_index = LABOR_STATES.index(profile["initial_state"])
    balance = float(profile["initial_balance_uf"])
    initial_wage = float(profile["initial_monthly_wage_uf"])
    wage_growth = float(profile["annual_real_wage_growth"])
    contribution_rate = float(profile["contribution_rate"])
    start_age = float(profile["start_age"])
    return_matrix = returns[[f"return_{fund}" for fund in ("A", "B", "C", "D", "E")]]
    records: list[dict[str, Any]] = []

    for month in range(months):
        state = LABOR_STATES[state_index]
        age = start_age + month / 12.0
        potential_wage = initial_wage * ((1.0 + wage_growth) ** (month / 12.0))
        contribution = contribution_rate * potential_wage if state == CONTRIBUTING_STATE else 0.0
        fund = generational_fund(age, cuts)
        monthly_return = float(return_matrix.iloc[month][f"return_{fund}"])
        opening_balance = balance
        balance = (balance + contribution) * (1.0 + monthly_return)
        records.append(
            {
                "scenario": scenario_name,
                "scenario_label": scenario["label"],
                "representative_path_id": f"{scenario_name}_{representative_index + 1:05d}",
                "month": month + 1,
                "age": age,
                "state": state,
                "potential_wage_uf": potential_wage,
                "contribution_uf": contribution,
                "fund_proxy": fund,
                "monthly_return": monthly_return,
                "opening_balance_uf": opening_balance,
                "closing_balance_uf": balance,
            }
        )
        state_index = int(
            (uniforms[representative_index, month] > cumulative[state_index]).sum()
        )
    return pd.DataFrame(records)


def _summary_table(
    path_results: pd.DataFrame,
    scenarios: dict[str, Any],
    baseline_scenario: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    baseline_values = path_results.loc[
        path_results["scenario"].eq(baseline_scenario), "final_balance_uf"
    ]
    baseline_median = float(baseline_values.median())
    for scenario_name, scenario in scenarios.items():
        group = path_results[path_results["scenario"].eq(scenario_name)]
        final = group["final_balance_uf"]
        median = float(final.median())
        rows.append(
            {
                "scenario": scenario_name,
                "scenario_label": scenario["label"],
                "paths": int(len(group)),
                "mean_final_balance_uf": float(final.mean()),
                "std_final_balance_uf": float(final.std(ddof=1)),
                "p10_final_balance_uf": float(final.quantile(0.10)),
                "median_final_balance_uf": median,
                "p90_final_balance_uf": float(final.quantile(0.90)),
                "median_total_contributions_uf": float(group["total_contributions_uf"].median()),
                "median_contribution_density": float(group["contribution_density"].median()),
                "median_gap_vs_baseline_uf": median - baseline_median,
                "median_gap_vs_baseline_pct": (
                    median / baseline_median - 1.0 if baseline_median > 0 else np.nan
                ),
                "share_below_baseline_median": float((final < baseline_median).mean()),
                "median_paired_gap_vs_baseline_uf": float(
                    group["paired_gap_vs_baseline_uf"].median()
                ),
                "median_paired_gap_vs_baseline_pct": float(
                    group["paired_gap_vs_baseline_pct"].median()
                ),
                "share_below_same_draw_baseline": float(
                    (group["paired_gap_vs_baseline_uf"] < 0).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def _state_occupancy(path_results: pd.DataFrame, months: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_name, group in path_results.groupby("scenario", sort=False):
        label = str(group["scenario_label"].iloc[0])
        denominator = len(group) * months
        for state in LABOR_STATES:
            total_months = int(group[f"months_{state}"].sum())
            rows.append(
                {
                    "scenario": scenario_name,
                    "scenario_label": label,
                    "state": state,
                    "person_months": total_months,
                    "share_person_months": total_months / denominator,
                }
            )
    return pd.DataFrame(rows)


def _transition_table(scenarios: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario_name, scenario in scenarios.items():
        matrix = scenario["transition_matrix"]
        for source in LABOR_STATES:
            for target in LABOR_STATES:
                rows.append(
                    {
                        "scenario": scenario_name,
                        "scenario_label": scenario["label"],
                        "source_state": source,
                        "target_state": target,
                        "monthly_probability": float(matrix[source][target]),
                    }
                )
    return pd.DataFrame(rows)


def simulate_milestone2(config: dict[str, Any]) -> Milestone2Outputs:
    validate_milestone2_config(config)
    clean_config = copy.deepcopy(config)
    clean_config.pop("_config_path", None)
    paths = int(config["paths_per_scenario"])
    seed = int(config["seed"])
    profile = config["profile"]
    cuts = [int(value) for value in config["fund_proxy"]["cuts"]]
    months = int(round((float(profile["retirement_age"]) - float(profile["start_age"])) * 12))
    market_returns = deterministic_market_returns(months)
    uniforms = np.random.default_rng(seed).random((paths, months))

    path_frames: list[pd.DataFrame] = []
    balance_histories: dict[str, np.ndarray] = {}
    for scenario_name, scenario in config["scenarios"].items():
        frame, balance_history = _simulate_scenario(
            scenario_name,
            scenario,
            profile,
            cuts,
            market_returns,
            uniforms,
        )
        path_frames.append(frame)
        balance_histories[scenario_name] = balance_history

    path_results = pd.concat(path_frames, ignore_index=True)
    baseline_by_draw = (
        path_results[path_results["scenario"].eq(config["baseline_scenario"])]
        .set_index("draw_id")["final_balance_uf"]
    )
    path_results["baseline_final_balance_same_draw_uf"] = path_results["draw_id"].map(
        baseline_by_draw
    )
    path_results["paired_gap_vs_baseline_uf"] = (
        path_results["final_balance_uf"]
        - path_results["baseline_final_balance_same_draw_uf"]
    )
    path_results["paired_gap_vs_baseline_pct"] = (
        path_results["final_balance_uf"]
        / path_results["baseline_final_balance_same_draw_uf"]
        - 1.0
    )
    scenario_summary = _summary_table(
        path_results, config["scenarios"], config["baseline_scenario"]
    )
    occupancy = _state_occupancy(path_results, months)
    transition_matrices = _transition_table(config["scenarios"])

    trajectory_frames: list[pd.DataFrame] = []
    representative_paths: dict[str, str] = {}
    for scenario_name, scenario in config["scenarios"].items():
        group = path_results[path_results["scenario"].eq(scenario_name)].reset_index(drop=True)
        median = float(group["final_balance_uf"].median())
        representative_index = int((group["final_balance_uf"] - median).abs().to_numpy().argmin())
        expected_balance = float(balance_histories[scenario_name][representative_index, -1])
        trajectory = _representative_trajectory(
            scenario_name,
            scenario,
            profile,
            cuts,
            market_returns,
            uniforms,
            representative_index,
        )
        if not np.isclose(float(trajectory["closing_balance_uf"].iloc[-1]), expected_balance):
            raise RuntimeError("La trayectoria representativa no reproduce su resultado final")
        trajectory_frames.append(trajectory)
        representative_paths[scenario_name] = str(group.loc[representative_index, "path_id"])

    representative_trajectories = pd.concat(trajectory_frames, ignore_index=True)
    metadata = {
        "experiment_name": config["experiment_name"],
        "status": "completed",
        "experiment_type": "synthetic_individual_life_course_monte_carlo",
        "methodological_scope": "hito_2_primera_version",
        "seed": seed,
        "paths_per_scenario": paths,
        "scenario_count": len(config["scenarios"]),
        "months": months,
        "years": months / 12,
        "common_random_numbers": True,
        "common_deterministic_market": True,
        "representative_paths": representative_paths,
        "profile": copy.deepcopy(profile),
        "fund_proxy": copy.deepcopy(config["fund_proxy"]),
        "scenario_assumptions": {
            name: {
                "label": scenario["label"],
                "description": scenario["description"],
            }
            for name, scenario in config["scenarios"].items()
        },
        "warnings": [
            "Las probabilidades de transición son supuestos de escenarios y no estimaciones HPA.",
            "Los fondos A-E son proxies históricos de riesgo y no los diez Fondos Generacionales definitivos.",
            "El mercado es común y determinista para aislar el efecto de la trayectoria laboral.",
            "Los resultados son sintéticos y no constituyen una predicción de pensión ni una estimación nacional.",
        ],
        "config": clean_config,
    }
    return Milestone2Outputs(
        path_results=path_results,
        scenario_summary=scenario_summary,
        state_occupancy=occupancy,
        transition_matrices=transition_matrices,
        representative_trajectories=representative_trajectories,
        market_returns=market_returns,
        metadata=metadata,
    )


def _write_summary_svg(summary: pd.DataFrame, trajectories: pd.DataFrame, path: Path) -> None:
    width, height = 1200, 780
    colors = ["#147d92", "#d98c10", "#b43b4f", "#6a5acd", "#4f772d"]
    p10_min = float(summary["p10_final_balance_uf"].min())
    p90_max = float(summary["p90_final_balance_uf"].max())
    spread = max(p90_max - p10_min, 1.0)
    xmin = max(0.0, p10_min - 0.08 * spread)
    xmax = p90_max + 0.08 * spread
    x0, x1 = 250.0, 1120.0

    def sx(value: float) -> float:
        return x0 + (value - xmin) / (xmax - xmin) * (x1 - x0)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#17324d}.title{font-size:30px;font-weight:700}.subtitle{font-size:16px;fill:#49657d}.label{font-size:16px;font-weight:600}.small{font-size:13px;fill:#49657d}.axis{stroke:#9fb2c2;stroke-width:1}.grid{stroke:#dce5ec;stroke-width:1}</style>",
        '<rect width="1200" height="780" fill="#f7fafc"/>',
        '<text class="title" x="60" y="55">Hito 2 · Gemelo individual estocástico</text>',
        '<text class="subtitle" x="60" y="84">Distribución Monte Carlo del saldo final y trayectorias representativas</text>',
        '<text class="label" x="60" y="135">Saldo final por escenario (P10 — mediana — P90)</text>',
    ]
    ticks = np.linspace(xmin, xmax, 6)
    for tick in ticks:
        x = sx(float(tick))
        svg.append(f'<line class="grid" x1="{x:.1f}" y1="155" x2="{x:.1f}" y2="350"/>')
        svg.append(f'<text class="small" x="{x:.1f}" y="375" text-anchor="middle">{tick:,.0f} UF</text>')
    for index, row in summary.reset_index(drop=True).iterrows():
        y = 195 + index * 62
        color = colors[index % len(colors)]
        label = html.escape(str(row["scenario_label"]))
        p10 = sx(float(row["p10_final_balance_uf"]))
        median = sx(float(row["median_final_balance_uf"]))
        p90 = sx(float(row["p90_final_balance_uf"]))
        svg.extend(
            [
                f'<text class="label" x="60" y="{y + 5}" dominant-baseline="middle">{label}</text>',
                f'<line x1="{p10:.1f}" y1="{y}" x2="{p90:.1f}" y2="{y}" stroke="{color}" stroke-width="8" stroke-linecap="round" opacity="0.42"/>',
                f'<circle cx="{median:.1f}" cy="{y}" r="9" fill="{color}"/>',
                f'<text class="small" x="{median:.1f}" y="{y - 17}" text-anchor="middle">{float(row["median_final_balance_uf"]):,.0f}</text>',
            ]
        )

    svg.append('<text class="label" x="60" y="435">Trayectoria de saldo del camino más cercano a la mediana</text>')
    chart_x0, chart_x1, chart_y0, chart_y1 = 90.0, 1120.0, 470.0, 700.0
    annual = trajectories[(trajectories["month"] % 12 == 0) | (trajectories["month"] == 1)].copy()
    max_balance = max(float(annual["closing_balance_uf"].max()), 1.0)
    max_month = int(trajectories["month"].max())
    for fraction in np.linspace(0, 1, 5):
        y = chart_y1 - fraction * (chart_y1 - chart_y0)
        value = fraction * max_balance
        svg.append(f'<line class="grid" x1="{chart_x0}" y1="{y:.1f}" x2="{chart_x1}" y2="{y:.1f}"/>')
        svg.append(f'<text class="small" x="{chart_x0 - 12}" y="{y + 4:.1f}" text-anchor="end">{value:,.0f}</text>')
    for index, (scenario, group) in enumerate(annual.groupby("scenario", sort=False)):
        color = colors[index % len(colors)]
        points = []
        for row in group.itertuples(index=False):
            x = chart_x0 + int(row.month) / max_month * (chart_x1 - chart_x0)
            y = chart_y1 - float(row.closing_balance_uf) / max_balance * (chart_y1 - chart_y0)
            points.append(f"{x:.1f},{y:.1f}")
        svg.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="4"/>')
        label = html.escape(str(group["scenario_label"].iloc[0]))
        legend_x = 390 + index * 245
        svg.append(f'<line x1="{legend_x}" y1="748" x2="{legend_x + 28}" y2="748" stroke="{color}" stroke-width="5"/>')
        svg.append(f'<text class="small" x="{legend_x + 36}" y="753">{label}</text>')
    svg.extend(
        [
            f'<line class="axis" x1="{chart_x0}" y1="{chart_y1}" x2="{chart_x1}" y2="{chart_y1}"/>',
            '<text class="small" x="90" y="730">Inicio</text>',
            f'<text class="small" x="{chart_x1}" y="730" text-anchor="end">Jubilación</text>',
            '<text class="small" x="60" y="753">Saldo (UF)</text>',
            '<text class="small" x="60" y="770">Escenarios sintéticos; no son una predicción.</text>',
            "</svg>",
        ]
    )
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def _write_readme(outputs: Milestone2Outputs, path: Path) -> None:
    summary = outputs.scenario_summary
    lines = [
        "# Hito 2 · Gemelo digital individual estocástico",
        "",
        "Primera versión reproducible del segundo hito. Simula trayectorias laborales mensuales desde la edad inicial hasta la jubilación mediante una cadena de Markov y compara al menos tres escenarios con Monte Carlo.",
        "",
        "## Resultado principal",
        "",
        "| Escenario | Mediana saldo final | P10 | P90 | Densidad mediana | Brecha pareada mediana | Bajo estable pareado |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.scenario_label} | {row.median_final_balance_uf:,.1f} UF | "
            f"{row.p10_final_balance_uf:,.1f} | {row.p90_final_balance_uf:,.1f} | "
            f"{row.median_contribution_density:.1%} | "
            f"{row.median_paired_gap_vs_baseline_uf:,.1f} UF | "
            f"{row.share_below_same_draw_baseline:.1%} |"
        )
    lines.extend(
        [
            "",
            "![Resumen de resultados](hito2-results.svg)",
            "",
            "## Interpretación correcta",
            "",
            "Las diferencias muestran cómo cambian los saldos sintéticos cuando solo se modifican las probabilidades de transición laboral. Todos los escenarios comparten perfil inicial, crecimiento salarial, mercado, semilla y regla proxy de fondos. La brecha pareada compara la misma extracción uniforme con su contraparte estable.",
            "",
            "Las probabilidades no están calibradas con HPA: son supuestos transparentes de escenarios. Los fondos A–E son proxies, el mercado es determinista y el resultado no predice pensiones individuales ni representa a Chile.",
            "",
            "## Reproducir",
            "",
            "```powershell",
            "gemelo-previsional hito2 --config config/hito2.json --output-dir examples/hito2",
            "```",
            "",
            "Consulte `docs/MILESTONE2.md` para la metodología y `hito2_summary.json` para el manifiesto completo.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_milestone2(config: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    outputs = simulate_milestone2(config)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    outputs.path_results.to_csv(output / "hito2_path_results.csv", index=False, encoding="utf-8")
    outputs.scenario_summary.to_csv(
        output / "hito2_scenario_summary.csv", index=False, encoding="utf-8"
    )
    outputs.state_occupancy.to_csv(
        output / "hito2_state_occupancy.csv", index=False, encoding="utf-8"
    )
    outputs.transition_matrices.to_csv(
        output / "hito2_transition_matrices.csv", index=False, encoding="utf-8"
    )
    outputs.representative_trajectories.to_csv(
        output / "hito2_representative_trajectories.csv", index=False, encoding="utf-8"
    )
    outputs.market_returns.to_csv(
        output / "hito2_market_returns.csv", index=False, encoding="utf-8"
    )
    with (output / "hito2_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(outputs.metadata, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    _write_summary_svg(outputs.scenario_summary, outputs.representative_trajectories, output / "hito2-results.svg")
    _write_readme(outputs, output / "README.md")
    return {
        "status": "completed",
        "experiment_name": outputs.metadata["experiment_name"],
        "scenarios": outputs.metadata["scenario_count"],
        "paths_per_scenario": outputs.metadata["paths_per_scenario"],
        "months": outputs.metadata["months"],
        "output_directory": str(output),
    }
