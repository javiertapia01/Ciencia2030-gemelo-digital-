# Experimentos toy del gemelo digital

Esta carpeta contiene una demostración completamente sintética y reproducible. No usa registros HPA, no representa a la población afiliada y no estima el efecto real de los Fondos Generacionales.

## Reproducir

Desde la raíz del repositorio:

```bash
python -m pip install -e .
gemelo-previsional toy --output-dir examples/toy --people 800 --months 120 --seed 2030
```

El experimento genera un mercado mensual determinista, tres arquetipos y una cohorte sintética de 800 personas. Ambos mundos reciben las mismas cotizaciones y retornos de mercado; solo cambia la asignación de fondo.

## Lecturas principales

| Dimensión | Resultado del escenario base |
|---|---:|
| Personas sintéticas | 800 |
| Horizonte | 120 meses |
| Cambio mediano de saldo | −11,8 UF |
| Cambio mediano relativo | −2,3% |
| Personas con mayor saldo | 26,5% |
| Error máximo al reproducir el mundo observado | 0 UF |

En los tres arquetipos, el cambio final fue:

| Arquetipo | Fondo observado | Saldo observado | Saldo con regla | Diferencia |
|---|:---:|---:|---:|---:|
| Joven | C | 561,4 UF | 588,7 UF | +27,3 UF |
| Edad media | A | 595,5 UF | 518,7 UF | −76,8 UF |
| Próxima al retiro | A | 917,7 UF | 742,4 UF | −175,3 UF |

Estos signos no son una predicción. Provienen de una única trayectoria de retornos sintéticos, creada para mostrar que el gemelo puede revelar distribución, heterogeneidad, trayectorias y sensibilidad al diseño.

![Resumen gráfico de los experimentos toy](toy-results.svg)

## Archivos

| Archivo | Contenido |
|---|---|
| `toy_summary.json` | Metadatos, validación y métricas principales. |
| `toy-results.svg` | Gráfico de arquetipos, distribución y sensibilidad. |
| `toy_market_returns.csv` | Retornos mensuales sintéticos de los fondos A–E. |
| `toy_archetype_trajectories.csv` | Saldos mensuales paralelos de tres arquetipos. |
| `toy_individual_results.csv` | Resultado final por persona y escenario. |
| `toy_age_summary.csv` | Resumen del escenario base por tramo de edad. |
| `toy_sensitivity_summary.csv` | Comparación de los tres calendarios de transición. |
