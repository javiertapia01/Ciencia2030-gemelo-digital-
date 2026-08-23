# Metodología implementada

## Núcleo individual compartido

La reconstrucción HPA y la simulación Markov conservan adaptadores separados, pero ambas aplican `individual_core.accounting_step_vectorized` y pueden expresarse mediante el contrato persona–mes v1.0. Esto garantiza equivalencia computacional de la identidad contable sin mezclar la validez histórica con los supuestos sintéticos. Véase `docs/INDIVIDUAL_CORE.md`.

## 1. Estimando

El estimando es la diferencia final entre dos reconstrucciones contables de la misma persona:

`ΔB = B(regla generacional por edad) − B(asignación multifondos observada)`.

Ingresos, cotizaciones derivadas, condición inicial y retornos de mercado son idénticos en ambos mundos. La única variable tratamiento es la secuencia de fondos.

## 2. Convenciones temporales y unidades

- Frecuencia: mensual, identificada como `AAAA-MM`.
- Saldo reportado: tratado como saldo en la fecha mensual de observación.
- Aporte: entra al comienzo del mes antes de aplicar el retorno.
- UF: valor del último día calendario de cada mes. Esta elección hace consistente un retorno real deflactado por UF con saldos de fin de mes expresados como pesos/UF.
- Nacimiento: se documenta día convencional 15. Como la base y el modelo trabajan a frecuencia mensual, la edad entera se obtiene con la diferencia de meses entre `fecha_nac=AAAAMM` y el período.
- Ventana activa inicial: 2008-01 a 2025-12, donde existen saldos HPA y retornos A–E.

## 3. Variables

### Remuneración y cotización

`W(i,t)` es la suma de `rem_imp` sobre todas las filas y pagadores de la persona–mes. La cotización en UF es:

`C(i,t) = 0,10 × min(W_pesos(i,t) / UF_pesos(t), tope_UF(t))`.

El flag de tope HPA se usa como control de consistencia, no como reemplazo del parámetro externo. Como el flag existe por fila/pagador y el cálculo se realiza después de agregar pagadores, se reporta la concordancia sin exigir igualdad perfecta.

### Fondo y saldo observados

Solo se usa `tipocuenta=1`. El saldo total es la suma A–E. El fondo observado es el de mayor saldo positivo. Si hay más de un fondo positivo se marca `transfer_flag`; si ninguno es positivo, la fila no es válida para recursión.

### Regla generacional

Escenario base:

| Edad | Proxy |
|---:|:---:|
| `<35` | A |
| `35–44` | B |
| `45–54` | C |
| `55–64` | D |
| `65+` | E |

Sensibilidades: todos los cortes se desplazan cinco años antes y cinco años después. Estas reglas son escenarios construidos con A–E; no se presentan como parámetros regulatorios observados.

## 4. Panel y brechas

El calendario analítico nace de los meses con saldo CCICO. Cuando hay saldo pero no fila CCICO, la remuneración se completa con cero y se activa `income_absent_flag`; su frecuencia se reporta. No se imputan remuneraciones positivas.

Para cada persona se selecciona el tramo continuo válido más largo. Una brecha mensual, saldo no positivo, fondo no inferible o retorno faltante impide cruzar esa discontinuidad. Se exige una historia mínima configurable.

## 5. Gate contable

Desde el saldo inicial reportado se reconstruye acumulativamente el saldo observado con las cotizaciones derivadas y el retorno del fondo observado. Para cada mes se calcula:

`error_relativo = (saldo_reconstruido − saldo_reportado) / saldo_reportado`.

La evaluación excluye saldos inferiores al mínimo configurable en UF para reducir la dominancia mecánica del redondeo de $50.000. El gate exige simultáneamente:

1. observaciones suficientes;
2. mediana del error absoluto bajo el umbral;
3. mediana del error absoluto en la ventana terminal de 12 meses bajo el umbral;
4. pendiente anual de la mediana mensual del error bajo el umbral absoluto.

La primera corrida de calibración mostró que una mediana global podía ocultar deterioro al final de una trayectoria larga; por eso el control terminal es independiente. Los umbrales quedan en el manifiesto de cada corrida y no se relajan silenciosamente para hacer pasar un resultado.

## 6. Diagnóstico mensual de un paso

El diagnóstico parte de saldos reportados consecutivos, no de la reconstrucción acumulada:

`R(i,t) = B_reportado(i,t+1) − B_predicho_desde_reportado(i,t)`.

El signo es saldo reportado menos saldo predicho. La comparación usa una muestra común de transiciones con saldo suficiente y con todos los insumos disponibles. Combina tres meses posibles para la cotización —anterior, actual y siguiente—, dos momentos de aplicación —antes o después del retorno— y cuatro convenciones de retorno: fondo dominante o cartera ponderada por saldos, usando el mes actual o el siguiente. Esto produce 24 variantes.

La partición se hace por persona, nunca por fila, de forma determinista con una semilla documentada. La variante con menor mediana del residuo relativo absoluto en calibración se congela y se evalúa en validación. La estratificación posterior utiliza solo validación y cubre año, edad, AFP, fondo, transferencias, etapa laboral, cercanía a fallecimiento, densidad y remuneración.

Este diagnóstico localiza convenciones o periodos problemáticos, pero no sustituye el gate acumulativo. Una variante favorable solo puede pasar al motor después de una decisión metodológica explícita y una nueva validación fuera de calibración.

## 7. Inferencia

- Wilcoxon signed-rank sobre diferencias individuales, usando aproximación normal con corrección de continuidad y empates.
- Bootstrap percentil remuestreando personas completas, no meses.
- OLS de la diferencia relativa sobre edad inicial, ingreso medio, densidad y fondo predominante; matriz de covarianza HC3.
- Estratificación por edad, cuartil de ingreso agrupado, densidad, sexo, AFP y fondo predominante.

Estas herramientas describen heterogeneidad e incertidumbre muestral de la HPA. No convierten la muestra en representativa de Chile ni corrigen la falta de factores de expansión.

## 8. Riesgos de interpretación

La identidad simplificada no incluye retiros, pagos de pensión, bonos, rezagos de acreditación, movimientos administrativos ni otros flujos que puedan afectar el saldo CCICO. Precisamente por eso el gate no es decorativo: si esos componentes impiden reconstruir el observado con error acotado, el efecto contrafactual no se interpreta.
