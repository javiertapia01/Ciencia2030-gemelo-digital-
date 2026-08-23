from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .individual_core import PERSON_MONTH_OUTPUT_COLUMNS, validate_person_month_contract


LABOR_STATES = ("cotizando", "desempleado", "informal", "licencia", "invalidez")
CONTRIBUTING_STATE = "cotizando"
ABSORBING_STATE = "invalidez"


def transition_matrix_array(scenario: dict[str, Any]) -> np.ndarray:
    matrix = scenario["transition_matrix"]
    return np.asarray(
        [[float(matrix[source][target]) for target in LABOR_STATES] for source in LABOR_STATES],
        dtype=float,
    )


def cumulative_transition_matrix(scenario: dict[str, Any]) -> np.ndarray:
    cumulative = np.cumsum(transition_matrix_array(scenario), axis=1)
    cumulative[:, -1] = 1.0
    return cumulative


def advance_markov_states(
    current_state_indices: np.ndarray,
    uniform_draws: np.ndarray,
    cumulative: np.ndarray,
) -> np.ndarray:
    thresholds = cumulative[current_state_indices]
    return (uniform_draws[:, None] > thresholds).sum(axis=1).astype(np.int8)


def adapt_markov_trajectories_to_person_month(trajectories: pd.DataFrame) -> pd.DataFrame:
    """Adapt representative Markov trajectories to the canonical person-month contract."""
    mapping = {
        "representative_path_id": "person_id",
        "month": "period",
        "state": "labor_state",
        "fund_proxy": "fund",
    }
    required_source = {
        *mapping,
        "age",
        "potential_wage_uf",
        "contribution_uf",
        "monthly_return",
        "opening_balance_uf",
        "closing_balance_uf",
    }
    missing = sorted(required_source - set(trajectories.columns))
    if missing:
        raise ValueError(f"La trayectoria Markov no contiene: {', '.join(missing)}")
    adapted = trajectories.rename(columns=mapping).copy()
    adapted.insert(0, "source", "markov_synthetic")
    validate_person_month_contract(adapted, require_closing_balance=True)
    optional = [column for column in ("scenario", "scenario_label") if column in adapted]
    return adapted[list(PERSON_MONTH_OUTPUT_COLUMNS) + optional]
