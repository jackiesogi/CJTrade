#!/usr/bin/env bash
# prewarm.sh — pull the whole experiment window into the local price DB.
#
#   ./exp/bin/prewarm.sh 1m 2317 [2330 ...]
#
# One process per (symbol, year) slice, because repeated get_kbars() calls in
# one process were observed to make later calls return 0 bars for ranges that
# have complete data.
#
# Sinopac caps a kbars request at 30 days and the market-data rate at 50 calls
# per 10s; ArenaX splits each slice into 28-day chunks, so a year is ~13 calls.
# The sleep between slices keeps the average well under the cap.
set -uo pipefail

TF="$1"; shift
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG="$ROOT/exp/prewarm.log"
PORT="${ARENAX_PORT:-8802}"
SLEEP="${PREWARM_SLEEP:-2}"

SLICES=(
  "2020-03-02 2021-01-01"
  "2021-01-01 2022-01-01"
  "2022-01-01 2023-01-01"
  "2023-01-01 2024-01-01"
  "2024-01-01 2025-01-01"
  "2025-01-01 2026-01-01"
  "2026-01-01 2026-11-12"
)

mkdir -p "$ROOT/exp"
for SYM in "$@"; do
  for S in "${SLICES[@]}"; do
    set -- $S
    OUT=$(ARENAX_PORT="$PORT" uv run python "$ROOT/exp/bin/prewarm_one.py" \
            "$SYM" "$TF" "$1" "$2" 2>&1 | grep -E 'bars=|ERROR' | tail -1)
    echo "$(date +%H:%M:%S) $OUT" | tee -a "$LOG"
    sleep "$SLEEP"
  done
done
