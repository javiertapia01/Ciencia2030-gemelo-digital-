# Contratos de datos

## HPA comprimido

Formato ZIP con CSV UTF-8-SIG separados por `;`. Los identificadores y fechas compactas se leen como texto.

### `caracteristicas_afiliados.csv`

Requeridas: `correl`, `sexo`, `fecha_nac`, `fecha_afil`, `fecha_fall`, `afp`, `region`.

- `correl`: único, no nulo, conservando ceros a la izquierda.
- `fecha_nac`: `AAAAMM` válido.

### `informacion_mensual_ccico.csv`

Requeridas: `correl`, `correl_pagador`, `agno`, `mes`, `rem_imp`, `rem_imp_tope_flag`.

- Se agregan todas las filas por `correl,period`.
- `rem_imp` se convierte a número; nulos no se inventan como monto positivo.
- Se conserva número de filas y pagadores como auditoría.

### `informacion_mensual_saldos.csv`

Requeridas: `correl`, `agno`, `mes`, `tipocuenta`, `saldoA_pesos` … `saldoE_pesos`.

- Solo `tipocuenta=1`.
- Duplicados persona–mes se suman y se cuentan.
- Nulos de un fondo se tratan como ausencia de saldo en ese fondo al inferir la composición.

## Rentabilidades

Formatos admitidos:

- `.xlsx`: encabezado en fila 4, columnas `Periodo`, `Fondo_A` … `Fondo_E`;
- `.csv`: las mismas columnas;
- `.xls`: solo si el entorno dispone explícitamente de `xlrd`.

Los valores fuente están en porcentaje real mensual y se dividen por 100. `Periodo` debe ser único y ningún retorno puede ser ≤−100%.

## Parámetros externos

CSV mensual con:

| Columna | Tipo | Regla |
|---|---|---|
| `period` | texto | `AAAA-MM`, único y cobertura completa |
| `uf_clp` | número | UF en pesos, positiva |
| `tope_uf` | número | tope obligatorio AFP en UF, positivo |
| `uf_convention` | texto | recomendado `calendar_month_end` |
| `uf_source` | URL | fuente oficial por fila |
| `tope_source` | URL | fuente oficial por fila |

El pipeline rechaza meses faltantes, duplicados, nulos y valores no positivos.

## Salidas

Siempre:

- `run_manifest.json`
- `data_quality.json`
- `validation_summary.json`
- `validation_errors_by_month.csv`
- `validation_errors_sample.csv`
- `one_step_selection.json` cuando `diagnostics.one_step.enabled=true`
- `one_step_variant_summary.csv` cuando `diagnostics.one_step.enabled=true`
- `one_step_residuals.csv` cuando `diagnostics.one_step.enabled=true`
- `one_step_stratification.csv` cuando `diagnostics.one_step.enabled=true`
- `manual_trajectories.csv`
- `exclusions.csv`

Solo si pasa el gate, o si se fuerza explícitamente como diagnóstico:

- `individual_results.csv`
- `population_summary.json`
- `sensitivity_summary.csv`
- `stratification.csv`
- `regression_ols_hc3.csv`

Si el gate falla se agrega `GATE_CLOSED.md`. Una corrida forzada mantiene `gate_passed=false` e `interpretation_allowed=false`.
Sin `--force-counterfactual`, las trayectorias de una corrida con gate cerrado contienen solo saldo reportado y reconstrucción observada; no incluyen columnas what-if ni diferencias contrafactuales.

El diagnóstico de un paso tampoco publica resultados contrafactuales. `one_step_residuals.csv` parte de saldos reportados consecutivos; `one_step_variant_summary.csv` compara variantes sobre las mismas transiciones; y `one_step_selection.json` registra la selección hecha únicamente en calibración y su evaluación separada en validación.

## Salidas del Hito 2

La corrida sintética `gemelo-previsional hito2` no usa HPA y escribe:

| Archivo | Contrato |
|---|---|
| `hito2_summary.json` | Configuración, alcance, semilla, supuestos, advertencias y caminos representativos. |
| `hito2_path_results.csv` | Una fila por escenario y camino Monte Carlo, con saldo final, contribuciones, densidad y meses por estado. |
| `hito2_scenario_summary.csv` | Media, desviación, P10, mediana, P90 y comparación con el escenario base. |
| `hito2_state_occupancy.csv` | Participación de cada estado en los persona–mes simulados. |
| `hito2_transition_matrices.csv` | Matrices mensuales en formato largo y auditable. |
| `hito2_representative_trajectories.csv` | Historia mensual del camino más cercano a la mediana de cada escenario. |
| `hito2_market_returns.csv` | Mercado sintético común utilizado por los escenarios. |
| `hito2-results.svg` | Resumen gráfico de distribuciones y trayectorias. |

`scenario` y `path_id` identifican de manera única los resultados. `draw_id` enlaza la misma extracción uniforme entre escenarios y permite interpretar `paired_gap_vs_baseline_uf`. `contribution_density` siempre pertenece a `[0,1]`; los saldos y contribuciones se expresan en UF reales del modelo.
