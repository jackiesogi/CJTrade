#!/bin/bash

BASE_URL="http://localhost:8801/control"
THRESHOLD=15
ANCHOR_TIME="2024-01-16T09:00:00"

function info()    { echo -e "\e[34m[INFO]\e[0m $1"; }
function success() { echo -e "\e[32m[PASS]\e[0m $1"; }
function error()   { echo -e "\e[31m[FAIL]\e[0m $1"; }

function cleanup() {
    if [ -n "$SERVER_PID" ]; then
        info "Cleaning up: Killing server (PID: $SERVER_PID)..."
        kill $SERVER_PID 2>/dev/null
        wait $SERVER_PID 2>/dev/null
        success "Server terminated."
    fi
}
trap cleanup EXIT

# 0. 紀錄啟動前時間
EXPECTED_INIT_EPOCH=$(python3 -c "import time; print(time.time())")

info "Starting server with 'uv run arenaxd'..."
uv run arenaxd >/dev/null 2>&1 &
SERVER_PID=$!

info "Waiting 10 seconds for startup..."
sleep 10

echo "--------------------------------------------------------"
echo "   ArenaX Time Lifecycle Test (Precheck -> Set -> Pause -> Resume)"
echo "--------------------------------------------------------"

# --- 1. Pre-check: Ensure server initial state is running ---
info "Pre-check: Verifying initial clock is running..."
PRE_1=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')
sleep 2
PRE_2=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')

if [ "$PRE_1" != "$PRE_2" ] && [ "$PRE_1" != "null" ]; then
    success "Pre-check: PASS (System clock is running by default)"
else
    error "Pre-check: FAIL (Clock is stuck or Server unreachable!)"
    exit 1
fi

# --- 2. Action: Set Time ---
info "Action: Setting anchor time to $ANCHOR_TIME..."
curl -s -X POST -H "Content-Type: application/json" \
     -d "{\"anchor_time\": \"$ANCHOR_TIME\"}" "$BASE_URL/set-time" > /dev/null

# --- 3. Validation: real_init_time (Default Arg Check) ---
SERVER_DATA=$(curl -s "$BASE_URL/get-time")
REAL_INIT_STR=$(echo "$SERVER_DATA" | jq -r '.real_init_time')

OFFSET=$(python3 - <<EOF
import email.utils, time
try:
    ts = email.utils.parsedate_to_datetime("$REAL_INIT_STR").timestamp()
    diff = ts - $EXPECTED_INIT_EPOCH
    if abs(diff - 28800) < 1000: diff -= 28800
    if abs(diff + 28800) < 1000: diff += 28800
    print(f"{abs(diff):.2f}")
except: print("9999")
EOF
)

if (( $(echo "$OFFSET < $THRESHOLD" | bc -l) )); then
    success "Real Init Time: PASS (Offset: ${OFFSET}s)"
else
    error "Real Init Time: FAIL (Offset: ${OFFSET}s)"
fi

# --- 4. Test: Pause (Should be frozen) ---
info "Action: Requesting Pause..."
curl -s -X POST "$BASE_URL/pause-time-progress" > /dev/null
M_PAUSE_1=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')
sleep 2
M_PAUSE_2=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')

if [ "$M_PAUSE_1" == "$M_PAUSE_2" ]; then
    success "Pause Check: PASS (Frozen at $M_PAUSE_1)"
else
    error "Pause Check: FAIL (Time leaked: $M_PAUSE_1 -> $M_PAUSE_2)"
fi

# --- 5. Test: Resume (Should resume) ---
info "Action: Requesting Resume..."
curl -s -X POST "$BASE_URL/resume-time-progress" > /dev/null
M_RESUME_1=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')
sleep 2
M_RESUME_2=$(curl -s "$BASE_URL/get-time" | jq -r '.mock_current_time')

if [ "$M_RESUME_1" != "$M_RESUME_2" ]; then
    success "Resume Check: PASS (Clock moving again)"
    JUMP=$(python3 - <<EOF
import email.utils
t1 = email.utils.parsedate_to_datetime("$M_RESUME_1").timestamp()
t2 = email.utils.parsedate_to_datetime("$M_RESUME_2").timestamp()
print(f"{(t2 - t1)/3600:.2f}")
EOF
    )
    info "Virtual time jumped ${JUMP} hours in 2s."
else
    error "Resume Check: FAIL (Still stuck)"
fi

echo "--------------------------------------------------------"
echo "   Validation Complete"
echo "--------------------------------------------------------"
