# Motor financiero reproducible v1

Primera adaptación controlada del prototipo recibido por el equipo. Combina una cadena de Markov laboral con retornos simples normales multivariados y diez fondos sintéticos por edad.

## Resultado de la configuración versionada

- Caminos: 10,000
- Horizonte: 528 meses
- Saldo final mediano: 2,193.37 UF
- P10–P90: 2,040.29–2,356.41 UF
- Densidad de cotización mediana: 89.8%

## Interpretación

Esta corrida estima la distribución conjunta sintética del saldo bajo incertidumbre laboral y financiera. No aísla todavía el efecto de una política de inversión y no reemplaza el Experimento I ni el Hito 2.

La configuración utiliza UF reales, semilla fija, flujos aleatorios independientes para trabajo y mercado, y el núcleo contable compartido. Los archivos de parámetros y diagnósticos permiten auditar carteras, covarianzas y momentos simulados.

Los parámetros provienen del script recibido y siguen pendientes de contrastarse con el archivo fuente `preámbulo.py`. Los fondos son sintéticos y la cotización constante es solo un supuesto de escenario.

## Reproducir

```powershell
gemelo-previsional motor-financiero --config config/motor_financiero.json --output-dir examples/motor_financiero
```

Consulte `docs/FINANCIAL_ENGINE.md` para la metodología y `motor_financiero_summary.json` para el manifiesto completo.
