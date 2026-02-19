#!/bin/bash
# Run CJTrade Broker API Stability Tests

set -e

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}======================================${NC}"
echo -e "${YELLOW}CJTrade Broker API Stability Tests${NC}"
echo -e "${YELLOW}======================================${NC}"
echo ""

# Run the tests
uv run python tests/test_broker_api_stability.py | tee stability_test_output.log

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ All stability tests passed!${NC}"
else
    echo ""
    echo -e "${RED}✗ Some tests failed (exit code: $EXIT_CODE)${NC}"
fi

exit $EXIT_CODE
