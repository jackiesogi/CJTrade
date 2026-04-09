#!/bin/bash

function read_arenax_mode() {
    read -p "Enter ArenaX mode (default: hist): " input
    if [ -z "$input" ]; then
        echo "No mode provided, defaulting to hist"
        export ARENAX_MODE=hist
    else
        export ARENAX_MODE=$input
    fi
}

function read_watch_list() {
    read -p "Enter watch list (comma-separated, e.g., 0050,2330,2357,2317): " input
    if [ -z "$input" ]; then
        echo "No watch list provided, defaulting to 1234"
        export CJSYS_WATCH_LIST=1234
    else
        export CJSYS_WATCH_LIST=$input
    fi
}

function read_initial_fund() {
    read -p "Enter initial fund (default: 500000): " input
    if [ -z "$input" ]; then
        echo "No initial fund provided, defaulting to 500000"
        export INITIAL_FUND=500000
    else
        export INITIAL_FUND=$input
    fi
}

function read_duration_days() {
    read -p "Enter duration in days (default: 5): " input
    if [ -z "$input" ]; then
        echo "No duration provided, defaulting to 5 days"
        export DURATION_DAYS=5
    else
        export DURATION_DAYS=$input
    fi
}

if [ "$1" == "default" ]; then
    export CJSYS_WATCH_LIST=1234
    export INITIAL_FUND=500000
    export DURATION_DAYS=5
    export ARENAX_MODE=hist
else
    read_watch_list
    read_initial_fund
    read_duration_days
    read_arenax_mode
fi

# Clean up
echo > ./llm_report.txt
echo > ./data/arenax_CJ.db
rm -f ./arenax_CJ.json

gnome-terminal() {
    command gnome-terminal --zoom=0.8 "$@"
}

# Validate initial fund equals 500,000
USERNAME=CJ bash scripts/gen_init_account.sh arenax $INITIAL_FUND
cat arenax_CJ.json

sleep 3

# Open up standalone terminal app to monitor LLM's response
gnome-terminal -- watch -n 10 -d "cat llm_report.txt"

# Open up SQLiteStudio to monitor order history
# /home/jck/SQLiteStudio/sqlitestudio ./data/arenax_CJ.db &
gnome-terminal -- watch -n 2 'sqlite3 -header -column data/arenax_CJ.db --markdown "
SELECT *
FROM orders
ORDER BY updated_at DESC
LIMIT 30;
"'

# Start!
# USERNAME=CJ WATCH_LIST=0050,2330,2357,2317 uv run system --broker=arenax
USERNAME=CJ \
CJSYS_STATE_FILE=arenax_CJ.json \
CJSYS_BACKTEST_DURATION_DAYS=$DURATION_DAYS \
uv run system --broker=arenax --mode=$ARENAX_MODE
