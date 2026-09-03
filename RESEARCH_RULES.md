# Reglas metodológicas

Estas reglas existen para evitar autoengañarnos con backtests que parecen
buenos pero no reflejan una ventaja real. Se aplican a todo el trabajo en
este proyecto, no solo al código, y son independientes del mercado
concreto que se esté investigando (crypto, FX, o cualquier otro).

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
El modelo exacto de costes (fee porcentual, spread, comisión fija, swap,
etc.) depende del mercado, pero el principio — nunca evaluar sin costes
realistas — no.

## 4. Registrar también los experimentos fallidos

Un experimento que no funcionó es información. No borres carpetas de
resultados de experimentos negativos; son evidencia de qué no funciona y
evitan repetir la misma idea meses después.

## 5. Comparar siempre contra un benchmark apropiado para el mercado

Toda estrategia activa debe compararse contra un benchmark pasivo
razonable (por ejemplo, buy-and-hold cuando el instrumento lo permite)
en el mismo símbolo, timeframe y período exacto (mismas fechas de
train/validation/test). Superar al benchmark en un período favorable no
es evidencia fuerte de ventaja; no superarlo en absoluto es evidencia
fuerte de que algo anda mal.

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
— no implica necesariamente una búsqueda automática de parámetros.

## 9. No optimizar salvo que esté explícitamente autorizado

Grid search masivo, algoritmos genéticos, machine learning, deep learning,
reinforcement learning, LLMs tomando decisiones de trading, o cualquier
forma de búsqueda automática de parámetros sobre el dataset completo o
sobre test, requieren autorización explícita y su propio diseño
metodológico (multiple-testing, preregistration, etc.) antes de usarse.
El objetivo por defecto es demostrar que el laboratorio produce
resultados correctos, no maximizar una métrica.

## 10. Los splits de datos nunca se mezclan aleatoriamente

`train`, `validation` y `test` son siempre bloques cronológicos contiguos y
no solapados (ver `src/data/splitter.py`). Mezclar aleatoriamente
introduciría información del futuro en el pasado.

## 11. Documentar todo supuesto no obvio

Si una decisión de implementación no es evidente por sí sola (por ejemplo,
cómo se modela el slippage, o qué pasa con una posición abierta al final
del dataset), debe quedar documentada en el código o en el README, no solo
en la cabeza de quien la escribió.

## 12. Warm-up de indicadores no es lo mismo que data leakage

`validation` y `test` pueden usar velas cronológicamente anteriores
(`train`, o `train+validation` respectivamente) únicamente para calentar
indicadores (ver `warmup_bars` en `src/strategies/base.py`). Esto es
correcto y necesario — sin ello, una SMA(100) arrancaría en frío al
principio de cada split y produciría señales artificialmente distintas de
las que produciría en producción. La línea que nunca debe cruzarse: esas
velas de warm-up jamás pueden abrir, mantener ni cerrar una posición, ni
contar en el equity curve, trades o métricas de ese split — si alguna vez lo
hicieran, dejaría de ser una evaluación de split independiente y empezaría a
inflar artificialmente el resultado del split. Ver
`tests/test_warmup.py` para la prueba de que esto se cumple.

## 13. No declarar una estrategia robusta solo porque el modo de evaluación cambió

Corregir un error metodológico (como el warm-up de indicadores) puede hacer
que el resultado de `test` cambie, a veces mejorando. Eso no es evidencia de
que la estrategia sea mejor — es evidencia de que la medición anterior
estaba sesgada. Un resultado post-corrección todavía debe pasar por todas
las demás reglas (comparación con benchmark, número de trades,
sensibilidad de parámetros, etc.) antes de tomarse en serio.

## 14. Preregistrar antes de mirar datos nuevos (forward/holdout)

Cualquier evaluación sobre un período de datos genuinamente nuevo (un
holdout final, una validación forward) requiere congelar de antemano
—antes de mirar el resultado— qué hipótesis/variantes se evalúan y con
qué parámetros. Una vez consumido, ese período no puede usarse otra vez
para seleccionar, ajustar, o rechazar variantes: cualquier idea inspirada
por lo que se observó ahí es post-hoc y necesita su propio período de
evaluación futuro, preregistrado de la misma forma, antes de poder
considerarse validada.

## 15. Contar siempre todas las pruebas realizadas (multiple testing)

Registra el número de familias de hipótesis y variantes de parámetros
evaluadas. Un mejor resultado se interpreta en el contexto de todas las
alternativas probadas, no de forma aislada. Un hallazgo "significativo"
después de escanear muchas variantes/horas/parámetros necesita una
corrección explícita (por ejemplo, Bonferroni) antes de tomarse en serio.

## 16. Preferir regiones de parámetros, no picos aislados

Un resultado con retorno alto en un único punto del espacio de parámetros,
pero con vecinos débiles, es una señal de alerta de sobreajuste, no un
descubrimiento.

## Historial de investigación por mercado

Las reglas específicas de una fase de investigación concreta (por
ejemplo, qué símbolo, qué ventana de datos, qué candidatos exactos se
congelaron) no son metodología universal — son el registro de una
investigación particular. El historial completo de la investigación
crypto (Phase 2 a Phase 4B) y sus reglas específicas de esa época están
preservados en
[`docs/history/crypto/RESEARCH_RULES_CRYPTO_ERA.md`](docs/history/crypto/RESEARCH_RULES_CRYPTO_ERA.md)
y en el estado ejecutable completo bajo el tag Git `crypto-research-final`.
