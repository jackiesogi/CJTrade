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

import pandas as pd
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
        self.example: str = ""  # Example usage string

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
            if self.example:
                print(f"Example: {self.example}")
            return False

        if provided_count > total_count:
            print(f"Error: '{self.name}' accepts at most {total_count} arguments")
            if self.example:
                print(f"Example: {self.example}")
            return False

        return True

    def _usage_line(self) -> str:
        """One-line usage: name <params> [optional] - description"""
        param_str = " ".join([f"<{p}>" for p in self.params])
        optional_str = " ".join([f"[{p}]" for p in self.optional_params])
        if self.variadic:
            param_str = f"{param_str} [...]" if param_str else "[...]"
        full_params = f"{param_str} {optional_str}".strip()
        if full_params:
            return f"{self.name} {full_params} - {self.description}"
        return f"{self.name} - {self.description}"

    def get_help(self) -> str:
        """Short one-line help (used by 'help' listing)."""
        return self._usage_line()

    def get_detailed_help(self) -> str:
        """Full help with example (used by 'help <cmd>' and validation errors)."""
        lines = [self._usage_line()]
        if self.example:
            lines.append(f"  Example: {self.example}")
        return "\n".join(lines)


# ========== Concrete Command Implementations ==========

class CreateCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "buy"
        self.description = "Place a buy order"
        self.params = ["symbol", "price", "quantity"]
        self.optional_params = ["intraday_odd"]
        self.example = "buy 0050 20.25 80"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        price = float(args[1])
        quantity = int(args[2])
        intraday_odd = bool(int(args[3])) if len(args) > 3 else True

        print(f"Buying {quantity} shares of {symbol} at {price} (intraday_odd={intraday_odd})")
        order_result = client.buy_stock(symbol, quantity=quantity, price=price, intraday_odd=intraday_odd)
        print(f"Order result: {order_result}")


class ListCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "sell"
        self.description = "Place a sell order"
        self.params = ["symbol", "price", "quantity"]
        self.optional_params = ["intraday_odd"]
        self.example = "sell 0050 30.65 120"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        price = float(args[1])
        quantity = int(args[2])
        intraday_odd = bool(int(args[3])) if len(args) > 3 else True

        print(f"Selling {quantity} shares of {symbol} at {price} (intraday_odd={intraday_odd})")
        order_result = client.sell_stock(symbol, quantity=quantity, price=price, intraday_odd=intraday_odd)
        print(f"Order result: {order_result}")


class SetCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "ohlcv"
        self.description = "Get market snapshot for one or more symbols"
        self.params = ["symbol"]  # At least one symbol required
        self.variadic = True  # Accept variable number of symbols
        self.example = "ohlcv 2330 0050 2317"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        products = [Product(symbol=symbol) for symbol in args]
        snapshots = client.get_snapshots(products)

        # Create DataFrame and reorder columns to highlight close price
        df = pd.DataFrame([s.__dict__ for s in snapshots])
        df = df.drop(columns=['exchange'], errors='ignore')
        df = df.drop(columns=['additional_note'], errors='ignore')

        # Reorder columns: symbol, timestamp, close, open, high, low, volume, ...
        if 'close' in df.columns:
            cols = ['symbol', 'timestamp', 'close', 'open', 'high', 'low', 'volume']
            other_cols = [c for c in df.columns if c not in cols]
            df = df[[c for c in cols if c in df.columns] + other_cols]

        print(df)


class HelpCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "help"
        self.description = "Show this help message"
        self.optional_params = ["command"]
        self.example = "help buy"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        if args:
            cmd_name = args[0]
            cmd = command_registry.get(cmd_name)
            if cmd:
                print(cmd.get_detailed_help())
            else:
                print(f"Unknown command: '{cmd_name}'")
        else:
            for cmd in command_registry.values():
                print(f"  {cmd.get_help()}")


class ClearCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "clear"
        self.description = "Clear the screen"
        self.example = "clear"

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


class SystemCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "system"
        self.variadic = True  # Accept variable number of symbols
        self.optional_args = ["cmd"]
        self.description = "Execute OS command"
        self.example = "system uname -a"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        if len(args) == 0:
            import platform
            print("OS:", platform.system())
            print("OS version:", platform.version())
            print("Release:", platform.release())
            print("Machine:", platform.machine())
            print("Processor:", platform.processor())
            print("Architecture:", platform.architecture())
            print("Full platform:", platform.platform())
        else:
            import subprocess
            # Join args into a single command string to support shell builtins (export, source, etc.)
            cmd_str = ' '.join(args)
            ret = subprocess.run(cmd_str, shell=True)
            print(ret.returncode)


class ExitCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "exit"
        self.description = "Close interactive shell"
        self.example = "exit"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        global exit_flag
        exit_flag = True


# ========== Command Registry ==========
command_registry: dict[str, CommandBase] = {}

def register_commands():
    """Register all available commands"""
    commands = [
        HelpCommand(),
        CreateCommand(),
        ListCommand(),
        SetCommand(),
        ClearCommand(),
        SystemCommand(),
        ExitCommand(),
    ]

    for cmd in commands:
        command_registry[cmd.name] = cmd


def set_exit_flag(client: AccountClient):
    global exit_flag
    exit_flag = True


# ========== Command Processing ==========
def process_command(cmd_line: str, client: AccountClient, **config: Any):
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

def print_supported_brokers():
    print("Currently supported:")
    print("  - sinopac (永豐金證券)")
    print("  - arenax (模擬環境)")
    print("Coming soon:")
    print("  - ibkr (盈透證券)")
    print("  - cathay (國泰證券)")
    print("  - mega (兆豐證券)")


# ========== Interactive Shell ==========
try:
    import readline
except ImportError:
    import pyreadline3 as readline

MAX_HISTORY_SIZE = 30

def init_readline():
    readline.set_history_length(MAX_HISTORY_SIZE)
    readline.parse_and_bind("tab: complete")

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
    print("\033[93m--------------------------------------------------------------------------\033[0m")
    print("\033[93mCJTrade Interactive Shell. Type 'help' for commands... (b^-^)b\033[0m")
    print("\033[93m--------------------------------------------------------------------------\033[0m")

    while not exit_flag:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            # readline.add_history(cmd)
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
    parser.add_argument("-B", "--broker", type=str, required=True)
    args, shell_argv = parser.parse_known_args()
    # print(args)

    exit_code = 0  # Default success
    # Load supported config files (recursive search for *.cjconf under directories)
    loaded = load_supported_config_files()

    config = {
        'api_key': os.environ["API_KEY"],
        'secret_key': os.environ["SECRET_KEY"],
        'ca_path': os.environ["CA_CERT_PATH"],
        'ca_passwd': os.environ["CA_PASSWORD"],
        'simulation': True if os.environ.get("SIMULATION") == "y" else False,

        'username': os.environ.get('USERNAME', 'user000'),
        'news_source': os.environ.get('NEWS_SOURCE', 'cnyes'),
        # 'mirror_db_path': './data/mock_user000.db',
        'arenax_host': os.environ.get('ARENAX_HOST', 'localhost'),
        'arenax_port': int(os.environ.get('ARENAX_PORT', 8801)),
    }


    if args.broker == 'sinopac':
        config["state_file"] = f"./sinopac_{config['username']}.json"
        config["mirror_db_path"] = f"./data/sinopac_{config['username']}.db"
        client = AccountClient(BrokerType.SINOPAC, **config)
    elif args.broker == 'mock':
        if os.environ.get("ALLOW_LEGACY_BROKER") != "y":
            raise Exception("This shell is not intended to be used with legacy broker, test ArenaX instead or set 'ALLOW_LEGACY_BROKER=y'")
        else:
            config["speed"] = 120.0  # 120x speed for mock broker
            config["state_file"] = f"./mock_{config['username']}.json"
            config["mirror_db_path"] = f"./data/mock_{config['username']}.db"
            client = AccountClient(BrokerType.MOCK, **config)
    elif args.broker == 'realistic':
        if os.environ.get("ALLOW_LEGACY_BROKER") != "y":
            raise Exception("This shell is not intended to be used with legacy broker, test ArenaX instead or set 'ALLOW_LEGACY_BROKER=y'")
        else:
            config["speed"] = 60.0  # 60x speed for mock broker
            config["state_file"] = f"./realistic_{config['username']}.json"
            config["mirror_db_path"] = f"./data/realistic_{config['username']}.db"
            real = AccountClient(BrokerType.SINOPAC, **config)
            client = AccountClient(BrokerType.MOCK, real_account=real, **config)
    elif args.broker == 'arenax_legacy':
        config["speed"] = 60.0  # 60x speed for mock broker
        config["state_file"] = f"./arenax_{config['username']}.json"
        config["mirror_db_path"] = f"./data/arenax_{config['username']}.db"
        real = AccountClient(BrokerType.SINOPAC, **config)
        client = AccountClient(BrokerType.ARENAX, real_account=real, **config)
    elif args.broker == "arenax":
        # call config setting api to configure the broker server
        config['api_key'] = 'testkey123'
        client = AccountClient(BrokerType.ARENAX, **config)
    elif args.broker in ['cathay', 'ibkr', 'mega']:
        print(f"Broker '{args.broker}' is currently not supported (coming soon)")
        print_supported_brokers()
        exit(0)
    else:
        print(f"Broker '{args.broker}' will not be supported anytime soon")
        print_supported_brokers()
        exit(0)

    client.connect()

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
            success = process_command(cmd_line, client, config=config)
            if not success:
                exit_code = 1
        else:
            # Regular interactive mode
            interactive_mode = True
            interactive_shell(client, config=config)

    except Exception as e:
        print(f"Fatal error: {e}")
        exit_code = 1
    finally:
        client.disconnect()

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
