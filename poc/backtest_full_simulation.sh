#!/usr/bin/env bash

set -e

# ------------------------
# Form: collect params + export env
# (Zenity / Web / CLI — auto-selected; persist handled by FormEngine)
# ------------------------
eval "$(uv run python -c '
from cjtrade.pkgs.ui import FormEngine
e = FormEngine("poc/backtest_full_simulation.toml", renderer="web")
e.print_exports(e.run())
' "$@")"

# ------------------------
# Clean up
# ------------------------
echo > ./llm_report.txt
echo > ./data/arenax_CJ.db
rm -f ./arenax_CJ.json

gnome-terminal() {
    PLATFORM=$(uname)
    if [[ "$PLATFORM" == "Darwin" || -n "$SKIP_DISPLAY" ]]; then
        echo "Stub...... $@"
    else
        command gnome-terminal --zoom=0.8 "$@"
    fi
}

# ------------------------
# Init account
# ------------------------
if [ "$ARENAX_MODE" = "paper" ] || [ "$ARENAX_MODE" = "real" ]; then
    echo "paper / real mode: account state will be synced from real broker, skipping init account generation."
    rm -f "arenax_CJ.json"   # ensure no stale file triggers mock-file path
else
    USERNAME=CJ bash scripts/gen_init_account.sh arenax "$INITIAL_FUND"
    cat arenax_CJ.json
fi

sleep 3

# ------------------------
# Monitoring
# ------------------------
gnome-terminal -- watch -n 10 -d "cat llm_report.txt"

gnome-terminal -- watch -n 2 'sqlite3 -header -column data/arenax_CJ.db --markdown "
SELECT *
FROM orders
ORDER BY updated_at DESC
LIMIT 30;
"'

# ------------------------
# Start system
# ------------------------
export USERNAME=CJ
export CJSYS_STATE_FILE=arenax_CJ.json

if [ "$BROKER" = "arenax" ]; then
    uv run system --broker=arenax --mode="$ARENAX_MODE"
else
    uv run system --broker="$BROKER" --mode=real
fi
