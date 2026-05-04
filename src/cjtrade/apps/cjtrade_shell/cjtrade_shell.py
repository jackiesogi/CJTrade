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
# from cjtrade.apps.ArenaX.arenax_account_client import *
# from cjtrade.pkgs.brokers.account_client import *
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
        intraday_odd = bool(int(args[3])) if len(args) > 3 else True

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
        self.optional_params = ["num_result"]
        self.description = "List all orders"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        num_result = int(args[0]) if len(args) > 0 else 5
        print("=== Order List ===")
        try:
            orders = client.list_orders()
            orders.sort(key=lambda o: o.created_at, reverse=True)  # Sort by creation time
            print(f"Found {len(orders)} orders")

            if orders:
                print(f"\nRecent {num_result} orders:")
                for i, order in enumerate(orders[:num_result]):
                    print(f"\nOrder {i+1}:")
                    print(f"  Order ID: {order.id[:7]}")
                    print(f"  Created At: {order.created_at}")
                    print(f"  Symbol: {order.symbol}")
                    print(f"  Action: {order.action}")
                    print(f"  Quantity: {order.quantity}")
                    print(f"  Price: {order.price}")
                    print(f"  Status: {order.status}")
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

        if positions:
            df = pd.DataFrame([p.__dict__ for p in positions])

            # Print DataFrame with colored unrealized_pnl values
            if 'unrealized_pnl' in df.columns:
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

                        # Find the pnl string in the line (handle various float formats)
                        import re
                        # Match the number with optional sign, decimals
                        pnl_pattern = re.escape(f"{pnl_value:.1f}")
                        # Also try matching with more precision in case pandas formats differently
                        pnl_str_alternatives = [
                            f"{pnl_value:.1f}",
                            f"{pnl_value:.2f}",
                            f"{pnl_value:.0f}",
                        ]

                        colored_line = line
                        for pnl_str in pnl_str_alternatives:
                            if pnl_str in line:
                                # Apply color to the pnl value in the line
                                if pnl_value > 0:
                                    colored_line = line.replace(pnl_str, f"\033[91m{pnl_str}\033[0m", 1)
                                elif pnl_value < 0:
                                    colored_line = line.replace(pnl_str, f"\033[92m{pnl_str}\033[0m", 1)
                                break

                        print(colored_line)
                    else:
                        print(line)
            else:
                print(df)

            # Print summary statistics
            if 'unrealized_pnl' in df.columns:
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
        else:
            # No positions - display empty table with header
            columns = ['symbol', 'quantity', 'avg_cost', 'current_price', 'market_value', 'unrealized_pnl']
            header = " | ".join(columns)
            print(header)
            print("-" * len(header))
            print("  (You have no position, purchase stock using 'buy' command)")

class RunAanalyticsCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "start"
        self.description = "Run analytics"
        self.params = ["symbol", "buy_target_price", "sell_target_price", "delay"]

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        symbol = args[0]
        buy = float(args[1])
        sell = float(args[2])
        delay = int(args[3])

        strategy = FixedPriceStrategy(buy_target_price=buy, sell_target_price=sell)
        FILL_FLAG = False

        while not FILL_FLAG:

            snapshots = client.get_snapshots([Product(symbol=symbol)])
            snapshot = snapshots[0]
            print(f"market state = TS:{snapshot.timestamp} O:{snapshot.open} H:{snapshot.high} L:{snapshot.low} C:{snapshot.close} V:{snapshot.volume}")

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
                sleep(delay)


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

    def execute(self, client: AccountClient, *args, **config) -> None:
        selection = config.get('news_source', 'cnyes').lower()

        # TODO: parse all valid env var into config table
        # rather than user code need to find env var by their own.
        news_client = NewsClient(provider_type=selection, api_key=os.getenv("NEWSAPI_API_KEY", ""))

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


class LLMCommand(CommandBase):
    def __init__(self):
        super().__init__()
        from cjtrade.pkgs.llm.azure_openai import AzureOpenAIClient
        self.name = "llm"
        self.params = ["prompt"]
        self.description = "Generate a response using the LLM."
        self.llm = AzureOpenAIClient(
            api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        )

    def format_account_state(self, client: AccountClient, search_news: bool, **config) -> str:
        balance = client.get_balance()
        positions = client.get_positions()
        orders = client.list_orders()
        # Get news
        headelines = []
        if search_news:
            from cjtrade.pkgs.analytics.informational.news_client import NewsClient
            news_engine = NewsClient(provider_type="cnyes", api_key="")
            headelines = news_engine.fetch_headline_news(n=10)
        news = "\n".join([f"{n.title} {n.content}" for n in headelines])
        position_summary = "\n".join([f"{p.symbol}: {p.quantity} shares at avg cost {p.avg_cost}" for p in positions])
        recent_trades = "\n".join([f"{o.symbol} {o.action} {o.quantity} shares at {o.price} ({o.status})" for o in orders[-15:]])
        return f"Account Balance: {balance}\nPositions:\n{position_summary}; Recent News:\n{news}; Recent Trades:\n{recent_trades}"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        prompt = args[0]
        # check if prompt have specific keyword
        search_news_trigger_keywords = ["新聞", "近期", "趨勢", "分析", "看法", "觀點", "評論", "世界",
                                        "國際", "國內", "財經", "經濟", "政治", "社會", "科技", "產業"]
        if any(keyword in prompt for keyword in search_news_trigger_keywords):
            search_news = True
        else:
            search_news = False
        formatted_state_str = self.format_account_state(client, search_news=search_news)
        full_prompt = f"{formatted_state_str}\n\nUser Question: {prompt}:"
        print(self.llm.generate_response(full_prompt))


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


class CancelAllCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "cancel"
        self.description = "Cancel all active orders"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        try:
            # Use unified broker API interface
            orders = client.list_orders()

            print(f"{len(orders)} entries found.")

            cancelled_count = 0
            for i, order in enumerate(orders):
                try:
                    # print(order)
                    order_id = order.id
                    status = order.status
                    symbol = order.symbol

                    print(f"\nProcessing {i+1}/{len(orders)}")
                    print(f"  ID: {order_id}")
                    print(f"  Symbol: {symbol}")
                    print(f"  Status: {status}")

                    # Cancel orders that are not yet filled or already cancelled
                    # OrderStatus: PLACED, COMMITTED_WAIT_MARKET_OPEN, COMMITTED_WAIT_MATCHING, PARTIAL can be cancelled
                    # OrderStatus: FILLED, CANCELLED, REJECTED cannot be cancelled
                    if status in ['PLACED', 'COMMITTED_WAIT_MARKET_OPEN', 'COMMITTED_WAIT_MATCHING', 'PARTIAL',
                                 'PreSubmitted', 'Submitted', 'PartFilled']:
                        print(f"  → Trying to cancel...")
                        result = client.cancel_order(order_id)
                        if result.status == OrderStatus.CANCELLED:
                            print(f"  → Cancelled successfully")
                            cancelled_count += 1
                        else:
                            print(f"  → Cancel failed: {result.message}")
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

        # Get paths to utility scripts
        from pathlib import Path
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent.parent
        self.ncal_script = project_root / 'cjtrade' / 'pkgs' / 'utils' / 'ncal.py'
        self.date_script = project_root / 'cjtrade' / 'pkgs' / 'utils' / 'date.py'

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        import sys

        if len(args) == 1:
            arg = args[0]

            # Check if it's a time adjustment command (+N or -N)
            if arg.startswith(('+', '-')):
                if client.get_broker_name() != "arenax":
                    print("Error: Time adjustment only available in ArenaX environment")
                    return

                try:
                    hours = float(arg)
                    client.broker_api.api.market.adjust_time(hours)
                    # Show updated time
                    ts = client.broker_api.get_system_time()
                    print(f"New mock time: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
                    return
                except ValueError:
                    print(f"Error: Unable to parse time adjustment '{arg}'")
                    return
            else:
                # Direct call with date argument
                subprocess.run([sys.executable, str(self.ncal_script), '--sunday', arg], shell=False)
                return

        # Get timestamp from broker or system
        bkr_name = client.get_broker_name()
        if bkr_name == 'arenax' or bkr_name in ['mock', 'realistic']:  # for backward-compatibility
            suffix = " (mock time)"
            ts = client.broker_api.get_system_time()['mock_current_time']
        else:
            suffix = ""
            ts = datetime.now()

        # Display current date/time
        print("Current datetime" + suffix, end="")
        print("\033[93m")  # yellow

        # Use Python date script for cross-platform compatibility
        subprocess.run([sys.executable, str(self.date_script), '-d', f'@{int(ts.timestamp())}'], shell=False)

        print("\033[0m")

        # Display calendar
        subprocess.run([sys.executable, str(self.ncal_script), '--sunday', ts.strftime('%Y-%m-%d')], shell=False)


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

        if Path("src/cjtrade/core/cjtrade_shell.py").is_file():
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            print(f"Interactive shell version: {commit}")
        print(f"Connected broker: {client.get_broker_name()}")
        print(f"News source: {os.getenv('NEWS_SOURCE', 'cnyes')}")


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


class SystemCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "system"
        self.variadic = True  # Accept variable number of symbols
        self.optional_args = ["cmd"]
        self.description = "Execute OS command"

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

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        global exit_flag
        exit_flag = True


# Note: When using PURE mock client, the kbar data is from yfinance,
# which doesn't provide small interval kbars(1m/5m/15m/30m) if the date is over 1 month.
class KbarAggregationCommand(CommandBase):
    def __init__(self):
        super().__init__()
        self.name = "replay"
        self.params = ["symbol", "range", "interval"]  # range means [T-range, T+1)
        self.description = "Replay historical K-bar and do aggregation"

    def execute(self, client: AccountClient, *args, **kwargs) -> None:
        import webbrowser
        import os

        symbol = args[0]
        range_days = int(args[1])
        interval = args[2]

        # calculate the latest market date (Mon-Fri)
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

        get_historical_kbars_helper(client, on_ready=on_ready, symbol=symbol,
                                      start=start_date, end=end_date, interval=interval)


def get_historical_kbars_helper(client: AccountClient, on_ready=None, symbol="2308",
                                  start="2026-01-07", end="2026-01-08", interval="15m") -> str:
    product = Product(symbol=symbol)
    # Drawer setup
    drawer = KbarChartClient(
        chart_type=KbarChartType.PLOTLY,
        auto_save=True,
        width=1200,
        height=800
    )

    # Set product to generate filename
    drawer.set_product(product)
    drawer.set_theme('nordic')

    # Get only 2026-01-07 data using [start, end) exclusive range
    # end='2026-01-08' will exclude 2026-01-08, getting only 2026-01-07
    kbars = client.get_kbars(product, start=start, end=end, interval=interval)
    print(f"Total kbars: {len(kbars)}")

    first_run = True
    for kbar in kbars:
        drawer.append_kbar(kbar)

        if first_run and on_ready:
            on_ready(drawer.get_output_filename())
            first_run = False

        sleep(0.3)

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
        LLMCommand(),
        KbarAggregationCommand(),
        CancelAllCommand(),
        ClearCommand(),
        SystemCommand(),
        InfoCommand(),
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
