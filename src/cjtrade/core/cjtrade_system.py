"""
Minimal Viable Trading System PoC
"""
import asyncio
import logging
import os
import signal
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.core.account_client import AccountClient
from cjtrade.core.account_client import BrokerType
from cjtrade.core.config_loader import load_supported_config_files
from cjtrade.llm.gemini import GeminiClient
from cjtrade.models import OrderAction
from cjtrade.models import Position
from cjtrade.models import Product
from dotenv import load_dotenv


# ==================== Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("cjtrade.system")

PRICE_MONITOR_INTERVAL = 2   # seconds
ANALYSIS_INTERVAL = 30       # seconds
LLM_REPORT_INTERVAL = 400    # seconds (5 minutes)
RISK_MAX_POSITION_PCT = 0.05 # 5% of total equity per trade
WINDOW_SIZE = 10             # Number of price points for Bollinger Bands calculation

SHUTDOWN = False
BACKTEST_MODE = True         # Start in backtest mode
BACKTEST_DURATION_DAYS = 1
BB_MIN_WIDTH_PCT = 0.005     # Minimum Bollinger Bands width (0.5%) to consider valid signals


# ==================== Mock Bollinger Bands ====================
# TODO: Replace with actual talib implementation
def calculate_bollinger_bands_mock(symbol: str, prices: List[float]) -> Dict:
    if not prices or len(prices) == 0:
        return None

    current_price = prices[-1]

    # Mock calculation (simple moving average approximation)
    window = min(WINDOW_SIZE, len(prices))
    recent_prices = prices[-window:]

    # Need at least WINDOW_SIZE data points for reliable BB calculation
    if len(recent_prices) < WINDOW_SIZE:
        log.debug(f"BB {symbol}: Insufficient data ({len(recent_prices)}/{WINDOW_SIZE} prices)")
        return None

    middle = sum(recent_prices) / len(recent_prices)
    std_dev = (sum((p - middle) ** 2 for p in recent_prices) / len(recent_prices)) ** 0.5

    upper = middle + (2 * std_dev)
    lower = middle - (2 * std_dev)

    # Avoid signals when bands are too narrow (low volatility / insufficient data)
    band_width = (upper - lower) / middle if middle > 0 else 0

    # Debug info
    log.info(f"BB Debug [{symbol}]: Price={current_price:.2f} | "
             f"Upper={upper:.2f} Mid={middle:.2f} Lower={lower:.2f} | "
             f"StdDev={std_dev:.2f} BandWidth={band_width*100:.2f}%")

    if band_width < BB_MIN_WIDTH_PCT:  # Less than 0.5% width
        log.info(f"⚪ BB {symbol}: Band too narrow ({band_width*100:.2f}% < {BB_MIN_WIDTH_PCT*100:.2f}%), signal=HOLD")
        signal = 'HOLD'
    else:
        # Generate signal based on Bollinger Bands strategy
        # Price touching lower band (oversold) → BUY
        # Price touching upper band (overbought) → SELL
        signal = 'HOLD'
        if current_price <= lower:
            signal = 'BUY'
            log.info(f"🟢 BB {symbol}: Price {current_price:.2f} <= Lower {lower:.2f} → BUY")
        elif current_price >= upper:
            signal = 'SELL'
            log.info(f"🔴 BB {symbol}: Price {current_price:.2f} >= Upper {upper:.2f} → SELL")
        else:
            log.info(f"⚪ BB {symbol}: Price in middle band → HOLD")

    return {
        'upper': round(upper, 2),
        'middle': round(middle, 2),
        'lower': round(lower, 2),
        'signal': signal,
        'price': current_price,
        'symbol': symbol,
        'std_dev': round(std_dev, 2),
        'band_width': round(band_width * 100, 2)  # as percentage
    }


# ==================== Trading System Class ====================
class TradingSystem:
    def __init__(self, client: AccountClient):
        self.client = client
        self.price_history: Dict[str, List[float]] = {}
        self.analysis_results: Dict[str, Dict] = {}
        self.llm_client: Optional[GeminiClient] = None

        # Use mock market time if available, otherwise real time
        if hasattr(self.client.broker_api, 'get_system_time'):
            self.start_time = self.client.broker_api.get_system_time()
            log.info(f"⏰ Using mock market start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.start_time = datetime.now()
            log.info(f"⏰ Using real system time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.backtest_mode = BACKTEST_MODE
        self.trade_log: List[Dict] = []  # Track all buy/sell actions
        self.strategy_cash_flow = 0.0  # Track net cash flow from strategy trades (buy = negative, sell = positive)

        # Track initial state for P&L calculation
        self.initial_balance = self.client.get_balance()
        self.initial_positions = self.client.get_positions()
        self.initial_equity = self.get_total_equity()

        # Record initial positions details to exclude their market value changes
        self.initial_position_symbols = set(p.symbol for p in self.initial_positions)
        log.info(f"📊 Initial State: Balance={self.initial_balance:.2f}, Equity={self.initial_equity:.2f}")
        log.info(f"💼 Existing positions: {', '.join(self.initial_position_symbols) if self.initial_position_symbols else 'None'}")

        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                self.llm_client = GeminiClient(api_key=api_key)
                log.info("LLM client initialized")
            except Exception as e:
                log.warning(f"Failed to initialize LLM client: {e}")
        else:
            log.warning("GEMINI_API_KEY not found, LLM reports disabled")

    def get_watch_symbols(self) -> List[str]:
        """Get list of symbols to monitor from current positions"""
        try:
            positions = self.client.get_positions()
            if positions:
                symbols = [p.symbol for p in positions]
                log.info(f"Watching {len(symbols)} symbols from positions: {', '.join(symbols)}")
                return symbols
            else:
                # No positions, return empty list
                log.warning("No positions found, nothing to monitor")
                return []
        except Exception as e:
            log.error(f"Failed to get positions: {e}")
            return []

    def get_total_equity(self) -> float:
        """Calculate total equity (balance + position value)"""
        try:
            balance = self.client.get_balance()
            positions = self.client.get_positions()

            position_value = sum(p.market_value for p in positions) if positions else 0
            return balance + position_value
        except Exception as e:
            log.error(f"Failed to get total equity: {e}")
            return 0.0

    def calculate_position_size(self, price: float) -> int:
        """Calculate safe position size based on risk control"""
        total_equity = self.get_total_equity()
        max_value = total_equity * RISK_MAX_POSITION_PCT

        # Calculate quantity (round down to nearest lot)
        quantity = int(max_value / price)

        # Minimum 1 share if we have enough equity
        if quantity < 1 and total_equity > price:
            quantity = 1

        log.info(f"Position sizing: equity={total_equity:.2f}, max_value={max_value:.2f}, quantity={quantity}")
        return quantity

    def should_exit_backtest(self) -> bool:
        """Check if backtest period is over"""
        if not self.backtest_mode:
            return False

        # Use mock market time if available
        if hasattr(self.client.broker_api, 'get_system_time'):
            current_time = self.client.broker_api.get_system_time()
        else:
            current_time = datetime.now()

        elapsed = current_time - self.start_time
        if elapsed.days >= BACKTEST_DURATION_DAYS:
            log.info(f"Backtest completed: {elapsed.days} days elapsed (mock market time)")
            return True
        return False

    def print_backtest_summary(self):
        """Print final P&L summary after backtest"""
        final_balance = self.client.get_balance()
        final_positions = self.client.get_positions()
        final_equity = self.get_total_equity()

        # Calculate total equity change (includes existing positions' market movements)
        total_equity_change = final_equity - self.initial_equity
        total_equity_change_pct = (total_equity_change / self.initial_equity * 100) if self.initial_equity > 0 else 0

        # Calculate strategy-specific P&L
        # Strategy P&L = change in balance + unrealized P&L of strategy-opened positions
        balance_change = final_balance - self.initial_balance

        # Get unrealized P&L only from positions opened by strategy (not in initial positions)
        strategy_position_value = 0.0
        for p in final_positions:
            if p.symbol not in self.initial_position_symbols:
                strategy_position_value += p.unrealized_pnl

        strategy_pnl = balance_change + strategy_position_value

        print("\n" + "="*80)
        print("🎯 BACKTEST SUMMARY")
        print("="*80)
        print(f"Duration: {BACKTEST_DURATION_DAYS} days")
        print(f"\nInitial State:")
        print(f"  Balance:   {self.initial_balance:>12,.2f}")
        print(f"  Equity:    {self.initial_equity:>12,.2f}")
        print(f"  Positions: {len(self.initial_positions)}")
        print(f"\nFinal State:")
        print(f"  Balance:   {final_balance:>12,.2f}")
        print(f"  Equity:    {final_equity:>12,.2f}")
        print(f"  Positions: {len(final_positions)}")
        print(f"\nP&L Analysis:")
        print(f"  Strategy P&L:     {strategy_pnl:>12,.2f} 🎯 (from {len(self.trade_log)} trades)")
        print(f"  Total Equity Δ:   {total_equity_change:>12,.2f} ({total_equity_change_pct:+.2f}%) 📈 (includes existing positions)")
                # Print trade log
        print(f"\nTrade History ({len(self.trade_log)} trades):")
        if self.trade_log:
            for i, trade in enumerate(self.trade_log, 1):
                action_symbol = "🟢" if trade['action'] == 'BUY' else "🔴"
                timestamp = trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {i}. [{timestamp}] {action_symbol} {trade['action']} {trade['quantity']} shares of {trade['symbol']} at {trade['price']:.2f} ({trade['reason']})")
        else:
            print("  No trades executed during backtest")

        if strategy_pnl > 0:
            print(f"\n✅ 策略為您帶來了 {strategy_pnl:,.2f} 的收益")
        elif strategy_pnl < 0:
            print(f"\n❌ 策略產生了 {abs(strategy_pnl):,.2f} 的虧損")
        else:
            print(f"\n⚪ 策略無損益（未執行交易或損益持平）")

        print("="*80 + "\n")

    async def monitor_prices(self):
        """Task 1: Continuous price monitoring"""
        log.info("Price monitoring started")

        while not SHUTDOWN:
            try:
                # Dynamically get symbols from current positions
                symbols = self.get_watch_symbols()

                if not symbols:
                    await asyncio.sleep(PRICE_MONITOR_INTERVAL)
                    continue

                for symbol in symbols:
                    snapshots = self.client.get_snapshots([Product(symbol=symbol)])

                    if snapshots:
                        snapshot = snapshots[0]
                        price = snapshot.close

                        # Initialize history if new symbol
                        if symbol not in self.price_history:
                            self.price_history[symbol] = []

                        # Store price history
                        self.price_history[symbol].append(price)
                        history_len = len(self.price_history[symbol])

                        # Keep last 100 prices
                        if history_len > 100:
                            self.price_history[symbol] = self.price_history[symbol][-100:]

                        log.info(f"  {symbol}: {price:.2f} (O:{snapshot.open:.2f} H:{snapshot.high:.2f} L:{snapshot.low:.2f}) | History: {history_len} prices")

            except Exception as e:
                log.error(f"Price monitoring error: {e}")

            await asyncio.sleep(PRICE_MONITOR_INTERVAL)

    async def analyze_signals(self):
        """Task 2: Bollinger Bands analysis"""
        log.info("Signal analysis started")

        while not SHUTDOWN:
            try:
                # Analyze all symbols we have price history for
                symbols = list(self.price_history.keys())
                log.info(f"Analyzing {len(symbols)} symbols: {symbols}")

                for symbol in symbols:
                    history_len = len(self.price_history.get(symbol, []))

                    if history_len < WINDOW_SIZE:
                        continue

                    # Run Bollinger Bands analysis
                    result = calculate_bollinger_bands_mock(
                        symbol,
                        self.price_history[symbol]
                    )

                    if result:
                        self.analysis_results[symbol] = result
                    else:
                        log.warning(f"{symbol}: BB calculation returned None")

            except Exception as e:
                log.error(f"Analysis error: {e}")

            await asyncio.sleep(ANALYSIS_INTERVAL)

    async def generate_llm_report(self):
        """Task 3: LLM summary reports"""
        log.info("LLM report generator started")

        while not SHUTDOWN:
            try:
                if not self.llm_client:
                    await asyncio.sleep(LLM_REPORT_INTERVAL)
                    continue

                # Collect current state
                positions = self.client.get_positions()
                balance = self.client.get_balance()

                # Build prompt
                prompt = f"""
                    作為量化交易分析師，請分析以下交易系统狀態並提供簡短建議：
                    時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    帳戶餘額: ${balance:,.2f}
                    持倉數量: {len(positions) if positions else 0}
                    持倉明細:
                """
                if positions:
                    for p in positions:
                        prompt += f"- {p.symbol}: {p.quantity}股 @${p.avg_cost:.2f}, 當前${p.current_price:.2f}, 盈虧${p.unrealized_pnl:,.2f}\n"
                else:
                    prompt += "- 無持倉\n"

                prompt += f"\n技術指標信號:\n"
                for symbol, result in self.analysis_results.items():
                    prompt += f"- {symbol}: {result['signal']} (價格${result['price']:.2f}, BB上軌${result['upper']:.2f}, 下軌${result['lower']:.2f})\n"

                prompt += "\n請用100字以內總結市場狀況和操作建議。"
                # Generate report
                log.info("Generating LLM report...")
                response = self.llm_client.generate_response(prompt)

                log.info(f"\n{'='*60}\nLLM REPORT\n{'='*60}\n{response}\n{'='*60}\n")

            except Exception as e:
                log.error(f"LLM report error: {e}")

            await asyncio.sleep(LLM_REPORT_INTERVAL)

    async def execute_orders(self):
        """Task 4: Order execution with risk control"""
        log.info("Order executor started")

        while not SHUTDOWN:
            try:
                # Check if backtest period is over
                if self.backtest_mode and self.should_exit_backtest():
                    log.info("🏁 Backtest completed. Shutting down...")
                    SHUTDOWN = True
                    break

                # Determine mode label
                if self.backtest_mode:
                    # Use mock market time if available
                    if hasattr(self.client.broker_api, 'get_system_time'):
                        current_time = self.client.broker_api.get_system_time()
                    else:
                        current_time = datetime.now()

                    elapsed = current_time - self.start_time
                    remaining = BACKTEST_DURATION_DAYS - elapsed.days
                    mode_prefix = f"[BACKTEST {remaining}d]"
                else:
                    mode_prefix = "[LIVE]"

                # Execute orders based on signals (both backtest and live mode)
                executed_any = False
                for symbol, result in self.analysis_results.items():
                    signal = result['signal']
                    price = result['price']

                    if signal == 'HOLD':
                        continue

                    # Check positions
                    positions = self.client.get_positions()
                    has_position = any(p.symbol == symbol for p in positions) if positions else False

                    if signal == 'BUY' and not has_position:
                        # Calculate position size
                        quantity = self.calculate_position_size(price)

                        if quantity > 0:
                            # Determine reason based on BB bands
                            lower_band = result.get('lower', 0)
                            reason = f"price {price:.2f} <= lower band {lower_band:.2f}"

                            log.info(f"{mode_prefix} 🟢 BUY Signal: {symbol} {quantity} shares @ ${price:.2f}")

                            try:
                                order_result = self.client.buy_stock(
                                    symbol,
                                    quantity=quantity,
                                    price=price * 1.01,  # Slightly above market
                                    intraday_odd=True
                                )

                                # Log the trade
                                trade_record = {
                                    'action': 'BUY',
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'price': price,
                                    'reason': reason,
                                    'timestamp': datetime.now()
                                }
                                self.trade_log.append(trade_record)
                                print(f"📝 BUY {quantity} shares of {symbol} at {price:.2f} ({reason})")

                                log.info(f"{mode_prefix} ✅ Order placed: {order_result}")
                                executed_any = True
                            except Exception as e:
                                log.error(f"{mode_prefix} ❌ Failed to place BUY order: {e}")

                    elif signal == 'SELL' and has_position:
                        # Find position quantity
                        position = next((p for p in positions if p.symbol == symbol), None)
                        if position:
                            quantity = position.quantity

                            # Determine reason based on BB bands
                            upper_band = result.get('upper', 0)
                            reason = f"price {price:.2f} >= upper band {upper_band:.2f}"

                            log.info(f"{mode_prefix} 🔴 SELL Signal: {symbol} {quantity} shares @ ${price:.2f}")

                            try:
                                order_result = self.client.sell_stock(
                                    symbol,
                                    quantity=quantity,
                                    price=price * 0.99,  # Slightly below market
                                    intraday_odd=False
                                )

                                # Log the trade
                                trade_record = {
                                    'action': 'SELL',
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'price': price,
                                    'reason': reason,
                                    'timestamp': datetime.now()
                                }
                                self.trade_log.append(trade_record)
                                print(f"📝 SELL {quantity} shares of {symbol} at {price:.2f} ({reason})")

                                log.info(f"{mode_prefix} ✅ Order placed: {order_result}")
                                executed_any = True
                            except Exception as e:
                                log.error(f"{mode_prefix} ❌ Failed to place SELL order: {e}")

                # Status update if no orders executed
                if not executed_any and len(self.analysis_results) > 0:
                    log.info(f"{mode_prefix} 💤 No actionable signals (all HOLD)")

            except Exception as e:
                log.error(f"Order execution error: {e}")

            await asyncio.sleep(ANALYSIS_INTERVAL)

    async def display_time(self):
        log.info("Time display started")

        while not SHUTDOWN:
            if self.client.get_broker_name() == "mock":
                ts = self.client.broker_api.get_system_time()
            else:
                ts = datetime.now()

            time_str = ts.strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{'='*60}")
            print(f"Current Time: \033[93m{time_str}\033[0m")
            print(f"{'='*60}\n")

            await asyncio.sleep(30)

    async def trigger_order_matching(self):
        """Task 6: Trigger order matching for mock broker"""
        # Only needed for mock broker backend
        if not (hasattr(self.client.broker_api, 'api') and
                hasattr(self.client.broker_api.api, '_trigger_order_matching')):
            log.info("Order matching task not needed (not using mock broker)")
            return

        log.info("Order matching task started")

        while not SHUTDOWN:
            print('check_if_any_order_can_be_filled()')
            try:
                self.client.broker_api.api._trigger_order_matching()
            except Exception as e:
                log.error(f"Order matching error: {e}")

            await asyncio.sleep(5)  # Check every 5 seconds


# ==================== Main Entry Point ====================
def signal_handler(sig, frame):
    global SHUTDOWN
    log.info(f"Received signal {sig}, shutting down...")
    SHUTDOWN = True


async def async_main():
    """Main async entry point"""
    global SHUTDOWN

    load_supported_config_files()

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize trading client
    config = {
        'api_key': os.environ.get("API_KEY", ""),
        'secret_key': os.environ.get("SECRET_KEY", ""),
        'ca_path': os.environ.get("CA_CERT_PATH", ""),
        'ca_passwd': os.environ.get("CA_PASSWORD", ""),
        'simulation': True,
        'username': os.environ.get('USERNAME', 'user000'),
        'speed': 60.0,
    }

    # Choose broker type
    broker_type = os.environ.get('BROKER_TYPE', 'mock').lower()

    if broker_type == 'mock':
        config["state_file"] = f"./mock_{config['username']}.json"
        config["mirror_db_path"] = f"./data/mock_{config['username']}.db"
        client = AccountClient(BrokerType.MOCK, **config)
    elif broker_type == 'realistic':
        config["state_file"] = f"./realistic_{config['username']}.json"
        config["mirror_db_path"] = f"./data/realistic_{config['username']}.db"
        real = AccountClient(BrokerType.SINOPAC, **config)
        client = AccountClient(BrokerType.MOCK, real_account=real, **config)
    else:
        log.error(f"Unsupported broker type: {broker_type}")
        return

    # Connect to broker
    client.connect()
    log.info(f"Connected to {broker_type} broker")

    # Initialize trading system (will auto-detect symbols from positions)
    system = TradingSystem(client)

    # Get initial watch list
    initial_symbols = system.get_watch_symbols()
    if not initial_symbols:
        log.warning("⚠️  No positions found. System will monitor positions as they are created.")

    # Launch async tasks
    tasks = [
        asyncio.create_task(system.monitor_prices(), name="price_monitor"),
        asyncio.create_task(system.analyze_signals(), name="signal_analysis"),
        asyncio.create_task(system.generate_llm_report(), name="llm_report"),
        asyncio.create_task(system.execute_orders(), name="order_executor"),
        asyncio.create_task(system.display_time(), name="time_display"),
        asyncio.create_task(system.trigger_order_matching(), name="order_matching"),
    ]

    os.system("clear")
    log.info("🏁 Trading system started")
    print("""
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%%%%%%%###%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%==*%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%%%%%%%%%%%%%%%%%%%%#+-.....:+#%%%=.......+%=..........-%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%..+%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%*...-+++=...#%%*+++++..+%*+++=..-++++%%%%%%%%%%%%%%%%%%%##%%%%%%%%%%%%##%#%..+%%%%%%##%%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%*..-#%%%%%#+#%%%%%%%%%..+%%%%%#..*%%%%%+.:%+-......%%#+:....-#:.+%%%+:....-#..+%%%*-....:=#%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%-.:%%%%%%%%%%%%%%%%%%%..+%%%%%#..*%%%%%+..-.-===-..%#:..=**+-...*%#-..=**+-...+%%-..=***-..*%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%..-%%%%%%%%%%%%%%%%%%%..+%%%%%#..*%%%%%+..:#%%%%+..%=..#%%%%%=..+%+..#%%%%%+..+#+..*#####-.:%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%-.:%%%%%%%%%++*%%%%%%%..+%%%%%#..*%%%%%+..*%%%%%###%:.-%%%%%%#..+%-.:%%%%%%# .+%=...........%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%*..-#%%%%%#=..*#%%%%%*..+%%%%%#..*%%%%%+..#%%%%%%%%%=..#%%%%%=..+%+..*%%%%%+..+%+..*%%%%%%%%%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%%*...=+*+=...*#::=++=..:%%%%%%#..*%%%%%+..#%%%%%%%%%#:..=**+-...+%#-..=**+-...+%%=..=+**=.:#%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%#+-.....:+#%#=:....:+#%%%%%%#..*%%%%%*..#%%%%%%%%%%#+:....-#:.*%%%+-....-*:.+%%%*-.....-*%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%%%%%###%%%%%%%%####%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%####%%%%%%%%%%%%##%%%%%%%%%%%%###%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#
""")
    log.info(f"Mode: {'BACKTEST (' + str(BACKTEST_DURATION_DAYS) + ' days)' if BACKTEST_MODE else 'LIVE'}")

    # Wait for shutdown
    try:
        while not SHUTDOWN:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")

    # Print backtest summary if in backtest mode
    if BACKTEST_MODE:
        system.print_backtest_summary()

    # Graceful shutdown
    log.info("Shutting down tasks...")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Disconnect
    client.disconnect()
    log.info("Bye!")


def main_system():
    """Entry point for the trading system"""
    import argparse

    parser = argparse.ArgumentParser(description="CJTrade Trading System")
    parser.add_argument("-B", "--broker", type=str, default="mock",
                        choices=["mock", "realistic", "sinopac"],
                        help="Broker type: mock, realistic, or sinopac")
    args = parser.parse_args()

    # Set broker type as environment variable for async_main to pick up
    os.environ['BROKER_TYPE'] = args.broker

    asyncio.run(async_main())
