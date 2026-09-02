#!/usr/bin/env bash
# Downloads the small demo dataset used by the example configs in configs/.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m src.cli download-data --symbol BTCUSDT --timeframe 1h --start 2023-01-01 --end 2024-01-01
