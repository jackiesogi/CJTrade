#!/usr/bin/env bash
# run.sh — one backtest + its insight report, logged as one CSV row.
# This is the ONLY way to run a backtest in this experiment.
#
#   ./exp/bin/run.sh <tag> <symbol> <strategy> <interval> <start> <duration> [params]
#
#   ./exp/bin/run.sh scr01 2317 DonchianBreakoutStrategy 1m 2021-01-01 1461 \
#       'donchian__period:100,risk__max_position_pct:0.5'
#
# Env:
#   BAL          initial balance, default 1000000
#   ARENAX_PORT  default 8802
#   EXPECT_BARS  if set, a different bar count marks the row BAR_MISMATCH
#
# Writes:
#   exp/runs.csv                    one row per run, append-only
#   exp/runs/<tag>/<sid>.insight.md, .insight.json
#
# Why the retry: the first request for a (symbol, interval, range) the broker
# has not served since it last started comes back with zero bars; a retry
# succeeds. A zero-bar run scored as "no trades" is indistinguishable from a
# real result, so a zero-bar run is never reported as ok.
set -uo pipefail

[[ $# -ge 6 ]] || { echo "usage: run.sh <tag> <symbol> <strategy> <interval> <start> <duration> [params]" >&2; exit 2; }
TAG="$1"; SYM="$2"; STRAT="$3"; IV="$4"; START="$5"; DUR="$6"; PARAMS="${7:-}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CSV="$ROOT/exp/runs.csv"
ART="$ROOT/exp/runs/$TAG"
BAL="${BAL:-1000000}"
PORT="${ARENAX_PORT:-8802}"

mkdir -p "$ART"
[[ -f "$CSV" ]] || echo "ts,tag,symbol,strategy,interval,start,duration,balance,params,bars,obs,fills,trips,win_rate,sharpe,sortino,calmar,cagr,vol_ann,mdd,time_in_market,flat_days,longest_dd_days,worst_month,win_month_pct,costs,gross_pnl,net_pnl,final_equity,session,status" > "$CSV"

# A strategy ending in .py is a file you wrote; anything else is one of the six
# built-in names. Both paths use the same engine, bars and cost model, so their
# numbers are comparable with each other.
if [[ "$STRAT" == *.py ]]; then
  MOD=(python "$ROOT/exp/bin/custom_backtest.py" --file "$STRAT")
  ARGS=(--symbol "$SYM" --start "$START" --duration "$DUR" --interval "$IV" --balance "$BAL")
else
  MOD=(python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest)
  ARGS=(--symbol "$SYM" --start "$START" --duration "$DUR" --interval "$IV"
        --balance "$BAL" --strategy "$STRAT" --no-browser)
fi
[[ -n "$PARAMS" ]] && ARGS+=(--params "$PARAMS")

BARS=""; OUT=""; ATTEMPT=0
for ATTEMPT in 1 2 3; do
  OUT=$(ARENAX_PORT="$PORT" uv run "${MOD[@]}" "${ARGS[@]}" 2>&1)
  BARS=$(grep -oE 'Starting run . [0-9]+ bars' <<<"$OUT" | grep -oE '[0-9]+' | head -1)
  [[ -n "$BARS" && "$BARS" != 0 ]] && break
  sleep 3
done

SID=$(grep -oE 'insight [0-9a-f]{8}' <<<"$OUT" | awk '{print $2}' | head -1)

STATUS=ok
if grep -q 'No kbars found' <<<"$OUT" || [[ -z "${BARS:-}" || "$BARS" == 0 ]]; then
  STATUS=NO_KBARS
elif [[ -z "$SID" ]]; then
  STATUS=NO_RESULT
fi

J=""
if [[ "$STATUS" == ok ]]; then
  uv run insight "$SID" --out "$ART" >/dev/null 2>&1
  J=$(ls "$ART"/*_"$SID".insight.json 2>/dev/null | head -1)
  [[ -z "$J" ]] && STATUS=NO_INSIGHT
fi

g () { [[ -n "$J" ]] && jq -r "$1 // \"\"" "$J" 2>/dev/null || echo ""; }

OBS=$(g '.performance.observations')
SHARPE=$(g '.performance.sharpe');      SORTINO=$(g '.performance.sortino')
CALMAR=$(g '.performance.calmar');      CAGR=$(g '.performance.cagr')
VOL=$(g '.performance.volatility_annual'); MDD=$(g '.performance.max_drawdown')
TIM=$(g '.performance.time_in_market');    FLAT=$(g '.performance.flat_periods')
LDD=$(g '.performance.tearsheet.metrics.longest_dd_days')
WORSTM=$(g '.performance.tearsheet.metrics.worst_month')
WINM=$(g '.performance.tearsheet.metrics.win_month')
FILLS=$(g '.activity.fills');           COSTS=$(g '.activity.costs')
TRIPS=$(g '.round_trips.count');        WR=$(g '.round_trips.win_rate')
GROSS=$(g '.round_trips.gross_pnl');    NET=$(g '.run.net_pnl')
EQ=$(g '.run.final_equity')

if [[ "$STATUS" == ok ]]; then
  [[ -z "$SHARPE" || "$SHARPE" == null ]] && STATUS=NO_METRICS
  [[ -n "${EXPECT_BARS:-}" && "$BARS" != "$EXPECT_BARS" ]] && STATUS="BAR_MISMATCH:$BARS"
  [[ "$ATTEMPT" != 1 && "$STATUS" == ok ]] && STATUS="ok(retry$ATTEMPT)"
fi

# Commas inside the params field would break every naive CSV reader, and the
# readers here are awk and column. Semicolons instead; nothing else is quoted.
PARAMS_CSV="${PARAMS//,/;}"
[[ -z "$PARAMS_CSV" ]] && PARAMS_CSV="-"

printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "$(date +%Y-%m-%dT%H:%M:%S)" "$TAG" "$SYM" "$STRAT" "$IV" "$START" "$DUR" "$BAL" "$PARAMS_CSV" \
  "${BARS:-}" "$OBS" "$FILLS" "$TRIPS" "$WR" "$SHARPE" "$SORTINO" "$CALMAR" "$CAGR" "$VOL" \
  "$MDD" "$TIM" "$FLAT" "$LDD" "$WORSTM" "$WINM" "$COSTS" "$GROSS" "$NET" "$EQ" "${SID:-}" "$STATUS" \
  >> "$CSV"

pct () { awk -v v="${1:-}" 'BEGIN{ if (v=="") print "na"; else printf "%+.2f%%", v*100 }'; }
printf '%-8s %-6s %-26s %-3s %s+%-5s bars=%-7s sharpe=%-8s cagr=%-9s mdd=%-9s TiM=%-8s trips=%-5s %s\n' \
  "$TAG" "$SYM" "$STRAT" "$IV" "$START" "$DUR" "${BARS:-0}" "${SHARPE:-na}" \
  "$(pct "$CAGR")" "$(pct "$MDD")" "$(pct "$TIM")" "${TRIPS:-0}" "$STATUS"
