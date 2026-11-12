#!/usr/bin/env bash
# report.sh — read exp/runs.csv back.
#
#   ./exp/bin/report.sh                 every run, newest last
#   ./exp/bin/report.sh scr01           only rows tagged scr01
#   ./exp/bin/report.sh --pass          only rows that clear every acceptance gate
#   ./exp/bin/report.sh --bad           only rows that did not produce a result
#
# Gates (PROTOCOL 0.1 minimum): sharpe >= 1.0, cagr >= 0.05, time_in_market <= 0.20.
# These are the full-period gates only. Passing them is NOT acceptance -- the
# stability requirement in PROTOCOL 0.2 is judged across segments, which this
# cannot see from one row.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CSV="$ROOT/exp/runs.csv"
[[ -f "$CSV" ]] || { echo "no runs yet: $CSV" >&2; exit 1; }

COLS='$2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7"\t"$9"\t"$10"\t"$13"\t"$15"\t"$18"\t"$20"\t"$21"\t"$30"\t"$31'
HDR="tag\tsym\tstrategy\tiv\tstart\tdur\tparams\tbars\ttrips\tsharpe\tcagr\tmdd\tTiM\tsid\tstatus"

case "${1:-}" in
  --pass) FILTER='$15+0>=1.0 && $18+0>=0.05 && $21+0<=0.20 && $31 ~ /^ok/' ;;
  --bad)  FILTER='$31 !~ /^ok/' ;;
  "")     FILTER='NR>1' ;;
  *)      FILTER="\$2==\"$1\"" ;;
esac

{ printf "$HDR\n"; awk -F, "NR>1 && ($FILTER) {print $COLS}" "$CSV"; } | column -t -s$'\t'
