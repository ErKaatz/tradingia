# Laboratorio de investigación y backtesting de estrategias de trading

Infraestructura para investigar estrategias de trading cuantitativo de forma
reproducible, auditable y sin autoengañarse con backtests irreales.

**Estado actual: fase de infraestructura.** Ninguna de las estrategias
incluidas se declara rentable. El objetivo de esta fase es demostrar que el
motor de backtesting es correcto, no encontrar una estrategia ganadora.

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
3. Regístrala en `src/strategies/registry.py`.
4. Añade un test en `tests/test_strategies.py`, incluyendo el test de
   invariancia por truncamiento (ver ejemplos existentes) que verifica que
   truncar el dataframe no cambia las señales pasadas.
5. Crea un config YAML en `configs/`.

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
  otros períodos o mercados sin volver a testear.

## Próxima fase (propuesta, no implementada)

- Análisis de sensibilidad de parámetros (perturbar +/-X% cada parámetro y
  ver si el resultado colapsa) antes de considerar cualquier estrategia
  mínimamente robusta.
- Registro estructurado de experimentos fallidos, no solo los prometedores.
- Paper trading en tiempo real sobre `src/execution/`, manteniendo la misma
  separación de responsabilidades (fuente de datos encapsulada, sin lógica
  de decisión en la capa de ejecución).
