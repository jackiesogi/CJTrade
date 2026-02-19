#!/bin/bash
set -e

# CMD="uv run python src/cjtrade/core/cjtrade_shell.py --broker=sinopac"
CMD="uv run python src/cjtrade/core/cjtrade_shell.py --broker=mock"
# CMD="uv run python src/cjtrade/core/cjtrade_shell.py --broker=realistic"

LOG_FILE="LAST_CJTRADE_INTEGRATION_TEST.log"

WAIT="&& sleep 1"
__() {
    eval "$CMD $1 $WAIT"
}

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

print_title() {
    MSG="Testing $1 command ..."
    echo -e "${YELLOW}${MSG}${NC}" | tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")
}

print_passed() {
    MSG="[PASSED] $1 command"
    echo -e "${GREEN}${MSG}${NC}\n" | tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")
}

exit_failed() {
    MSG="[FAILED] $1 command"
    echo -e "${RED}${MSG}${NC}" | tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE")
    exit 1
}

echo "=== Testing CJTrade Shell Commands ==="

# info
print_title "info"
__ "info" || exit_failed "info command"
print_passed "info"

# cal 2026
print_title "date"
__ "date 2026" || exit_failed "date command"
print_passed "date"

# buy 0050 @20.25 80 shares
print_title "buy"
__ "buy 0050 20.25 80" || exit_failed "buy command"
print_passed "buy"

# sell 0050 @30.65 120 shares
print_title "sell"
__ "sell 0050 30.65 120" || exit_failed "sell command"
print_passed "sell"

# List orders
print_title "lsodr"
__ "lsodr" || exit_failed "lsodr command"
print_passed "lsodr"

# ohlcv 2330
print_title "ohlcv"
__ "ohlcv 2330" || exit_failed "ohlcv command"
print_passed "ohlcv"

# bidask 2330 with intraday_odd=1
print_title "bidask"
__ "bidask 2330" || exit_failed "bidask command"
print_passed "bidask"

# kbar 2330
print_title "kbars"
__ "kbars 2330" || exit_failed "kbar command"
print_passed "kbars"

# List positions
print_title "lspos"
__ "lspos" || exit_failed "lspos command"
print_passed "lspos"

# Check balance
print_title "balance"
__ "balance" || exit_failed "balance command"
print_passed "balance"

# Get market movers ranking
print_title "rank"
__ "rank" || exit_failed "rank command"
print_passed "rank"

# Search news with keyword
print_title "news"
__ "news" || exit_failed "news command"
print_passed "news"

# Search news (alternative command)
print_title "search"
__ "search 台積電" || exit_failed "search command"
print_passed "search"

# Get help
print_title "help"
__ "help" || exit_failed "help command"
print_passed "help"

# Test clear command
print_title "clear"
__ "clear" || exit_failed "clear command"
print_passed "clear"

# Cancel all orders (optional - might not have orders to cancel)
print_title "cancel"
__ "cancel" || echo "Warning: cancel command failed (might be no orders to cancel)"
print_passed "cancel"

# Start analytics (commented out as it runs indefinitely)
# echo -e "${YELLOW}Testing start command...${NC}"
# eval "$CMD start 2330 500 600" || exit_failed "start command"

echo "=== All tests completed successfully ==="
