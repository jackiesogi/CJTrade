#!/usr/bin/env bash
# windows.sh — the pre-registered evaluation windows.
#
# Two kinds, and they answer different questions:
#
#   ROLLING (overlapping, steps 1 month, 182 days each)
#     ./exp/bin/windows.sh is       43 windows, 2021-01-01 .. 2024-07-01
#     ./exp/bin/windows.sh oos      17 windows, 2025-01-01 .. 2026-05-01
#     Shows the full distribution and the worst case, including windows that
#     straddle a turn. Neighbours share 5/6 of their bars, so these are NOT
#     independent tests -- never count them as "17 confirmations".
#
#   SEGMENTS (non-overlapping, printed as "start duration")
#     ./exp/bin/windows.sh is-seg    8 segments of 182d covering 2021-01-01..2024-12-29
#     ./exp/bin/windows.sh oos-seg   4 segments of 170d covering 2025-01-01..2026-11-09
#     ./exp/bin/windows.sh stress-seg 1 segment  of 182d from 2020-03-02
#     Each segment is disjoint, so passing on k of them is k independent
#     pieces of evidence. This is what "stable across 3-5 periods" means.
#
# These lists are FIXED. Editing them to chase a result destroys the only
# thing that makes the holdout number mean anything.
set -euo pipefail

roll () {  # first n
  local first="$1" n="$2" i
  for ((i=0; i<n; i++)); do date -j -v+"${i}"m -f %Y-%m-%d "$first" +%Y-%m-%d; done
}

seg () {   # first n duration   -> "start duration" per line, back to back
  local first="$1" n="$2" dur="$3" i d="$1"
  for ((i=0; i<n; i++)); do
    echo "$d $dur"
    d=$(date -j -v+"${dur}"d -f %Y-%m-%d "$d" +%Y-%m-%d)
  done
}

case "${1:-}" in
  is)          roll 2021-01-01 43 ;;
  oos)         roll 2025-01-01 17 ;;
  stress)      roll 2020-03-01  5 ;;
  is-seg)      seg  2021-01-01  8 182 ;;
  oos-seg)     seg  2025-01-01  4 170 ;;
  stress-seg)  seg  2020-03-02  1 182 ;;
  *) echo "usage: windows.sh is|oos|stress|is-seg|oos-seg|stress-seg" >&2; exit 2 ;;
esac
