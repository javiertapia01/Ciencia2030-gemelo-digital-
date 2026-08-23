# Hito 2 · Gemelo digital individual estocástico

## Objetivo y alcance

Esta primera versión simula una vida previsional completa desde los 25 hasta los 65 años y compara tres escenarios laborales mediante Monte Carlo. Su pregunta es:

> Manteniendo iguales el perfil inicial, el crecimiento salarial, el mercado y la regla proxy de fondos, ¿cómo cambia la distribución del saldo final cuando cambian las transiciones de la vida laboral?

Es un análisis sintético de escenarios. No calibra todavía las transiciones con HPA, no reconstruye los diez Fondos Generacionales y no predice una pensión ni representa a la población chilena.

## Estados laborales

La cadena de Markov mensual contiene cinco estados antes de la jubilación:

| Estado | Cotiza | Interpretación |
|---|:---:|---|
| `cotizando` | Sí | Empleo formal con aporte obligatorio. |
| `desempleado` | No | Periodo sin empleo formal. |
| `informal` | No | Actividad sin cotización previsional. |
| `licencia` | No | Laguna médica simplificada. |
| `invalidez` | No | Estado absorbente hasta la jubilación. |

La jubilación se trata como el fin determinista del horizonte, no como una transición aleatoria. Solo `cotizando` genera aporte. Esta es una simplificación deliberada: licencias e invalidez reales pueden involucrar coberturas y pagos que deberán incorporarse en una versión posterior.

## Dinámica mensual

Para cada camino simulado y mes:

1. el estado vigente determina si existe cotización;
2. el salario potencial real crece a una tasa anual común;
3. la edad determina el fondo proxy A–E;
4. la cotización y el retorno actualizan el saldo;
5. una extracción uniforme determina el estado del mes siguiente según la matriz del escenario.

La identidad contable es:

\[
B_{i,t+1}=(B_{i,t}+0{,}10\,W_t\,I[S_{i,t}=\text{cotizando}])(1+r_{F(t),t})
\]

Los tres escenarios usan los mismos números aleatorios (*common random numbers*) y el mismo mercado determinista. Esto reduce ruido al compararlos y aísla el efecto de las probabilidades laborales.

El identificador `draw_id` empareja el mismo flujo uniforme entre escenarios. Además de comparar sus distribuciones, el análisis calcula para cada extracción la brecha frente a la trayectoria estable sometida al mismo flujo aleatorio.

## Escenarios

| Escenario | Propósito |
|---|---|
| Estable | Alta permanencia en empleo formal y episodios breves de desempleo o licencia. |
| Intermitente | Mayor entrada y persistencia en desempleo e informalidad. |
| Adverso | Lagunas frecuentes, informalidad prolongada y mayor riesgo ilustrativo de invalidez. |

Las probabilidades completas están en `config/hito2.json` y se copian a `hito2_transition_matrices.csv`. Son supuestos transparentes para sensibilidad, no parámetros estimados. Cada fila se valida para que tenga probabilidades no negativas que sumen uno, y `invalidez` debe ser absorbente.

## Perfil y mercado comunes

- edad inicial: 25 años;
- jubilación: 65 años;
- horizonte: 480 meses;
- salario inicial: 40 UF mensuales;
- crecimiento salarial real: 1% anual;
- saldo inicial: 10 UF;
- cotización: 10% del salario cuando el estado es `cotizando`;
- regla de fondos: A antes de 35, B entre 35–44, C entre 45–54, D entre 55–64 y E desde 65;
- mercado: trayectoria sintética determinista compartida por todos los caminos.

## Monte Carlo y resultados

La configuración base ejecuta 2.000 caminos por escenario con semilla 2030. Se reportan:

- saldo final medio, desviación estándar, P10, mediana y P90;
- contribuciones totales y densidad de cotización;
- brecha de la mediana frente al escenario estable;
- mediana de las brechas pareadas y fracción de extracciones bajo su contraparte estable;
- fracción de caminos bajo la mediana estable;
- ocupación agregada de cada estado;
- una trayectoria completa por escenario, elegida por cercanía a la mediana.

La trayectoria representativa no se selecciona por conveniencia: se elige mecánicamente como el camino cuyo saldo final está más cerca de la mediana del escenario.

## Reproducir

Desde la raíz del repositorio:

```powershell
python -m pip install -e .
gemelo-previsional hito2 --config config/hito2.json --output-dir examples/hito2
```

Para una corrida rápida de verificación:

```powershell
gemelo-previsional hito2 --config config/hito2.json --output-dir tmp/hito2-smoke --paths 40
```

## Criterios de validación

La implementación exige:

1. al menos tres escenarios;
2. matrices completas, finitas, no negativas y con filas que sumen uno;
3. invalidez absorbente;
4. horizonte entero de meses y término exacto en la edad de jubilación;
5. saldos finitos y no negativos;
6. reproducibilidad exacta con la misma semilla;
7. reproducción exacta del saldo final de cada trayectoria representativa.

## Qué puede y qué no puede afirmarse

Formulación válida:

> Bajo estos supuestos sintéticos, las trayectorias con más lagunas producen esta distribución de densidad de cotización y saldo final frente al escenario estable.

Formulación inválida:

> Estas son las pensiones que obtendrán las personas chilenas o las probabilidades reales de desempleo, informalidad, licencia e invalidez.

## Próximas mejoras

1. estimar desde HPA la transición binaria entre cotizar y no cotizar, separando calibración y validación;
2. usar fuentes externas para distinguir las causas de las lagunas;
3. incorporar cotizaciones o coberturas durante licencias e invalidez;
4. modelar incertidumbre salarial y de mercado;
5. sustituir la proxy A–E por los diez Fondos Generacionales cuando existan parámetros defendibles;
6. escalar las vidas sintéticas al nivel AFP del tercer hito.
