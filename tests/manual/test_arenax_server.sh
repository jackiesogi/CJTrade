#!/bin/bash
set -euo pipefail
export DISPLAY=:0

HOST="127.0.0.1"
PORT="8801"
BASE_URL="http://${HOST}:${PORT}"
PID_FILE="/tmp/arenax.pid"

cleanup() {
    if [[ -f "${PID_FILE}" ]]; then
        ARENAX_SERVER_PID=$(cat "${PID_FILE}")
        if [[ -n "${ARENAX_SERVER_PID}" ]]; then
            kill -9 "${ARENAX_SERVER_PID}" >/dev/null 2>&1 || true
        fi
        rm -f "${PID_FILE}"
    fi
}

trap cleanup EXIT

start_server() {
    with_gui=$1
    if [ $with_gui -eq 1 ]; then
        gnome-terminal -- bash -c 'uv run arenaxd & echo $! > /tmp/arenax.pid; wait'
    else
        uv run arenaxd > /dev/null 2>&1 &
        echo $! > /tmp/arenax.pid
    fi
}

wait_for_server() {
    local retries=60
    local wait_seconds=2
    while (( retries > 0 )); do
        if curl -s "${BASE_URL}/health" >/dev/null; then
            return 0
        fi
        sleep "${wait_seconds}"
        retries=$((retries - 1))
    done
    echo "Server did not become ready" >&2
    return 1
}

assert_json_eq() {
    local label=$1
    local value=$2
    local expected=$3
    if [[ "${value}" != "${expected}" ]]; then
        echo "Assertion failed: ${label} expected ${expected}, got ${value}" >&2
        exit 1
    fi
    echo "Pass"
}

get_json_field() {
    local url=$1
    local field=$2
    curl -s "${url}" | jq -r "${field}"
}

post_json() {
    local url=$1
    local payload=$2
    curl -s -X POST -H "Content-Type: application/json" -d "${payload}" "${url}"
}

if [[ ${1:-} == "--gui" ]]; then
    start_server 1
else
    start_server 0
fi

wait_for_server

ARENAX_SERVER_PID=$(cat "${PID_FILE}")
echo "Server pid = ${ARENAX_SERVER_PID}"
echo "Server ready!"

code=$(curl -o /dev/null -s -w "%{http_code}\n" "${BASE_URL}/health")
if [ "${code}" -ne 200 ]; then
    exit 1
fi

res=$(curl -s "${BASE_URL}/health")
assert_json_eq "health.backend_connected" "$(echo "${res}" | jq -r .backend_connected)" "false"
assert_json_eq "health.ok" "$(echo "${res}" | jq -r .ok)" "true"
assert_json_eq "health.running" "$(echo "${res}" | jq -r .running)" "false"

start_res=$(post_json "${BASE_URL}/control/start" "{}")
assert_json_eq "start.ok" "$(echo "${start_res}" | jq -r .ok)" "true"
assert_json_eq "start.running" "$(echo "${start_res}" | jq -r .running)" "true"

time_res=$(curl -s "${BASE_URL}/control/get-time")
assert_json_eq "get-time.playback_speed" "$(echo "${time_res}" | jq -r .playback_speed)" "12000"

anchor_time=$(date -u +"%Y-%m-%dT%H:%M:%S")
set_time_res=$(post_json "${BASE_URL}/control/set-time" "{\"anchor_time\": \"${anchor_time}\", \"days_back\": 5}")
assert_json_eq "set-time.ok" "$(echo "${set_time_res}" | jq -r .ok)" "true"

config_res=$(curl -s "${BASE_URL}/control/get-config")
if [[ "$(echo "${config_res}" | jq -r .server_config)" == "null" ]]; then
    echo "Assertion failed: get-config.server_config missing" >&2
    exit 1
fi
echo "Pass"

stop_res=$(post_json "${BASE_URL}/control/stop" "{}")
assert_json_eq "stop.ok" "$(echo "${stop_res}" | jq -r .ok)" "true"
assert_json_eq "stop.running" "$(echo "${stop_res}" | jq -r .running)" "false"
