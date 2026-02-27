"""Simplified test output formatter for CJTrade tests

This module provides a custom test runner that:
- Shows simplified output on console (test name + result)
- Captures all detailed output (setup, teardown, errors) to log file
- Redirects broker API debug output to log file only
"""
import sys
import unittest
from io import StringIO


# Global log buffer for detailed logging
_log_buffer = None


def get_log_buffer():
    """Get the global log buffer for writing detailed logs"""
    return _log_buffer


class LogBufferWithWriteln:
    """Wrapper around StringIO to add writeln method for unittest compatibility"""
    def __init__(self, buf):
        self.buf = buf

    def write(self, data):
        self.buf.write(data)

    def writeln(self, data=''):
        self.buf.write(data + '\n')

    def flush(self):
        pass


class LogOnlyStream:
    """Stream that writes only to log buffer, not console"""
    def __init__(self, log_buffer):
        self.log_buffer = log_buffer

    def write(self, data):
        self.log_buffer.write(data)

    def writeln(self, data=''):
        self.log_buffer.write(data + '\n')

    def flush(self):
        pass


class SimplifiedTestResult(unittest.TextTestResult):
    """Custom test result that shows simplified output to console"""

    def __init__(self, stream, descriptions, verbosity, log_stream):
        # Use log buffer for detailed output, not console
        super().__init__(log_stream, descriptions, verbosity)
        self.console_stream = stream
        self.test_results = []

    def startTest(self, test):
        super().startTest(test)
        # Get test description
        test_method = getattr(test, test._testMethodName)
        description = test_method.__doc__ or "No description"
        description = description.strip()

        # Print test header to console only
        test_name = test._testMethodName
        self.console_stream.write(f"\n{test_name}... {description}\n")
        self.console_stream.flush()

        # Write to log buffer
        _log_buffer.write(f"\n{'='*70}\n")
        _log_buffer.write(f"{test_name}: {description}\n")
        _log_buffer.write(f"{'='*70}\n")

    def addSuccess(self, test):
        super().addSuccess(test)
        self.console_stream.write("✓ PASSED\n")
        self.console_stream.flush()
        _log_buffer.write("\nResult: PASSED\n")

    def addError(self, test, err):
        super().addError(test, err)
        self.console_stream.write("✗ ERROR\n")
        self.console_stream.flush()

        # Write full traceback to log buffer only
        import traceback
        _log_buffer.write("\nResult: ERROR\n")
        _log_buffer.write("Error Details:\n")
        _log_buffer.write(''.join(traceback.format_exception(*err)))
        _log_buffer.write("\n")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.console_stream.write("✗ FAILED\n")
        self.console_stream.flush()

        # Write full traceback to log buffer only
        import traceback
        _log_buffer.write("\nResult: FAILED\n")
        _log_buffer.write("Failure Details:\n")
        _log_buffer.write(''.join(traceback.format_exception(*err)))
        _log_buffer.write("\n")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.console_stream.write(f"⊘ SKIPPED ({reason})\n")
        self.console_stream.flush()
        _log_buffer.write(f"\nResult: SKIPPED\nReason: {reason}\n")


class SimplifiedTestRunner(unittest.TextTestRunner):
    """Custom test runner that uses SimplifiedTestResult"""

    def __init__(self, stream, verbosity, log_stream):
        self.log_stream = log_stream
        super().__init__(stream=stream, verbosity=verbosity)

    def _makeResult(self):
        return SimplifiedTestResult(self.stream, self.descriptions,
                                    self.verbosity, self.log_stream)


def run_tests_with_simplified_output(test_suite, log_filename='LAST_TEST_RUN.log'):
    """Run tests with simplified console output and detailed log file

    Args:
        test_suite: unittest.TestSuite to run
        log_filename: Name of the log file to write detailed output

    Returns:
        unittest.TestResult object
    """
    global _log_buffer

    # Create a string buffer to capture detailed output
    _log_buffer = StringIO()

    # Write header to log buffer
    _log_buffer.write("="*70 + "\n")
    _log_buffer.write("CJTrade Test Suite - Detailed Log\n")
    _log_buffer.write("="*70 + "\n\n")

    # Create log stream wrapper
    log_stream = LogBufferWithWriteln(_log_buffer)

    # Redirect stdout and stderr to log buffer during tests
    # to capture broker API debug output
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    # Print header to console
    print("\n" + "="*70)
    print("CJTrade Test Suite")
    print("="*70)

    # Redirect outputs during test execution
    sys.stdout = LogOnlyStream(_log_buffer)
    sys.stderr = LogOnlyStream(_log_buffer)

    try:
        runner = SimplifiedTestRunner(stream=old_stdout, verbosity=2, log_stream=log_stream)
        result = runner.run(test_suite)
    finally:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Print summary to console
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    success_count = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"Success: {success_count}/{result.testsRun}")
    print(f"Failure: {len(result.failures)}/{result.testsRun}")
    print(f"Error: {len(result.errors)}/{result.testsRun}")
    print(f"Skip: {len(result.skipped)}/{result.testsRun}")
    print("="*70)

    # Write summary to log buffer
    _log_buffer.write("\n" + "="*70 + "\n")
    _log_buffer.write("TEST SUMMARY\n")
    _log_buffer.write("="*70 + "\n")
    _log_buffer.write(f"Tests run: {result.testsRun}\n")
    _log_buffer.write(f"Successes: {success_count}\n")
    _log_buffer.write(f"Failures: {len(result.failures)}\n")
    _log_buffer.write(f"Errors: {len(result.errors)}\n")
    _log_buffer.write(f"Skipped: {len(result.skipped)}\n")
    _log_buffer.write("="*70 + "\n")

    # Write complete log to file
    with open(log_filename, 'w') as f:
        f.write(_log_buffer.getvalue())
    print(f"\nDetailed log written to: {log_filename}")

    return result
