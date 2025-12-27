# Interactive shell
# Supported commands:
#   help:   Show this help message
#   lsodr:  List all orders
#   lspos:  List all positions
#   exit:   Close interactive shell
from time import sleep, time
import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Optional, Any
from cjtrade.core.account_client import AccountClient
from cjtrade.tests.test_basic_flow import *

exit_flag = False


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

class BuyCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "buy"
        self.description = "Place a buy order"
        self.params = ["symbol", "price", "quantity"]
        self.optional_params = ["intraday_odd"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        price = float(args[1])
        quantity = int(args[2])
        intraday_odd = bool(int(args[3])) if len(args) > 3 else True

        print(f"Buying {quantity} shares of {symbol} at {price} (intraday_odd={intraday_odd})")
        order_result = client.buy_stock(symbol, quantity=quantity, price=price, intraday_odd=intraday_odd)
        print(f"Order result: {order_result}")


class SellCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "sell"
        self.description = "Place a sell order"
        self.params = ["symbol", "price", "quantity"]
        self.optional_params = ["intraday_odd"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        price = float(args[1])
        quantity = int(args[2])
        intraday_odd = bool(int(args[3])) if len(args) > 3 else False

        print(f"Selling {quantity} shares of {symbol} at {price} (intraday_odd={intraday_odd})")
        order_result = client.sell_stock(symbol, quantity=quantity, price=price, intraday_odd=intraday_odd)
        print(f"Order result: {order_result}")


class SnapshotCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "ohlcv"
        self.description = "Get market snapshot for one or more symbols"
        self.params = ["symbol"]  # At least one symbol required
        self.variadic = True  # Accept variable number of symbols

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        products = [Product(symbol=symbol) for symbol in args]
        snapshots = client.get_snapshots(products)
        df = pd.DataFrame([s.__dict__ for s in snapshots])
        df = df.drop(columns=['exchange'], errors='ignore')
        print(df)


class BidAskCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "bidask"
        self.description = "Get bid/ask quote"
        self.params = ["symbol"]
        self.optional_params = ["intraday_odd"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        intraday_odd = bool(int(args[1])) if len(args) > 1 else False

        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )
        bid_ask = client.get_bid_ask(product, intraday_odd=intraday_odd)
        print(f"Bid/Ask for {symbol}: {bid_ask}")


class ListOrdersCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "lsodr"
        self.description = "List all orders"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        print("=== Order List ===")
        try:
            orders = client.list_orders()
            print(f"Found {len(orders)} orders")

            if orders:
                print("\nRecent 5 orders:")
                for i, order in enumerate(orders[-5:]):
                    print(f"\nOrder {i+1}:")
                    print(f"  Order ID: {order.get('id', 'N/A')}")
                    print(f"  Symbol: {order.get('symbol', 'N/A')}")
                    print(f"  Action: {order.get('action', 'N/A')}")
                    print(f"  Quantity: {order.get('quantity', 'N/A')}")
                    print(f"  Price: {order.get('price', 'N/A')}")
                    print(f"  Status: {order.get('status', 'N/A')}")
            else:
                print("No orders found")
        except Exception as e:
            print(f"Error: {e}")


class ListPositionsCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "lspos"
        self.description = "List all positions"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        positions = client.get_positions()
        df = pd.DataFrame([p.__dict__ for p in positions])
        print(df)


class BalanceCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "balance"
        self.description = "Show account balance"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        balance = client.get_balance()
        print(f"Account Balance: {balance}")


class MoversCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "rank"
        self.description = "Rank market movers"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        movers = client.get_market_movers()
        df = pd.DataFrame(list(movers.items()), columns=['Symbol', 'Change'])
        print(df)


class CancelAllCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "cancel"
        self.description = "Cancel all active orders"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        try:
            api = client.broker.api
            api.update_status()
            trades = api.list_trades()

            print(f"{len(trades)} entries found.")

            cancelled_count = 0
            for i, trade in enumerate(trades):
                try:
                    status = trade.status.status.value
                    print(f"\nProcessing {i+1}/{len(trades)}")
                    print(f"  ID: {trade.status.id}")
                    print(f"  Product: {getattr(trade.contract, 'code', 'N/A')}")
                    print(f"  Status: {status}")

                    if status in ['PreSubmitted', 'Submitted', 'PartialFilled']:
                        print(f"  → Trying to cancel...")
                        result = api.cancel_order(trade)
                        print(f"  → Cancel result: {result}")
                        cancelled_count += 1
                    else:
                        print(f"  → Skipping (Status: {status})")

                except Exception as e:
                    print(f"  → Cancel failed: {e}")

            print(f"\n=== Processing complete ===")
            print(f"Attempted to cancel {cancelled_count} orders")

        except Exception as e:
            print(f"Error occurred while canceling orders: {e}")


class HelpCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "help"
        self.description = "Show this help message"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        for cmd in command_registry.values():
            print(f"  {cmd.get_help()}")


class ClearCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "clear"
        self.description = "Clear the screen"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        import os
        os.system('cls' if os.name == 'nt' else 'clear')


class ExitCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "exit"
        self.description = "Close interactive shell"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        global exit_flag
        exit_flag = True


# ========== Command Registry ==========
command_registry: dict[str, CommandBase] = {}

def register_commands():
    """Register all available commands"""
    commands = [
        HelpCommand(),
        BuyCommand(),
        SellCommand(),
        SnapshotCommand(),
        MoversCommand(),
        BidAskCommand(),
        ListOrdersCommand(),
        ListPositionsCommand(),
        BalanceCommand(),
        CancelAllCommand(),
        ClearCommand(),
        ExitCommand(),
    ]

    for cmd in commands:
        command_registry[cmd.name] = cmd


def set_exit_flag(client: AccountClient):
    global exit_flag
    exit_flag = True


# ========== Legacy Test Functions (kept for reference) ==========
def test_sinopac_buy_0050(client: AccountClient):
    order_result = client.buy_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")

def test_sinopac_sell_0050(client: AccountClient):
    order_result = client.sell_stock("0050", quantity=2, price=62.6, intraday_odd=True)
    print(f"--- order_result: {order_result}")

def test_sinopac_bidask_0050(client: AccountClient):
    product = Product(
        type=ProductType.STOCK,
        exchange=Exchange.TSE,
        symbol="0050"
    )
    bid_ask = client.get_bid_ask(product, intraday_odd=True)
    print(f"Bid/Ask for 0050: {bid_ask}")

def test_sinopac_get_account_positions(client: AccountClient):
    positions = client.get_positions()

    df = pd.DataFrame([p.__dict__ for p in positions])
    print(df)


def test_sinopac_get_account_balance(client: AccountClient):
    balance = client.get_balance()
    print(f"Account Balance: {balance}")


def test_sinopac_cancel_all_orders(client: AccountClient):
    try:
        api = client.broker.api
        api.update_status()
        trades = api.list_trades()

        print(f"{len(trades)} entries found.")

        cancelled_count = 0
        for i, trade in enumerate(trades):
            try:
                # Only cancel orders that are not yet filled
                status = trade.status.status.value
                print(f"\nProcessing {i+1}/{len(trades)}")
                print(f"  ID: {trade.status.id}")
                print(f"  Product: {getattr(trade.contract, 'code', 'N/A')}")
                print(f"  Status: {status}")
                print(f"  Quantity: {trade.order.quantity}")
                print(f"  Price: {trade.order.price}")

                # Only cancel orders that are not yet filled
                if status in ['PreSubmitted', 'Submitted', 'PartialFilled']:
                    print(f"  → Trying to cancel...")
                    result = api.cancel_order(trade)
                    print(f"  → Cancel result: {result}")
                    cancelled_count += 1
                else:
                    print(f"  → Skipping (Status: {status})")

            except Exception as e:
                print(f"  → Cancel failed: {e}")

        print(f"\n=== Processing complete ===")
        print(f"Attempted to cancel {cancelled_count} orders")

        # Check cancellation results
        print("\n=== Check cancellation results ===")
        api.update_status()
        remaining_trades = api.list_trades()
        active_orders = [t for t in remaining_trades if t.status.status.value in ['PreSubmitted', 'Submitted', 'PartialFilled']]
        print(f"Remaining active orders: {len(active_orders)}")

        if active_orders:
            print("Still have active orders:")
            for trade in active_orders:
                print(f"  ID: {trade.status.id}, Status: {trade.status.status.value}")
        else:
            print("All orders have been successfully canceled or completed")

    except Exception as e:
        print(f"Error occurred while canceling orders: {e}")


def test_sinopac_list_orders_real(client: AccountClient):
    print("=== Test Order List Query ===")

    try:
        orders = client.list_orders()
        print(f"Found {len(orders)} orders")

        if orders:
            print("\nRecent 5 orders:")
            for i, order in enumerate(orders[-5:]):
                print(f"\nOrder {i+1}:")
                print(f"  Order ID: {order.get('id', 'N/A')}")
                print(f"  Symbol: {order.get('symbol', 'N/A')}")
                print(f"  Action: {order.get('action', 'N/A')}")
                print(f"  Quantity: {order.get('quantity', 'N/A')}")
                print(f"  Price: {order.get('price', 'N/A')}")
                print(f"  Status: {order.get('status', 'N/A')}")
                print(f"  Order Type: {order.get('order_type', 'N/A')}")
                print(f"  Price Type: {order.get('price_type', 'N/A')}")
                print(f"  Order Lot: {order.get('order_lot', 'N/A')}")
                print(f"  Order Time: {order.get('order_datetime', 'N/A')}")
                print(f"  Deals: {order.get('deals', 'N/A')}")
                print(f"  Order Number: {order.get('ordno', 'N/A')}")
        else:
            print("No orders found")

    except Exception as e:
        print(f"Error occurred while querying orders: {e}")


def show_help(client: AccountClient):
    print("help:    Show this help message")
    print("clear:   Clear the screen")
    print("lsodr:   List all orders")
    print("lspos:   List all positions")
    print("buy:     Place a buy order for 0050")
    print("sell:    Place a sell order for 0050")
    print("snap:    Get market snapshot for 0050")
    print("bidask:  Get bid/ask for 0050")
    print("cancel:  Cancel all active orders")
    print("balance: Show account balance")
    print("exit:    Close interactive shell")


def clear_screen(client: AccountClient):
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


def test_sinopac_get_snapshot_0050(client: AccountClient):
    product = Product(symbol="0050")
    snapshots = client.get_snapshots([product])
    df = pd.DataFrame([s.__dict__ for s in snapshots])
    print(df)


# ========== Command Processing ==========
def process_command(cmd_line: str, client: AccountClient):
    """Parse and execute command with arguments"""
    cmd_line = cmd_line.strip()

    if not cmd_line:
        return

    # Split command and arguments
    parts = cmd_line.split()
    cmd_name = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    # Look up command
    cmd = command_registry.get(cmd_name)
    if cmd is None:
        print(f"Unknown command: '{cmd_name}'")
        print("Type 'help' to see available commands")
        return

    # Validate arguments
    if not cmd.validate_args(args):
        return

    # Execute command
    try:
        cmd.execute(client, *args)
    except ValueError as e:
        print(f"Invalid argument: {e}")
    except Exception as e:
        print(f"Command failed: {e}")



# ========== Interactive Shell ==========
import readline
MAX_HISTORY_SIZE = 30

def init_readline():
    readline.set_history_length(MAX_HISTORY_SIZE)
    readline.parse_and_bind("tab: complete")

def interactive_shell(client: AccountClient):
    global exit_flag
    exit_flag = False

    # Register all commands
    register_commands()

    # sleep 1 second
    sleep(1)
    process_command("clear", client)
    init_readline()
    print("\033[93m--------------------------------------------------------------------------\033[0m")
    print("\033[93mCJTrade Interactive Shell. Type 'help' for commands... (b^-^)b\033[0m")
    print("\033[93m--------------------------------------------------------------------------\033[0m")

    while not exit_flag:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            readline.add_history(cmd)
            process_command(cmd, client)

        except (EOFError, KeyboardInterrupt):
            break
    print("Bye!")


if __name__ == "__main__":
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    interactive_shell(client)
    client.disconnect()
