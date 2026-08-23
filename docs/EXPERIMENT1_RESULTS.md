# Experimento I · resultados históricos validados

## Conclusión

En 26.172 personas HPA con al menos 24 meses continuos y contablemente reconstruibles entre enero de 2008 y julio de 2020, la regla generacional proxy A–E produjo una diferencia mediana de **−0,452 UF (−0,789%)** respecto de la asignación multifondos observada. El **31,39%** terminó con un saldo mayor bajo la regla proxy.

Este es un contrafactual histórico condicionado a la muestra, el mercado observado, la cotización reconstruida y la regla etaria declarada. No es una predicción de la reforma, una estimación nacional ni una recomendación de inversión.

## Diseño en dos etapas

La convención contable no se eligió usando el signo del contrafactual:

1. En una muestra reproducible de 100 personas, 76 tuvieron historia elegible y se dividieron sin solapamiento en 38 para calibración y 38 para validación.
2. Se compararon 24 convenciones solo en calibración. La seleccionada fue `current_end__weighted_next`: cotización del mes actual al cierre y retorno del mes siguiente ponderado por los saldos positivos A–E de ese mes.
3. Sin reajustarla, el gate acumulativo pasó en las 38 personas elegibles de validación.
4. Con la convención congelada se ejecutó la cohorte completa. La comparación exploratoria de 24 variantes no se repitió a escala completa; el gate acumulativo, las sensibilidades y la inferencia sí se ejecutaron.

La ventana termina en 2020-07 porque los retiros extraordinarios posteriores son salidas de la CCICO no observadas como flujo por el modelo. La Superintendencia de Pensiones documenta el inicio del [primer retiro](https://www.spensiones.cl/portal/institucional/594/w3-article-14028.html) el 30 de julio de 2020, del [segundo](https://www.spensiones.cl/portal/institucional/594/w3-article-14331.html) el 10 de diciembre de 2020 y del [tercero](https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-10419.html) el 28 de abril de 2021.

## Gate contable

| Métrica | Validación reservada | Cohorte completa | Umbral |
|---|---:|---:|---:|
| Observaciones elegibles | 4.409 | 2.899.369 | ≥100 |
| Mediana del error relativo absoluto | 1,74% | 2,18% | ≤10% |
| Mediana absoluta en ventana terminal | 2,22% | 2,99% | ≤10% |
| Deriva anual de la mediana mensual | −0,037 pp | −0,081 pp | ≤0,5 pp en valor absoluto |
| Gate | Pasa | Pasa | Todos los controles |

## Resultado base

| Indicador | Resultado |
|---|---:|
| Personas elegibles | 26.172 |
| Diferencia mediana | −0,452 UF |
| Diferencia mediana relativa | −0,789% |
| IC bootstrap 95% de la mediana | [−0,482; −0,415] UF |
| Personas con diferencia positiva | 31,39% |
| IC bootstrap 95% de la fracción positiva | [30,81%; 31,93%] |
| Diferencia media | +3,533 UF |
| Diferencia relativa media | −0,835% |

La media en UF es positiva mientras la mediana y la media porcentual son negativas. No es una contradicción: una cola de ganancias absolutas grandes en personas con saldos altos domina la media en UF. Por eso la mediana, la distribución completa y la escala porcentual son más informativas que una sola media monetaria.

La distribución base fue heterogénea: P10 = −23,26 UF, P25 = −5,27 UF, mediana = −0,45 UF, P75 = +0,30 UF y P90 = +13,43 UF. Hubo 16.749 diferencias negativas, 1.208 iguales a cero y 8.215 positivas.

## Sensibilidad de cortes etarios

| Regla | Mediana UF | Mediana relativa | Fracción positiva | Signo distinto del escenario base |
|---|---:|---:|---:|---:|
| Transición 5 años antes | −0,096 | −0,287% | 42,54% | 26,39% |
| Base | −0,452 | −0,789% | 31,39% | 0,00% |
| Transición 5 años después | −0,886 | −1,241% | 24,62% | 16,97% |

La magnitud y hasta el signo individual son sensibles a los cortes. El resultado no respalda una afirmación universal de ganancia o pérdida por edad; respalda una distribución histórica bajo reglas proxy concretas.

## Cobertura y exclusiones

- 32.877 personas aparecen en características.
- 29.711 tienen al menos una fila de saldo CCICO en la ventana.
- 26.172 cumplen la historia continua mínima y entran al resultado.
- 3.539 personas con saldo fueron excluidas por historia continua insuficiente.
- El panel contiene 3.816.090 persona–mes; el 53,38% de los meses con saldo no tiene fila de remuneración y se trata como cotización cero, según el contrato documentado.

## Revisión manual de trayectorias

De las 30 personas preseleccionadas para auditoría, 27 resultaron elegibles. La revisión cubrió edades iniciales entre 16 y 76 años, fondos predominantes B–E, historias de 25 a 151 meses y resultados contrafactuales tanto positivos como negativos.

La revisión también encontró cinco trayectorias con mediana individual del error absoluto superior a 10%. Los casos más extremos terminan con saldos reportados muy bajos y saldos reconstruidos altos, especialmente en edades de pensión, patrón compatible con pagos o movimientos no observados por la identidad simplificada. El gate poblacional pasa porque sus controles son distribucionales, pero eso no garantiza precisión para cada persona. Por esta razón:

- la mediana y los intervalos por persona son la lectura principal;
- la media en UF se reporta con cautela por su sensibilidad a colas y escala de saldo;
- ningún resultado individual debe interpretarse como predicción personalizada;
- una versión futura puede agregar un dominio específico de acumulación que trate por separado pagos de pensión y movimientos administrativos.

## Reproducción local

La fase de calibración/validación:

```powershell
gemelo-previsional run --config config/experiment.local.json --sample-size 100 --output-dir output/runs/experimento_i_validado_100
```

Después de confirmar que la convención configurada coincide con la seleccionada y que el gate reservado pasa, la cohorte completa:

```powershell
gemelo-previsional run --config config/experiment.local.json --skip-one-step-diagnostics --output-dir output/runs/experimento_i_completo
```

Los microdatos y las corridas permanecen fuera de Git. El manifiesto completo, hashes de insumos y salidas locales de esta ejecución están en `output/runs/experimento_i_completo_20260823/`.
