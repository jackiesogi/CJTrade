#!/usr/bin/env python3
"""
Simple wrapper to run integration tests via 'uv run test'
"""
import subprocess
import sys
from pathlib import Path

from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import setup_logging

log = get_logger("test_runner")


def main():
    """Run the integration test script"""
    setup_logging()
    # Get the project root directory (go up from src/cjtrade to project root)
    project_root = Path(__file__).parent.parent.parent
    test_script = project_root / "tests" / "test_cjtrade_integration.sh"

    if not test_script.exists():
        log.error("test script not found: %s", test_script)
        sys.exit(1)

    # Pass through all command line arguments to the test script
    # Use bash explicitly to execute the script
    cmd = ["bash", str(test_script)] + sys.argv[1:]

    try:
        # Run the test script
        result = subprocess.run(cmd, cwd=project_root)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        log.warning("interrupted by user")
        sys.exit(130)
    except Exception as e:
        log.error("running tests failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
