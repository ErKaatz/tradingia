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

## 12. Warm-up de indicadores no es lo mismo que data leakage

`validation` y `test` pueden usar velas cronológicamente anteriores
(`train`, o `train+validation` respectivamente) únicamente para calentar
indicadores (ver `warmup_bars` en `src/strategies/base.py`). Esto es
correcto y necesario — sin ello, una SMA(100) arrancaría en frío al
principio de cada split y produciría señales artificialmente distintas de
las que produciría en producción. La línea que nunca debe cruzarse: esas
velas de warm-up jamás pueden abrir, mantener ni cerrar una posición, ni
contar en el equity curve, trades o métricas de ese split — si alguna vez lo
hicieran, dejaría de ser `independent_split_evaluation` y empezaría a
inflar artificialmente el resultado del split. Ver
`tests/test_warmup.py` para la prueba de que esto se cumple.

## 13. No declarar una estrategia robusta solo porque el modo de evaluación cambió

Corregir un error metodológico (como el warm-up de indicadores) puede hacer
que el resultado de `test` cambie, a veces mejorando. Eso no es evidencia de
que la estrategia sea mejor — es evidencia de que la medición anterior
estaba sesgada. Un resultado post-corrección todavía debe pasar por todas
las demás reglas (comparación con buy-and-hold, número de trades,
sensibilidad de parámetros, etc.) antes de tomarse en serio.

## Phase 2 additions — registered before multi-year results

14. **FINAL_HOLDOUT is locked.** Data from 2025-01-01 onward is not used to select, tune, reject, compare, or refine strategies during Phase 2. `allow_final_holdout_evaluation` remains false and the runner refuses Phase-2 execution if it is enabled.
15. **Count every test.** Record the number of hypothesis families and total parameter variants evaluated. A best result is interpreted in the context of all alternatives tried (multiple-testing risk).
16. **Prefer parameter regions, not isolated peaks.** An isolated high-return parameter set with weak neighbors is a robustness warning, not a discovery.
17. **Stress without retuning.** Cost stress and fixed-parameter walk-forward tests do not trigger parameter changes inside the same evaluation cycle.
18. **Failed experiments remain visible.** Negative or inconclusive hypotheses are logged rather than deleted or silently redefined.
19. **No profitability language in Phase 2.** Allowed labels are `REJECTED`, `PROMISING BUT UNPROVEN`, and `NEEDS MORE DATA/TESTING` only.

## Phase 2.5 — frozen breakout robustness study

- The Phase-2.5 grid is frozen before its results are inspected: entry lookback `[96,120,144,168,192,240]` and exit lookback `[36,48,60,72]`.
- Do not refine the grid after seeing Phase-2.5 results. A later refinement would be a new hypothesis family / research phase and must be counted as additional multiple testing.
- A local parameter plateau is evidence of robustness only when neighboring settings also behave reasonably; a single spike is not a candidate.
- All 24 Phase-2.5 variants receive identical cost-stress scenarios. Stress testing is not restricted to variants chosen after ranking.
- Entry-time regime labels use only trailing information: 90-day return for trend and 30-day realized volatility for volatility. Regime labels are diagnostics only and may not alter trades in Phase 2.5.
- The stricter Phase-2.5 triage requires long-horizon coverage, at least 60% positive calendar years, local plateau support, survival under the extreme registered cost scenario, and either excess return or at least 20 percentage points of max-drawdown reduction versus Buy & Hold.
- `PROMISING BUT UNPROVEN` remains a research triage label, never a claim of future profitability.
- FINAL_HOLDOUT from 2025-01-01 remains locked throughout Phase 2.5.

## Final holdout opening — preregistered decision (2026-09-02)

The 2025+ final holdout is authorized to be opened exactly once for two frozen breakout candidates only:

- Breakout 168/60
- Breakout 168/72

This consumes the holdout for **both** configurations. No third parameter set may be tested on 2025+ and no tuning decision may subsequently describe 2025+ as untouched out-of-sample evidence. Pre-2025 rows are permitted only as trailing indicator warm-up; the portfolio starts FLAT at the holdout boundary. Cost stress A-E may be calculated for these same two frozen candidates, but must not be used to search new parameters.

## Post-holdout diagnostics

Once the 2025+ final holdout has been opened, it is consumed forever for the tested family. Diagnostic analysis of that period may be used to generate new hypotheses, but any threshold, filter, stop, confirmation rule, regime rule, or parameter inspired by those diagnostics is post-hoc. It must not be described as out-of-sample evidence and must be validated only on genuinely future forward/paper data.

## Phase 3 — forward-only hypotheses after consumed holdout

- The 2025-01-01 through 2026-09-02 period is permanently consumed and may not be presented as fresh out-of-sample evidence again.
- Phase-3 forward evaluation begins at **2026-09-03 00:00 UTC**.
- Exactly four hypotheses are preregistered: baseline breakout 168/60, baseline breakout 168/72, 168/60 with fixed 24h confirmation, and 168/60 with an adaptive trailing-volatility gate.
- The 24h confirmation and volatility-gate ideas were motivated by post-holdout diagnostics and are therefore **post-hoc hypotheses**, not validated improvements.
- No parameter grid, threshold search, or retroactive selection is allowed on 2025-2026 for these hypotheses.
- Success/failure of Phase 3 must be judged only from forward/paper observations dated 2026-09-03 or later.

## POST-HOC / HOLDOUT ALREADY CONSUMED — family comparison

Only breakout was carried to the final holdout, because it was the most promising family during Phase 2/2.5 research. `src/research/post_holdout_family_comparison.py` retrospectively evaluates the OTHER Phase-2-registered families (sma_cross, momentum, mean_reversion) against the same already-consumed 2025-01-01 to 2026-09-02 period, to understand whether the regime shift that hurt breakout was breakout-specific or broader.

- This is **not** a new holdout and **not** out-of-sample evidence. Every output is labeled `POST-HOC / HOLDOUT ALREADY CONSUMED`.
- Only configurations already registered in Phase 2 research are evaluated (read verbatim from `research/parameter_studies/<family>.csv`); no new SMA pair, momentum lookback, or RSI threshold may be introduced under this label.
- Breakout is not re-run: its recent-period numbers are read from the already-consumed `research/final_holdout/` artifacts, never from a fresh backtest.
- The recent window is hardcoded to exactly `[2025-01-01, 2026-09-02]`, matching the final holdout; the module refuses to run if a config tries to change it.
- Allowed classification labels are descriptive only: `RECENTLY RESILIENT`, `RECENTLY DEGRADED`, `CONSISTENTLY WEAK`, `REGIME-SENSITIVE`, `INCONCLUSIVE`. Never `PROVEN`, `PROFITABLE`, or `OUT-OF-SAMPLE WINNER`.
- Any hypothesis generated from this comparison (see `research/post_holdout_family_comparison/HYPOTHESES_POST_HOC.md`) is post-hoc by construction and may only earn evidence from genuinely future data, following the same preregister-before-look discipline as Phase 3. It does not amend Phase 3's existing preregistration.
- Phase 3's forward preregistration (`PHASE3_FORWARD.md`, `src/forward/`, `src/strategies/breakout_forward.py`) is a separate, frozen surface and is never read, imported, or modified by this comparison.

## Phase 3B — POST-HOC regime research

`src/research/regime_study.py` investigates whether causal, trailing-only regime features (realized volatility, ATR, ADX, SMA slope, autocorrelation, Kaufman efficiency ratio, range compression, directional persistence, pct-positive-bars) explain when a trend/breakout strategy should not be traded. It does not search new strategy parameters, does not grid-search thresholds, and uses no machine learning (no clustering, no decision trees, no random forest/XGBoost, no Optuna).

- Every output is labeled `POST-HOC REGIME RESEARCH / NOT OUT-OF-SAMPLE VALIDATION`. 2025-2026 remains already-consumed data throughout.
- Every feature is trailing-only and verified truncation-invariant (`tests/test_regime_features.py`); regime labels never use future information, manual labeling, or subsequent performance to define a regime.
- Winner/loser separation (Cohen's d, Mann-Whitney U, univariate AUC) is exploratory: a feature is never declared predictive from a p-value alone, sample size is always reported, and an effect must survive a documented filter (coherent mechanism, visible research-vs-recent difference, not single-year-dependent, adequate trade count, not a duplicate transformation of another feature) before it can support a hypothesis — see `research/regime_study/hypotheses.md` for features considered and explicitly rejected.
- At most 3 forward hypotheses may be formulated per run (`MAX_HYPOTHESES`, enforced at import time); a third is never forced just to fill the quota if no candidate clears the filter.
- Any exploratory simulation used to sanity-check a hypothesis is limited to exactly one variant (no grid, no iterating toward a better result), uses a threshold policy that is either self-relative (a trailing statistic of the feature's own history) or an external literature-standard value — never a number fit to 2025-2026 — and always reports gate impact (% time blocked, trades/winners/losers avoided, exposure change) alongside return, so a filter cannot look good purely by blocking almost everything.
- None of these hypotheses are validated by this phase. They require their own separate forward preregistration (following Phase 3's discipline) before any evidentiary weight can be assigned to them.
- Phase 3's forward preregistration (`PHASE3_FORWARD.md`, `src/forward/`, `src/strategies/breakout_forward.py`, `configs/forward_validation.yaml`) is a separate, frozen surface. `src/research/phase3_guard.py`'s `assert_phase3_intact()` is called before and after every Phase 3B run and raises immediately on any mismatch (changed frozen start date, changed variant names, changed file content, or a missing guarded file).

## Phase 4A — POST-HOC short-horizon research

- Every Phase-4A historical result is labeled `POST-HOC SHORT-HORIZON RESEARCH / NOT OUT-OF-SAMPLE VALIDATION`. The 2018-2024 and 2025-2026 samples are both already observed.
- Phase 4A is limited to BTCUSDT 15m and 1h. Other timeframes require a separately declared phase; they may not be added opportunistically after looking at results.
- The strategy variants are frozen in `src/research/short_horizon_study.py::FROZEN_VARIANTS`. No optimizer, adaptive parameter search, machine learning, shorting, or leverage is permitted in this phase.
- All frozen variants receive the same four execution-cost scenarios. A variant is not `INTERESTING POST-HOC` unless its net expectancy remains positive under both BASE and CONSERVATIVE costs and it has adequate trade count.
- Spread is modeled as an additive component of effective slippage because the frozen engine exposes one adverse execution-price adjustment. Maker fills are not assumed; short-horizon tests use taker execution.
- Gross-vs-net, fee, spread/slippage, turnover, MAE/MFE, annual, quarterly and cross-timeframe reports must remain visible. An apparent edge that is mostly execution-cost drag is not promoted.
- Time-of-day analysis is descriptive only and cannot become a trading rule inside this phase. Multiple comparisons are explicitly reported/corrected.
- Parameter robustness is judged across the already-frozen variants; no neighboring parameter is created after results are seen to rescue a family.
- Monte Carlo and moving-block bootstrap are diagnostics, not proof of future profitability. Their limitations remain explicit.
- Allowed Phase-4A classifications are `REJECTED`, `INTERESTING POST-HOC`, `COST-SENSITIVE`, `REGIME-SENSITIVE`, and `INSUFFICIENT EVIDENCE` only.
- At most three frozen variants may be proposed for a future forward phase. Phase 4A does not create that forward phase; any candidate must be preregistered separately before it can receive future evidence.
- Phase 3's existing forward preregistration is immutable. Phase 4A fingerprints and verifies the guarded Phase-3 files before and after running and aborts on any mismatch.
