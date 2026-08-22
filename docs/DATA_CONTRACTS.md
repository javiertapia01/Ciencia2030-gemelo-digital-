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
