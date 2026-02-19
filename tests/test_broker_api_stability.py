#!/usr/bin/env python3
"""
CJTrade Broker API Stability Test Suite
==========================================
Main entry point for running all broker API stability tests.

Tests are organized into categories:
- normal.py: Normal operation flows
- edge.py: Edge cases and boundary conditions
- state.py: Database and state consistency
- stress.py: Load and stress scenarios
- integration.py: End-to-end integration flows

Usage:
    python tests/test_broker_api_stability.py

Or via bash script:
    ./tests/run_broker_stability_tests.sh
"""

import os
import sys
import unittest
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import test modules
from tests.cj_api.normal import TestNormalOperations
from tests.cj_api.edge import TestEdgeCases
from tests.cj_api.state import TestStateConsistency
from tests.cj_api.stress import TestStressScenarios
from tests.cj_api.integration import TestIntegrationFlows

# Import test formatter
from tests.utils import run_tests_with_simplified_output


def create_test_suite():
    """Create a test suite containing all broker API tests"""
    suite = unittest.TestSuite()

    # Add all test classes
    loader = unittest.TestLoader()

    # Normal operations (test_01-05)
    # suite.addTests(loader.loadTestsFromTestCase(TestNormalOperations))

    # Edge cases (test_10-19)
    # suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    # State consistency (test_20-33)
    suite.addTests(loader.loadTestsFromTestCase(TestStateConsistency))

    # Stress tests (test_40-41)
    # suite.addTests(loader.loadTestsFromTestCase(TestStressScenarios))

    # Integration tests (test_50-51)
    # suite.addTests(loader.loadTestsFromTestCase(TestIntegrationFlows))

    return suite


def main():
    parser = argparse.ArgumentParser(
        description='CJTrade Broker API Stability Test Suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Available brokers:
  mock     - Mock broker (default, safe for testing)
  sinopac  - 永豐金證券
  yuanta   - 元大證券
  cathay   - 國泰證券

Examples:
  %(prog)s                              # Fast unit tests with mock broker
  %(prog)s --broker=sinopac --delay=10  # Test with Sinopac, 10s between tests
  %(prog)s --broker=mock --verbose      # Verbose output with mock broker

Recommendations:
  - Use mock broker for rapid development and CI/CD
  - Use real brokers with --delay=8-10 for integration testing
  - Real broker tests maintain full isolation but run slower
  - Set CONFIRM_REAL_BROKER_TEST='yes_i_understand_the_risks' for real brokers
        '''
    )
    parser.add_argument(
        '--broker',
        type=str,
        default='mock',
        choices=['mock', 'sinopac', 'yuanta', 'cathay'],
        help='Broker to test (default: mock)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print all test output to stdout (default: simplified output)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0,
        help='Delay in seconds between tests when using real brokers (default: 0 for mock, recommended: 10 for real brokers)'
    )
    args = parser.parse_args()

    from cjtrade.core.config_loader import load_supported_config_files
    from cjtrade.core.account_client import BrokerType
    from tests.cj_api.base import BaseBrokerTest

    load_supported_config_files()

    # Set broker type for all tests
    broker_name_map = {
        'mock': BrokerType.MOCK,
        'sinopac': BrokerType.SINOPAC,
        'yuanta': BrokerType.YUANTA,
        'cathay': BrokerType.CATHAY
    }
    BaseBrokerTest.test_broker_type = broker_name_map[args.broker]

    # Set delay for real broker testing
    if args.broker != 'mock':
        # Auto-set delay if not specified
        if args.delay == 0:
            args.delay = 8.0  # Default 8 seconds for real brokers
            print(f"Auto-setting delay to {args.delay}s for real broker testing")
    BaseBrokerTest.test_delay = args.delay

    print(f"Testing with broker: {args.broker.upper()}")
    if args.broker != 'mock':
        print("⚠️  WARNING: Testing with real broker!")
        print(f"⚠️  Delay between tests: {args.delay}s (to avoid connection limits)")
    # Create test suite
    suite = create_test_suite()

    # Run tests with appropriate output format
    if args.verbose:
        # Verbose mode: use standard unittest runner with all output to stdout
        print("Running tests in verbose mode (all output to stdout)...\n")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
    else:
        # Simplified mode: simplified console output, detailed log to file
        result = run_tests_with_simplified_output(
            suite,
            log_filename='LAST_BROKER_STABILITY_TEST.log'
        )

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
