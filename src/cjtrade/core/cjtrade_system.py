"""
Minimal Viable Trading System PoC
"""
import asyncio
import logging
import os
import signal
from asyncio import Queue
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.core.account_client import AccountClient
from cjtrade.core.account_client import BrokerType
from cjtrade.core.config_loader import load_supported_config_files
from cjtrade.llm.gemini import GeminiClient
from cjtrade.models import Product
from dotenv import load_dotenv


# ==================== Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s"
)
log = logging.getLogger("cjtrade.system")

PRICE_MONITOR_INTERVAL = 120  # seconds
ANALYSIS_INTERVAL = 240       # seconds
RISK_MAX_POSITION_PCT = 0.05  # 5% of total equity per trade
LLM_REPORT_INTERVAL = 90000    # seconds
DISPLAY_TIME_INTERVAL = 60    # seconds
CHECK_FILL_INTERVAL = 120     # seconds
WINDOW_SIZE = 100              # Number of price points for Bollinger Bands calculation

SHUTDOWN = False
BACKTEST_MODE = True         # Start in backtest mode
BACKTEST_DURATION_DAYS = 60
BB_MIN_WIDTH_PCT = 0.01     # Minimum Bollinger Bands width (0.5%) to consider valid signals


# ==================== Mock Bollinger Bands ====================
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

    band_width = (upper - lower) / middle if middle > 0 else 0

    log.info(f"BB Debug [{symbol}]: Price={current_price:.2f} | "
             f"Upper={upper:.2f} Mid={middle:.2f} Lower={lower:.2f} | "
             f"StdDev={std_dev:.2f} BandWidth={band_width*100:.2f}%")

    if band_width < BB_MIN_WIDTH_PCT:
        log.info(f"⚪ BB {symbol}: Band too narrow ({band_width*100:.2f}% < {BB_MIN_WIDTH_PCT*100:.2f}%), signal=HOLD")
        signal = 'HOLD'
    else:
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
        'band_width': round(band_width * 100, 2)
    }


# ==================== Trading System Class ====================
class TradingSystem:
    def __init__(self, client: AccountClient):
        self.client = client
        self.price_history: Dict[str, List[float]] = {}
        self.analysis_results: Dict[str, Dict] = {}
        self.llm_client: Optional[GeminiClient] = None

        if hasattr(self.client.broker_api, 'get_system_time'):
            self.start_time = self.client.broker_api.get_system_time()
            log.info(f"⏰ Using mock market start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.start_time = datetime.now()
            log.info(f"⏰ Using real system time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.backtest_mode = BACKTEST_MODE
        self.trade_log: List[Dict] = []
        self.strategy_cash_flow = 0.0
        self.signal_queue: Queue = Queue()

        # Get playback speed from mock broker backend (for time-scaled delays)
        self.playback_speed = 1.0
        if hasattr(self.client.broker_api, 'api') and hasattr(self.client.broker_api.api, 'market'):
            self.playback_speed = self.client.broker_api.api.market.playback_speed
            log.info(f"⚡ Playback speed: {self.playback_speed}x")

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

    def mock_env_sleep(self, seconds: float) -> float:
        """Return sleep time scaled by playback speed"""
        return seconds / self.playback_speed

    def get_watch_symbols(self) -> List[str]:
        """Get list of symbols to monitor from current positions"""
        symbols = []
        try:
            if os.environ.get('WATCH_LIST'):
                symbols = os.environ['WATCH_LIST'].split(',')
                log.info(f"Watching symbols from WATCH_LIST env: {', '.join(symbols)}")

            positions = self.client.get_positions()
            if positions:
                s = [p.symbol for p in positions]
                symbols = list(set(symbols + s))
                log.info(f"Watching {len(symbols)} symbols from positions: {', '.join(symbols)}")

            if len(symbols) == 0:
                log.warning("No position to monitor (Try `export WATCH_LIST=2330,0050` env variable)")

            return symbols
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

        if quantity < 1 and total_equity > price:
            quantity = 1

        log.info(f"Position sizing: equity={total_equity:.2f}, max_value={max_value:.2f}, quantity={quantity}")
        return quantity

    def should_exit_backtest(self) -> bool:
        """Check if backtest period is over (based on trading days)

        Trading day definition:
        - Day 0: 09:00 start, 13:30 close = 1 completed trading day
        - After 13:30, the day is considered complete
        """
        if not self.backtest_mode:
            return False

        # Use mock market time if available
        if hasattr(self.client.broker_api, 'get_system_time'):
            current_time = self.client.broker_api.get_system_time()
        else:
            current_time = datetime.now()

        # Calculate completed trading days
        start_date = self.start_time.date()
        current_date = current_time.date()
        calendar_days = (current_date - start_date).days

        # If market has closed today (after 13:30), count today as completed
        market_close_time = current_time.replace(hour=13, minute=30, second=0, microsecond=0)
        if current_time >= market_close_time:
            completed_trading_days = calendar_days + 1
        else:
            completed_trading_days = calendar_days

        if completed_trading_days >= BACKTEST_DURATION_DAYS:
            log.info(f"Backtest completed: {completed_trading_days} trading days completed (started {start_date}, now {current_date} {current_time.strftime('%H:%M')})")
            return True
        return False

    def print_backtest_summary(self):
        """Print final P&L summary after backtest"""
        final_balance = self.client.get_balance()
        final_positions = self.client.get_positions()
        final_equity = self.get_total_equity()

        total_equity_change = final_equity - self.initial_equity
        total_equity_change_pct = (total_equity_change / self.initial_equity * 100) if self.initial_equity > 0 else 0
        balance_change = final_balance - self.initial_balance

        # Calculate realized P&L from closed positions
        realized_pnl = 0.0
        buy_prices = {}  # Track buy prices from strategy trades

        # Initialize with initial positions as if they were "bought" at their avg_cost
        for p in self.initial_positions:
            buy_prices[p.symbol] = [(p.avg_cost, p.quantity)]

        for trade in self.trade_log:
            symbol = trade['symbol']
            if trade['action'] == 'BUY':
                if symbol not in buy_prices:
                    buy_prices[symbol] = []
                buy_prices[symbol].append((trade['price'], trade['quantity']))
            elif trade['action'] == 'SELL':
                if symbol not in buy_prices:
                    continue

                sell_price = trade['price']
                sell_qty = trade['quantity']

                # Calculate realized P&L using FIFO
                remaining_qty = sell_qty
                while remaining_qty > 0 and buy_prices[symbol]:
                    buy_price, buy_qty = buy_prices[symbol][0]
                    qty_to_close = min(remaining_qty, buy_qty)
                    realized_pnl += (sell_price - buy_price) * qty_to_close

                    if qty_to_close >= buy_qty:
                        buy_prices[symbol].pop(0)
                    else:
                        buy_prices[symbol][0] = (buy_price, buy_qty - qty_to_close)

                    remaining_qty -= qty_to_close

        # Calculate unrealized P&L
        unrealized_strategy_pnl = 0.0
        unrealized_initial_pnl = 0.0

        for p in final_positions:
            if p.symbol not in self.initial_position_symbols:
                unrealized_strategy_pnl += p.unrealized_pnl
            else:
                unrealized_initial_pnl += p.unrealized_pnl

        # Separate realized P&L into strategy vs initial positions
        # All realized is now in realized_pnl, but we need to know which part came from initial positions
        # For simplicity, we'll show total realized P&L
        total_unrealized = unrealized_strategy_pnl + unrealized_initial_pnl

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
        print(f"\nPerformance:")
        print(f"  Total P&L:         {total_equity_change:>12,.2f} ({total_equity_change_pct:>+6.2f}%)")
        print(f"  ├─ Realized P&L:   {realized_pnl:>12,.2f}")
        print(f"  └─ Unrealized P&L: {total_unrealized:>12,.2f}")
        print(f"     ├─ Strategy:    {unrealized_strategy_pnl:>12,.2f}")
        print(f"     └─ Initial:     {unrealized_initial_pnl:>12,.2f}")
        print(f"\nCash Flow:")
        print(f"  Balance Change:    {balance_change:>12,.2f}")
        print(f"\nTrade History ({len(self.trade_log)} trades):")
        if self.trade_log:
            for i, trade in enumerate(self.trade_log, 1):
                action_symbol = "🟢" if trade['action'] == 'BUY' else "🔴"
                timestamp = trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {i}. [{timestamp}] {action_symbol} {trade['action']} {trade['quantity']} shares of {trade['symbol']} at {trade['price']:.2f} ({trade['reason']})")
        else:
            print("  No trades executed during backtest")

        if total_equity_change > 0:
            print(f"\n✅ 總權益增加 {total_equity_change:,.2f} ({total_equity_change_pct:+.2f}%)")
        elif total_equity_change < 0:
            print(f"\n❌ 總權益減少 {abs(total_equity_change):,.2f} ({total_equity_change_pct:.2f}%)")
        else:
            print(f"\n⚪ 策略無損益（未執行交易或損益持平）")

        print("="*80 + "\n")

    async def monitor_prices(self):
        log.info("Price monitoring started")

        while not SHUTDOWN:
            try:
                is_market_open = self.client.broker_api.api.market.is_market_open()

                # Auto-skip to next trading day at 2PM (only in backtest mode)
                if not is_market_open and self.backtest_mode:
                    current_time = self.client.broker_api.get_system_time()

                    # Check if it's 2PM (14:00)
                    market = self.client.broker_api.api.market
                    # log.info("⏭️  2PM reached, skipping to next trading day (9AM)...")

                    # calculate diff to next day 9AM
                    diff = ((current_time + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0) - current_time).total_seconds()
                    diff = diff / 3600
                    print(f"current time {current_time}")
                    market.adjust_time(diff)  # Jump 19 hours: 14:00 + 19 = 09:00 next day
                    print(f"current time {current_time}")

                    log.debug("⏸️  Market closed, skipping price monitoring")
                    await asyncio.sleep(self.mock_env_sleep(PRICE_MONITOR_INTERVAL))
                    continue

                symbols = self.get_watch_symbols()

                if not symbols:
                    await asyncio.sleep(self.mock_env_sleep(PRICE_MONITOR_INTERVAL))
                    continue

                for symbol in symbols:
                    snapshots = self.client.get_snapshots([Product(symbol=symbol)])

                    if snapshots:
                        snapshot = snapshots[0]
                        price = snapshot.close

                        if symbol not in self.price_history:
                            self.price_history[symbol] = []
                            log.info(f"✨ Initialized price history for {symbol}")

                        self.price_history[symbol].append(price)

                        # Keep last 100 prices
                        if len(self.price_history[symbol]) > 100:
                            self.price_history[symbol] = self.price_history[symbol][-100:]

                        history_len = len(self.price_history[symbol])
                        log.info(f"  {symbol}: {price:.2f} (O:{snapshot.open:.2f} H:{snapshot.high:.2f} L:{snapshot.low:.2f}) | History: {history_len} prices")

            except Exception as e:
                log.error(f"Price monitoring error: {e}")

            await asyncio.sleep(self.mock_env_sleep(PRICE_MONITOR_INTERVAL))

    async def analyze_signals(self):
        log.info("Signal analysis started")

        while not SHUTDOWN:
            try:
                symbols = list(self.price_history.keys())
                log.info(f"Analyzing {len(symbols)} symbols: {symbols}")

                for symbol in symbols:
                    history_len = len(self.price_history.get(symbol, []))

                    if history_len < WINDOW_SIZE:
                        continue

                    result = calculate_bollinger_bands_mock(
                        symbol,
                        self.price_history[symbol]
                    )

                    if result:
                        old_signal = self.analysis_results.get(symbol, {}).get('signal', None)
                        new_signal = result['signal']

                        if new_signal != 'HOLD' and new_signal != old_signal:
                            log.info(f"📢 Signal changed: {symbol} {old_signal} → {new_signal} @ {result['price']:.2f}")
                            await self.signal_queue.put({
                                'symbol': symbol,
                                'signal': new_signal,
                                'result': result,
                                'timestamp': datetime.now()
                            })

                        self.analysis_results[symbol] = result
                    else:
                        log.warning(f"{symbol}: BB calculation returned None")

            except Exception as e:
                log.error(f"Analysis error: {e}")

            await asyncio.sleep(self.mock_env_sleep(ANALYSIS_INTERVAL))

    def format_trading_context(self) -> str:
        """Format recent trading activity and market state for LLM analysis"""
        positions = self.client.get_positions()
        balance = self.client.get_balance()
        equity = self.get_total_equity()

        # Get recent trades (last 10)
        recent_trades = self.trade_log[-10:] if len(self.trade_log) > 10 else self.trade_log

        context = "=== TRADING SYSTEM CONTEXT ===\n\n"
        context += f"📊 ACCOUNT STATUS\n"
        context += f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        context += f"Balance:   ${balance:>12,.2f}\n"
        context += f"Equity:    ${equity:>12,.2f}\n"
        context += f"Positions: {len(positions) if positions else 0}\n\n"

        # Current positions
        context += f"📈 CURRENT POSITIONS\n"
        if positions:
            for p in positions:
                pnl_pct = (p.unrealized_pnl / (p.avg_cost * p.quantity) * 100) if p.avg_cost > 0 else 0
                context += f"  {p.symbol:6s} | Qty: {p.quantity:>4d} | Avg: ${p.avg_cost:>7.2f} | Now: ${p.current_price:>7.2f} | P&L: ${p.unrealized_pnl:>9,.2f} ({pnl_pct:>+6.2f}%)\n"
        else:
            context += "  (No positions)\n"

        # Recent price action (last 5 prices for each symbol)
        context += f"\n💹 RECENT PRICE ACTION (Last 5 ticks)\n"
        for symbol in sorted(self.price_history.keys()):
            prices = self.price_history[symbol][-5:]
            if len(prices) >= 2:
                price_change = prices[-1] - prices[0]
                price_change_pct = (price_change / prices[0] * 100) if prices[0] > 0 else 0
                prices_str = " → ".join([f"{p:.2f}" for p in prices])
                context += f"  {symbol:6s} | {prices_str} (Δ {price_change:+.2f}, {price_change_pct:+.2f}%)\n"

        # BB signals
        context += f"\n🎯 BOLLINGER BANDS SIGNALS\n"
        for symbol in sorted(self.analysis_results.keys()):
            result = self.analysis_results[symbol]
            signal_icon = "🟢" if result['signal'] == 'BUY' else "🔴" if result['signal'] == 'SELL' else "⚪"
            context += f"  {signal_icon} {symbol:6s} | Signal: {result['signal']:4s} | Price: ${result['price']:>7.2f} | Upper: ${result['upper']:>7.2f} | Mid: ${result['middle']:>7.2f} | Lower: ${result['lower']:>7.2f}\n"

        # Recent trades
        context += f"\n📝 RECENT TRADES ({len(recent_trades)} trades)\n"
        if recent_trades:
            for i, trade in enumerate(recent_trades, 1):
                action_icon = "🟢" if trade['action'] == 'BUY' else "🔴"
                ts = trade['timestamp'].strftime('%m-%d %H:%M')
                context += f"  {i:2d}. [{ts}] {action_icon} {trade['action']:4s} {trade['quantity']:>3d}x {trade['symbol']:6s} @ ${trade['price']:>7.2f} | {trade['reason']}\n"
        else:
            context += "  (No trades yet)\n"

        return context

    async def generate_llm_report(self):
        log.info("LLM report generator started")

        while not SHUTDOWN:
            try:
                if not self.llm_client:
                    await asyncio.sleep(self.mock_env_sleep(LLM_REPORT_INTERVAL))
                    continue

                context = self.format_trading_context()

                prompt = f"""{context}

=== ANALYSIS REQUEST ===
作為專業量化交易分析師，請基於以上交易系統狀態進行分析：

1. 評估當前策略表現（根據近期交易和持倉盈虧）
2. 分析市場趨勢（根據價格走勢和BB訊號）
3. 識別潛在風險或機會
4. 提供具體可行的操作建議

請用150字以內提供精簡分析報告。"""

                log.info("Generating LLM report...")
                response = self.llm_client.generate_response(prompt)

                log.info(f"\n{'='*60}\n🤖 LLM ANALYSIS REPORT\n{'='*60}\n{response}\n{'='*60}\n")

            except Exception as e:
                log.error(f"LLM report error: {e}")

            await asyncio.sleep(self.mock_env_sleep(LLM_REPORT_INTERVAL))

    async def execute_orders(self):
        global SHUTDOWN
        log.info("Order executor started (event-driven mode)")

        while not SHUTDOWN:
            try:
                # Check if backtest period is over
                if self.backtest_mode and self.should_exit_backtest():
                    log.info("🏁 Backtest completed. Shutting down...")
                    SHUTDOWN = True
                    break

                # Wait for signal events from the queue
                # Note: timeout should NOT be scaled - it's real-world I/O operation
                try:
                    signal_event = await asyncio.wait_for(self.signal_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

                symbol = signal_event['symbol']
                signal = signal_event['signal']
                result = signal_event['result']
                price = result['price']

                if self.backtest_mode:
                    if hasattr(self.client.broker_api, 'get_system_time'):
                        current_time = self.client.broker_api.get_system_time()
                    else:
                        current_time = datetime.now()

                    start_date = self.start_time.date()
                    current_date = current_time.date()
                    calendar_days = (current_date - start_date).days

                    market_close_time = current_time.replace(hour=13, minute=30, second=0, microsecond=0)
                    if current_time >= market_close_time:
                        completed_trading_days = calendar_days + 1
                    else:
                        completed_trading_days = calendar_days

                    remaining = BACKTEST_DURATION_DAYS - completed_trading_days
                    mode_prefix = f"[BACKTEST {remaining}d]"
                else:
                    mode_prefix = "[LIVE]"

                log.info(f"{mode_prefix} ⚡ Processing signal event: {symbol} {signal} @ {price:.2f}")

                positions = self.client.get_positions()
                has_position = any(p.symbol == symbol for p in positions) if positions else False

                if signal == 'BUY':
                    quantity = self.calculate_position_size(price)

                    if quantity > 0:
                        lower_band = result.get('lower', 0)
                        reason = f"price {price:.2f} <= lower band {lower_band:.2f}"

                        log.info(f"{mode_prefix} 🟢 BUY Signal: {symbol} {quantity} shares @ ${price:.2f}")

                        try:
                            order_result = self.client.buy_stock(
                                symbol,
                                quantity=quantity,
                                price=price * 1.01,
                                intraday_odd=True
                            )

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
                        except Exception as e:
                            log.error(f"{mode_prefix} ❌ Failed to place BUY order: {e}")

                elif signal == 'SELL' and has_position:
                    position = next((p for p in positions if p.symbol == symbol), None)
                    if position:
                        quantity = min(self.calculate_position_size(price), position.quantity)

                        upper_band = result.get('upper', 0)
                        reason = f"price {price:.2f} >= upper band {upper_band:.2f}"

                        log.info(f"{mode_prefix} 🔴 SELL Signal: {symbol} {quantity} shares @ ${price:.2f}")

                        try:
                            order_result = self.client.sell_stock(
                                symbol,
                                quantity=quantity,
                                price=price * 0.99,
                                intraday_odd=False
                            )

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
                        except Exception as e:
                            log.error(f"{mode_prefix} ❌ Failed to place SELL order: {e}")

            except Exception as e:
                log.error(f"Order execution error: {e}")

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

            await asyncio.sleep(self.mock_env_sleep(DISPLAY_TIME_INTERVAL))

    async def trigger_order_matching(self):
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

            await asyncio.sleep(self.mock_env_sleep(CHECK_FILL_INTERVAL))


# ==================== Main Entry Point ====================
def signal_handler(sig, frame):
    global SHUTDOWN
    log.info(f"Received signal {sig}, shutting down...")
    SHUTDOWN = True


async def async_main():
    """Main async entry point"""
    global SHUTDOWN

    load_supported_config_files()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config = {
        'api_key': os.environ.get("API_KEY", ""),
        'secret_key': os.environ.get("SECRET_KEY", ""),
        'ca_path': os.environ.get("CA_CERT_PATH", ""),
        'ca_passwd': os.environ.get("CA_PASSWORD", ""),
        'simulation': True,
        'username': os.environ.get('USERNAME', 'user000'),
        # 'speed': 60.0,
    }

    broker_type = os.environ.get('BROKER_TYPE', 'mock').lower()

    if broker_type == 'mock':
        config["speed"] = 120.0
        config["state_file"] = f"./mock_{config['username']}.json"
        config["mirror_db_path"] = f"./data/mock_{config['username']}.db"
        client = AccountClient(BrokerType.MOCK, **config)
    elif broker_type == 'realistic':
        config["speed"] = 6000.0
        config["state_file"] = f"./realistic_{config['username']}.json"
        config["mirror_db_path"] = f"./data/realistic_{config['username']}.db"
        real = AccountClient(BrokerType.SINOPAC, **config)
        client = AccountClient(BrokerType.MOCK, real_account=real, **config)
    else:
        log.error(f"Unsupported broker type: {broker_type}")
        return

    client.connect()
    log.info(f"Connected to {broker_type} broker")

    system = TradingSystem(client)

    initial_symbols = system.get_watch_symbols()
    if not initial_symbols:
        log.warning("⚠️  No positions found. System will monitor positions as they are created.")

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

    try:
        while not SHUTDOWN:
            await asyncio.sleep(system.mock_env_sleep(1))
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")

    if BACKTEST_MODE:
        system.print_backtest_summary()

    log.info("Shutting down tasks...")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

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

    os.environ['BROKER_TYPE'] = args.broker

    asyncio.run(async_main())
