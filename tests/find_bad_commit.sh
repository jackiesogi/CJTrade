#!/bin/bash
# utilize git bisect to find the bad commit that introduced a bug
# --good
# --bad
# --script

GOOG_COMMIT=""
BAD_COMMIT=""
TEST_SCRIPT=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --good) GOOD_COMMIT="$2"; shift ;;
        --bad) BAD_COMMIT="$2"; shift ;;
        --script) TEST_SCRIPT="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [[ -z "$GOOD_COMMIT" ]]; then
    read -p "Enter the known good commit hash: " GOOD_COMMIT
    if [[ -z "$GOOD_COMMIT" ]]; then
        echo "Good commit hash is required."
        exit 1
    fi
fi

if [[ -z "$BAD_COMMIT" ]]; then
    read -p "Enter the known bad commit hash: " BAD_COMMIT
    if [[ -z "$BAD_COMMIT" ]]; then
        echo "Bad commit hash is required."
        exit 1
    fi
fi

if [[ -z "$TEST_SCRIPT" ]]; then
    read -p "Enter the path to the test script: " TEST_SCRIPT
    if [[ -z "$TEST_SCRIPT" ]]; then
        echo "Test script path is required."
        exit 1
    fi
fi

# Start git bisect
git bisect start
git bisect bad $BAD_COMMIT
git bisect good $GOOD_COMMIT
git bisect run $TEST_SCRIPT
