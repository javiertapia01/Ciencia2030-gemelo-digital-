from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "experiment_name": "experimento_i_asignacion_generacional",
    "window": {"start": "2008-01", "end": "2025-12"},
    "population": {
        "ids": [],
        "sample_size": None,
        "sample_seed": 2030,
        "minimum_history_months": 24,
    },
    "model": {
        "contribution_rate": 0.10,
        "contribution_timing": "start_of_month",
        "birth_day_convention": 15,
        "uf_convention": "calendar_month_end",
        "observed_fund_rule": "largest_positive_balance",
        "cuts": [35, 45, 55, 65],
        "sensitivity_cuts": {
            "transicion_5_anios_antes": [30, 40, 50, 60],
            "base": [35, 45, 55, 65],
            "transicion_5_anios_despues": [40, 50, 60, 70],
        },
    },
    "validation": {
        "minimum_observations": 100,
        "minimum_observed_balance_uf": 5.0,
        "max_median_absolute_relative_error": 0.10,
        "final_window_months": 12,
        "max_final_window_median_absolute_relative_error": 0.10,
        "max_absolute_annual_drift": 0.005,
    },
    "inference": {
        "bootstrap_iterations": 2000,
        "bootstrap_seed": 2030,
        "confidence_level": 0.95,
    },
    "outputs": {
        "base_directory": "../output/runs",
        "manual_trajectory_people": 30,
        "write_all_trajectories": False,
    },
}


class ConfigurationError(ValueError):
    """Raised when an experiment configuration is incomplete or inconsistent."""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_path(value: str, base_dir: Path) -> str:
    path = Path(value)
    return str((base_dir / path).resolve()) if not path.is_absolute() else str(path.resolve())


def _validate_period(value: str, label: str) -> None:
    try:
        period = __import__("pandas").Period(value, freq="M")
    except Exception as exc:  # pragma: no cover - pandas gives version-specific errors
        raise ConfigurationError(f"{label} debe tener formato AAAA-MM: {value!r}") from exc
    if str(period) != value:
        raise ConfigurationError(f"{label} debe tener formato canónico AAAA-MM: {value!r}")


def validate_config(config: dict[str, Any]) -> None:
    inputs = config.get("inputs", {})
    required = ("hpa_zip", "returns_workbook", "parameters_csv")
    missing = [name for name in required if not inputs.get(name)]
    if missing:
        raise ConfigurationError(f"Faltan rutas de entrada: {', '.join(missing)}")

    start = config["window"]["start"]
    end = config["window"]["end"]
    _validate_period(start, "window.start")
    _validate_period(end, "window.end")
    if start > end:
        raise ConfigurationError("window.start no puede ser posterior a window.end")

    rate = float(config["model"]["contribution_rate"])
    if not 0 < rate <= 1:
        raise ConfigurationError("model.contribution_rate debe estar en (0, 1]")
    if config["model"]["contribution_timing"] != "start_of_month":
        raise ConfigurationError("Esta versión solo admite contribution_timing=start_of_month")
    if config["model"]["observed_fund_rule"] != "largest_positive_balance":
        raise ConfigurationError(
            "Esta versión solo admite observed_fund_rule=largest_positive_balance"
        )

    for name, cuts in config["model"]["sensitivity_cuts"].items():
        if len(cuts) != 4 or list(cuts) != sorted(cuts):
            raise ConfigurationError(f"Los cortes de {name!r} deben ser cuatro edades crecientes")
    if list(config["model"]["cuts"]) != list(config["model"]["sensitivity_cuts"]["base"]):
        raise ConfigurationError("model.cuts debe coincidir con model.sensitivity_cuts.base")
    birth_day = int(config["model"]["birth_day_convention"])
    if not 1 <= birth_day <= 28:
        raise ConfigurationError("birth_day_convention debe estar entre 1 y 28")

    validation = config["validation"]
    if int(validation["minimum_observations"]) <= 0:
        raise ConfigurationError("validation.minimum_observations debe ser positivo")
    if int(validation["final_window_months"]) <= 0:
        raise ConfigurationError("validation.final_window_months debe ser positivo")
    for key in (
        "minimum_observed_balance_uf",
        "max_median_absolute_relative_error",
        "max_final_window_median_absolute_relative_error",
        "max_absolute_annual_drift",
    ):
        if float(validation[key]) < 0:
            raise ConfigurationError(f"validation.{key} no puede ser negativo")

    sample_size = config["population"].get("sample_size")
    if sample_size is not None and int(sample_size) <= 0:
        raise ConfigurationError("population.sample_size debe ser positivo o null")
    if int(config["population"]["minimum_history_months"]) < 2:
        raise ConfigurationError("minimum_history_months debe ser al menos 2")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        supplied = json.load(handle)
    config = _deep_merge(DEFAULT_CONFIG, supplied)
    base_dir = config_path.parent
    for key in ("hpa_zip", "returns_workbook", "parameters_csv"):
        config["inputs"][key] = _resolve_path(config["inputs"][key], base_dir)
    config["outputs"]["base_directory"] = _resolve_path(
        config["outputs"]["base_directory"], base_dir
    )
    config["_config_path"] = str(config_path)
    validate_config(config)
    return config
