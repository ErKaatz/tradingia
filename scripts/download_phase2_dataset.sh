#!/usr/bin/env bash
set -euo pipefail
# Download the full research+locked-holdout history. The research runner will
# use only rows before 2025-01-01; newer rows remain locked for a later phase.
START="${1:-2018-01-01}"
END="${2:-$(date -u +%Y-%m-%d)}"
python -m src.cli download-data --symbol BTCUSDT --timeframe 1h --start "$START" --end "$END"
