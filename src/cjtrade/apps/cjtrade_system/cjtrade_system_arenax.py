"""
Minimal Viable Trading System PoC
"""
import asyncio
import logging
import os
import signal
import sys
import time
import uuid
from asyncio import Queue
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Dict
from typing import List
from typing import Optional

import numpy as np
from cjtrade.apps.cjtrade_system.extensions.ntfy_sh import push_to_ntfy_sh
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.analytics.technical import ta
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.brokers.account_client import BrokerType
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from cjtrade.pkgs.llm.azure_openai import AzureOpenAIClient
from cjtrade.pkgs.llm.chatpdf import ChatPDFClient
from cjtrade.pkgs.llm.gemini import GeminiClient
from cjtrade.pkgs.llm.llm_pool import LLMPool
from cjtrade.pkgs.llm.mock_llm import MockLLMClient
from cjtrade.pkgs.models import Product
from cjtrade.pkgs.models.backtest import BacktestResult
from dotenv import load_dotenv


 # ==================== Configuration ====================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s: %(message)s",
    handlers=[
        logging.FileHandler("cjtrade_system.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

log = logging.getLogger("cjtrade.system_arenax")

# load_supported_config_files()
# Need to read from env variables
# Here are the settings that exposed to users/operators
config = {}

# CJCONF is for the brokers / services configuration (e.g. API keys, certs, etc.)
def load_cjconf():
    load_supported_config_files()
    keys = ['API_KEY', 'SECRET_KEY', 'CA_CERT_PATH', 'CA_PASSWORD', 'SIMULATION',
            'USERNAME', 'LLM_API_KEY', 'LLM_MODEL', 'GEMINI_API_KEY', 'NEWSAPI_API_KEY']
    for key in keys:
        if os.environ.get(key):
            config[key.lower()] = os.environ[key]

    config['simulation'] = config.get('simulation', 'y').lower() == 'y'
    config['ca_path'] = config.get('ca_cert_path', "")
    config['ca_passwd'] = config.get('ca_password', "")


# TODO: config control flow is a MESS...... = =
# CJSYS is for CJTrade System itself
# Note that need to consider bridging to real brokers in the future, so don't
# make CJSYS too specific to ArenaX !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
def load_cjsys(broker: str, mode: str):
    """
    Load CJTrade system configuration from .cjsys files
    """
    # Find config file relative to this module
    import pathlib
    config_dir = pathlib.Path(__file__).parent / "configs"
    file_to_load = config_dir / f"{broker}_{mode}.cjsys"

    if mode == 'paper' and broker == 'arenax':
        pass
        # log.error("Using paper mode for arenax broker does not make sense!"
        #           " If you want to use paper mode, please switch to the 'realistic'!")
        # exit(1)

    if not file_to_load.exists():
        log.warning(f"Config file {file_to_load} not found, create one based on the template in configs/ dir")
        return

    log.info(f"Loading config file {file_to_load}")
    load_dotenv(file_to_load, override=False)
    keys = ['CJSYS_WATCH_LIST', 'CJSYS_REMOTE_HOST', 'CJSYS_REMOTE_PORT', 'CJSYS_ANALYSIS_INTERVAL', 'CJSYS_CHECK_FILL_INTERVAL',
            'CJSYS_BACKTEST_DURATION_DAYS', 'CJSYS_BACKTEST_PLAYBACK_SPEED', 'CJSYS_DISPLAY_TIME_INTERVAL', 'CJSYS_LLM_REPORT_INTERVAL',
            'CJSYS_PRICE_MONITOR_INTERVAL', 'CJSYS_BB_MIN_WIDTH_PCT', 'CJSYS_BB_WINDOW_SIZE', 'CJSYS_RISK_MAX_POSITION_PCT']
    for key in keys:
        if os.environ.get(key):
            log.info(f"  {key}={os.environ[key]}")
            config[key.lower()] = os.environ[key]

    # Adjust the types of certain keys
    config['launch_mode'] = mode
    config['remote_host'] = config.get('cjsys_remote_host', 'localhost')
    config['remote_port'] = int(config.get('cjsys_remote_port', 8801))
    # Map to ArenaXBrokerAPI_v2 expected keys
    config['arenax_host'] = config['remote_host']
    config['arenax_port'] = config['remote_port']
    config['backtest_duration_days'] = int(config.get('cjsys_backtest_duration_days', 7))
    config['watch_list'] = config.get('cjsys_watch_list', "").split(',') if config.get('cjsys_watch_list') else []
    config['analysis_interval'] = float(config.get('cjsys_analysis_interval', 30))
    config['check_fill_interval'] = float(config.get('cjsys_check_fill_interval', 60))
    config['display_time_interval'] = float(config.get('cjsys_display_time_interval', 40))
    config['llm_report_interval'] = float(config.get('cjsys_llm_report_interval', 300))
    config['price_monitor_interval'] = float(config.get('cjsys_price_monitor_interval', 60))
    config['bb_min_width_pct'] = float(config.get('cjsys_bb_min_width_pct', 0.01))
    config['bb_window_size'] = int(config.get('cjsys_bb_window_size', 20))
    config['risk_max_position_pct'] = float(config.get('cjsys_risk_max_position_pct', 0.05))


def print_config():
    log.info(f"System Configuration: {config}")

# ==================== System Config ====================
@dataclass
class SystemConfig:
    watch_list: str
    analysis_interval: float
    check_fill_interval: float
    display_time_interval: float
    llm_report_interval: float
    price_monitor_interval: float
    bb_min_width_pct: float
    bb_window_size: int
    risk_max_position_pct: float
    launch_mode: str
    backtest_duration_days: float
    remote_host: str = "localhost"      # Default for direct cjtrade_system launch (without runner)
    remote_port: int = 8801             # Default for direct cjtrade_system launch (without runner)
    # backtest_playback_speed: float


def _apply_config(cfg: SystemConfig) -> None:
    """Write a SystemConfig into module-level globals used by all coroutines."""
    global LAUNCH_MODE, REMOTE_HOST, REMOTE_PORT
    global BACKTEST_DURATION_DAYS, BACKTEST_PLAYBACK_SPEED
    global WATCH_LIST
    global ANALYSIS_INTERVAL, CHECK_FILL_INTERVAL, DISPLAY_TIME_INTERVAL, LLM_REPORT_INTERVAL, PRICE_MONITOR_INTERVAL
    global BB_MIN_WIDTH_PCT, BB_WINDOW_SIZE
    global RISK_MAX_POSITION_PCT

    BACKTEST_DURATION_DAYS     = cfg.backtest_duration_days
    # BACKTEST_PLAYBACK_SPEED    = cfg.backtest_playback_speed
    LAUNCH_MODE                = cfg.launch_mode
    REMOTE_HOST                = cfg.remote_host
    REMOTE_PORT                = cfg.remote_port
    WATCH_LIST                 = cfg.watch_list
    PRICE_MONITOR_INTERVAL     = cfg.price_monitor_interval
    ANALYSIS_INTERVAL          = cfg.analysis_interval
    CHECK_FILL_INTERVAL        = cfg.check_fill_interval
    DISPLAY_TIME_INTERVAL      = cfg.display_time_interval
    LLM_REPORT_INTERVAL        = cfg.llm_report_interval
    BB_MIN_WIDTH_PCT           = cfg.bb_min_width_pct
    BB_WINDOW_SIZE             = cfg.bb_window_size
    RISK_MAX_POSITION_PCT      = cfg.risk_max_position_pct


SHUTDOWN = False

# ==================== Bollinger Bands (TA-Lib) ====================
# TODO: Construct a specific datatype for bollinger band result
def calculate_bollinger_bands_mock(symbol: str, prices: List[float]) -> Dict:
    """Calculate Bollinger Bands using TA-Lib, maintaining same interface as mock version"""
    if not prices or len(prices) == 0:
        return None

    # Need at least WINDOW_SIZE data points for reliable BB calculation
    if len(prices) < BB_WINDOW_SIZE:
        log.debug(f"BB {symbol}: Insufficient data ({len(prices)}/{BB_WINDOW_SIZE} prices)")
        return None
    current_price, prices_array = prices[-1], np.array(prices, dtype=float)

    # Calculate Bollinger Bands using TA-Lib
    upper_bands, middle_bands, lower_bands = ta.bb(prices_array, timeperiod=BB_WINDOW_SIZE, nbdevup=2, nbdevdn=2)
    upper, middle, lower = upper_bands[-1], middle_bands[-1], lower_bands[-1]
    std_dev = (upper - middle) / 2  # Because upper = middle + 2*std
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
        'upper': round(upper, 2), 'middle': round(middle, 2),
        'lower': round(lower, 2), 'signal': signal,
        'price': current_price, 'symbol': symbol,
        'std_dev': round(std_dev, 2), 'band_width': round(band_width * 100, 2)
    }

# ==================== Trading System Class ====================
class TradingSystem:
    def __init__(self, client: AccountClient):
        self.client = client
        self.price_history: Dict[str, List[float]] = {}
        self.analysis_results: Dict[str, Dict] = {}
        self.llm_pool: Optional[List] = None
        self.launch_mode = LAUNCH_MODE

        if self.launch_mode in ['backtest', 'demo']:
            self.start_time = self.client.broker_api.get_system_time()['mock_current_time']
            log.info(f"⏰ Using mock market start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.start_time = datetime.now()
            log.info(f"⏰ Using real system time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.trade_log: List[Dict] = []
        self.strategy_cash_flow = 0.0
        self.signal_queue: Queue = Queue()

        # Get playback speed from mock broker backend (for time-scaled delays)
        self.playback_speed = 1.0
        if self.launch_mode in ['backtest', 'demo']:
            #self.playback_speed = self.client.broker_api.api.market.playback_speed
            self.playback_speed = self.client.broker_api.middleware.get_config()['internal_config']['playback_speed']
            log.info(f"⚡ Playback speed: {self.playback_speed}x (response from server, not set by user)")

        self.initial_balance = self.client.get_balance()
        self.initial_positions = self.client.get_positions()
        self.initial_equity = self.get_total_equity()

        # Record initial positions details to exclude their market value changes
        self.initial_position_symbols = set(p.symbol for p in self.initial_positions)
        log.info(f"📊 Initial State: Balance={self.initial_balance:.2f}, Equity={self.initial_equity:.2f}")
        log.info(f"💼 Existing positions: {', '.join(self.initial_position_symbols) if self.initial_position_symbols else 'None'}")

        # ── Backtest session tracking ─────────────────────────────────────────
        # Unique ID stamped on every order placed this session.
        # The server propagates it into fill_history so we can filter exactly
        # this run's trades when building BacktestResult after the backtest ends.
        self.session_id: str = str(uuid.uuid4())
        self.session_start_time: str = datetime.now().isoformat()
        # Client-side equity curve recorded after every snapshot() call.
        # {"time": ISO-minute, "value": total_portfolio_float}
        self._equity_curve: List[Dict] = []
        self._equity_last_minute: str = ""   # dedup key: only one point per minute
        log.info(f"🔑 Session ID: {self.session_id}")

        api_key_1 = os.getenv("AZURE_OPENAI_API_KEY")
        api_key_2 = os.getenv("CHATPDF_APIKEY")
        api_key_3 = os.getenv("GEMINI_API_KEY")

        if api_key_1 or api_key_2:
            try:
                self.llm_client_0 = MockLLMClient()
                self.llm_client_1 = AzureOpenAIClient(api_key=api_key_1, deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                                                      endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                                                      model_name=os.getenv("AZURE_OPENAI_MODEL_NAME"))
                self.llm_client_2 = ChatPDFClient(api_key=api_key_2, pdf_src=os.environ.get('CHATPDF_BASIC_SOURCE_FILE'))
                self.llm_client_3 = GeminiClient(api_key=api_key_3)
                self.llm_pool = LLMPool([self.llm_client_0, self.llm_client_0])  # Create a pool
                log.info("LLM client initialized")
            except Exception as e:
                log.warning(f"Failed to initialize LLM client: {e}")
        else:
            log.warning("GEMINI_API_KEY not found, LLM reports disabled")

    def mock_env_sleep(self, seconds: float) -> float:
        """Return sleep time scaled by playback speed"""
        return seconds / self.playback_speed

    def _format_trade_log_line_summary(self, trade: Dict, index: int) -> str:
        """
        Format trade for SUMMARY display (with color emoji, compact).
        Used in the final 【Trade History】 section.

        Output format:
          {index:2d}. [{mock_time}] {emoji} {action:4s} {quantity:>4d} shares {symbol:6s} @ ${price:>7.2f}

        Example:
          1. [2023-11-27 11:31] 🟢 BUY   154 shares 3443   @ $1615.00
        """
        action = trade['action']
        action_icon = "🟢" if action == 'BUY' else "🔴"

        # Use mock_time if available (backtest mode), otherwise use timestamp
        if 'mock_time' in trade:
            time_obj = trade['mock_time']
        else:
            time_obj = trade['timestamp']

        # Format time as YYYY-MM-DD HH:MM
        if isinstance(time_obj, str):
            ts_str = time_obj  # Already formatted
        else:
            ts_str = time_obj.strftime('%Y-%m-%d %H:%M')

        return (f"  {index:2d}. [{ts_str}] {action_icon} {action:4s} {trade['quantity']:>4d} shares "
                f"{trade['symbol']:6s} @ ${trade['price']:>7.2f}")

    def _format_trade_log_line_log(self, trade: Dict) -> str:
        """
        Format trade for LOG output (matches oneshot backtest.log format).
        Used in the INFO-level logging during execution.

        Output format (matches bb_1m.py strategy logging):
          ts: YYYY-MM-DD HH:MM:SS | ACTION symbol @ price * qty shares (reason)

        Example:
          ts: 2023-11-27 11:31:00 | BUY 3443 @ 1635.00 * 91 shares (BB lower=1639.34)
        """
        action = trade['action']

        # Use mock_time if available, otherwise use timestamp
        if 'mock_time' in trade:
            time_obj = trade['mock_time']
        else:
            time_obj = trade['timestamp']

        # Format time as YYYY-MM-DD HH:MM:SS (full ISO format)
        if isinstance(time_obj, str):
            ts_str = time_obj
        else:
            ts_str = time_obj.strftime('%Y-%m-%d %H:%M:%S')

        reason = trade.get('reason', 'N/A')
        return (f"ts: {ts_str} | {action} {trade['symbol']} @ {trade['price']:.2f} * "
                f"{trade['quantity']} shares ({reason})")

    def print_trade_history_as_logs(self) -> None:
        """
        Print trade history in oneshot backtest.log format (for debugging/comparison).
        This allows easy comparison between full_sim and oneshot backtest logs.

        Output: Each trade on a separate line in INFO format.
        """
        if not self.trade_log:
            log.info("No trades executed")
            return

        log.info(f"【Trade History (oneshot format)】({len(self.trade_log)} trades)")
        for trade in self.trade_log:
            log.info(self._format_trade_log_line_log(trade))

    def get_watch_symbols(self) -> List[str]:
        """Get list of symbols to monitor from watch_list config + current positions"""
        symbols = []
        try:
            symbols = list(config.get('watch_list', []))
            positions = self.client.get_positions()
            if positions:
                position_symbols = [p.symbol for p in positions]
                symbols = list(set(symbols + position_symbols))

            if len(symbols) == 0:
                log.warning("No symbols to monitor – set CJSYS_WATCH_LIST in your .cjsys config or ensure you have open positions")
            else:
                log.info(f"Watching {len(symbols)} symbol(s): {', '.join(sorted(symbols))}")

            return symbols
        except Exception as e:
            log.error(f"Failed to get watch symbols: {e}")
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

    def _record_equity_point(self, snapshot_time: datetime, snapshot_price: float, symbol: str) -> None:
        """Append one equity sample to the local equity curve (deduped by minute).

        Uses the price already fetched by monitor_prices() so no extra HTTP call
        is made.  Balance and other positions' prices come from the last values
        already cached on the client (get_balance / get_positions one call each,
        not per-symbol).
        """
        minute_key = snapshot_time.replace(second=0, microsecond=0).isoformat()
        if minute_key == self._equity_last_minute:
            return  # already recorded this minute

        # Mark the minute as "attempted" immediately so we never loop-retry on error
        self._equity_last_minute = minute_key

        try:
            balance = self.client.get_balance()
            positions = self.client.get_positions() or []
            position_value = sum(
                (snapshot_price if p.symbol == symbol else p.current_price) * p.quantity
                for p in positions
            )
            total = round(balance + position_value, 2)
            self._equity_curve.append({"time": minute_key, "value": total})
            log.debug(f"📈 Equity point recorded: {minute_key} = {total:,.2f}")
        except Exception as e:
            log.warning(f"_record_equity_point failed ({minute_key}): {e}")

    def build_backtest_result(self) -> Optional[BacktestResult]:
        """Fetch fill_history from the server filtered by session_id and assemble
        a BacktestResult.

        Call this immediately after the backtest loop exits, before client.disconnect().
        """
        try:
            middleware = self.client.broker_api.middleware
            raw = middleware.get_backtest_state(session_id=self.session_id)
            if raw is None:
                log.warning("get_backtest_state() returned None – BacktestResult not built")
                return None

            result = BacktestResult(
                initial_balance=self.initial_balance,
                final_balance=raw["final_balance"],
                equity_curve=list(self._equity_curve),
                fill_history=raw["fill_history"],   # already filtered by session_id
                session_id=self.session_id,
                start_time=self.session_start_time,
            )
            log.info(
                f"📦 BacktestResult built: {len(result.equity_curve)} equity points, "
                f"{len(result.fill_history)} fills"
            )
            return result
        except Exception as e:
            log.error(f"Failed to build BacktestResult: {e}")
            return None

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
        if not self.launch_mode in ['backtest', 'demo']:
            return False

        # Use mock market time for backtest modes; paper mode uses real wall-clock time
        if self.launch_mode in ['backtest', 'demo']:
            current_time = self.client.broker_api.get_system_time()['mock_current_time']
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
        """Print comprehensive backtest summary with clear accounting breakdown"""

        # ========== 1. Get Final State ==========
        final_balance = self.client.get_balance()
        final_positions = self.client.get_positions()
        final_equity = self.get_total_equity()

        # ========== 2. Calculate Position Values ==========
        initial_position_value = self.initial_equity - self.initial_balance

        final_initial_position_value = 0.0  # Market value of initial positions
        final_strategy_position_value = 0.0  # Market value of strategy positions

        for p in final_positions:
            position_value = p.quantity * p.current_price
            if p.symbol in self.initial_position_symbols:
                final_initial_position_value += position_value
            else:
                final_strategy_position_value += position_value

        # ========== 3. Calculate Strategy Cash Flow ==========
        # Cash spent on buys (negative) and received from sells (positive)
        strategy_cash_flow = 0.0
        for trade in self.trade_log:
            if trade['action'] == 'BUY':
                strategy_cash_flow -= trade['price'] * trade['quantity']
            elif trade['action'] == 'SELL':
                strategy_cash_flow += trade['price'] * trade['quantity']

        # ========== 4. Calculate Realized P&L (FIFO) ==========
        realized_pnl = 0.0
        buy_queue = {}  # {symbol: [(price, qty), ...]}

        # Pre-fill with initial positions at their avg_cost
        for p in self.initial_positions:
            buy_queue[p.symbol] = [(p.avg_cost, p.quantity)]

        for trade in self.trade_log:
            symbol = trade['symbol']
            if trade['action'] == 'BUY':
                if symbol not in buy_queue:
                    buy_queue[symbol] = []
                buy_queue[symbol].append((trade['price'], trade['quantity']))

            elif trade['action'] == 'SELL':
                if symbol not in buy_queue:
                    continue
                sell_price = trade['price']
                sell_qty = trade['quantity']

                remaining_qty = sell_qty
                while remaining_qty > 0 and buy_queue[symbol]:
                    buy_price, buy_qty = buy_queue[symbol][0]
                    qty_to_close = min(remaining_qty, buy_qty)
                    realized_pnl += (sell_price - buy_price) * qty_to_close

                    if qty_to_close >= buy_qty:
                        buy_queue[symbol].pop(0)
                    else:
                        buy_queue[symbol][0] = (buy_price, buy_qty - qty_to_close)
                    remaining_qty -= qty_to_close

        # ========== 5. Calculate Unrealized P&L ==========
        unrealized_initial_pnl = 0.0
        unrealized_strategy_pnl = 0.0

        for p in final_positions:
            if p.symbol in self.initial_position_symbols:
                unrealized_initial_pnl += p.unrealized_pnl
            else:
                unrealized_strategy_pnl += p.unrealized_pnl

        # ========== 6. Calculate Total Changes ==========
        balance_change = final_balance - self.initial_balance
        equity_change = final_equity - self.initial_equity
        equity_change_pct = (equity_change / self.initial_equity * 100) if self.initial_equity > 0 else 0

        # ========== 7. Print Report ==========
        print("\n" + "="*80)
        print("📊 BACKTEST SUMMARY")
        print("="*80)
        print(f"Duration: {BACKTEST_DURATION_DAYS} trading days")

        # --- SECTION 1: Account Overview ---
        print(f"\n【Account Overview】")
        print(f"                    Beginning              Ending              Change")
        print(f"  Cash Balance    {self.initial_balance:>12,.2f}  {final_balance:>12,.2f}  {balance_change:>12,.2f}")
        print(f"  Stock Value     {initial_position_value:>12,.2f}  {final_initial_position_value + final_strategy_position_value:>12,.2f}  {(final_initial_position_value + final_strategy_position_value - initial_position_value):>12,.2f}")
        print(f"  Total Equity    {self.initial_equity:>12,.2f}  {final_equity:>12,.2f}  {equity_change:>12,.2f} ({equity_change_pct:>+6.2f}%)")

        # --- SECTION 2: Cash Flow Analysis ---
        print(f"\n【Cash Flow Analysis】")
        print(f"  Strategy Buy Expenditure:     {-min(strategy_cash_flow, 0):>12,.2f}")
        print(f"  Strategy Sell Income:         {max(strategy_cash_flow, 0):>12,.2f}")
        print(f"  Strategy Net Cash Flow:       {strategy_cash_flow:>12,.2f}")
        print(f"  Cash Balance Change:          {balance_change:>12,.2f}")

        # --- SECTION 3: P&L Breakdown ---
        print(f"\n【P&L Breakdown】")
        print(f"  Total P&L:              {equity_change:>12,.2f} ({equity_change_pct:>+6.2f}%)")
        print(f"  ├─ Realized:        {realized_pnl:>12,.2f}")
        print(f"  └─ Unrealized:      {unrealized_initial_pnl + unrealized_strategy_pnl:>12,.2f}")
        print(f"     ├─ Initial Positions:            {unrealized_initial_pnl:>12,.2f}")
        print(f"     └─ Strategy Positions:            {unrealized_strategy_pnl:>12,.2f}")

        # --- SECTION 4: Position Summary ---
        print(f"\n【Position Summary】")
        initial_symbols = [p.symbol for p in self.initial_positions]
        final_symbols = [p.symbol for p in final_positions]
        strategy_symbols = [s for s in final_symbols if s not in self.initial_position_symbols]

        print(f"  Initial Positions: {len(self.initial_positions)} ({', '.join(initial_symbols) if initial_symbols else 'None'})")
        print(f"  Final Positions: {len(final_positions)} ({', '.join(final_symbols) if final_symbols else 'None'})")
        if strategy_symbols:
            print(f"  Strategy Additions: {len(strategy_symbols)} ({', '.join(strategy_symbols)})")

        # --- SECTION 5: Trade History ---
        print(f"\n【Trade History】({len(self.trade_log)} trades)")
        if self.trade_log:
            for i, trade in enumerate(self.trade_log, 1):
                print(self._format_trade_log_line_summary(trade, i))
        else:
            print("  No trades executed.")

        # --- SECTION 6: Final Verdict ---
        print(f"\n" + "="*80)
        if equity_change > 0:
            print(f"✅ Strategy Performance: Profit {equity_change:,.2f} ({equity_change_pct:+.2f}%)")
        elif equity_change < 0:
            print(f"❌ Strategy Performance: Loss {abs(equity_change):,.2f} ({equity_change_pct:.2f}%)")
        else:
            print(f"⚪ Strategy Performance: Break-even")
        print("="*80 + "\n")

        # --- BONUS: Print trade history in oneshot backtest.log format ---
        # This allows easy comparison between full_sim and oneshot backtest logs
        log.info("")
        log.info("="*80)
        self.print_trade_history_as_logs()
        log.info("="*80)

    async def monitor_prices(self):
        log.info("Price monitoring started")

        while not SHUTDOWN:
            try:
                # is_market_open = self.client.broker_api.api.market.is_market_open()  # only specific to MockBroker
                is_market_open = self.client.is_market_open()  # only specific to MockBroker

                # Market closed: server handles time-skipping internally (AX_SKIP_NON_TRADING_HOURS).
                # cjtrade_system simply waits; no direct adjust_time() call needed.
                if not is_market_open:
                    log.debug("⏸️  Market closed, waiting for server to advance time...")
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

                        # Record equity curve point using this fresh price (deduped by minute)
                        self._record_equity_point(snapshot.timestamp, price, symbol)

            except Exception as e:
                log.error(f"Price monitoring error: {e}")

            await asyncio.sleep(self.mock_env_sleep(PRICE_MONITOR_INTERVAL))

    async def analyze_signals(self):
        log.info("Signal analysis started")

        while not SHUTDOWN:
            try:
                symbols = list(self.price_history.keys())
                log.debug(f"Analyzing {len(symbols)} symbols: {symbols}")  # debug: empty on first tick is normal

                for symbol in symbols:
                    history_len = len(self.price_history.get(symbol, []))

                    if history_len < BB_WINDOW_SIZE:
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

    # TODO: If account state file is synced with real account, this format would not
    #       consume 'initial_sync' fill order (a mechanism for syncing current price)
    #       and only having default current price (which is around 100), so most of
    #       the stock performance will be very very low, and does not reflect the truth.
    #       hint: `Position().unrealized_pnl`
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
        context += f"Positions: {len(positions) if positions else 0}\n\n"  # <----- HERE!!!

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
                # Use mock_time if available, otherwise timestamp
                if 'mock_time' in trade:
                    time_obj = trade['mock_time']
                else:
                    time_obj = trade['timestamp']
                ts = time_obj.strftime('%m-%d %H:%M')
                action_icon = "🟢" if trade['action'] == 'BUY' else "🔴"
                context += f"  {i:2d}. [{ts}] {action_icon} {trade['action']:4s} {trade['quantity']:>3d}x {trade['symbol']:6s} @ ${trade['price']:>7.2f} | {trade['reason']}\n"
        else:
            context += "  (No trades yet)\n"

        return context

    async def generate_llm_report(self):
        log.info("LLM report generator started")

        while not SHUTDOWN:
            try:
                if not self.llm_pool:
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
                response = self.llm_pool.generate_response(prompt)

                log.info(f"\n{'='*60}\n🤖 LLM ANALYSIS REPORT\n{'='*60}\n{response}\n{'='*60}\n")
                # also print to file for record
                with open("llm_report.txt", "a") as f:
                    f.write(f"\n{'='*60}\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} LLM ANALYSIS REPORT\n{'='*60}\n{response}\n{'='*60}\n")

            except Exception as e:
                log.error(f"LLM report error: {e}")

            # TODO: Currently this is just a workaround
            # Resume server-side time progression now that the client is fully connected.
            # The server pauses mock time right after initialisation so that client
            # startup lag does not silently consume backtest time at high playback speed.
            # Ensure we operate on the module-level flag so the change persists.
            global RESUME_TIME_AFTER_CLIENT_READY
            if not RESUME_TIME_AFTER_CLIENT_READY and LAUNCH_MODE in ('backtest', 'demo'):
                try:
                    self.client.broker_api.middleware.resume_time_progress()
                    log.info("▶ Mock time resumed (client ready)")
                except Exception as e:
                    log.warning(f"Could not resume time progress: {e}")
                # mark resumed so we don't attempt again
                RESUME_TIME_AFTER_CLIENT_READY = True  # flag to trigger time resume in monitor_prices()


            await asyncio.sleep(self.mock_env_sleep(LLM_REPORT_INTERVAL))

    async def execute_orders(self):
        global SHUTDOWN
        log.info("Order executor started (event-driven mode)")

        while not SHUTDOWN:
            try:
                # Check if backtest period is over
                if self.launch_mode in ['backtest', 'demo'] and self.should_exit_backtest():
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

                if self.launch_mode in ['backtest', 'demo']:
                    current_time = self.client.broker_api.get_system_time()['mock_current_time']

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
                    mode_prefix = "[PAPER]"

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
                                intraday_odd=True,
                                opt_field={"session_id": self.session_id},
                            )

                            # Get mock_current_time for backtest alignment
                            try:
                                mock_time = self.client.broker_api.get_system_time()['mock_current_time']
                            except:
                                mock_time = datetime.now()

                            trade_record = {
                                'action': 'BUY',
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'reason': reason,
                                'timestamp': datetime.now(),
                                'mock_time': mock_time
                            }
                            self.trade_log.append(trade_record)
                            print(f"📝 BUY {quantity} shares of {symbol} at {price:.2f} ({reason})")

                            log.info(f"{mode_prefix} ✅ Order placed: {order_result}")
                            push_to_ntfy_sh(title="New order placed", message=f"Buy {symbol} {quantity} shares @ ${price:.2f}")
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
                                intraday_odd=False,
                                opt_field={"session_id": self.session_id},
                            )

                            # Get mock_current_time for backtest alignment
                            try:
                                mock_time = self.client.broker_api.get_system_time()['mock_current_time']
                            except:
                                mock_time = datetime.now()

                            trade_record = {
                                'action': 'SELL',
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'reason': reason,
                                'timestamp': datetime.now(),
                                'mock_time': mock_time
                            }
                            self.trade_log.append(trade_record)
                            print(f"📝 SELL {quantity} shares of {symbol} at {price:.2f} ({reason})")

                            log.info(f"{mode_prefix} ✅ Order placed: {order_result}")
                            push_to_ntfy_sh(title="New order placed", message=f"Sell {symbol} {quantity} shares @ ${price:.2f}")
                        except Exception as e:
                            log.error(f"{mode_prefix} ❌ Failed to place SELL order: {e}")

            except Exception as e:
                log.error(f"Order execution error: {e}")

    async def display_time(self):
        log.info("Time display started")

        while not SHUTDOWN:
            if "arenax" in self.client.get_broker_name():
                ts = self.client.broker_api.get_system_time()['mock_current_time']
            else:
                ts = self.client.broker_api.get_system_time()['real_current_time']

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
            # print('check_if_any_order_can_be_filled()')
            try:
                pass
                # self.client.broker_api.api._trigger_order_matching()
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
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # TODO: Currently this is just a workaround
    global RESUME_TIME_AFTER_CLIENT_READY
    RESUME_TIME_AFTER_CLIENT_READY = False

    # Get broker type (default: mock)
    broker_type = os.environ.get('BROKER_TYPE', 'arenax').lower()

    # Load broker/service configurations (API keys, certs, etc.)
    load_cjconf()

    # Determine backtest mode from env or default to 'y'
    launch_mode = os.environ.get('LAUNCH_MODE').lower()

    # Load system configurations from .cjsys file (intervals, window size, etc.)
    load_cjsys(broker=broker_type, mode=launch_mode)

    # print_config()
    # import time
    # time.sleep(30)

    # Create SystemConfig from loaded config dict
    cfg = SystemConfig(
        backtest_duration_days=config['backtest_duration_days'],
        watch_list=config['watch_list'],
        analysis_interval=config['analysis_interval'],
        check_fill_interval=config['check_fill_interval'],   # maybe not needed
        display_time_interval=config['display_time_interval'],
        llm_report_interval=config['llm_report_interval'],
        price_monitor_interval=config['price_monitor_interval'],
        bb_min_width_pct=config['bb_min_width_pct'],
        bb_window_size=config['bb_window_size'],
        risk_max_position_pct=config['risk_max_position_pct'],
        launch_mode=config['launch_mode'],
        remote_host=config.get('remote_host', 'localhost'),
        remote_port=config.get('remote_port', 8801),
    )

    # Apply config to module-level globals
    _apply_config(cfg)

    log.info(
        f"System config loaded: {broker_type} | "
        f"window={cfg.bb_window_size} | "
    )

    # Prepare broker client config
    username = config.get('username', 'user000')
    config["state_file"] = f"./{broker_type}_{username}.json"
    config["mirror_db_path"] = f"./data/{broker_type}_{username}.db"

    # Create broker client based on type
    if broker_type == 'arenax':
        config['api_key'] = "testkey123"
        client = AccountClient(BrokerType.ARENAX, **config)
    elif broker_type == 'sinopac':
        pass    # pass for now since it is dangerous while developing and testing.
    else:
        log.error(f"Unsupported broker type: {broker_type}")
        return

    try:
        client.connect()
        log.info(f"Connected to {broker_type} broker")
    except ConnectionError as e:
        print(f"Cannot connect to {broker_type} broker: {e}")
        exit(1)

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
        # asyncio.create_task(system.trigger_order_matching(), name="order_matching"),
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
    log.info(f"Mode: {'BACKTEST (' + str(BACKTEST_DURATION_DAYS) + ' days)' if LAUNCH_MODE in ['backtest', 'demo'] else LAUNCH_MODE}")
    print("CJTrade System is about to launch", end=" ")
    countdown = 8
    for i in range(countdown, 0, -1):
        print(f"...", end="", flush=True)
        time.sleep(1)

    try:
        while not SHUTDOWN:
            await asyncio.sleep(system.mock_env_sleep(1))
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")

    if LAUNCH_MODE == 'backtest' or LAUNCH_MODE == 'demo':
        system.print_backtest_summary()
        prefix = "backtest"
    else:
        system.print_backtest_summary()
        prefix = "paper"

    # Build and persist result immediately, before disconnect,
    # so fill_history is still queryable on the server.
    result = system.build_backtest_result()
    if result is not None:
        save_path = f"{prefix}_{system.session_id[:8]}.pkl"
        result.save(save_path)
        log.info(f"💾 Result saved → {save_path}")
        BacktestReport(result).full_report()

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
    parser.add_argument("-B", "--broker", type=str, default="arenax",
                        choices=["arenax", "sinopac"],
                        help="Broker type: arenax or sinopac")
    parser.add_argument("-m", "--mode", type=str, default='backtest',
                        choices=['backtest', 'paper', 'demo'],
                        help="Backtest mode: backtest, paper or demo")
    args = parser.parse_args()

    os.environ['BROKER_TYPE'] = args.broker
    os.environ['LAUNCH_MODE'] = args.mode

    asyncio.run(async_main())
