# TradingIA — Resumen consolidado

Actualizado: 2026-09-07. Este documento consolida el estado del repositorio y
los resultados de investigación FX realizados hasta Phase 5E preregistrada.
Es un resumen; los artefactos enlazados conservan el detalle auditable.

## Estado operativo y seguridad

- Enfoque actual: **FX-first / MT5-first**.
- Crypto es únicamente histórico; el punto de referencia es el tag
  `crypto-research-final`.
- LIVE permanece deshabilitado: la política local tiene
  `live.live_trading_enabled: false`; no existe ruta `/v1/live/...`.
- La cuenta utilizada para comprobaciones fue HFM MT5 Demo. Durante estas
  fases no se enviaron órdenes, no se abrieron/cerraron posiciones y no se
  habilitó LIVE.
- El bridge permite superficies demo protegidas para fases futuras, pero este
  trabajo fue exclusivamente de lectura, cálculo local y backtesting.

## Fundación FX — Phase 5A y 5B

Phase 5A estableció la ingesta histórica EURUSD/M15 y la validación de datos.

Phase 5B implementó el motor económico FX independiente:

- Posiciones `LONG`/`SHORT`/`FLAT`, una posición máxima, lotes fijos y
  ejecución causal: señal al cierre de barra *i*, fill en apertura de *i+1*.
- Convención BID/ASK: LONG abre ASK/cierra BID; SHORT abre BID/cierra ASK.
- Costes auditables: spread, slippage, comisión y swap, con la identidad
  `net_pnl = gross_pnl - spread_cost - slippage_cost - commission_cost - swap_cost`.
- PnL EURUSD/USD validado contra el oráculo read-only real de MT5
  `order_calc_profit()` para 0.01 lotes: cuatro casos LONG/SHORT ganancia y
  pérdida coincidieron exactamente (+/- USD 5 para movimientos de 0.0050).
- El bridge filtra barras que MT5 devuelva fuera del intervalo solicitado y
  traduce errores de tick de backend a respuesta segura 502.

Detalles: [PHASE5B_STATUS.md](PHASE5B_STATUS.md).

## Calibración de costes — Phase 5C

El perfil de costes quedó congelado usando EURUSD/M15 de HFM Demo:

| Elemento | Valor |
|---|---|
| Dataset de coste SHA-256 | `0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9` |
| Captura | 2,459 barras, 2026-08-03 a 2026-09-07 14:30 UTC |
| Spread | P95 por hora UTC; 67 puntos a 00, 26 a 01, 16 a 02–22, 31 a 23 |
| Fingerprint spread | `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575` |
| Comisión | `NoCommission` explícito, supuesto de research |
| Swap long | débito USD 8.3/lote/cruce |
| Swap short | USD 0/lote/cruce |
| Triple swap | miércoles (Python weekday 2) |
| Fingerprint no-spread | `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36` |
| Slippage | 1 punto adverso por fill, supuesto conservador |

Detalles: [PHASE5C_STATUS.md](PHASE5C_STATUS.md).

## Dataset de investigación

- Símbolo/timeframe: `EURUSD` / `M15`.
- Intervalo disponible: 2022-09-01 00:00 UTC a 2026-09-04 23:45 UTC.
- Barras: 99,597.
- Dataset SHA-256:
  `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59`.
- Se detectaron 35 gaps inesperados; fueron registrados y nunca rellenados.

Splits congelados:

| Split | Intervalo | Estado |
|---|---|---|
| Development | 2022-09-01 → 2024-08-30 23:45 UTC | Consumido en Phase 5D |
| Validation | 2024-09-02 → 2025-08-29 23:45 UTC | Consumido una vez en Phase 5D |
| Untouched test | 2025-09-01 → 2026-09-04 23:45 UTC | **UNTOUCHED** |

## Phase 5D — Baselines FX

Phase 5D evaluó ocho estrategias simples preregistradas y tres controles con
USD 100 iniciales, 0.01 lotes, P95 horario, 1 punto de slippage, ejecución
siguiente apertura, ventana activa 01:00–19:45 UTC y sin posiciones
intencionales entre 20:00–00:45 UTC.

### Run 1 preservado

Run 1 permitió que la simulación siguiera operando tras equity <= 0. Sus
resultados trade-level negativos permanecen como observaciones reales, pero
las métricas account-level dejaron de ser interpretables. No fue borrado ni
sobrescrito.

### Run 2: política de insolvencia

Run ID: `phase5d_run2_insolvency_policy`.

La corrección metodológica registró `INSOLVENCY` y terminó el backtest en el
primer mark con equity <= 0. No inventa margin-call intrabar ni stop-out de
broker. Si el cierre realiza saldo <= 0, impide una nueva entrada en esa misma
barra. Las métricas indefinidas se escriben como `null`, nunca `NaN`.

Resultados Run 2; P/L es net PnL realizado hasta el mark terminal e `I`
significa insolvencia:

| Variante | Development | Validation | Decisión |
|---|---:|---:|---|
| control-flat | 0, solvente | 0, solvente | CONTROL |
| control-long | -99.14, I 2024-03-22 | -98.80, I 2025-01-02 | CONTROL |
| control-short | -89.87, I 2023-07-12 | -96.39, I 2025-06-26 | CONTROL |
| trend-ema-20-100 | -89.26, I 2022-12-15 | -99.10, I 2025-05-06 | REJECT |
| trend-ema-50-200 | -99.47, I 2022-12-22 | -74.88, solvente | REJECT |
| mean-z-20-2 | -96.32, I 2023-03-10 | -97.03, I 2025-03-14 | REJECT |
| mean-z-40-2 | -99.53, I 2023-04-18 | -97.66, I 2025-06-12 | REJECT |
| momentum-4 | -99.89, I 2022-11-01 | -99.96, I 2024-10-15 | REJECT |
| momentum-16 | -99.02, I 2022-10-13 | -99.57, I 2024-10-18 | REJECT |
| session-breakout-00-06 | -99.05, I 2023-01-23 | -99.86, I 2025-01-29 | REJECT |
| session-breakout-07-10 | -98.90, I 2023-01-19 | -99.82, I 2025-01-17 | REJECT |

Resultado final: **8 REJECT, 0 CANDIDATE**. Ninguna variante de 5D puede
pasar al untouched test. Phase 5D está formalmente cerrada.

Detalles: [PHASE5D_RUN2_RESULTS.md](PHASE5D_RUN2_RESULTS.md),
[PHASE5D_PREREGISTRATION.md](PHASE5D_PREREGISTRATION.md),
[PHASE5D_MULTIPLE_TESTING_LEDGER.md](PHASE5D_MULTIPLE_TESTING_LEDGER.md) y
[PHASE5D_STATUS.md](PHASE5D_STATUS.md).

## Phase 5E — Estado actual: preregistrada, sin performance

Phase 5E es investigación nueva y no intenta reparar post-hoc las estrategias
de 5D. Mantiene exactamente el dataset, costes, tamaño, política de cuenta y
rango test reservado. Se congelaron ocho variantes event-driven y un control:

- `compression-expansion-16-4`, `compression-expansion-24-6`
- `session-range-01-08`, `session-range-02-09`
- `expansion-reversal-32-2p5-2`, `expansion-reversal-48-2p25-4`
- `impulse-continuation-32-2p5-2`, `impulse-continuation-48-2p25-4`
- `control-flat`

El protocolo separa development en inner A (2022-09-01 → 2023-08-31) e
inner B (2023-09-01 → 2024-08-30), usa development agregado, y reserva una
única evaluación validation. El runner rechaza estructuralmente `test` y, por
ahora, bloquea cualquier performance hasta recibir autorización explícita.

Reglas candidatas: solvente; >=30 trades; PnL y expectancy positivos; PF > 1;
drawdown firmado >= -20%; 10 long y 10 short; concentración por trade <=30%;
costes/gross reference PnL <=75% solo si gross reference PnL es positivo;
estabilidad positiva en ambos inner splits y concentración anual positiva <=70%.

Fingerprint preregistro Phase 5E:
`b5359b37c865ecf72666a62aee4d3849b8386ea5eb1b4c4df0d43fb9bf7dcd10`.

Detalles: [PHASE5E_PREREGISTRATION.md](PHASE5E_PREREGISTRATION.md) y
[PHASE5E_MULTIPLE_TESTING_LEDGER.md](PHASE5E_MULTIPLE_TESTING_LEDGER.md).

## Verificación técnica reciente

- Tests FX de Phase 5E más regresiones relacionadas: **28 passed**.
- Pruebas adicionales relevantes de coste, estrategias baselines e insolvencia:
  incluidas en esa ejecución.
- `git diff --check`: aprobado.
- No se hizo push ni commit de los cambios de trabajo actuales.

## Próximo paso autorizado requerido

Phase 5E no debe evaluar development ni validation sin una autorización
explícita posterior. Si se autoriza, el orden será: inner A, inner B,
development agregado, congelación del batch, validation una sola vez y
clasificación; el untouched test seguirá bloqueado.
