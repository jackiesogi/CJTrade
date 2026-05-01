#!/bin/bash
# Test script for cjtrade system
# Usage: ./test_system.sh <broker_type>
# Example: ./test_system.sh mock

if [ -z "$1" ]; then
    echo "Error: Broker type is required"
    echo "Usage: $0 <broker_type>"
    echo "Example: $0 mock"
    exit 1
fi

export USERNAME=$(whoami)
export WATCH_LIST=1101,1234,1737,2356,2449,2498,2913,6902

state_file="${1}_${USERNAME}.json"

# Remove existing state file
rm -f "$state_file" > /dev/null 2>&1

# Generate an empty state file
uv run cjtrade --broker="$1" exit

# Check if state file was created
if [ ! -f "$state_file" ]; then
    echo "Error: Failed to create state file $state_file"
    exit 1
fi

# Substitute the balance to 500,000
cat "$state_file" | jq '.balance = 500000' > tmp.json && mv tmp.json "$state_file"

# Run the trading system
time uv run system --broker="$1"
