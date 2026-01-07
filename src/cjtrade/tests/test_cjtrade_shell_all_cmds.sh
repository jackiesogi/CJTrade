#!/bin/bash
set -e

CMD="uv run python src/cjtrade/tests/cjtrade_shell.py"

exit_failed() {
    echo "Command failed: $1"
    exit 1
}

echo "=== Testing CJTrade Shell Commands ==="

# buy 0050 @20.25 80 shares
echo "Testing buy command..."
eval "$CMD buy 0050 20.25 80" || exit_failed "buy command"

# sell 0050 @30.65 120 shares
echo "Testing sell command..."
eval "$CMD sell 0050 30.65 120" || exit_failed "sell command"

# ohlcv 2330
echo "Testing ohlcv command..."
eval "$CMD ohlcv 2330" || exit_failed "ohlcv command"

# bidask 2330 with intraday_odd=1
echo "Testing bidask command..."
eval "$CMD bidask 2330" || exit_failed "bidask command"

# List orders
echo "Testing lsodr command..."
eval "$CMD lsodr" || exit_failed "lsodr command"

# List positions
echo "Testing lspos command..."
eval "$CMD lspos" || exit_failed "lspos command"

# Check balance
echo "Testing balance command..."
eval "$CMD balance" || exit_failed "balance command"

# Get market movers ranking
echo "Testing rank command..."
eval "$CMD rank" || exit_failed "rank command"

# Search news with keyword
echo "Testing news command..."
eval "$CMD news" || exit_failed "news command"

# Search news (alternative command)
echo "Testing search command..."
eval "$CMD search 台積電" || exit_failed "search command"

# Get help
echo "Testing help command..."
eval "$CMD help" || exit_failed "help command"

# Test clear command
echo "Testing clear command..."
eval "$CMD clear" || exit_failed "clear command"

# Cancel all orders (optional - might not have orders to cancel)
echo "Testing cancel command..."
eval "$CMD cancel" || echo "Warning: cancel command failed (might be no orders to cancel)"

# Start analytics (commented out as it runs indefinitely)
# echo "Testing start command..."
# eval "$CMD start 2330 500 600" || exit_failed "start command"

echo "=== All tests completed successfully ==="
