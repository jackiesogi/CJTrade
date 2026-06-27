#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ------------------------
# --show-params: early exit (no form needed)
# ------------------------
for arg in "$@"; do
    if [[ "$arg" == "--show-params" ]]; then
        uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest \
          --interval 1d --show-params
        exit 0
    fi
done

# ------------------------
# Form: collect params + export env
# (CLI prompts only for fields not supplied via CLI args)
# ------------------------
eval "$(uv run python -c '
from cjtrade.pkgs.ui import FormEngine
e = FormEngine("poc/backtest.toml", renderer="cli")
e.print_exports(e.run())
' "$@")"

# Export port so Python modules pick up the correct server port
case "$ARENAX_MODE" in
    backtest) export ARENAX_PORT=8802 ;;
    paper)    export ARENAX_PORT=8803 ;;
    *)        export ARENAX_PORT=8801 ;;
esac

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
    local port
    case "$ARENAX_MODE" in
        backtest)
            port=8802
            ;;
        paper)
            port=8803
            ;;
        demo|"")
            port=8801
            ;;
        *)
            # Fallback to demo/default port for unknown mode
            port=8801
            ;;
    esac

    local url="http://127.0.0.1:${port}/health"
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
    # Unset AX_ env vars so load_dotenv(override=False) inside arenaxd picks up the
    # correct backend config file (e.g. backtest.cjsys → port 8802) instead of being
    # silently shadowed by stale values from a previous session.
    unset AX_HOST_PORT AX_HOST_ADDRESS AX_LAUNCH_MODE AX_STATE_FILE
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

if [[ "$COMPARE_MODE" == "1" || "$COMPARE_MODE" == "True" || "$COMPARE_MODE" == "y" ]]; then
  CMD="$CMD --compare"
fi

if [ -n "$START_DATE" ]; then
    CMD="$CMD --start $START_DATE"
fi

echo -e "${GREEN}Executing OneShot Backtest...${NC}"
echo -e "${YELLOW}Command: $CMD${NC}"
eval $CMD
