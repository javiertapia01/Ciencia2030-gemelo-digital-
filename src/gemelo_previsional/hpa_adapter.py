from __future__ import annotations

import numpy as np
import pandas as pd

from .individual_core import PERSON_MONTH_OUTPUT_COLUMNS, post_person_month
from .io import FUNDS
from .model import generational_fund


def adapt_hpa_panel_to_person_month(
    panel: pd.DataFrame,
    *,
    fund_mode: str = "observed",
    cuts: list[int] | None = None,
    drop_invalid: bool = False,
) -> pd.DataFrame:
    """Adapt the historical HPA panel to the canonical person-month accounting contract."""
    required = {
        "correl",
        "period",
        "age",
        "wage_uf",
        "contribution_uf",
        "observed_fund",
        "balance_uf",
        *(f"return_{fund}" for fund in FUNDS),
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"El panel HPA no contiene: {', '.join(missing)}")
    if fund_mode not in {"observed", "generational"}:
        raise ValueError("fund_mode debe ser 'observed' o 'generational'")
    if fund_mode == "generational":
        if cuts is None or len(cuts) != 4 or list(cuts) != sorted(set(cuts)):
            raise ValueError(
                "cuts debe contener cuatro edades crecientes para fund_mode='generational'"
            )

    working = panel.copy()
    if fund_mode == "observed":
        funds = working["observed_fund"].astype("string")
        source = "hpa_observed"
    else:
        funds = pd.Series(
            [generational_fund(float(age), cuts or []) for age in working["age"]],
            index=working.index,
            dtype="string",
        )
        source = "hpa_generational"

    selected_returns = np.full(len(working), np.nan, dtype=float)
    for fund in FUNDS:
        mask = funds.eq(fund).fillna(False).to_numpy(dtype=bool)
        selected_returns[mask] = pd.to_numeric(
            working.loc[mask, f"return_{fund}"], errors="coerce"
        ).to_numpy(dtype=float)

    adapted = pd.DataFrame(
        {
            "source": source,
            "person_id": working["correl"].astype(str),
            "period": working["period"].astype(str),
            "age": pd.to_numeric(working["age"], errors="coerce"),
            "labor_state": np.where(
                pd.to_numeric(working["contribution_uf"], errors="coerce").gt(0),
                "cotizando",
                "sin_cotizar",
            ),
            "potential_wage_uf": pd.to_numeric(working["wage_uf"], errors="coerce"),
            "contribution_uf": pd.to_numeric(
                working["contribution_uf"], errors="coerce"
            ),
            "fund": funds,
            "monthly_return": selected_returns,
            "opening_balance_uf": pd.to_numeric(working["balance_uf"], errors="coerce"),
        }
    )
    if drop_invalid:
        adapted = adapted[
            adapted["fund"].isin(FUNDS)
            & adapted[
                [
                    "age",
                    "potential_wage_uf",
                    "contribution_uf",
                    "monthly_return",
                    "opening_balance_uf",
                ]
            ]
            .notna()
            .all(axis=1)
            & adapted["age"].ge(0)
            & adapted["potential_wage_uf"].ge(0)
            & adapted["opening_balance_uf"].ge(0)
            & adapted["contribution_uf"].ge(0)
            & adapted["monthly_return"].gt(-1)
        ].copy()
    posted = post_person_month(adapted)
    return posted[list(PERSON_MONTH_OUTPUT_COLUMNS)]


def hpa_contract_sample(
    panel: pd.DataFrame,
    *,
    people: int,
    seed: int,
) -> pd.DataFrame:
    """Return a reproducible, non-exhaustive HPA contract sample for human audit."""
    identifiers = panel["correl"].drop_duplicates()
    count = min(max(int(people), 0), len(identifiers))
    selected = identifiers.sample(n=count, random_state=int(seed)).tolist() if count else []
    sample = panel[panel["correl"].isin(selected)].copy()
    return adapt_hpa_panel_to_person_month(sample, drop_invalid=True)
