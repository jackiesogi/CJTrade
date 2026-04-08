#!/bin/bash

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
else
    read_watch_list
    read_initial_fund
    read_duration_days
fi

# Define cleanup function
function cleanup() {
    if [ -n "$ARENAX_PID" ]; then
        echo -e "\n${YELLOW}Stopping ArenaX broker server (PID: $ARENAX_PID)...${NC}"
        kill $ARENAX_PID 2>/dev/null || true
    fi
}

function ping_server_backend() {
    local url="http://127.0.0.1:8801/health"

    function check_status() {
        local response
        response=$(curl -s --max-time 3 "$url" 2>/dev/null) || return 1
        if [[ $(echo "$response" | jq -r '.running' 2>/dev/null) == "true" ]]; then
            return 0
        else
            return 1
        fi
    }

    check_status
}

if ! ping_server_backend > /dev/null; then
    echo "Starting ArenaX broker server..."
    # uv run arenaxd --backend=hist > /dev/null 2>&1 &
    uv run arenaxd > /dev/null 2>&1 &  # for simplicity
    ARENAX_PID=$!

    # start the server in background
    echo -n "Waiting for server to be ready..."
    for i in {1..60}; do
        if ping_server_backend > /dev/null; then
            echo -e " ${GREEN}Ready!${NC}"
            sleep 2  # wait a bit to ensure server is fully up
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

uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest \
  --symbol $CJSYS_WATCH_LIST \
  --interval 1m \
  --balance $INITIAL_FUND
