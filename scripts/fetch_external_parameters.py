from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd


# Tope obligatorio AFP/salud/accidentes en UF. Los cambios provisionales de
# enero 2019 y enero 2021 se representan con overrides mensuales.
ANNUAL_TOPE_UF = {
    2008: 60.0,
    2009: 60.0,
    2010: 64.7,
    2011: 66.0,
    2012: 67.4,
    2013: 70.3,
    2014: 72.3,
    2015: 73.2,
    2016: 74.3,
    2017: 75.7,
    2018: 78.3,
    2019: 79.2,
    2020: 80.2,
    2021: 81.6,
    2022: 81.6,
    2023: 81.6,
    2024: 84.3,
    2025: 87.8,
}

MONTHLY_OVERRIDES = {
    "2019-01": 79.3,
    "2021-01": 81.7,
}

TOPE_SOURCES = {
    2008: "https://www.spensiones.cl/portal/institucional/594/articles-7206_libroVIIedicion.pdf",
    2009: "https://www.spensiones.cl/portal/institucional/594/articles-7206_libroVIIedicion.pdf",
    2010: "https://www.spensiones.cl/portal/institucional/594/articles-7206_libroVIIedicion.pdf",
    2011: "https://www.spensiones.cl/portal/institucional/594/w3-article-7591.html",
    2012: "https://www.spensiones.cl/portal/institucional/594/articles-8634_recurso_1.pdf",
    2013: "https://www.spensiones.cl/portal/institucional/594/w3-article-10422.html",
    2014: "https://www.spensiones.cl/portal/institucional/594/w3-article-10422.html",
    2015: "https://www.spensiones.cl/portal/institucional/594/articles-14919_recurso_1.pdf",
    2016: "https://www.spensiones.cl/transparencia/9%20de%202017.pdf",
    2017: "https://www.spensiones.cl/transparencia/9%20de%202017.pdf",
    2018: "https://www.spensiones.cl/portal/institucional/594/articles-12946_recurso_1.pdf",
    2019: "https://www.spensiones.cl/portal/institucional/594/w3-article-13553.html",
    2020: "https://www.spensiones.cl/portal/institucional/594/w3-article-13843.html",
    2021: "https://www71.spensiones.cl/portal/institucional/594/w3-article-14366.html",
    2022: "https://www.spensiones.cl/portal/institucional/594/w3-article-15074.html",
    2023: "https://www.spensiones.cl/portal/institucional/594/w3-article-15486.html",
    2024: "https://www.spensiones.cl/portal/institucional/594/w3-article-15891.html",
    2025: "https://www.spensiones.cl/portal/institucional/594/w3-article-16252.html",
}

MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def fetch_year(year: int) -> list[dict[str, object]]:
    if year not in ANNUAL_TOPE_UF:
        raise ValueError(f"No hay tope documentado para {year}")
    # El SII mantuvo dos rutas históricas y el año de transición no es uniforme.
    candidates = [
        f"https://www.sii.cl/valores_y_fechas/uf/uf{year}.htm",
        f"https://www.sii.cl/pagina/valores/uf/uf{year}.htm",
    ]
    html = None
    url = None
    for candidate in candidates:
        try:
            request = Request(candidate, headers={"User-Agent": "gemelo-previsional/0.1"})
            with urlopen(request, timeout=30) as response:
                candidate_html = response.read().decode("utf-8-sig", errors="replace")
        except HTTPError:
            continue
        if "<table" in candidate_html.lower() and len(candidate_html) > 1000:
            html = candidate_html
            url = candidate
            break
    if html is None or url is None:
        raise RuntimeError(f"No se encontró una página UF utilizable para {year}")
    tables = pd.read_html(StringIO(html), decimal=",", thousands=".", flavor="lxml")
    wide = next(
        (table for table in reversed(tables) if "Día" in table.columns and set(MONTHS).issubset(table.columns)),
        None,
    )
    if wide is None:
        raise RuntimeError(f"No se encontró la tabla anual UF en {url}")
    rows: list[dict[str, object]] = []
    for month_number, month_name in enumerate(MONTHS, start=1):
        values = pd.to_numeric(wide[month_name], errors="coerce").dropna()
        if values.empty:
            raise RuntimeError(f"UF sin valores para {year}-{month_number:02d}")
        period = f"{year}-{month_number:02d}"
        rows.append(
            {
                "period": period,
                "uf_clp": float(values.iloc[-1]),
                "tope_uf": float(MONTHLY_OVERRIDES.get(period, ANNUAL_TOPE_UF[year])),
                "uf_convention": "calendar_month_end",
                "uf_source": url,
                "tope_source": TOPE_SOURCES[year],
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga UF oficial SII y agrega topes oficiales SP")
    parser.add_argument("--start-year", type=int, default=2008)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.start_year > args.end_year:
        parser.error("--start-year no puede ser posterior a --end-year")
    records: list[dict[str, object]] = []
    for year in range(args.start_year, args.end_year + 1):
        print(f"Descargando UF {year}...")
        records.extend(fetch_year(year))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(output, index=False, encoding="utf-8")
    print(f"Escritos {len(records)} meses en {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
