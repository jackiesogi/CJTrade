#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

CONFIG_DIR="$HOME/.config/cjsys"
mkdir -p "$CONFIG_DIR"

LAST_FILE="$CONFIG_DIR/last_watch_list"

DEFAULT_WATCH_LIST="1234"
DEFAULT_FUND=500000
DEFAULT_DAYS=365
DEFAULT_INTERVAL="1d"
DEFAULT_MODE="hist"

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
INTERVAL=""
PARAMS=""
ARENAX_MODE=""
START_DATE=""
SHOW_PARAMS=0

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
        --start)
            START_DATE="$2"
            shift 2
            ;;
        --days)
            DURATION_DAYS="$2"
            shift 2
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --params)
            PARAMS="$2"
            shift 2
            ;;
        --show-params)
            SHOW_PARAMS=1
            shift
            ;;
        --mode)
            ARENAX_MODE="$2"
            shift 2
            ;;
        --default)
            WATCH_LIST="$LAST_USED"
            INITIAL_FUND=$DEFAULT_FUND
            DURATION_DAYS=$DEFAULT_DAYS
            INTERVAL=$DEFAULT_INTERVAL
            ARENAX_MODE=$DEFAULT_MODE
            shift
            ;;
        --compare)
            COMPARE_MODE=1
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

if [ -z "$INITIAL_FUND" ]; then
    read -p "Enter initial fund (default: $DEFAULT_FUND): " input
    INITIAL_FUND=${input:-$DEFAULT_FUND}
fi

if [ -z "$START_DATE" ]; then
    read -p "Enter start date (YYYY-MM-DD, default: today): " input
    START_DATE=${input:-$(date +%Y-%m-%d)}
fi

if [ -z "$DURATION_DAYS" ]; then
    read -p "Enter duration days (default: $DEFAULT_DAYS): " input
    DURATION_DAYS=${input:-$DEFAULT_DAYS}
fi

if [ -z "$INTERVAL" ]; then
    read -p "Enter interval (1m/5m/1h/1d, default: $DEFAULT_INTERVAL): " input
    INTERVAL=${input:-$DEFAULT_INTERVAL}
fi

if [ -z "$ARENAX_MODE" ]; then
    read -p "Enter mode (default: $DEFAULT_MODE): " input
    ARENAX_MODE=${input:-$DEFAULT_MODE}
fi

if [ -z "$COMPARE_MODE" ]; then
    read -p "Run in compare mode? (y/N): " input
    if [[ "$input" =~ ^[Yy]$ ]]; then
        COMPARE_MODE=1
    else
        COMPARE_MODE=0
    fi
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
export INTERVAL
export PARAMS
export ARENAX_MODE
export COMPARE_MODE

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
function cleanup() {
    if [ -n "$ARENAX_PID" ]; then
        echo -e "\n${YELLOW}Stopping ArenaX broker server (PID: $ARENAX_PID)...${NC}"
        kill $ARENAX_PID 2>/dev/null || true
    fi
}

function ping_server_backend() {
    local url="http://127.0.0.1:8801/health"
    local response
    response=$(curl -s --max-time 3 "$url" 2>/dev/null) || return 1
    if [[ $(echo "$response" | jq -r '.running' 2>/dev/null) == "true" ]]; then
        return 0
    else
        return 1
    fi
}

if ! ping_server_backend > /dev/null; then
    echo "Starting ArenaX broker server..."
    uv run arenaxd --backend=$ARENAX_MODE > /dev/null 2>&1 &
    ARENAX_PID=$!

    echo -n "Waiting for server to be ready..."
    for i in {1..60}; do
        if ping_server_backend > /dev/null; then
            echo -e " ${GREEN}Ready!${NC}"
            sleep 2
            break
        fi
        echo -n "."
        sleep 1
    done

    if ! ping_server_backend > /dev/null; then
        echo -e "\n${RED}Error: ArenaX server did not start within expected time.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}ArenaX server is already running.${NC}"
fi

trap cleanup EXIT SIGINT SIGTERM

# Handle --show-params
if [ "$SHOW_PARAMS" = "1" ]; then
    uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest \
      --interval "$INTERVAL" \
      --show-params
    exit 0
fi

sleep 5
CMD="uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest \
  --symbol $CJSYS_WATCH_LIST \
  --interval $INTERVAL \
  --balance $INITIAL_FUND \
  --duration $DURATION_DAYS"

if [ -n "$PARAMS" ]; then
    CMD="$CMD --params \"$PARAMS\""
fi

if [ -n "$START_DATE" ]; then
    CMD="$CMD --start $START_DATE"
fi

if [[ "$COMPARE_MODE" == "1" || "$COMPARE_MODE" == "true" || "$COMPARE_MODE" == "y" ]]; then
  CMD="$CMD --compare"
fi

if [ -n "$START_DATE" ]; then
    CMD="$CMD --start $START_DATE"
fi

echo -e "${GREEN}Executing OneShot Backtest...${NC}"
eval $CMD
