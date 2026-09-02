# Laboratorio de investigación y backtesting de estrategias de trading

Infraestructura para investigar estrategias de trading cuantitativo de forma
reproducible, auditable y sin autoengañarse con backtests irreales.

**Estado actual: Fase 1.5 — endurecimiento metodológico.** Ninguna de las
estrategias incluidas se declara rentable. El objetivo de esta fase es
demostrar que el motor de backtesting es correcto y auditable, no encontrar
una estrategia ganadora.

No hay conexión a dinero real ni ejecución de órdenes reales en ningún punto
de este código.

## Arquitectura

```
src/
  data/          # Fuente de datos encapsulada (provider), cache local, split train/val/test
  strategies/    # Estrategias: solo deciden posición deseada (FLAT/LONG) por vela
  backtesting/   # Motor: aplica señales con ejecución en la siguiente vela, fees, slippage
  metrics/       # Funciones puras de métricas de performance
  experiments/   # Orquestación: config -> datos -> split -> backtest -> resultados persistidos
  execution/     # Reservado para paper trading futuro (vacío por ahora)
  cli/           # Interfaz de línea de comandos
configs/         # Configs YAML de experimentos
data/raw/        # Cache local de OHLCV descargado (no versionado en git)
results/         # Carpetas de experimentos generadas (no versionado en git)
tests/           # Tests unitarios con datasets sintéticos de resultado conocido
```

### Principio de diseño: el motor debe ser legible, no solo rápido

`src/backtesting/engine.py` simula vela a vela con un bucle explícito, no
con una vectorización opaca. Es deliberadamente lento comparado con lo que
se podría lograr vectorizando todo el backtest, pero cada trade puede
trazarse exactamente a la vela y precio que lo produjo. Correctitud y
auditabilidad priman sobre velocidad en esta fase.

### Regla anti-lookahead central

Una estrategia decide su posición deseada para la vela `i` usando solo datos
de `df.iloc[:i+1]` (ver `src/strategies/base.py`). El motor de backtesting
**nunca** ejecuta al precio que generó la señal: desplaza la señal una vela
hacia adelante (`shift(1)`) y ejecuta al **open de la vela siguiente**. Esto
ocurre dentro del motor, no en cada estrategia, para que no pueda olvidarse
al añadir una estrategia nueva.

Esto se verificó manualmente comparando trades reales contra los datos
OHLCV crudos (ver sección "Resultados y verificación manual" abajo).

### Modelo de ejecución y supuestos documentados

- Solo dos estados: FLAT (sin posición) y LONG (invertido con
  `position_size_fraction` del equity disponible en el momento de entrada).
  No hay short ni leverage en esta fase.
- Slippage: costo fraccional fijo aplicado en contra del trader — compras al
  `open * (1 + slippage)`, ventas al `open * (1 - slippage)`. Es una
  simplificación (el slippage real depende del tamaño de la orden y la
  profundidad del libro), pero es determinista y documentada.
- Fees: porcentaje del valor nocional, cobrado en la entrada y en la salida.
- No hay fills intrabar: una señal de salida no obtiene un precio mejor
  mirando el high/low de la vela.
- Si al final del dataset queda una posición abierta, se fuerza su cierre al
  `close` de la última vela, para que el equity final esté completamente
  realizado y sea auditable. Esto es una convención de fin de backtest, no
  una regla que aplique durante el resto de la simulación.

### Warm-up de indicadores entre splits

Cada estrategia declara `warmup_bars` (número de velas trailing que necesita
antes de que su indicador deje de ser degenerado/NaN): SMA cross usa
`slow - 1`, momentum usa `lookback`, RSI mean-reversion usa `rsi_period * 4`
(margen documentado para que la suavización EWM de Wilder converja).

El runner (`src/experiments/runner.py`) usa `slice_with_warmup` para que
`validation` pueda tomar prestadas hasta `warmup_bars` velas
**cronológicamente anteriores** de `train`, y `test` de `train+validation`
— nunca de datos posteriores al propio split. Esas velas de warm-up sirven
solo para calentar el indicador: el motor de backtest tiene prohibido abrir,
mantener o cerrar una posición durante ellas (`evaluation_start` en
`BacktestEngine.run`), y quedan excluidas del equity curve y del historial
de trades de ese split. `train` no tiene split anterior del que tomar
contexto, así que sus propias primeras `warmup_bars` velas arrancan en frío,
igual que en la Fase 1 — es inherente a ser el primer período del dataset.

Se verificó explícitamente (`tests/test_warmup.py`) que la señal en las
primeras velas de `validation`/`test` coincide exactamente con la que
produciría ejecutar la estrategia sobre el historial continuo completo
hasta ese instante — nunca con una señal artificialmente fría, y nunca con
una señal influida por datos posteriores al punto evaluado.

### Modo de evaluación de splits: `independent_split_evaluation`

Es el único modo implementado. Cada split arranca FLAT con el capital
inicial completo configurado, independientemente de lo que la estrategia
"venía haciendo" justo antes — el warm-up afecta a la señal, nunca al
estado de portfolio. Cada split fuerza cierre de posición en su propia
última vela. Esto responde a "¿cómo se comporta esta estrategia de forma
independiente en cada uno de estos tres períodos?", no a "¿qué habría hecho
una única ejecución continua de principio a fin?".

Ese segundo enfoque (`continuous_walk_forward`: capital y posición
continúan cronológicamente de un split al siguiente) es un modo futuro,
explícitamente no implementado todavía, documentado en
`src/experiments/runner.py` para que no se confunda accidentalmente con el
modo actual cuando se implemente.

### Validación de datos y de señales

Antes de cada backtest, `src/data/validation.py` valida el OHLCV completo:
columnas requeridas, ausencia de NaN, timestamps estrictamente crecientes
(detecta duplicados), precios positivos, volumen no negativo, y relaciones
high/low válidas respecto a open/close. También detecta huecos temporales
relativos al timeframe declarado; por defecto (`allow_data_gaps: false` en
el config) cualquier hueco detectado hace fallar la validación, porque para
BTC/USDT spot 1h se espera continuidad. Un dataset o mercado que
legítimamente tenga huecos puede declarar `allow_data_gaps: true`
explícitamente en su config.

`BacktestEngine.run` valida además que las señales recibidas sean
exclusivamente FLAT/LONG, sin NaN, y de longitud compatible con los datos —
antes de simular nada.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Descarga de datos

Los datos se descargan de la API pública de Binance (no requiere API key,
solo lee datos de mercado, nunca coloca órdenes) y se cachean localmente en
`data/raw/<SYMBOL>_<timeframe>.parquet`.

```bash
python -m src.cli download-data --symbol BTCUSDT --timeframe 1h --start 2023-01-01 --end 2024-01-01
```

La fuente de datos está encapsulada detrás de la interfaz `DataProvider`
(`src/data/providers.py`). Para usar otra fuente, implementa esa interfaz;
el resto del sistema (loader, splitter, engine, CLI) no cambia.

## Ejecutar un backtest

```bash
python -m src.cli backtest configs/sma_cross.yaml
```

Esto:

1. Carga los datos cacheados para el símbolo/timeframe del config.
2. Los divide cronológicamente en train/validation/test (nunca aleatorio).
3. Ejecuta la estrategia con los mismos parámetros fijos en cada partición.
4. Calcula métricas por partición.
5. Guarda todo en `results/<fecha>_<num>_<estrategia>/`.

Cada carpeta de experimento contiene:

```
config.json           # config completa + hash del dataset + período de datos
metrics.json           # métricas de las 3 particiones juntas
summary.md             # resumen legible
train/  validation/  test/
  trades.csv            # historial de trades
  equity.csv            # equity curve por vela
  metrics.json           # métricas de esa partición
```

## Comparar experimentos

```bash
python -m src.cli compare results/2026-09-02_001_buy_and_hold results/2026-09-02_002_sma_cross
```

Imprime una tabla comparando retorno, número de trades, win rate, profit
factor, drawdown y Sharpe por experimento y partición.

## Crear una estrategia nueva

1. Crea un archivo en `src/strategies/` con una clase que herede de
   `Strategy` (`src/strategies/base.py`) e implemente
   `generate_signals(df) -> pd.Series` devolviendo `FLAT` (0) o `LONG` (1)
   por fila.
2. **La fila `i` solo puede depender de `df.iloc[:i+1]`.** No uses
   `.shift(-1)`, ventanas hacia adelante, ni nada que mire el futuro.
3. Si tu indicador necesita historial trailing (media móvil, RSI, lookback,
   ...), sobreescribe la property `warmup_bars` con el número de velas
   necesario. Si no lo haces, el valor por defecto es 0 y tu estrategia
   arrancará en frío al inicio de cada split — puede seguir siendo correcto
   (no hay lookahead), pero pierdes el contexto de warm-up entre splits.
4. Regístrala en `src/strategies/registry.py`.
5. Añade tests en `tests/test_strategies.py` (incluyendo el test de
   invariancia por truncamiento) y, si declaras `warmup_bars > 0`, añade tu
   estrategia a la lista `STRATEGIES` en `tests/test_warmup.py` para
   verificar que su señal en validation/test coincide con la de ejecución
   continua.
6. Crea un config YAML en `configs/`.

## Interpretación de resultados

- **No mires las métricas de `test` y luego cambies parámetros.** En cuanto
  lo hagas, ese test deja de ser out-of-sample. Ver `RESEARCH_RULES.md`.
- Un número bajo de trades (regla práctica: menos de ~30) hace que win
  rate, profit factor y expectancy no sean estadísticamente confiables; el
  sistema lo marca explícitamente en `notes` dentro de `metrics.json`.
- Cuando una métrica no tiene sentido para los datos disponibles (por
  ejemplo, Sharpe sin varianza suficiente, o retorno anualizado con muy
  pocas velas), la métrica se reporta como `null` con una nota explicando
  por qué, en vez de un número engañoso.
- Compara siempre contra `buy_and_hold` en el mismo período exacto.
- `annualized_return` se calcula a partir del tiempo real transcurrido entre
  el primer y último timestamp del split (no del número de velas dividido
  por una frecuencia nominal), así que sigue siendo correcto aunque falten
  velas.
- `sortino_ratio` usa la definición estándar de Sortino & van der Meer:
  downside deviation es la raíz cuadrática media de `(retorno - MAR)` sobre
  **todas** las velas por debajo del Minimum Acceptable Return (MAR, por
  defecto 0), dividido por el tamaño total de la muestra — no solo por el
  número de velas perdedoras. Un Sharpe o Sortino alto sigue sin implicar
  ventaja real por sí solo: ver regla 7 en `RESEARCH_RULES.md`.

## Limitaciones conocidas

- Solo long/flat: no hay short ni leverage.
- Sin fills intrabar ni simulación de profundidad de libro; el slippage es
  un supuesto fraccional fijo, no un modelo de impacto de mercado.
- Sin ejecución real de órdenes ni paper trading en vivo todavía —
  `src/execution/` está reservado para eso en una fase posterior.
- Sin búsqueda de parámetros (intencional en esta fase, ver
  `RESEARCH_RULES.md`): las estrategias incluidas no fueron optimizadas.
- El motor asume una única posición a la vez sobre un único símbolo; no
  hay soporte de portafolio multi-activo todavía.
- El dataset usado en las demos es un año de velas 1h de BTC/USDT spot
  (2023-01-01 a 2024-01-01); resultados en ese período no generalizan a
  otros períodos o mercados sin volver a testear. Ese dataset tiene además
  un hueco real de una vela (2023-03-24 13:00 UTC) confirmado directamente
  contra la API pública de Binance — no es un artefacto de este código; los
  configs de demo lo declaran explícitamente con `allow_data_gaps: true`.
- Solo se implementa `independent_split_evaluation`; `continuous_walk_forward`
  (capital y posición continuos entre splits) queda documentado como modo
  futuro pero no implementado.
- El slippage y el modelo de gaps son deliberadamente simples; no hay
  simulación de profundidad de libro ni de impacto de mercado.

## Próxima fase (propuesta, no implementada)

- Análisis de sensibilidad de parámetros (perturbar +/-X% cada parámetro y
  ver si el resultado colapsa) antes de considerar cualquier estrategia
  mínimamente robusta.
- Registro estructurado de experimentos fallidos, no solo los prometedores.
- Implementar `continuous_walk_forward` como modo de evaluación alternativo
  y explícito, sin mezclarlo con `independent_split_evaluation`.
- Paper trading en tiempo real sobre `src/execution/`, manteniendo la misma
  separación de responsabilidades (fuente de datos encapsulada, sin lógica
  de decisión en la capa de ejecución).

## Phase 2 — robustness research

Phase 2 is intentionally separate from the normal train/validation/test experiment runner. It adds a locked final holdout, controlled parameter studies, yearly stability reports, fixed-parameter walk-forward evaluation, cost stress, trade-return Monte Carlo diagnostics, and a Donchian-style breakout strategy.

Download the multi-year BTCUSDT 1h cache on a machine with network access:

```bash
./scripts/download_phase2_dataset.sh 2018-01-01 2026-09-02
```

Then run:

```bash
python -m src.cli research configs/research_phase2.yaml
```

The Phase-2 config locks `2025-01-01` onward as `FINAL_HOLDOUT`. The Phase-2 runner refuses to run if `allow_final_holdout_evaluation` is enabled. Reports are written under `research/`; holdout metrics are not generated.

## Phase 2.5: focused breakout robustness

After Phase 2, run the frozen breakout-neighborhood robustness pass without opening FINAL_HOLDOUT:

```bash
python -m src.cli research25 configs/research_phase25.yaml
```

It evaluates exactly 24 pre-registered breakout variants and writes plateau, cost-stress, fixed walk-forward, trade-regime and Monte Carlo reports to `research/phase25/`. The 2025+ final holdout remains blocked by code.
