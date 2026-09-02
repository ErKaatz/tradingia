# Reglas metodológicas

Estas reglas existen para evitar autoengañarnos con backtests que parecen
buenos pero no reflejan una ventaja real. Se aplican a todo el trabajo en
este proyecto, no solo al código.

## 1. Nunca evaluar una estrategia basándose solamente en train

`train` sirve para desarrollar la idea y ajustar la implementación.
`validation` sirve para elegir entre variantes o detectar overfitting
grosero. `test` es la única partición que se acerca a una estimación
honesta de comportamiento futuro, y solo si se respeta la regla 2.

## 2. Nunca modificar parámetros después de mirar `test` y seguir llamándolo out-of-sample

En cuanto se mira el resultado de `test` y se cambia cualquier parámetro,
regla, o umbral de la estrategia, ese `test` queda "quemado": ya no es
out-of-sample para esa estrategia. Si se quiere seguir iterando, hay que
usar un período de test nuevo (más datos, o un período distinto) o aceptar
que la siguiente evaluación en ese mismo test es solo informativa, no una
prueba de generalización.

Práctica recomendada: decide y congela los parámetros usando solo
train/validation. Corre test una única vez por versión de la estrategia.

## 3. Incluir siempre fees y slippage

Ningún backtest de este proyecto debe ejecutarse con fees o slippage en
cero, salvo que el objetivo explícito sea depurar el motor mismo. Una
estrategia que solo es rentable sin fees no es una estrategia rentable.

## 4. Registrar también los experimentos fallidos

Un experimento que no funcionó es información. No borres carpetas de
`results/` de experimentos negativos; son evidencia de qué no funciona y
evitan repetir la misma idea meses después.

## 5. Comparar siempre contra buy-and-hold

Toda estrategia activa debe compararse contra `buy_and_hold` en el mismo
símbolo, timeframe y período exacto (mismas fechas de train/validation/test).
Superar a buy-and-hold en un mercado alcista no es evidencia fuerte de
ventaja; no superarlo en absoluto es evidencia fuerte de que algo anda mal.

## 6. Desconfiar de estrategias con pocos trades

Con menos de ~30 trades, win rate, profit factor y expectancy tienen
demasiada varianza para ser confiables — un par de trades distintos pueden
cambiar la conclusión por completo. El sistema marca esto automáticamente
en `metrics.json` (`notes`), pero la responsabilidad de no ignorar la nota
es humana.

## 7. Un Sharpe alto no implica necesariamente una ventaja real

Un Sharpe (o Sortino) alto puede deberse a:

- Un período de mercado favorable no representativo (ej. un solo tramo
  alcista fuerte).
- Pocos trades con una cola de resultados aún no observada.
- Errores metodológicos (lookahead, fees mal aplicados, mirar el futuro sin
  darse cuenta) que inflan el resultado artificialmente.

Un Sharpe alto es una pista para investigar más, no una conclusión.

## 8. Probar sensibilidad de parámetros antes de considerar una estrategia robusta

Antes de tomar en serio cualquier resultado, perturbar los parámetros
principales (por ejemplo, `fast`/`slow` en un cruce de medias) en un rango
razonable alrededor del valor usado y verificar que el resultado no colapsa
ante cambios pequeños. Una estrategia cuyo resultado depende de un valor de
parámetro muy específico probablemente está sobreajustada a ese período de
datos, no capturando un efecto real. Esto es una revisión manual/cualitativa
en esta fase — no implica una búsqueda automática de parámetros (ver
regla 9).

## 9. No optimizar todavía

Explícitamente fuera de alcance en esta fase del proyecto: grid search
masivo, algoritmos genéticos, machine learning, deep learning, reinforcement
learning, LLMs tomando decisiones de trading, o cualquier forma de búsqueda
automática de parámetros sobre el dataset completo o sobre test. El objetivo
actual es demostrar que el laboratorio produce resultados correctos, no
maximizar una métrica.

## 10. Los splits de datos nunca se mezclan aleatoriamente

`train`, `validation` y `test` son siempre bloques cronológicos contiguos y
no solapados (ver `src/data/splitter.py`). Mezclar aleatoriamente
introduciría información del futuro en el pasado.

## 11. Documentar todo supuesto no obvio

Si una decisión de implementación no es evidente por sí sola (por ejemplo,
cómo se modela el slippage, o qué pasa con una posición abierta al final
del dataset), debe quedar documentada en el código o en el README, no solo
en la cabeza de quien la escribió.
