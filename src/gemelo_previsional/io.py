from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


CHARACTERISTICS_MEMBER = "caracteristicas_afiliados.csv"
CCICO_MEMBER = "informacion_mensual_ccico.csv"
BALANCES_MEMBER = "informacion_mensual_saldos.csv"
FUNDS = ("A", "B", "C", "D", "E")
BALANCE_COLUMNS = tuple(f"saldo{fund}_pesos" for fund in FUNDS)


class DataContractError(ValueError):
    """Raised when an input violates a documented data contract."""


def sha256_file(path: str | Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame, required: Iterable[str], source: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise DataContractError(f"{source}: faltan columnas requeridas: {', '.join(missing)}")


def _period_from_year_month(frame: pd.DataFrame, source: str) -> pd.Series:
    year = frame["agno"].astype("string").str.strip()
    month = frame["mes"].astype("string").str.strip().str.zfill(2)
    valid = year.str.fullmatch(r"\d{4}", na=False) & month.str.fullmatch(
        r"0[1-9]|1[0-2]", na=False
    )
    if not bool(valid.all()):
        examples = frame.loc[~valid, ["agno", "mes"]].head(5).to_dict(orient="records")
        raise DataContractError(f"{source}: períodos inválidos; ejemplos={examples}")
    return year + "-" + month


def _open_member(archive: zipfile.ZipFile, member: str):
    if member not in archive.namelist():
        raise DataContractError(f"El archivo HPA no contiene {member!r}")
    return archive.open(member)


def load_characteristics(hpa_zip: str | Path) -> pd.DataFrame:
    usecols = ["correl", "sexo", "fecha_nac", "fecha_afil", "fecha_fall", "afp", "region"]
    with zipfile.ZipFile(hpa_zip) as archive, _open_member(archive, CHARACTERISTICS_MEMBER) as raw:
        frame = pd.read_csv(
            raw,
            sep=";",
            dtype="string",
            encoding="utf-8-sig",
            usecols=usecols,
            keep_default_na=True,
            na_values=[""],
        )
    _require_columns(frame, usecols, CHARACTERISTICS_MEMBER)
    frame["correl"] = frame["correl"].str.strip()
    if frame["correl"].isna().any() or frame["correl"].duplicated().any():
        raise DataContractError("caracteristicas_afiliados.csv: correl debe ser único y no nulo")
    valid_birth = frame["fecha_nac"].str.fullmatch(r"\d{6}", na=False)
    birth_month = pd.to_numeric(frame["fecha_nac"].str[-2:], errors="coerce")
    if not bool((valid_birth & birth_month.between(1, 12)).all()):
        bad = frame.loc[~(valid_birth & birth_month.between(1, 12)), "fecha_nac"].head(5).tolist()
        raise DataContractError(f"fecha_nac debe tener formato AAAAMM; ejemplos inválidos={bad}")
    return frame


def select_population(
    characteristics: pd.DataFrame,
    explicit_ids: Iterable[str] | None,
    sample_size: int | None,
    sample_seed: int,
) -> tuple[pd.DataFrame, set[str] | None]:
    explicit = [str(value).strip() for value in (explicit_ids or []) if str(value).strip()]
    if explicit:
        missing = sorted(set(explicit).difference(characteristics["correl"]))
        if missing:
            raise DataContractError(f"IDs solicitados ausentes de características: {missing[:10]}")
        selected = characteristics[characteristics["correl"].isin(explicit)].copy()
        return selected, set(explicit)
    if sample_size is not None and sample_size < len(characteristics):
        selected = characteristics.sample(n=int(sample_size), random_state=int(sample_seed)).copy()
        return selected, set(selected["correl"].tolist())
    return characteristics.copy(), None


def load_monthly_income(
    hpa_zip: str | Path,
    start: str,
    end: str,
    selected_ids: set[str] | None = None,
    chunksize: int = 250_000,
) -> pd.DataFrame:
    usecols = [
        "correl",
        "correl_pagador",
        "agno",
        "mes",
        "rem_imp",
        "rem_imp_tope_flag",
    ]
    pieces: list[pd.DataFrame] = []
    with zipfile.ZipFile(hpa_zip) as archive, _open_member(archive, CCICO_MEMBER) as raw:
        chunks = pd.read_csv(
            raw,
            sep=";",
            dtype="string",
            encoding="utf-8-sig",
            usecols=usecols,
            chunksize=chunksize,
            keep_default_na=True,
            na_values=[""],
            low_memory=False,
        )
        for chunk in chunks:
            _require_columns(chunk, usecols, CCICO_MEMBER)
            chunk["correl"] = chunk["correl"].str.strip()
            if selected_ids is not None:
                chunk = chunk[chunk["correl"].isin(selected_ids)]
            if chunk.empty:
                continue
            chunk["period"] = _period_from_year_month(chunk, CCICO_MEMBER)
            chunk = chunk[chunk["period"].between(start, end)]
            if chunk.empty:
                continue
            chunk["rem_imp"] = pd.to_numeric(chunk["rem_imp"], errors="coerce")
            chunk["rem_imp_tope_flag"] = pd.to_numeric(
                chunk["rem_imp_tope_flag"], errors="coerce"
            ).fillna(0)
            grouped = (
                chunk.groupby(["correl", "period"], sort=False, observed=True)
                .agg(
                    wage_clp=("rem_imp", lambda values: values.sum(min_count=1)),
                    source_tope_flag=("rem_imp_tope_flag", "max"),
                    payer_count=("correl_pagador", "nunique"),
                    income_source_rows=("correl", "size"),
                )
                .reset_index()
            )
            pieces.append(grouped)
    if not pieces:
        return pd.DataFrame(
            columns=[
                "correl",
                "period",
                "wage_clp",
                "source_tope_flag",
                "payer_count",
                "income_source_rows",
            ]
        )
    combined = pd.concat(pieces, ignore_index=True)
    combined = (
        combined.groupby(["correl", "period"], sort=False, observed=True)
        .agg(
            wage_clp=("wage_clp", lambda values: values.sum(min_count=1)),
            source_tope_flag=("source_tope_flag", "max"),
            payer_count=("payer_count", "sum"),
            income_source_rows=("income_source_rows", "sum"),
        )
        .reset_index()
    )
    return combined


def load_monthly_balances(
    hpa_zip: str | Path,
    start: str,
    end: str,
    selected_ids: set[str] | None = None,
    chunksize: int = 250_000,
) -> pd.DataFrame:
    usecols = ["correl", "agno", "mes", "tipocuenta", *BALANCE_COLUMNS]
    pieces: list[pd.DataFrame] = []
    with zipfile.ZipFile(hpa_zip) as archive, _open_member(archive, BALANCES_MEMBER) as raw:
        chunks = pd.read_csv(
            raw,
            sep=";",
            dtype="string",
            encoding="utf-8-sig",
            usecols=usecols,
            chunksize=chunksize,
            keep_default_na=True,
            na_values=[""],
            low_memory=False,
        )
        for chunk in chunks:
            _require_columns(chunk, usecols, BALANCES_MEMBER)
            chunk = chunk[chunk["tipocuenta"].astype("string").str.strip().eq("1")]
            chunk["correl"] = chunk["correl"].str.strip()
            if selected_ids is not None:
                chunk = chunk[chunk["correl"].isin(selected_ids)]
            if chunk.empty:
                continue
            chunk["period"] = _period_from_year_month(chunk, BALANCES_MEMBER)
            chunk = chunk[chunk["period"].between(start, end)]
            if chunk.empty:
                continue
            for column in BALANCE_COLUMNS:
                chunk[column] = pd.to_numeric(chunk[column], errors="coerce")
            grouped = (
                chunk.groupby(["correl", "period"], sort=False, observed=True)
                .agg(
                    **{
                        column: (column, lambda values: values.sum(min_count=1))
                        for column in BALANCE_COLUMNS
                    },
                    balance_source_rows=("correl", "size"),
                )
                .reset_index()
            )
            pieces.append(grouped)
    if not pieces:
        return pd.DataFrame(columns=["correl", "period", *BALANCE_COLUMNS])
    combined = pd.concat(pieces, ignore_index=True)
    combined = (
        combined.groupby(["correl", "period"], sort=False, observed=True)
        .agg(
            **{
                column: (column, lambda values: values.sum(min_count=1))
                for column in BALANCE_COLUMNS
            },
            balance_source_rows=("balance_source_rows", "sum"),
        )
        .reset_index()
    )

    numeric = combined.loc[:, BALANCE_COLUMNS].fillna(0.0)
    positive = numeric.gt(0)
    combined["positive_fund_count"] = positive.sum(axis=1).astype("int8")
    combined["transfer_flag"] = combined["positive_fund_count"].gt(1)
    combined["balance_clp"] = numeric.sum(axis=1)
    maximum = numeric.max(axis=1)
    combined["observed_fund"] = numeric.idxmax(axis=1).str.extract(r"saldo([A-E])_")[0]
    combined.loc[maximum.le(0), "observed_fund"] = pd.NA
    combined["no_balance_flag"] = maximum.le(0)
    return combined


def load_returns(workbook: str | Path, sheet_name: str | None = None) -> pd.DataFrame:
    path = Path(workbook)
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path)
    elif path.suffix.lower() == ".xlsx":
        raw = pd.read_excel(path, sheet_name=sheet_name or 0, header=3)
    elif path.suffix.lower() == ".xls":
        try:
            raw = pd.read_excel(path, sheet_name=sheet_name or 0)
        except ImportError as exc:
            raise DataContractError(
                "Leer .xls requiere xlrd. Use la hoja 2_Rentab_Real_Mensual_Sist del "
                "consolidado .xlsx incluido en el proyecto o instale xlrd explícitamente."
            ) from exc
    else:
        raise DataContractError(f"Formato de rentabilidades no soportado: {path.suffix}")

    normalized = {str(column).strip().lower(): column for column in raw.columns}
    period_key = next((key for key in ("periodo", "período", "period") if key in normalized), None)
    if period_key is None:
        raise DataContractError("Rentabilidades: no se encontró columna Periodo")
    output = pd.DataFrame({"period": raw[normalized[period_key]].astype("string").str[:7]})
    for fund in FUNDS:
        candidates = (f"fondo_{fund.lower()}", f"fondo tipo {fund.lower()}", f"fondo {fund.lower()}")
        key = next((candidate for candidate in candidates if candidate in normalized), None)
        if key is None:
            raise DataContractError(f"Rentabilidades: no se encontró la serie del Fondo {fund}")
        output[f"return_{fund}"] = pd.to_numeric(raw[normalized[key]], errors="coerce") / 100.0
    output = output[output["period"].str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", na=False)]
    if output["period"].duplicated().any():
        raise DataContractError("Rentabilidades: Periodo debe ser único")
    values = output[[f"return_{fund}" for fund in FUNDS]]
    if bool((values <= -1).any(axis=None)):
        raise DataContractError("Rentabilidades: se encontró un retorno mensual <= -100%")
    return output.sort_values("period").reset_index(drop=True)


def load_parameters(path: str | Path, start: str, end: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"period": "string"})
    required = ["period", "uf_clp", "tope_uf"]
    _require_columns(frame, required, str(path))
    frame = frame[frame["period"].between(start, end)].copy()
    frame["uf_clp"] = pd.to_numeric(frame["uf_clp"], errors="coerce")
    frame["tope_uf"] = pd.to_numeric(frame["tope_uf"], errors="coerce")
    expected = pd.period_range(start, end, freq="M").astype(str)
    missing = sorted(set(expected).difference(frame["period"]))
    if missing:
        raise DataContractError(f"Parámetros externos: faltan meses: {missing[:12]}")
    if frame["period"].duplicated().any():
        raise DataContractError("Parámetros externos: period debe ser único")
    if frame[["uf_clp", "tope_uf"]].isna().any(axis=None):
        raise DataContractError("Parámetros externos: uf_clp y tope_uf no admiten nulos")
    if bool((frame[["uf_clp", "tope_uf"]] <= 0).any(axis=None)):
        raise DataContractError("Parámetros externos: uf_clp y tope_uf deben ser positivos")
    return frame.sort_values("period").reset_index(drop=True)


def build_panel(
    balances: pd.DataFrame,
    income: pd.DataFrame,
    characteristics: pd.DataFrame,
    returns: pd.DataFrame,
    parameters: pd.DataFrame,
    contribution_rate: float,
) -> pd.DataFrame:
    if balances.empty:
        raise DataContractError("No hay saldos CCICO en la población y ventana seleccionadas")
    panel = balances.merge(income, on=["correl", "period"], how="left", validate="one_to_one")
    panel = panel.merge(characteristics, on="correl", how="left", validate="many_to_one")
    panel = panel.merge(returns, on="period", how="left", validate="many_to_one")
    panel = panel.merge(parameters, on="period", how="left", validate="many_to_one")
    if panel[["fecha_nac", "uf_clp", "tope_uf"]].isna().any(axis=None):
        raise DataContractError("Panel: faltan características o parámetros para filas con saldo")

    panel["income_absent_flag"] = panel["wage_clp"].isna()
    panel["wage_clp"] = panel["wage_clp"].fillna(0.0).clip(lower=0.0)
    panel["source_tope_flag"] = panel["source_tope_flag"].fillna(0).astype("int8")
    panel["payer_count"] = panel["payer_count"].fillna(0).astype("int16")
    panel["wage_uf"] = panel["wage_clp"] / panel["uf_clp"]
    panel["calculated_tope_flag"] = panel["wage_uf"].ge(panel["tope_uf"])
    panel["contribution_uf"] = contribution_rate * np.minimum(
        panel["wage_uf"], panel["tope_uf"]
    )
    panel["balance_uf"] = panel["balance_clp"] / panel["uf_clp"]

    birth_year = pd.to_numeric(panel["fecha_nac"].str[:4], errors="raise")
    birth_month = pd.to_numeric(panel["fecha_nac"].str[4:6], errors="raise")
    period_year = pd.to_numeric(panel["period"].str[:4], errors="raise")
    period_month = pd.to_numeric(panel["period"].str[5:7], errors="raise")
    age_months = (period_year * 12 + period_month) - (birth_year * 12 + birth_month)
    panel["age"] = np.floor(age_months / 12).astype("int16")
    panel["period_ordinal"] = pd.PeriodIndex(panel["period"], freq="M").asi8
    return panel.sort_values(["correl", "period_ordinal"]).reset_index(drop=True)
