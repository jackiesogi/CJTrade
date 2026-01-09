#!/bin/bash
set -e

CMD="uv run python src/cjtrade/tests/cjtrade_shell.py"
WAIT="&& sleep 1"
__() {
    eval "$CMD $1 $WAIT"
}

exit_failed() {
    echo "Command failed: $1"
    exit 1
}

echo "=== Testing CJTrade Shell Commands ==="

# buy 0050 @20.25 80 shares
echo "Testing buy command..."
__ "buy 0050 20.25 80" || exit_failed "buy command"

# sell 0050 @30.65 120 shares
echo "Testing sell command..."
__ "sell 0050 30.65 120" || exit_failed "sell command"

# ohlcv 2330
echo "Testing ohlcv command..."
__ "ohlcv 2330" || exit_failed "ohlcv command"

# bidask 2330 with intraday_odd=1
echo "Testing bidask command..."
__ "bidask 2330" || exit_failed "bidask command"

# List orders
echo "Testing lsodr command..."
__ "lsodr" || exit_failed "lsodr command"

# List positions
echo "Testing lspos command..."
__ "lspos" || exit_failed "lspos command"

# Check balance
echo "Testing balance command..."
__ "balance" || exit_failed "balance command"

# Get market movers ranking
echo "Testing rank command..."
__ "rank" || exit_failed "rank command"

# Search news with keyword
echo "Testing news command..."
__ "news" || exit_failed "news command"

# Search news (alternative command)
echo "Testing search command..."
__ "search 台積電" || exit_failed "search command"

# Get help
echo "Testing help command..."
__ "help" || exit_failed "help command"

# Test clear command
echo "Testing clear command..."
__ "clear" || exit_failed "clear command"

# Cancel all orders (optional - might not have orders to cancel)
echo "Testing cancel command..."
__ "cancel" || echo "Warning: cancel command failed (might be no orders to cancel)"

# Start analytics (commented out as it runs indefinitely)
# echo "Testing start command..."
# eval "$CMD start 2330 500 600" || exit_failed "start command"

echo "=== All tests completed successfully ==="
