#!/usr/bin/env bash

set -e

CONFIG_DIR="$HOME/.config/cjsys"
mkdir -p "$CONFIG_DIR"

LAST_FILE="$CONFIG_DIR/last_watch_list"

DEFAULT_WATCH_LIST="1234"
DEFAULT_FUND=500000
DEFAULT_DAYS=5
DEFAULT_MODE="backtest"

# ------------------------
# Load last used
# ------------------------
if [ -f "$LAST_FILE" ]; then
    LAST_USED=$(cat "$LAST_FILE")
fi

# ------------------------
# Parse CLI args
# ------------------------
WATCH_LIST=""
INITIAL_FUND=""
DURATION_DAYS=""
ARENAX_MODE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --watch-list)
            WATCH_LIST="$2"
            shift 2
            ;;
        --fund)
            INITIAL_FUND="$2"
            shift 2
            ;;
        --days)
            DURATION_DAYS="$2"
            shift 2
            ;;
        --mode)
            ARENAX_MODE="$2"
            shift 2
            ;;
        --default)
            WATCH_LIST="$LAST_USED"
            INITIAL_FUND=$DEFAULT_FUND
            DURATION_DAYS=$DEFAULT_DAYS
            ARENAX_MODE=$DEFAULT_MODE
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# ------------------------
# Interactive fallback
# ------------------------
if [ -z "$WATCH_LIST" ]; then
    read -p "Enter watch list (comma-separated): " input
    if [ -n "$input" ]; then
        WATCH_LIST="$input"
    elif [ -n "$LAST_USED" ]; then
        echo "Using last used: $LAST_USED"
        WATCH_LIST="$LAST_USED"
    else
        echo "Using default: $DEFAULT_WATCH_LIST"
        WATCH_LIST="$DEFAULT_WATCH_LIST"
    fi
fi

if [ -z "$INITIAL_FUND" ] && [ "$ARENAX_MODE" != "paper" ]; then
    read -p "Enter initial fund (default: $DEFAULT_FUND): " input
    INITIAL_FUND=${input:-$DEFAULT_FUND}
fi

if [ -z "$DURATION_DAYS" ]; then
    read -p "Enter duration days (default: $DEFAULT_DAYS): " input
    DURATION_DAYS=${input:-$DEFAULT_DAYS}
fi

if [ -z "$ARENAX_MODE" ]; then
    read -p "Enter mode (default: $DEFAULT_MODE): " input
    ARENAX_MODE=${input:-$DEFAULT_MODE}
fi

# ------------------------
# Persist last used
# ------------------------
echo "$WATCH_LIST" > "$LAST_FILE"

# ------------------------
# Export env
# ------------------------
export CJSYS_WATCH_LIST="$WATCH_LIST"
export INITIAL_FUND
export DURATION_DAYS
export ARENAX_MODE

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
USERNAME=CJ \
CJSYS_STATE_FILE=arenax_CJ.json \
CJSYS_BACKTEST_DURATION_DAYS="$DURATION_DAYS" \
uv run system --broker=arenax --mode="$ARENAX_MODE"
