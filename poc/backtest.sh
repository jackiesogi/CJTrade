#!/bin/bash

if [ -z $CYSYS_WATCH_LIST ]; then
    echo "CJSYS_WATCH_LIST not set, defaulting to 1234"
    export CJSYS_WATCH_LIST=1234
fi

# Clean up
echo > ./llm_report.txt
echo > ./data/arenax_CJ.db
rm -f ./arenax_CJ.json

gnome-terminal() {
    command gnome-terminal --zoom=0.8 "$@"
}

# Validate initial fund equals 500,000
USERNAME=CJ bash scripts/gen_init_account.sh arenax 500000
cat arenax_CJ.json

sleep 3

# Open up standalone terminal app to monitor LLM's response
gnome-terminal -- watch -n 10 -d "cat llm_report.txt"

# Open up SQLiteStudio to monitor order history
# /home/jck/SQLiteStudio/sqlitestudio ./data/arenax_CJ.db &
gnome-terminal -- watch -n 2 'sqlite3 -header -column data/arenax_CJ.db --markdown "
SELECT *
FROM orders
ORDER BY updated_at DESC
LIMIT 30;
"'

# Start!
# USERNAME=CJ WATCH_LIST=0050,2330,2357,2317 uv run system --broker=arenax
USERNAME=CJ CJSYS_STATE_FILE=arenax_CJ.json uv run system --broker=arenax --mode=hist
