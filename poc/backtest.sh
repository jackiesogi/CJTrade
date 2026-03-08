# Clean up
echo > ./llm_report.txt
echo > ./data/realistic_CJ.db

# Create an empty realistic_CJ.json
USERNAME=CJ uv run cjtrade --broker=realistic exit

# Replace balance from 0 -> 500,000 (Initial funds)
jq '.balance = 500000.0' realistic_CJ.json > tmp.json
mv tmp.json realistic_CJ.json

# Validate initial fund equals 500,000
USERNAME=CJ uv run cjtrade --broker=realistic balance

sleep 15

# Open up standalone terminal app to monitor LLM's response
gnome-terminal -- watch -n 10 "cat llm_report.txt"

# Open up SQLiteStudio to monitor order history
/opt/SQLiteStudio/sqlitestudio ./data/realistic_CJ.db &

# Start!
USERNAME=CJ WATCH_LIST=0050,2330,2357,2317 uv run system --broker=realistic
