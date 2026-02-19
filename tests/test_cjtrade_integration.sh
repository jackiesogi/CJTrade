
# =============================================================================
# CJTrade Shell Integration Test Suite
# ---
# It basically do the same thing as test_cjtrade_shell_all_cmds.sh
# but with better structure, logging, and reporting.
# =============================================================================
# Usage:
#   ./test_cjtrade_shell_all_cmds.sh [options]
#
# Options:
#   --broker=<name>     Specify broker (mock/sinopac/realistic, default: mock)
#   --group=<name>      Run specific test group (trading/query/market/system/all)
#   --continue-on-error Don't exit on first failure
#   --no-log           Don't write to log file
#   -h, --help         Show this help message
# =============================================================================

set -e

# ============= Configuration =============
DEFAULT_BROKER="mock"
BROKER="${DEFAULT_BROKER}"
LOG_FILE="LAST_CJTRADE_INTEGRATION_TEST.log"
SLEEP_BETWEEN_TESTS=1
CONTINUE_ON_ERROR=false
ENABLE_LOGGING=true
TEST_GROUP="all"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Test statistics
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0

# ============= Help Message =============
show_help() {
    cat << EOF
CJTrade Shell Integration Test Suite

Usage: $0 [options]

Options:
    --broker=<name>      Specify broker (mock/sinopac/realistic, default: mock)
    --group=<name>       Run specific test group:
                         - trading: buy, sell, cancel commands
                         - query: lsodr, lspos, balance commands
                         - market: ohlcv, bidask, kbars, rank commands
                         - system: info, date, help, clear commands
                         - news: news, search commands
                         - all: run all tests (default)
    --continue-on-error  Don't exit on first failure
    --no-log            Don't write to log file
    -h, --help          Show this help message

Examples:
    $0                                    # Run all tests with mock broker
    $0 --broker=sinopac --group=trading  # Run trading tests with sinopac
    $0 --continue-on-error               # Run all tests, don't stop on error
EOF
    exit 0
}

# ============= Parse Arguments =============
for arg in "$@"; do
    case $arg in
        --broker=*)
            BROKER="${arg#*=}"
            ;;
        --group=*)
            TEST_GROUP="${arg#*=}"
            ;;
        --continue-on-error)
            CONTINUE_ON_ERROR=true
            set +e  # Disable exit on error
            ;;
        --no-log)
            ENABLE_LOGGING=false
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "Unknown option: $arg"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# ============= Setup =============
CMD="uv run python src/cjtrade/core/cjtrade_shell.py --broker=${BROKER}"

# Initialize log file
if [ "$ENABLE_LOGGING" = true ]; then
    echo "=== CJTrade Integration Test Log ===" > "$LOG_FILE"
    echo "Date: $(date)" >> "$LOG_FILE"
    echo "Broker: ${BROKER}" >> "$LOG_FILE"
    echo "Test Group: ${TEST_GROUP}" >> "$LOG_FILE"
    echo "======================================" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
fi

# ============= Helper Functions =============
log_output() {
    if [ "$ENABLE_LOGGING" = true ]; then
        echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE"
    fi
}

print_header() {
    local msg="=== $1 ==="
    echo -e "${CYAN}${msg}${NC}"
    log_output "$msg"
}

print_test_start() {
    local name="$1"
    local desc="$2"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    local msg="[${TOTAL_TESTS}] Testing: ${name}"
    [ -n "$desc" ] && msg="${msg} (${desc})"
    echo -e "${YELLOW}${msg}${NC}"
    log_output "$msg"
}

print_passed() {
    PASSED_TESTS=$((PASSED_TESTS + 1))
    local msg="[PASSED] $1\n"
    echo -e "${GREEN}${msg}${NC}"
    log_output "$msg"
}

print_failed() {
    FAILED_TESTS=$((FAILED_TESTS + 1))
    local msg="[FAILED] $1\n"
    echo -e "${RED}${msg}${NC}"
    log_output "$msg"

    if [ "$CONTINUE_ON_ERROR" = false ]; then
        print_summary
        exit 1
    fi
}

print_skipped() {
    SKIPPED_TESTS=$((SKIPPED_TESTS + 1))
    local msg="[SKIPPED] $1\n"
    echo -e "${BLUE}${msg}${NC}"
    log_output "$msg"
}

print_summary() {
    echo ""
    print_header "Test Summary"
    echo -e "Total:   ${TOTAL_TESTS}"
    echo -e "${GREEN}Passed:  ${PASSED_TESTS}${NC}"
    [ $FAILED_TESTS -gt 0 ] && echo -e "${RED}Failed:  ${FAILED_TESTS}${NC}" || echo -e "Failed:  ${FAILED_TESTS}"
    [ $SKIPPED_TESTS -gt 0 ] && echo -e "${BLUE}Skipped: ${SKIPPED_TESTS}${NC}" || echo -e "Skipped: ${SKIPPED_TESTS}"

    if [ $FAILED_TESTS -eq 0 ]; then
        echo -e "\n${GREEN}✓ All tests passed!${NC}"
        log_output "✓ All tests passed!"
    else
        echo -e "\n${RED}✗ Some tests failed${NC}"
        log_output "✗ Some tests failed"
    fi
}

__() {
    eval "$CMD $1 && sleep $SLEEP_BETWEEN_TESTS"
}

run_cmd() {
    local test_name="$1"
    local cmd_args="$2"
    local description="$3"

    print_test_start "$test_name" "$description"

    # Capture both stdout and stderr, display to console and log to file
    if [ "$ENABLE_LOGGING" = true ]; then
        # Use temporary file to capture output
        local temp_output=$(mktemp)
        __ "$cmd_args" 2>&1 | tee "$temp_output"
        local exit_code=${PIPESTATUS[0]}

        # Append test output to log file (strip color codes)
        sed 's/\x1b\[[0-9;]*m//g' "$temp_output" >> "$LOG_FILE"
        echo "" >> "$LOG_FILE"
        rm -f "$temp_output"
    else
        __ "$cmd_args"
        local exit_code=$?
    fi

    if [ $exit_code -eq 0 ]; then
        print_passed "$test_name"
        return 0
    else
        print_failed "$test_name"
        return 1
    fi
}

# ============= Test Definitions =============
# Format: "test_name|command_args|description|group"
declare -a ALL_TESTS=(
    # System commands
    "clear|clear|Clear screen|system"
    "info|info|Show system information|system"
    "date|date 2026|Display calendar|system"
    "help|help|Show help message|system"

    # Trading commands
    "buy|buy 0050 20.25 80|Buy 80 shares of 0050 @20.25|trading"
    "sell|sell 0050 30.65 120|Sell 120 shares of 0050 @30.65|trading"
    "cancel|cancel|Cancel pending orders|trading"

    # Query commands
    "lsodr|lsodr|List all orders|query"
    "lspos|lspos|List all positions|query"
    "balance|balance|Check account balance|query"

    # Market data commands
    "ohlcv|ohlcv 2330|Get OHLCV data for 2330|market"
    "bidask|bidask 2330|Get bid/ask for 2330|market"
    "kbars|kbars 2330|Get K-bar chart for 2330|market"
    "rank|rank|Get market movers ranking|market"

    # News commands
    "news|news|Search news|news"
    "search|search 台積電|Search news with keyword|news"
)

# ============= Test Execution =============
should_run_test() {
    local test_group="$1"

    if [ "$TEST_GROUP" = "all" ]; then
        return 0
    elif [ "$TEST_GROUP" = "$test_group" ]; then
        return 0
    else
        return 1
    fi
}

run_tests() {
    print_header "CJTrade Shell Integration Tests"
    echo "Broker: ${BROKER}"
    echo "Test Group: ${TEST_GROUP}"
    echo ""

    for test_def in "${ALL_TESTS[@]}"; do
        IFS='|' read -r test_name cmd_args description group <<< "$test_def"

        if should_run_test "$group"; then
            run_cmd "$test_name" "$cmd_args" "$description"
        else
            print_test_start "$test_name" "$description"
            print_skipped "${test_name} (not in selected test group)"
        fi
    done

    echo ""
    print_summary

    # Exit with error code if any tests failed
    [ $FAILED_TESTS -eq 0 ] && exit 0 || exit 1
}

# ============= Main =============
run_tests