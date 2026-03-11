#!/bin/bash

set -e

broker=$1
balance=$2

print_usage_exit_with() {
    echo "Usage: $0 <broker> [balance]"
    echo "Example: $0 mock 10000"
    exit "$1"
}

[ -z "$broker" ] && print_usage_exit_with 1
[ -z "$balance" ] && balance=10000.0
[ -z "$USERNAME" ] && USERNAME=$(whoami)

out_file="${broker}_${USERNAME}.json"

cat <<EOF > "$out_file"
{
    "balance": 0.0,
    "positions": [],
    "orders_placed": [],
    "orders_committed": [],
    "orders_filled": [],
    "orders_cancelled": [],
    "all_order_status": {},
    "fill_history": []
}
EOF

jq --argjson balance "$balance" '.balance = $balance' "$out_file" > tmp.json
mv tmp.json "$out_file"

echo "Initialized account state for broker '$broker' with balance $balance in file '$out_file'"
