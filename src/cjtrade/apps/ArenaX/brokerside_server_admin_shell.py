import asyncio
import os
import subprocess
from abc import ABC
from abc import abstractmethod
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from time import sleep
from time import time
from typing import Any
from typing import List
from typing import Optional
from xmlrpc import client

import pandas as pd
from cjtrade.apps.ArenaX.arenax_middleware import ArenaXMiddleWare
from cjtrade.pkgs.analytics.fundamental import *
from cjtrade.pkgs.analytics.informational.news_client import *
from cjtrade.pkgs.analytics.technical.models import *
from cjtrade.pkgs.analytics.technical.strategies.fixed_price import *
from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.chart.kbar_client import KbarChartClient
from cjtrade.pkgs.chart.kbar_client import KbarChartType
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from cjtrade.pkgs.models import *
from dotenv import load_dotenv
# TODO: Simplify the import structure by adding __init__.py to commonly-used modules

exit_flag = False
interactive_mode = False  # Track if running in interactive mode

# ========== Command Pattern Implementation ==========
class CommandBase(ABC):
    """Base class for all commands"""

    def __init__(self):
        self.name: str = ""
        self.description: str = ""
        self.params: List[str] = []  # Parameter names
        self.optional_params: List[str] = []  # Optional parameter names
        self.variadic: bool = False  # If True, accepts variable number of arguments

    @abstractmethod
    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        """Execute the command with given arguments"""
        pass

    def validate_args(self, args: List[str]) -> bool:
        """Validate if provided arguments match required parameters"""
        required_count = len(self.params)
        total_count = required_count + len(self.optional_params)
        provided_count = len(args)

        # For variadic commands, only check minimum requirements
        if self.variadic:
            if provided_count < required_count:
                min_args = f"at least {required_count}" if required_count > 0 else "any number of"
                print(f"Error: '{self.name}' requires {min_args} arguments")
                return False
            return True

        # For fixed-arg commands, check exact requirements
        if provided_count < required_count:
            print(f"Error: '{self.name}' requires {required_count} arguments: {', '.join(self.params)}")
            if self.optional_params:
                print(f"Optional: {', '.join(self.optional_params)}")
            return False

        if provided_count > total_count:
            print(f"Error: '{self.name}' accepts at most {total_count} arguments")
            return False

        return True

    def get_help(self) -> str:
        """Return help text for this command"""
        param_str = " ".join([f"<{p}>" for p in self.params])
        optional_str = " ".join([f"[{p}]" for p in self.optional_params])

        # Add variadic indicator
        if self.variadic:
            param_str = f"{param_str} [...]" if param_str else "[...]"

        full_params = f"{param_str} {optional_str}".strip()

        if full_params:
            return f"{self.name} {full_params} - {self.description}"
        return f"{self.name} - {self.description}"


# ========== Concrete Command Implementations ==========

class HealthCheckCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "health"
        self.description = "Check server health status"
        self.params = []

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        print(client.check_health())


class ShowConfigCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "config"
        self.description = "Show current config"
        self.params = []

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        response = client.get_config()
        print("Server configuration:")
        for key, value in response["server_config"].items():
            print(f"  {key}: {value}")
        print("Backend configuration:")
        for key, value in response["backend_config"].items():
            print(f"  {key}: {value}")


class StartServerCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "start"
        self.description = "Start the backend server"

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        res = client.start_backend(headers={"X-Client": "admin-shell"})
        print(f"Start response: {res}")


class StopServerCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "stop"
        self.description = "Stop the backend server"

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        res = client.stop_backend(headers={"X-Client": "admin-shell"})
        print(f"Stop response: {res}")


class SetTimeCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "set-time"
        self.description = "Set mock init time"
        self.params = ["anchor_time"]  # format: YYYY-MM-DD

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        anchor_time = args[0]
        # parse to isoformat
        anchor_time = datetime.fromisoformat(anchor_time).isoformat()
        res = client.set_time(anchor_time, headers={"X-Client": "admin-shell"})
        print(f"Set-time response: {res}")


class PauseCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "pause"
        self.description = "Pause mock time progression"

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        res = client.pause_time_progress(headers={"X-Client": "admin-shell"})
        print(f"Pause response: {res}")


class ResumeCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "resume"
        self.description = "Resume mock time progression"

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        res = client.resume_time_progress(headers={"X-Client": "admin-shell"})
        print(f"Resume response: {res}")


class ShowTimeCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "time"
        self.description = "Show system time"
        self.params = []

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        res = client.get_system_time(headers={"X-Client": "admin-shell"})
        print(f"System time: {res}")


class QueryCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "query"
        self.description = "Get price of a symbol"
        self.params = ["symbol"]

    def execute(self, client: ArenaXMiddleWare, *args, **kwargs) -> None:
        symbol = args[0]
        res = client.get_price_from_exchange(symbol, headers={"X-Client": "admin-shell"})
        print(f"Price of {symbol}: {res}")


class ExitCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "exit"
        self.description = "Close interactive shell"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        global exit_flag
        exit_flag = True


class ClearCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "clear"
        self.description = "Clear the screen"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        import os
        import sys

        # Flush all output buffers before clearing to avoid mixed output
        sys.stdout.flush()
        sys.stderr.flush()

        # Only actually clear screen in interactive mode
        # In non-interactive mode (testing), just acknowledge the command
        if interactive_mode:
            os.system('cls' if os.name == 'nt' else 'clear')
        print_header()


class HelpCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "help"
        self.description = "Show this help message"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        for cmd in command_registry.values():
            print(f"  {cmd.get_help()}")


# ========== Command Registry ==========
command_registry: dict[str, CommandBase] = {}

def register_commands():
    """Register all available commands"""
    commands = [
        HealthCheckCommand(),
        ShowConfigCommand(),
        StartServerCommand(),
        StopServerCommand(),
        SetTimeCommand(),
        PauseCommand(),
        ResumeCommand(),
        ShowTimeCommand(),
        QueryCommand(),
        ExitCommand(),
        ClearCommand(),
        HelpCommand(),
    ]

    for cmd in commands:
        command_registry[cmd.name] = cmd


def set_exit_flag(client: AccountClient):
    global exit_flag
    exit_flag = True


# ========== Command Processing ==========
def process_command(cmd_line: str, client: ArenaXMiddleWare, **config: Any):
    """Parse and execute command with arguments"""
    cmd_line = cmd_line.strip()

    if not cmd_line:
        return True  # Empty command is okay

    # Split command and arguments
    parts = cmd_line.split()
    cmd_name = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    # Look up command
    cmd = command_registry.get(cmd_name)
    if cmd is None:
        print(f"Unknown command: '{cmd_name}'")
        print("Type 'help' to see available commands")
        return False

    # Validate arguments
    if not cmd.validate_args(args):
        return False

    # Execute command
    try:
        cmd.execute(client, *args, **config)
        return True
    except ValueError as e:
        print(f"Invalid argument: {e}")
        return False
    except Exception as e:
        print(f"Command failed: {e}")
        return False


# ========== Interactive Shell ==========
try:
    import readline
except ImportError:
    import pyreadline3 as readline

MAX_HISTORY_SIZE = 30

def init_readline():
    readline.set_history_length(MAX_HISTORY_SIZE)
    readline.parse_and_bind("tab: complete")

def print_header():
    # Red version
    print("\033[91m--------------------------------------------------------------------------\033[0m")
    print("\033[91mArenaX Server Admin Shell. Use it with caution!!!\033[0m")
    print("\033[91m--------------------------------------------------------------------------\033[0m")


def interactive_shell(client: AccountClient, config: dict = None):
    global exit_flag
    exit_flag = False

    if config is None:
        config = {}

    # Register all commands
    register_commands()

    # sleep 1 second
    sleep(1)
    process_command("clear", client, **config)
    init_readline()

    while not exit_flag:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            readline.add_history(cmd)
            process_command(cmd, client, **config)

        except (EOFError, KeyboardInterrupt):
            break
    print("Bye!")


def main():
    import sys
    import argparse

    # Force line buffering for stdout and stderr to keep output in order
    # This prevents stderr (errors/warnings from yfinance) and stdout (our logs)
    # from appearing out of order
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser()
    args, shell_argv = parser.parse_known_args()

    exit_code = 0  # Default success
    # Load supported config files (recursive search for *.cjconf under directories)
    loaded = load_supported_config_files()

    config = {
        'username': os.environ.get('USERNAME', 'arenax_admin'),
    }


    mid = ArenaXMiddleWare()

    try:
        # Register all commands
        register_commands()

        # Check if command line arguments are provided
        if shell_argv:
            # Direct command execution mode (non-interactive)
            global interactive_mode
            interactive_mode = False

            # shell_argv[0] is command, shell_argv[1:] are its arguments
            command = shell_argv[0]
            args = shell_argv[1:]

            cmd_line = f"{command} {' '.join(args)}".strip()
            print(f"Executing: {cmd_line}")
            success = process_command(cmd_line, mid, config=config)
            if not success:
                exit_code = 1
        else:
            # Regular interactive mode
            interactive_mode = True
            interactive_shell(mid, config=config)

    except Exception as e:
        print(f"Fatal error: {e}")
        exit_code = 1
    finally:
        pass

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
