#!/bin/bash
# Run CJTrade Broker API Stability Tests

set -e

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Declare variable to store PID
ARENAX_PID=""

# dependency check: jq
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: 'jq' is not installed. Please install it first.${NC}"
    exit 1
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

# TODO: Note that this is just a workaround to ensure the server
#       has a consistent init account state every time doing tests.
function prepare_init_account() {
cat <<EOF > hist_account_state.json
{ "balance": 999999,
  "positions": [
    {
        "symbol": "0050",
        "quantity": 100000,
        "avg_cost": 60.63,
        "current_price": 48.73,
        "market_value": 64518.5,
        "unrealized_pnl": 15755.6
    }
  ],
  "orders_placed": [],
  "orders_committed": [],
  "orders_filled": [],
  "orders_cancelled": [],
  "all_order_status": {},
  "fill_history": []
}
EOF
cat <<EOF > none_account_state.json
{ "balance": 999999,
  "positions": [
    {
        "symbol": "0050",
        "quantity": 100000,
        "avg_cost": 60.63,
        "current_price": 48.73,
        "market_value": 64518.5,
        "unrealized_pnl": 15755.6
    }
  ],
  "orders_placed": [],
  "orders_committed": [],
  "orders_filled": [],
  "orders_cancelled": [],
  "all_order_status": {},
  "fill_history": []
}
EOF
}

# Add trap
trap cleanup EXIT SIGINT SIGTERM

echo -e "${YELLOW}======================================${NC}"
echo -e "${YELLOW}CJTrade Broker API Stability Tests${NC}"
echo -e "${YELLOW}======================================${NC}"
echo ""

prepare_init_account

if [[ "$@" == *"--broker arenax"* ]] || [[ "$@" == *"--broker=arenax"* ]] || [[ -z "$@" ]]; then
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
fi

# Resolve which integration directory to run based on --broker= argument.
# Defaults to arenax. Extend the case block for other brokers as needed.
BROKER="arenax"
for arg in "$@"; do
    case "$arg" in
        --broker=*) BROKER="${arg#--broker=}" ;;
        --broker)   shift; BROKER="$1" ;;
    esac
done

INTEGRATION_DIR="tests/integration/${BROKER}"
if [[ ! -d "$INTEGRATION_DIR" ]]; then
    echo -e "${RED}Error: No integration tests found for broker '${BROKER}' (looked in ${INTEGRATION_DIR})${NC}"
    exit 1
fi

# use PIPESTATUS[0] to ensure we capture the exit code of the test command, not tee
uv run pytest "$INTEGRATION_DIR" -v | tee stability_test_output.log
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All stability tests passed!${NC}"
else
    echo ""
    echo -e "${RED}✗ Some tests failed (exit code: $EXIT_CODE)${NC}"
fi

# Mirror the output log to LAST_BROKER_STABILITY_TEST.log for backward compatibility
if [ -f stability_test_output.log ]; then
    cp stability_test_output.log LAST_BROKER_STABILITY_TEST.log
    echo -e "${YELLOW}Test output saved to LAST_BROKER_STABILITY_TEST.log${NC}"
fi

exit $EXIT_CODE
