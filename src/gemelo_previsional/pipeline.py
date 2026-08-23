from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from . import __version__
from .diagnostics import run_one_step_diagnostics
from .io import (
    build_panel,
    load_characteristics,
    load_monthly_balances,
    load_monthly_income,
    load_parameters,
    load_returns,
    select_population,
    sha256_file,
)
from .model import simulate_panel
from .statistics import (
    ols_hc3,
    population_summary,
    sensitivity_summary,
    stratification_table,
    validation_summary,
)


def _progress(message: str) -> None:
    print(f"[gemelo-previsional] {message}", file=sys.stderr, flush=True)


def _prepare_output_directory(config: dict[str, Any], output_dir: Path | None) -> Path:
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(config["outputs"]["base_directory"]) / stamp
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"El directorio de salida no está vacío: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def _write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(_jsonable(value), handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _data_quality(
    characteristics_all: pd.DataFrame,
    characteristics_selected: pd.DataFrame,
    income: pd.DataFrame,
    balances: pd.DataFrame,
    panel: pd.DataFrame,
) -> dict[str, Any]:
    income_present = ~panel["income_absent_flag"]
    flag_agreement = panel.loc[income_present, "source_tope_flag"].astype(bool).eq(
        panel.loc[income_present, "calculated_tope_flag"]
    )
    return {
        "people_in_characteristics": int(characteristics_all["correl"].nunique()),
        "people_selected": int(characteristics_selected["correl"].nunique()),
        "people_with_income_rows": int(income["correl"].nunique()) if not income.empty else 0,
        "people_with_ccico_balance_rows": int(balances["correl"].nunique()),
        "person_months_income": int(len(income)),
        "person_months_ccico_balance": int(len(balances)),
        "person_months_panel": int(len(panel)),
        "income_absent_share_within_balance_calendar": float(panel["income_absent_flag"].mean()),
        "multiple_payer_share_among_income_months": float(
            panel.loc[income_present, "payer_count"].gt(1).mean()
        )
        if income_present.any()
        else None,
        "multi_fund_transfer_share": float(panel["transfer_flag"].mean()),
        "no_positive_balance_share": float(panel["no_balance_flag"].mean()),
        "duplicate_balance_source_row_share": float(panel["balance_source_rows"].gt(1).mean()),
        "tope_flag_agreement_share_among_income_months": float(flag_agreement.mean())
        if len(flag_agreement)
        else None,
        "tope_flag_note": (
            "El indicador fuente se calcula por fila/pagador; el indicador reconstruido se calcula "
            "después de sumar pagadores. Una discrepancia no implica por sí sola error."
        ),
    }


def _write_validation_outputs(
    output_dir: Path,
    errors: pd.DataFrame,
    trajectories: pd.DataFrame,
    manual_people: int,
    seed: int,
    write_all: bool,
    include_counterfactual: bool,
) -> None:
    if not errors.empty:
        monthly = (
            errors.groupby("period", sort=True)
            .agg(
                observations=("relative_error", "count"),
                median_relative_error=("relative_error", "median"),
                median_absolute_relative_error=("relative_error", lambda values: values.abs().median()),
                mean_relative_error=("relative_error", "mean"),
            )
            .reset_index()
        )
        monthly.to_csv(output_dir / "validation_errors_by_month.csv", index=False, encoding="utf-8")
        sample_n = min(5000, len(errors))
        errors.sample(n=sample_n, random_state=seed).sort_values(
            ["correl", "period"]
        ).to_csv(output_dir / "validation_errors_sample.csv", index=False, encoding="utf-8")

    if not trajectories.empty:
        export_trajectories = trajectories
        if not include_counterfactual:
            counterfactual_columns = [
                column
                for column in trajectories.columns
                if column.startswith("what_if_") or column.startswith("delta_uf__")
            ]
            export_trajectories = trajectories.drop(columns=counterfactual_columns)
        people = trajectories["correl"].drop_duplicates()
        count = min(int(manual_people), len(people))
        selected = people.sample(n=count, random_state=seed).tolist() if count else []
        export_trajectories[export_trajectories["correl"].isin(selected)].sort_values(
            ["correl", "period"]
        ).to_csv(output_dir / "manual_trajectories.csv", index=False, encoding="utf-8")
        if write_all:
            export_trajectories.to_csv(
                output_dir / "all_trajectories.csv", index=False, encoding="utf-8"
            )


def run_experiment(
    config: dict[str, Any],
    output_dir: Path | None = None,
    force_counterfactual: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    output_dir = _prepare_output_directory(config, output_dir)
    inputs = config["inputs"]
    for key in ("hpa_zip", "returns_workbook", "parameters_csv"):
        if not Path(inputs[key]).is_file():
            raise FileNotFoundError(f"No existe inputs.{key}: {inputs[key]}")

    _progress("leyendo características y seleccionando población")
    characteristics_all = load_characteristics(inputs["hpa_zip"])
    characteristics, selected_ids = select_population(
        characteristics_all,
        explicit_ids=config["population"].get("ids"),
        sample_size=config["population"].get("sample_size"),
        sample_seed=int(config["population"]["sample_seed"]),
    )

    start = config["window"]["start"]
    end = config["window"]["end"]
    _progress("agregando remuneraciones por persona-mes y pagadores")
    income = load_monthly_income(inputs["hpa_zip"], start, end, selected_ids)
    _progress("extrayendo saldos CCICO e infiriendo fondo observado")
    balances = load_monthly_balances(inputs["hpa_zip"], start, end, selected_ids)
    _progress("leyendo rentabilidades y parámetros UF/tope")
    returns = load_returns(inputs["returns_workbook"], inputs.get("returns_sheet"))
    parameters = load_parameters(inputs["parameters_csv"], start, end)
    if "uf_convention" in parameters:
        conventions = set(parameters["uf_convention"].dropna().astype(str))
        expected_convention = str(config["model"]["uf_convention"])
        if conventions != {expected_convention}:
            raise ValueError(
                "La convención UF de parámetros externos no coincide con la configuración: "
                f"esperada={expected_convention!r}, encontradas={sorted(conventions)}"
            )

    _progress("construyendo panel real en UF")
    panel = build_panel(
        balances,
        income,
        characteristics,
        returns,
        parameters,
        contribution_rate=float(config["model"]["contribution_rate"]),
    )
    quality = _data_quality(characteristics_all, characteristics, income, balances, panel)
    _write_json(output_dir / "data_quality.json", quality)

    manifest = {
        "experiment_name": config["experiment_name"],
        "software_version": __version__,
        "started_at_utc": started_at,
        "status": "running",
        "methodological_status": "validation_pending",
        "force_counterfactual": bool(force_counterfactual),
        "config": {key: value for key, value in config.items() if not key.startswith("_")},
        "input_sha256": {
            "hpa_zip": sha256_file(inputs["hpa_zip"]),
            "returns_workbook": sha256_file(inputs["returns_workbook"]),
            "parameters_csv": sha256_file(inputs["parameters_csv"]),
        },
    }
    _write_json(output_dir / "run_manifest.json", manifest)

    one_step_config = config["diagnostics"]["one_step"]
    one_step_selection: dict[str, Any] | None = None
    if bool(one_step_config["enabled"]):
        _progress("comparando convenciones con residuos mensuales de un paso")
        one_step = run_one_step_diagnostics(
            panel,
            minimum_history_months=int(config["population"]["minimum_history_months"]),
            minimum_balance_uf=float(config["validation"]["minimum_observed_balance_uf"]),
            calibration_share=float(one_step_config["calibration_share"]),
            split_seed=int(one_step_config["split_seed"]),
            large_relative_residual_threshold=float(
                one_step_config["large_relative_residual_threshold"]
            ),
        )
        one_step_selection = one_step.selection
        _write_json(output_dir / "one_step_selection.json", one_step.selection)
        one_step.variant_summary.to_csv(
            output_dir / "one_step_variant_summary.csv", index=False, encoding="utf-8"
        )
        one_step.residuals.to_csv(
            output_dir / "one_step_residuals.csv", index=False, encoding="utf-8"
        )
        one_step.stratification.to_csv(
            output_dir / "one_step_stratification.csv", index=False, encoding="utf-8"
        )

    _progress("reconstruyendo trayectorias observadas y escenarios generacionales")
    simulation = simulate_panel(
        panel,
        sensitivity_cuts=config["model"]["sensitivity_cuts"],
        minimum_history_months=int(config["population"]["minimum_history_months"]),
    )
    if simulation.individual.empty:
        raise RuntimeError("Ninguna persona cumple los requisitos de historia continua")
    simulation.exclusions.to_csv(
        output_dir / "exclusions.csv", index=False, encoding="utf-8"
    )
    validation = validation_summary(simulation.validation_errors, config["validation"])
    _write_json(output_dir / "validation_summary.json", validation)
    gate_passed = bool(validation["gate_passed"])
    calculate_outputs = gate_passed or force_counterfactual
    _write_validation_outputs(
        output_dir,
        simulation.validation_errors,
        simulation.trajectories,
        manual_people=int(config["outputs"]["manual_trajectory_people"]),
        seed=int(config["population"]["sample_seed"]),
        write_all=bool(config["outputs"]["write_all_trajectories"]),
        include_counterfactual=calculate_outputs,
    )

    if calculate_outputs:
        _progress("calculando métricas poblacionales, sensibilidad y heterogeneidad")
        simulation.individual.to_csv(
            output_dir / "individual_results.csv", index=False, encoding="utf-8"
        )
        population = population_summary(simulation.individual, "base", config["inference"])
        population["interpretation_allowed"] = gate_passed
        population["warning"] = (
            None
            if gate_passed
            else "Resultado forzado pese a gate contable fallido; no debe interpretarse causalmente."
        )
        _write_json(output_dir / "population_summary.json", population)
        sensitivity_summary(
            simulation.individual, list(config["model"]["sensitivity_cuts"])
        ).to_csv(output_dir / "sensitivity_summary.csv", index=False, encoding="utf-8")
        stratification_table(simulation.individual, "base").to_csv(
            output_dir / "stratification.csv", index=False, encoding="utf-8"
        )
        ols_hc3(simulation.individual, "base").to_csv(
            output_dir / "regression_ols_hc3.csv", index=False, encoding="utf-8"
        )

    if gate_passed:
        status = "completed"
        methodological_status = "counterfactual_interpretable_under_documented_assumptions"
    else:
        status = "gate_closed"
        methodological_status = (
            "counterfactual_forced_not_interpretable"
            if force_counterfactual
            else "counterfactual_not_published"
        )
        (output_dir / "GATE_CLOSED.md").write_text(
            "# Gate contable cerrado\n\n"
            "La reconstrucción del saldo observado no cumplió todos los umbrales configurados. "
            "Por diseño, el contrafactual no se interpreta ni se publica como resultado salvo que "
            "la corrida haya usado `--force-counterfactual`; en ese caso solo sirve para diagnóstico.\n\n"
            "Revise `validation_summary.json`, `validation_errors_by_month.csv`, "
            "`manual_trajectories.csv` y los supuestos de cotización, tope, UF y timing.\n",
            encoding="utf-8",
        )

    duration = perf_counter() - started
    manifest.update(
        {
            "status": status,
            "methodological_status": methodological_status,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "output_directory": str(output_dir),
            "gate_passed": gate_passed,
            "eligible_people": int(len(simulation.individual)),
            "one_step_diagnostic": one_step_selection,
        }
    )
    _write_json(output_dir / "run_manifest.json", manifest)
    _progress(f"corrida terminada con estado={status} en {duration:.1f}s")
    return {
        "status": status,
        "gate_passed": gate_passed,
        "eligible_people": int(len(simulation.individual)),
        "one_step_selected_variant": (
            one_step_selection["selected_variant"] if one_step_selection else None
        ),
        "output_directory": str(output_dir),
        "duration_seconds": round(duration, 3),
    }
