from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


PERSON_MONTH_CONTRACT_VERSION = "1.0"
PERSON_MONTH_INPUT_COLUMNS = (
    "source",
    "person_id",
    "period",
    "age",
    "labor_state",
    "potential_wage_uf",
    "contribution_uf",
    "fund",
    "monthly_return",
    "opening_balance_uf",
)
PERSON_MONTH_OUTPUT_COLUMNS = PERSON_MONTH_INPUT_COLUMNS + ("closing_balance_uf",)
SUPPORTED_FUNDS = ("A", "B", "C", "D", "E")


def accounting_step_vectorized(
    balance: Any,
    contribution: Any,
    monthly_return: Any,
    *,
    contribution_timing: str = "start",
) -> np.ndarray:
    """Apply the shared accounting identity to scalar or broadcastable array inputs."""
    if contribution_timing not in {"start", "end"}:
        raise ValueError("contribution_timing debe ser 'start' o 'end'")
    balances, contributions, returns = np.broadcast_arrays(
        np.asarray(balance, dtype=float),
        np.asarray(contribution, dtype=float),
        np.asarray(monthly_return, dtype=float),
    )
    if not (
        np.isfinite(balances).all()
        and np.isfinite(contributions).all()
        and np.isfinite(returns).all()
    ):
        raise ValueError("Saldo, cotización y retorno deben ser finitos")
    if bool((balances < 0).any()) or bool((contributions < 0).any()):
        raise ValueError("Saldo y cotización no pueden ser negativos")
    if bool((returns <= -1).any()):
        raise ValueError("El retorno mensual debe ser mayor que -100%")
    if contribution_timing == "start":
        closing = (balances + contributions) * (1.0 + returns)
    else:
        closing = balances * (1.0 + returns) + contributions
    if not np.isfinite(closing).all() or bool((closing < 0).any()):
        raise RuntimeError("El núcleo contable produjo saldos inválidos")
    return closing


def validate_person_month_contract(
    frame: pd.DataFrame,
    *,
    require_closing_balance: bool = True,
) -> None:
    """Validate the canonical person-month schema shared by historical and synthetic adapters."""
    required = (
        PERSON_MONTH_OUTPUT_COLUMNS if require_closing_balance else PERSON_MONTH_INPUT_COLUMNS
    )
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"Faltan columnas del contrato persona-mes: {', '.join(missing)}")
    if frame.empty:
        return

    for column in ("source", "person_id", "period", "labor_state", "fund"):
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} no puede contener valores vacíos")
    if frame.duplicated(["source", "person_id", "period"]).any():
        raise ValueError("El contrato persona-mes contiene claves source/person_id/period duplicadas")
    if not frame["fund"].isin(SUPPORTED_FUNDS).all():
        raise ValueError(f"fund debe pertenecer a {SUPPORTED_FUNDS}")

    numeric_columns = [
        "age",
        "potential_wage_uf",
        "contribution_uf",
        "monthly_return",
        "opening_balance_uf",
    ]
    if require_closing_balance:
        numeric_columns.append("closing_balance_uf")
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Las columnas numéricas del contrato persona-mes deben ser finitas")
    if bool((numeric["age"] < 0).any()):
        raise ValueError("age no puede ser negativa")
    for column in (
        "potential_wage_uf",
        "contribution_uf",
        "opening_balance_uf",
    ):
        if bool((numeric[column] < 0).any()):
            raise ValueError(f"{column} no puede ser negativa")
    if bool((numeric["monthly_return"] <= -1).any()):
        raise ValueError("monthly_return debe ser mayor que -100%")

    if require_closing_balance:
        expected = accounting_step_vectorized(
            numeric["opening_balance_uf"].to_numpy(),
            numeric["contribution_uf"].to_numpy(),
            numeric["monthly_return"].to_numpy(),
        )
        actual = numeric["closing_balance_uf"].to_numpy()
        if not np.allclose(expected, actual, rtol=1e-12, atol=1e-10):
            raise ValueError("closing_balance_uf no satisface la identidad contable compartida")


def post_person_month(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate person-month inputs and append closing balances with the shared kernel."""
    validate_person_month_contract(frame, require_closing_balance=False)
    result = frame.copy()
    result["closing_balance_uf"] = accounting_step_vectorized(
        result["opening_balance_uf"].to_numpy(dtype=float),
        result["contribution_uf"].to_numpy(dtype=float),
        result["monthly_return"].to_numpy(dtype=float),
    )
    validate_person_month_contract(result, require_closing_balance=True)
    leading = [column for column in PERSON_MONTH_OUTPUT_COLUMNS if column in result]
    trailing = [column for column in result.columns if column not in leading]
    return result[leading + trailing]
