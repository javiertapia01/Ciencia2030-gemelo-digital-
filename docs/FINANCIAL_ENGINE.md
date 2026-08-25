# Motor financiero reproducible v1

## Objetivo y alcance

Esta ruta adapta de manera controlada las piezas útiles del prototipo `markov (1).py`: una cadena laboral mensual, retornos correlacionados de cinco clases de activos y una regla de diez fondos por edad.

La pregunta de esta primera versión es:

> Bajo un perfil, una matriz laboral, diez carteras sintéticas y un modelo de mercado explícitos, ¿qué distribución conjunta de saldos produce la incertidumbre laboral y financiera?

El motor es sintético. No modifica el Experimento I ni el Hito 2, no usa HPA para calibrar las transiciones y no representa todavía carteras regulatorias oficiales.

## Separación de componentes

El motor mantiene separados:

1. el flujo aleatorio laboral;
2. el flujo aleatorio financiero;
3. la regla de fondo según edad;
4. la política simplificada de cotización;
5. la identidad contable compartida.

La semilla maestra se divide mediante `numpy.random.SeedSequence.spawn` en dos flujos PCG64 independientes. Así, el consumo de números aleatorios del mercado no altera las transiciones laborales y viceversa.

## Dinámica mensual

Para cada camino y mes:

1. el estado laboral vigente determina si existe cotización;
2. el salario potencial real determina el aporte;
3. se sortean los cinco retornos de activos de manera conjunta;
4. los pesos convierten esos retornos en retornos de FG01–FG10;
5. la edad selecciona el fondo aplicable;
6. el núcleo contable actualiza el saldo;
7. un sorteo laboral independiente determina el estado del mes siguiente.

Con la convención versionada de aporte al inicio, la identidad es:

\[
B_{i,t+1}=(B_{i,t}+C_{i,t})(1+r_{i,F(t),t}).
\]

La configuración permite usar aporte al cierre, pero cambiar esa opción define otro experimento y queda registrado en el manifiesto.

## Mercado v1

El vector de retornos simples mensuales de activos sigue:

\[
R_{i,t}\sim\mathcal{N}(\mu,\Sigma).
\]

Para el fondo \(f\), con pesos \(w_f\):

\[
r_{i,f,t}=w_f^\top R_{i,t}.
\]

La validación exige que la covarianza sea finita, simétrica y semidefinida positiva. Las carteras deben ser no negativas y sumar exactamente uno. Si una simulación genera un retorno simple menor o igual a −100%, la corrida falla: no se recortan valores silenciosamente.

Este modelo preserva correlaciones contemporáneas, pero no reproduce adecuadamente colas pesadas, autocorrelación, crisis o cambios de régimen. Es una línea base reproducible, no el modelo financiero definitivo.

## Fondos sintéticos y corrección documentada

Los fondos se denominan FG01–FG10 para evitar presentarlos como carteras oficiales. La asignación conserva los límites inclusivos del script recibido: FG01 hasta los 35 años, FG02 hasta los 40 y así sucesivamente.

La cartera original del tercer fondo sumaba 0,90. El motor no normaliza automáticamente configuraciones inválidas. En la configuración versionada se tomó la decisión explícita de aumentar la renta fija nacional de 0,15 a 0,25, completando el 10% faltante. Esta decisión queda marcada como pendiente de confirmar con `preámbulo.py`.

Con el perfil de 21 a 65 años, la última edad mensual simulada es 64 años y 11 meses. Por eso se utilizan FG01–FG07; FG08–FG10 se validan y quedan disponibles para horizontes posteriores a 65.

## Unidades y cotización

Salarios, aportes y saldos se expresan en UF reales. Esto evita mezclar un salario nominal en pesos con retornos cuya base de precios no estaba documentada.

La tasa constante de 14,5% reproduce un escenario simplificado de 10% del trabajador más 4,5% patronal directo. No representa la gradualidad vigente ni separa los destinos del aporte del empleador. La nota metodológica es obligatoria en la configuración para impedir que este supuesto quede oculto.

## Parámetros y procedencia

Las medias, covarianzas, matrices laborales y carteras provienen del archivo recibido. Ese archivo los atribuye a `preámbulo.py`, que no estuvo disponible al implementar esta versión. Por ello:

- los valores están versionados y son auditables;
- su procedencia incompleta se registra en JSON;
- pueden usarse para reproducir el mecanismo;
- no deben interpretarse como estimaciones empíricas validadas.

## Salidas

La corrida genera:

| Archivo | Contenido |
|---|---|
| `motor_financiero_summary.json` | Manifiesto, semilla, configuración, correcciones y advertencias. |
| `motor_financiero_path_results.csv` | Saldo, aportes, densidad y meses por estado para cada camino. |
| `motor_financiero_balance_summary.csv` | Media, dispersión y cuantiles del saldo final. |
| `motor_financiero_asset_parameters.csv` | Momentos mensuales y anualizados de los activos. |
| `motor_financiero_asset_covariance.csv` | Covarianzas y correlaciones derivadas. |
| `motor_financiero_fund_parameters.csv` | Pesos y momentos analíticos de FG01–FG10. |
| `motor_financiero_return_diagnostics.csv` | Comparación de momentos analíticos y simulados. |
| `motor_financiero_transition_matrix.csv` | Matriz laboral en formato largo. |
| `motor_financiero_state_occupancy.csv` | Ocupación agregada de estados laborales. |
| `motor_financiero_representative_trajectories.csv` | Caminos más cercanos a P10, mediana y P90. |

## Reproducir

Desde la raíz del repositorio:

```powershell
python -m pip install -e .
gemelo-previsional motor-financiero --config config/motor_financiero.json --output-dir examples/motor_financiero
```

Corrida rápida:

```powershell
gemelo-previsional motor-financiero --config config/motor_financiero.json --output-dir tmp/motor-financiero-smoke --paths 40
```

Pruebas específicas:

```powershell
python -m unittest tests.test_financial_engine -v
```

## Criterios de validación

La implementación exige:

1. semilla no negativa y al menos veinte caminos;
2. horizonte entero de meses y unidades UF reales;
3. matriz laboral completa, no negativa y con filas que suman uno;
4. covarianza simétrica y semidefinida positiva;
5. diez carteras completas, no negativas y totalmente invertidas;
6. retornos simples finitos y mayores que −100%;
7. saldos finitos y no negativos;
8. reproducción exacta con igual configuración y semilla;
9. verificación de la identidad contable en las trayectorias representativas;
10. registro explícito de fuentes, correcciones y limitaciones.

## Interpretación correcta

Formulación válida:

> Bajo los supuestos sintéticos versionados, la combinación de estas transiciones laborales y este mercado normal multivariado genera la distribución reportada de saldos.

Formulación inválida:

> Esta es la distribución esperada de las pensiones chilenas o el efecto causal de los Fondos Generacionales.

El paso posterior será comparar políticas usando los mismos caminos laborales y financieros, y luego sustituir o complementar el modelo normal con remuestreo histórico y escenarios de estrés.
