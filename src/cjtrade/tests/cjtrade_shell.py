# Interactive shell
# Supported commands:
#   help:   Show this help message
#   lsodr:  List all orders
#   lspos:  List all positions
#   exit:   Close interactive shell
from time import sleep, time
import pandas as pd
import subprocess
import asyncio
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Any
from dotenv import load_dotenv
from cjtrade.analytics.informational.news_client import *
from cjtrade.tests.test_basic_flow import *
from cjtrade.analytics.technical.strategies.fixed_price import *
from cjtrade.analytics.technical.models import *
from cjtrade.analytics.fundamental import *

exit_flag = False


load_dotenv()

config = {
    'api_key': os.environ["API_KEY"],
    'secret_key': os.environ["SECRET_KEY"],
    'ca_path': os.environ["CA_CERT_PATH"],
    'ca_passwd': os.environ["CA_PASSWORD"],
    'simulation': False  # Use production environment to see actual holdings
}

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
        df = df.drop(columns=['additional_note'], errors='ignore')
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

        # Print DataFrame with colored unrealized_pnl values
        if not df.empty and 'unrealized_pnl' in df.columns:
            # Get the formatted string without colors
            table_str = df.to_string()
            lines = table_str.split('\n')

            # Print header (first line)
            print(lines[0])

            # Print data rows with colored unrealized_pnl
            for i, line in enumerate(lines[1:], start=0):
                if i < len(df):
                    # Get the unrealized_pnl value for this row
                    pnl_value = df.iloc[i]['unrealized_pnl']
                    pnl_str = f"{pnl_value:.1f}"  # Match the format pandas uses

                    # Apply color to the pnl value in the line
                    if pnl_value > 0:
                        colored_line = line.replace(pnl_str, f"\033[91m{pnl_str}\033[0m", 1)
                    elif pnl_value < 0:
                        colored_line = line.replace(pnl_str, f"\033[92m{pnl_str}\033[0m", 1)
                    else:
                        colored_line = line

                    print(colored_line)
                else:
                    print(line)
        else:
            print(df)

        if not df.empty and 'unrealized_pnl' in df.columns:
            total_cost = (df['avg_cost'] * df['quantity']).sum()
            total_val = df['market_value'].sum()
            total_pnl = df['unrealized_pnl'].sum()
            pnl_pct = (total_pnl / total_cost * 100) if total_cost != 0 else 0.0
            print(f"\nTotal Cost: {total_cost:,.3f}")
            print(f"Market Value: {total_val:,.3f}")
            if pnl_pct >= 0:
                print(f"Total Unrealized PnL: \033[91m{total_pnl:,.3f} (+{pnl_pct:.2f}%)\033[0m")
            else:
                print(f"Total Unrealized PnL: \033[92m{total_pnl:,.3f} ({pnl_pct:.2f}%)\033[0m")

class RunAanalyticsCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "start"
        self.description = "Run analytics"
        self.params = ["symbol", "buy_target_price", "sell_target_price"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        buy = float(args[1])
        sell = float(args[2])

        strategy = FixedPriceStrategy(buy_target_price=buy, sell_target_price=sell)
        FILL_FLAG = False

        while not FILL_FLAG:

            snapshots = client.get_snapshots([Product(symbol=symbol)])
            snapshot = snapshots[0]
            print(f"fetch market state = O:{snapshot.open} H:{snapshot.high} L:{snapshot.low} C:{snapshot.close} V:{snapshot.volume}")

            # TODO: To be more accurate, caller may need to construct
            # their kbar of time unit they want, rather than using
            # the OHLCV info from `Snapshot`, since it is 1-day OHLCV.
            # The method here used to work with mock broker (since mock.get_snapshots()
            # acutally return exact one 1-min kbar).
            state = OHLCVState(ts=snapshot.timestamp, o=snapshot.open, h=snapshot.high,
                               l=snapshot.low, c=snapshot.close, v=snapshot.volume)

            intention = strategy.evaluate(state)

            if intention.action == SignalAction.BUY:
                print(f"\nAccept buy signal at price: {snapshot.close}, reason: {intention.reason}\n")
                order_result = client.buy_stock(symbol, quantity=100, price=snapshot.close + 0.1, intraday_odd=True)
                print(f"Order result: {order_result}")
                FILL_FLAG = True
            elif intention.action == SignalAction.SELL:
                print(f"\nAccept sell signal at price: {snapshot.close}, reason: {intention.reason}\n")
                order_result = client.sell_stock(symbol, quantity=100, price=snapshot.close - 0.1, intraday_odd=False)
                print(f"Order result: {order_result}")
                FILL_FLAG = True

            if not FILL_FLAG:
                sleep(60)


class BalanceCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "balance"
        self.description = "Show account balance"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        balance = client.get_balance()
        print(f"Account Balance: {balance}")


class AnnouncementCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "news"
        self.description = "Get recent important announcements"
        self.optional_params = ["days"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        days = int(args[0]) if len(args) > 0 else 3
        async def _async_get_announcement():
            async with CompanyInfoProvider() as provider:
                announcements = await provider.get_recent_announcements(days=days)
                print(f"Found {len(announcements)} announcements")
                for ann in announcements[:10]:
                    title = ann.title[:50] + "..." if len(ann.title) > 50 else ann.title
                    print(f"- {ann.symbol} {ann.company_name} {ann.event_date.strftime('%Y-%m-%d')} {title}")

        try:
            asyncio.run(_async_get_announcement())
        except Exception as e:
            print(f"Failed to get announcements: {e}")


class SearchOnlineNewsCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "search"
        self.description = "Search online news articles"
        self.variadic = True  # Accept variable number of symbols
        self.optional_args = ["query"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        news_client = NewsClient(provider_type=NewsProviderType.CNYES)
        # news_client = NewsClient(provider_type=NewsProviderType.MOCK)
        # news_client = NewsClient(provider_type=NewsProviderType.NEWS_API,
        #                          api_key=os.getenv("NEWSAPI_API_KEY", ""))
        print(f"source: {news_client.get_provider_name()}")
        if len(args) == 0:
            query = ""
            print("No search query provided, fetching latest news...")
        else:
            query = args[0]

        articles = []

        try:
            if query is None or query.strip() == "":
                articles = news_client.fetch_headline_news()
            else:
                articles = news_client.search_by_keyword(query)

            print(f"Found {len(articles)} articles.")
            for article in articles[:10]:
                title = article.title[:100] + "..." if len(article.title) > 100 else article.title
                print(f"- {title}")
        except Exception as e:
            print(f"Error searching news: {e}")



# TODO: Support start/end/interval parameters
class KbarsCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "kbars"
        self.params = ["symbol"]
        self.description = "Get K-bars (candlestick data)"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        # TODO: Mock only have one kbar in List, Sinopac should have all kbars in the query range
        kbars = client.get_kbars(Product(symbol=symbol), start="2026-01-07", end="2026-01-08", interval="1m")
        print(kbars)


class MoversCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "rank"
        self.description = "Rank market movers"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        movers = client.get_market_movers()
        if not movers:
            print("No market movers data available.")
            return
        df = pd.DataFrame(list(movers.items()), columns=['Symbol', 'Change'])
        print(df)


# TODO: Also need to test mock broker
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


class CalendarCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "date"
        self.description = "Show the calendar"
        self.optional_params = ["year"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        # yellow
        print("\033[93m")
        if os.name == 'nt':
            subprocess.run(['date', '/T'])
        else:
            subprocess.run(['date'])
        print("\033[0m")

        if len(args) == 1:
            exe_arr = ['cal', args[0]]
        else:
            exe_arr = ['cal']

        subprocess.run(exe_arr)



class InfoCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "info"
        self.description = "Shell info"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        try:
            subprocess.check_output(
                ["git", "rev-parse", "--is-inside-work-tree"],
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            return

        if Path("cjtrade_shell.py").is_file():
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            print(f"Interactive shell version: {commit}")
        print(f"Connected broker: {client.get_broker_name()}")
        print(f"News source: {NewsProviderType.CNYES.value}")


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


class KbarAggregationCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "replay"
        self.params = ["symbol", "range", "interval"]  # range means [T-range, T+1)
        self.description = "Replay historical K-bar and do aggregation"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        from cjtrade.chart.test_kbar_chart import test_sinopac_historical_kbars
        import webbrowser
        import os

        symbol = args[0]
        range_days = int(args[1])
        interval = args[2]

        # calculate the latest market date (Mon-Fri)
        from datetime import datetime, timedelta
        import pandas as pd

        today = datetime.now()

        # If today is Sat(5) or Sun(6), revert to last Friday
        if today.weekday() == 5:  # Saturday
            latest_market_date = today - timedelta(days=1)
        elif today.weekday() == 6:  # Sunday
            latest_market_date = today - timedelta(days=2)
        else:
            latest_market_date = today

        # Use BusinessDay to calculate start date (approx trading days)
        # range_days ago
        start_date_obj = latest_market_date - pd.tseries.offsets.BusinessDay(n=range_days)

        start_date = start_date_obj.strftime('%Y-%m-%d')
        end_date = (latest_market_date + timedelta(days=1)).strftime('%Y-%m-%d')

        print(f"Replay range: {start_date} -> {end_date} (Latest market date: {latest_market_date.strftime('%Y-%m-%d')})")

        def on_ready(filename):
            if filename:
                print(f"Opening chart: {filename}")
                webbrowser.open(f"file://{os.path.abspath(filename)}")

        test_sinopac_historical_kbars(on_ready=on_ready, symbol=symbol,
                                      start=start_date, end=end_date, interval=interval)


# ========== Command Registry ==========
command_registry: dict[str, CommandBase] = {}

def register_commands():
    """Register all available commands"""
    commands = [
        HelpCommand(),
        CalendarCommand(),
        BuyCommand(),
        SellCommand(),
        SnapshotCommand(),
        MoversCommand(),
        BidAskCommand(),
        ListOrdersCommand(),
        ListPositionsCommand(),
        RunAanalyticsCommand(),
        BalanceCommand(),
        AnnouncementCommand(),
        SearchOnlineNewsCommand(),
        KbarsCommand(),
        KbarAggregationCommand(),
        CancelAllCommand(),
        ClearCommand(),
        InfoCommand(),
        ExitCommand(),
    ]

    for cmd in commands:
        command_registry[cmd.name] = cmd


def set_exit_flag(client: AccountClient):
    global exit_flag
    exit_flag = True


# ========== Command Processing ==========
def process_command(cmd_line: str, client: AccountClient):
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
        cmd.execute(client, *args)
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
    print("  - mock (模擬環境)")
    print("Coming soon:")
    print("  - ibkr (盈透證券)")
    print("  - cathay (國泰證券)")
    print("  - mega (兆豐證券)")


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
    import sys
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-B", "--broker", type=str, required=True)
    args, shell_argv = parser.parse_known_args()
    # print(args)

    exit_code = 0  # Default success

    if args.broker == 'sinopac':
        client = AccountClient(BrokerType.SINOPAC, **config)
    elif args.broker == 'mock':
        real = AccountClient(BrokerType.SINOPAC, **config)
        client = AccountClient(BrokerType.MOCK, real_account=real)
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
            # Direct command execution mode
            # shell_argv[0] is command, shell_argv[1:] are its arguments
            command = shell_argv[0]
            args = shell_argv[1:]

            cmd_line = f"{command} {' '.join(args)}".strip()
            print(f"Executing: {cmd_line}")
            success = process_command(cmd_line, client)
            if not success:
                exit_code = 1
        else:
            # Regular interactive mode
            interactive_shell(client)

    except Exception as e:
        print(f"Fatal error: {e}")
        exit_code = 1
    finally:
        client.disconnect()

    sys.exit(exit_code)
