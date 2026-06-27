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
from abc import ABC
from abc import abstractmethod
from asyncio import Queue
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import numpy as np
from aiohttp import web as _aiohttp_web
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
from dotenv import dotenv_values


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


def print_config():
    log.info(f"System Configuration: {config}")


def build_system_config(broker: str, mode: str) -> "SystemConfig":
    """Build SystemConfig with explicit priority: os.environ > .cjsys file > default.

    This is the single entry point for system config loading.
    Unlike load_cjsys(), this function:
      - Does NOT mutate os.environ or the module-level config dict
      - Returns an immutable SystemConfig directly (no KeyError possible)
      - Applies and logs the priority resolution for every key
    """
    import pathlib

    cfg_file = pathlib.Path(__file__).parent / "configs" / f"{broker}_{mode}.cjsys"
    if cfg_file.exists():
        log.info(f"Loading config file {cfg_file}")
        file_cfg = dotenv_values(cfg_file)
    else:
        log.warning(f"Config file {cfg_file} not found, using defaults")
        file_cfg = {}

    def _get(key: str, default=None):
        """Priority: os.environ > file > default."""
        env_key = f"CJSYS_{key.upper()}"
        val = os.environ.get(env_key) or file_cfg.get(env_key)
        if val is not None and str(val).strip():
            log.info(f"  {env_key}={val}")
            return str(val).strip()
        return default

    _raw_duration = _get('BACKTEST_DURATION_DAYS') or ''
    if _raw_duration:
        backtest_duration_days = int(_raw_duration)
    elif mode in ('backtest', 'demo'):
        backtest_duration_days = 7
    else:
        backtest_duration_days = float('inf')

    _raw_wl = _get('WATCH_LIST') or ''
    watch_list = [s.strip() for s in _raw_wl.split(',') if s.strip() and s.strip().lower() != 'none']

    return SystemConfig(
        launch_mode=mode,
        watch_list=watch_list,
        remote_host=_get('REMOTE_HOST', 'localhost'),
        remote_port=int(_get('REMOTE_PORT', 8801) or 8801),
        backtest_duration_days=backtest_duration_days,
        analysis_interval=float(_get('ANALYSIS_INTERVAL', 30) or 30),
        check_fill_interval=float(_get('CHECK_FILL_INTERVAL', 60) or 60),
        display_time_interval=float(_get('DISPLAY_TIME_INTERVAL', 40) or 40),
        llm_report_interval=float(_get('LLM_REPORT_INTERVAL', 300) or 300),
        price_monitor_interval=float(_get('PRICE_MONITOR_INTERVAL', 60) or 60),
        bb_min_width_pct=float(_get('BB_MIN_WIDTH_PCT', 0.01) or 0.01),
        bb_window_size=int(_get('BB_WINDOW_SIZE', 20) or 20),
        risk_max_position_pct=float(_get('RISK_MAX_POSITION_PCT', 0.05) or 0.05),
        api_host=_get('API_HOST', '0.0.0.0'),
        api_port=int(_get('API_PORT', 8899) or 8899),
    )

# ==================== System Config ====================
@dataclass
class SystemConfig:
    # ── Broker-agnostic fields (required) ─────────────────────────────
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
    # ── Broker-agnostic fields (optional) ─────────────────────────────
    # For real/live/paper mode, backtest_duration_days = inf (never stops by duration)
    # For backtest/demo mode, set to the desired number of trading days
    backtest_duration_days: float = float('inf')
    # ── ArenaX-specific fields (only meaningful when broker == "arenax") ─
    remote_host: str = "localhost"      # ArenaX server address
    remote_port: int = 8801             # ArenaX server port
    # ── CJTrade System API server ─────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8899

    def to_dict(self) -> dict:
        import dataclasses, math
        d = dataclasses.asdict(self)
        # JSON can't represent inf; replace with the string "inf" for readability
        for k, v in d.items():
            if isinstance(v, float) and math.isinf(v):
                d[k] = "inf"
        return d

    def dump_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _apply_config(cfg: SystemConfig) -> None:
    """Write a SystemConfig into module-level globals used by all coroutines."""
    global LAUNCH_MODE, REMOTE_HOST, REMOTE_PORT
    global BACKTEST_DURATION_DAYS, BACKTEST_PLAYBACK_SPEED
    global WATCH_LIST
    global ANALYSIS_INTERVAL, CHECK_FILL_INTERVAL, DISPLAY_TIME_INTERVAL, LLM_REPORT_INTERVAL, PRICE_MONITOR_INTERVAL
    global BB_MIN_WIDTH_PCT, BB_WINDOW_SIZE
    global RISK_MAX_POSITION_PCT
    global CJTRADE_API_HOST, CJTRADE_API_PORT

    BACKTEST_DURATION_DAYS     = cfg.backtest_duration_days
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
    CJTRADE_API_HOST           = cfg.api_host
    CJTRADE_API_PORT           = cfg.api_port


SHUTDOWN = False



# ====================  Signal abstraction  ====================

@dataclass
class SignalResult:
    """Unified return type for all signal strategies.

    Every strategy must populate *signal*, *symbol*, *price*, and
    *timestamp*.  Strategy-specific indicators (e.g. BB bands, DCA period)
    go into *meta* so callers can remain generic while still being able to
    render strategy-specific detail when needed.

    *target_quantity* lets a strategy control its own position sizing:
      ``None``  — use the system's default ``calculate_position_size()``
      ``0``     — do not trade (strategy says skip this signal)
      ``>0``    — trade exactly this many shares
    """
    signal: str                              # 'BUY' | 'SELL' | 'HOLD'
    symbol: str
    price: float                             # current market price at signal time
    timestamp: datetime
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    target_quantity: Optional[int] = None    # see docstring above


class SignalStrategy(ABC):
    """Base class for all live-system trading strategies.

    Each subclass receives the same inputs (symbol, prices, current_time,
    current_quantity) and returns the same *SignalResult* type, making
    strategies interchangeable inside TradingSystem without any caller changes.

    *current_quantity* is the number of shares currently held for *symbol*.
    Strategies may use it to implement position-stacking logic (or prevent it).
    """

    @abstractmethod
    def calculate(
        self,
        symbol: str,
        prices: List[float],
        current_time: datetime,
        current_quantity: int = 0,
    ) -> Optional[SignalResult]:
        """Return a SignalResult for the current bar, or None if insufficient data."""
        ...


# ====================          DCA Strategy          ====================

class DCAStrategy(SignalStrategy):
    """Time-based DCA: emit BUY once every *period_days* per symbol.

    Trigger state is managed internally, so callers never need to thread
    ``last_trigger_time`` through ``analysis_results``.
    Intentionally stacks positions: each period trigger buys a fixed lot
    regardless of what is already held.
    """

    def __init__(self, period_days: int = 30) -> None:
        self._period = timedelta(days=period_days)
        self._last_trigger: Dict[str, datetime] = {}

    def calculate(
        self,
        symbol: str,
        prices: List[float],
        current_time: datetime,
        current_quantity: int = 0,
    ) -> Optional[SignalResult]:
        if not prices:
            return None
        price = prices[-1]
        last = self._last_trigger.get(symbol)

        if last is None or (current_time - last) >= self._period:
            self._last_trigger[symbol] = current_time
            label = 'No previous trigger' if last is None else f'{(current_time - last).days}d elapsed'
            log.info(f"DCA {symbol}: {label}, signal=BUY")
            return SignalResult(
                signal='BUY', symbol=symbol, price=price,
                timestamp=current_time,
                reason=f"DCA: {self._period.days}-day period elapsed",
                meta={'period_days': self._period.days, 'last_trigger_time': current_time.isoformat()},
            )

        days_since = (current_time - last).days
        log.info(f"DCA {symbol}: {days_since}/{self._period.days} days elapsed, signal=HOLD")
        return SignalResult(
            signal='HOLD', symbol=symbol, price=price,
            timestamp=current_time,
            reason=f"DCA: waiting ({days_since}/{self._period.days} days)",
            meta={'period_days': self._period.days, 'last_trigger_time': last.isoformat()},
        )


# ====================  Bollinger Bands Strategy  ====================

class BollingerBandsStrategy(SignalStrategy):
    """Bollinger Band mean-reversion: BUY at lower band, SELL at upper band.

    Position model: single entry, full exit — no stacking.
    - BUY  fires only when flat (``current_quantity == 0``).
    - SELL liquidates the entire position (``target_quantity = current_quantity``).
    This keeps each trade a clean round-trip, making per-trade P&L well-defined.
    """

    def __init__(self, window: int = 20, min_width_pct: float = 0.01) -> None:
        self._window = window
        self._min_width_pct = min_width_pct

    def calculate(
        self,
        symbol: str,
        prices: List[float],
        current_time: datetime,
        current_quantity: int = 0,
    ) -> Optional[SignalResult]:
        if not prices or len(prices) < self._window:
            log.debug(f"BB {symbol}: Insufficient data ({len(prices) if prices else 0}/{self._window} prices)")
            return None

        price = prices[-1]
        prices_arr = np.array(prices, dtype=float)
        upper_bands, middle_bands, lower_bands = ta.bb(prices_arr, timeperiod=self._window, nbdevup=2.5, nbdevdn=2.5)
        upper, middle, lower = upper_bands[-1], middle_bands[-1], lower_bands[-1]
        std_dev = (upper - middle) / 2
        band_width = (upper - lower) / middle if middle > 0 else 0

        log.info(f"BB Debug [{symbol}]: Price={price:.2f} | "
                 f"Upper={upper:.2f} Mid={middle:.2f} Lower={lower:.2f} | "
                 f"StdDev={std_dev:.2f} BandWidth={band_width*100:.2f}%")

        if band_width < self._min_width_pct:
            signal = 'HOLD'
            reason = f"band too narrow ({band_width*100:.2f}%)"
            log.info(f"⚪ BB {symbol}: {reason}, signal=HOLD")
        elif price <= lower:
            signal = 'BUY'
            reason = f"price {price:.2f} <= lower {lower:.2f}"
            log.info(f"🟢 BB {symbol}: {reason}")
        elif price >= upper:
            signal = 'SELL'
            reason = f"price {price:.2f} >= upper {upper:.2f}"
            log.info(f"🔴 BB {symbol}: {reason}")
        else:
            signal = 'HOLD'
            reason = "price in middle band"
            log.info(f"⚪ BB {symbol}: {reason}")

        # Non-stacking: skip BUY if already in position; full-exit on SELL
        target_quantity: Optional[int] = None
        if signal == 'BUY' and current_quantity > 0:
            signal = 'HOLD'
            reason = f"already holding {current_quantity} shares, skipping (no stacking)"
            log.info(f"⚪ BB {symbol}: {reason}")
        elif signal == 'SELL' and current_quantity > 0:
            target_quantity = current_quantity  # sell everything

        return SignalResult(
            signal=signal, symbol=symbol, price=price,
            timestamp=current_time,
            reason=reason,
            meta={
                'upper': round(upper, 2),
                'middle': round(middle, 2),
                'lower': round(lower, 2),
                'std_dev': round(std_dev, 2),
                'band_width': round(band_width * 100, 2),
            },
            target_quantity=target_quantity,
        )

# CJTrade lightweight API server (for FinHub / external consumers)
CJTRADE_API_HOST = "0.0.0.0"
CJTRADE_API_PORT = 8899

# ==================== Trading System Class ====================
class TradingSystem:
    def __init__(self, client: AccountClient):
        self.client = client
        self.price_history: Dict[str, List[float]] = {}
        self.analysis_results: Dict[str, SignalResult] = {}
        # self.strategy: SignalStrategy = DCAStrategy(period_days=30)
        self.strategy: SignalStrategy = BollingerBandsStrategy(window=BB_WINDOW_SIZE, min_width_pct=BB_MIN_WIDTH_PCT)
        self.llm_pool: Optional[List] = None
        self.launch_mode = LAUNCH_MODE

        if self.is_backtest:
            self.start_time = self.current_time()
            log.info(f"⏰ Using mock market start time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.start_time = self.current_time()
            log.info(f"⏰ Using real system time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        self.trade_log: List[Dict] = []
        self.strategy_cash_flow = 0.0
        self.signal_queue: Queue = Queue()

        # Get playback speed from mock broker backend (for time-scaled delays)
        self.playback_speed = 1.0
        if self.is_backtest:
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

        self.llm_client_0 = MockLLMClient()
        self.llm_pool = LLMPool([self.llm_client_0])   # always enabled; real clients added below if keys exist

        if api_key_1 or api_key_2:
            try:
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
            log.warning("No LLM API keys found, using MockLLM")

    # ── Mode helpers ──────────────────────────────────────────────────────────

    @property
    def is_backtest(self) -> bool:
        """True for modes that use ArenaX virtual clock (backtest / demo).
        paper/real use wall-clock time and do not have playback speed or duration limits."""
        return self.launch_mode in ('backtest', 'demo')

    def current_time(self) -> datetime:
        """Current trading time for all modes.
        ArenaX_RealMarket.mock_current_time returns datetime.now(), so this call
        is valid for paper/real as well — no branching needed."""
        return self.client.broker_api.get_system_time()['mock_current_time']

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
        """Get list of symbols to monitor from watch_list config, or from current positions if watch_list is empty"""
        symbols = []
        try:
            symbols = list(WATCH_LIST) if WATCH_LIST else []

            # Only add current positions if watch_list is empty
            if len(symbols) == 0:
                positions = self.client.get_positions()
                if positions:
                    position_symbols = [p.symbol for p in positions]
                    symbols = list(set(position_symbols))
                    log.info(f"No CJSYS_WATCH_LIST specified. Watching {len(symbols)} symbol(s) from current positions: {', '.join(sorted(symbols))}")
                else:
                    log.warning("No symbols to monitor – set CJSYS_WATCH_LIST in your .cjsys config or ensure you have open positions")
            else:
                log.info(f"Watching {len(symbols)} symbol(s) from CJSYS_WATCH_LIST: {', '.join(sorted(symbols))}")

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
        """Calculate position size as a fixed percentage of total equity.

        Uses ``RISK_MAX_POSITION_PCT`` (default 5 %) of current equity per order.
        Rounds down to the nearest share; minimum 1 share if equity covers it.
        """
        total_equity = self.get_total_equity()
        max_value = total_equity * RISK_MAX_POSITION_PCT

        quantity = int(max_value / price) if price > 0 else 0
        if quantity < 1 and total_equity > price:
            quantity = 1

        log.info(f"Position sizing: equity={total_equity:.2f}, "
                 f"{RISK_MAX_POSITION_PCT*100:.0f}% = {max_value:.2f}, "
                 f"quantity={quantity} @ {price:.2f}")
        return quantity

    def should_exit_backtest(self) -> bool:
        """Check if backtest period is over (based on trading days)

        Trading day definition:
        - Day 0: 09:00 start, 13:30 close = 1 completed trading day
        - After 13:30, the day is considered complete
        """
        if not self.is_backtest:
            return False

        current_time = self.current_time()

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
                current_time = self.current_time()

                positions = self.client.get_positions() or []
                pos_qty = {p.symbol: p.quantity for p in positions}

                for symbol in symbols:
                    history_len = len(self.price_history.get(symbol, []))

                    if history_len < BB_WINDOW_SIZE:
                        continue

                    prices = self.price_history.get(symbol, [])
                    result = self.strategy.calculate(symbol, prices, current_time,
                                                     current_quantity=pos_qty.get(symbol, 0))

                    if result:
                        old_signal = self.analysis_results[symbol].signal if symbol in self.analysis_results else None
                        new_signal = result.signal

                        if new_signal != 'HOLD' and new_signal != old_signal:
                            log.info(f"📢 Signal changed: {symbol} {old_signal} → {new_signal} @ {result.price:.2f}")
                            await self.signal_queue.put({
                                'symbol': symbol,
                                'signal': new_signal,
                                'result': result,
                                'timestamp': current_time
                            })

                        self.analysis_results[symbol] = result
                    else:
                        log.warning(f"{symbol}: signal calculation returned None")

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

        # Signals
        context += f"\n🎯 SIGNALS\n"
        for symbol in sorted(self.analysis_results.keys()):
            result = self.analysis_results[symbol]
            signal_icon = "🟢" if result.signal == 'BUY' else "🔴" if result.signal == 'SELL' else "⚪"
            line = f"  {signal_icon} {symbol:6s} | Signal: {result.signal:4s} | Price: ${result.price:>7.2f}"
            if 'upper' in result.meta:
                line += (f" | Upper: ${result.meta['upper']:>7.2f}"
                         f" | Mid: ${result.meta['middle']:>7.2f}"
                         f" | Lower: ${result.meta['lower']:>7.2f}")
            elif result.reason:
                line += f" | {result.reason}"
            context += line + "\n"

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
            # Resume server-side mock time on the first tick, regardless of whether
            # an LLM is configured.  Must run before any `continue` so that the
            # backtest always starts progressing even when LLM keys are absent.
            global RESUME_TIME_AFTER_CLIENT_READY
            if not RESUME_TIME_AFTER_CLIENT_READY and self.is_backtest:
                try:
                    self.client.broker_api.middleware.resume_time_progress()
                    log.info("▶ Mock time resumed (client ready)")
                except Exception as e:
                    log.warning(f"Could not resume time progress: {e}")
                RESUME_TIME_AFTER_CLIENT_READY = True

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
                time.sleep(10)
            except Exception as e:
                log.error(f"LLM report error: {e}")

            await asyncio.sleep(self.mock_env_sleep(LLM_REPORT_INTERVAL))

    async def execute_orders(self):
        global SHUTDOWN
        log.info("Order executor started (event-driven mode)")

        while not SHUTDOWN:
            try:
                # Check if backtest period is over
                if self.is_backtest and self.should_exit_backtest():
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
                price = result.price

                if self.is_backtest:
                    current_time = self.current_time()

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
                    mode_prefix = f"[{self.launch_mode.upper()}]"

                log.info(f"{mode_prefix} ⚡ Processing signal event: {symbol} {signal} @ {price:.2f}")

                positions = self.client.get_positions()
                has_position = any(p.symbol == symbol for p in positions) if positions else False

                if signal == 'BUY':
                    quantity = (result.target_quantity
                                if result.target_quantity is not None
                                else self.calculate_position_size(price))

                    if quantity > 0:
                        lower_band = result.meta.get('lower', 0)
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
                            mock_time = self.current_time()

                            trade_record = {
                                'action': 'BUY',
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'reason': reason,
                                'timestamp': datetime.now(),
                                'mock_time': mock_time,
                                'order_status': order_result.status.value if hasattr(order_result.status, 'value') else str(order_result.status),
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
                        quantity = (result.target_quantity
                                    if result.target_quantity is not None
                                    else position.quantity)  # default: full exit
                        quantity = min(quantity, position.quantity)

                        upper_band = result.meta.get('upper', 0)
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
                            mock_time = self.current_time()

                            trade_record = {
                                'action': 'SELL',
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'reason': reason,
                                'timestamp': datetime.now(),
                                'mock_time': mock_time,
                                'order_status': order_result.status.value if hasattr(order_result.status, 'value') else str(order_result.status),
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
            ts = self.current_time()

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


# ==================== CJTrade Lightweight API Server ====================

async def run_api_server(system: 'TradingSystem') -> None:
    """Read-only HTTP server that Finhub (and other consumers) can poll.

    Runs inside the same asyncio event loop as the trading system.
    All endpoints are GET-only (or auth POST); no order execution here.

    Endpoints
    ---------
    POST /api/auth/login          Accept any username, return a bearer token.
    GET  /api/account             Cash balance, equity, P&L summary.
    GET  /api/positions           Current open positions (holdings).
    GET  /api/trades              Executed trade log (newest-first).
    GET  /api/equity_curve        Equity-curve data points.
    """

    @_aiohttp_web.middleware
    async def _cors(request, handler):
        """Allow cross-origin requests from the Finhub frontend."""
        if request.method == 'OPTIONS':
            return _aiohttp_web.Response(status=204, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            })
        resp = await handler(request)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    async def login(request):
        """Issue a CJTrade bearer token.

        Accepts any username for now; token format is ``cjtrade-{username}``.
        Caller (Finhub) should send ``{"username": "john"}`` in the body.
        """
        try:
            data = await request.json()
        except Exception:
            data = {}
        username = data.get('username', 'anonymous')
        return _aiohttp_web.json_response({
            'access_token': f'cjtrade-{username}',
            'token_type': 'bearer',
            'username': username,
        })

    async def get_account(request):
        try:
            balance = system.client.get_balance()
            equity  = system.get_total_equity()
            pnl     = equity - system.initial_equity
            pnl_pct = (pnl / system.initial_equity * 100) if system.initial_equity > 0 else 0
            return _aiohttp_web.json_response({
                'balance':         round(balance, 2),
                'equity':          round(equity, 2),
                'initial_equity':  round(system.initial_equity, 2),
                'pnl':             round(pnl, 2),
                'pnl_pct':         round(pnl_pct, 2),
                'session_id':      system.session_id,
                'launch_mode':     system.launch_mode,
            })
        except Exception as e:
            log.error(f"API /account error: {e}")
            return _aiohttp_web.json_response({'error': str(e)}, status=500)

    async def get_positions(request):
        try:
            positions = system.client.get_positions() or []
            result = []
            for p in positions:
                cost    = p.avg_cost * p.quantity
                pnl_pct = (p.unrealized_pnl / cost * 100) if cost > 0 else 0
                result.append({
                    'symbol':            p.symbol,
                    'quantity':          p.quantity,
                    'avg_cost':          round(p.avg_cost, 2),
                    'current_price':     round(p.current_price, 2),
                    'market_value':      round(p.market_value, 2),
                    'unrealized_pnl':    round(p.unrealized_pnl, 2),
                    'unrealized_pnl_pct': round(pnl_pct, 2),
                })
            return _aiohttp_web.json_response(result)
        except Exception as e:
            log.error(f"API /positions error: {e}")
            return _aiohttp_web.json_response({'error': str(e)}, status=500)

    async def get_trades(request):
        try:
            # Use fill_history from broker server as ground truth.
            # Every entry here is already confirmed FILLED; no status ambiguity.
            middleware = system.client.broker_api.middleware
            raw = middleware.get_backtest_state(session_id=system.session_id)
            fills = raw.get("fill_history", []) if raw else []

            trades = []
            for f in reversed(fills):   # newest-first
                action = f.get("action", "")
                qty = abs(f.get("quantity", 0))
                trades.append({
                    'action':       action,
                    'symbol':       f.get("symbol", ""),
                    'quantity':     qty,
                    'price':        round(f.get("price", 0.0), 2),
                    'timestamp':    f.get("time", ""),
                    'reason':       f.get("reason", ""),
                    'order_status': 'FILLED',
                })
            return _aiohttp_web.json_response(trades)
        except Exception as e:
            log.error(f"API /trades error: {e}")
            return _aiohttp_web.json_response({'error': str(e)}, status=500)

    async def get_equity_curve(request):
        try:
            return _aiohttp_web.json_response(system._equity_curve)
        except Exception as e:
            log.error(f"API /equity_curve error: {e}")
            return _aiohttp_web.json_response({'error': str(e)}, status=500)

    app = _aiohttp_web.Application(middlewares=[_cors])
    app.router.add_post('/api/v1/auth/login',   login)
    app.router.add_get('/api/v1/account',       get_account)
    app.router.add_get('/api/v1/positions',     get_positions)
    app.router.add_get('/api/v1/trades',        get_trades)
    app.router.add_get('/api/v1/equity_curve',  get_equity_curve)
    # Catch-all OPTIONS for preflight
    app.router.add_route('OPTIONS', r'/{path_info:.*}',
        lambda r: _aiohttp_web.Response(status=204, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type',
        })
    )

    runner = _aiohttp_web.AppRunner(app, access_log=None)
    await runner.setup()
    site = _aiohttp_web.TCPSite(runner, CJTRADE_API_HOST, CJTRADE_API_PORT)
    await site.start()
    log.info(f"🌐 CJTrade API server: http://{CJTRADE_API_HOST}:{CJTRADE_API_PORT}/api/")

    try:
        while not SHUTDOWN:
            await asyncio.sleep(1)
    finally:
        await runner.cleanup()
        log.info("CJTrade API server stopped")


# ==================== Main Entry Point ====================
def signal_handler(sig, frame):
    global SHUTDOWN
    log.info(f"Received signal {sig}, shutting down...")
    SHUTDOWN = True


async def async_main(cfg: SystemConfig, broker: str):
    """Main async entry point.

    cfg and broker are passed explicitly by the runner (or main_system).
    No env reading here — config is already resolved before this is called.
    """
    global SHUTDOWN
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # TODO: Currently this is just a workaround
    global RESUME_TIME_AFTER_CLIENT_READY
    RESUME_TIME_AFTER_CLIENT_READY = False

    # Load broker/service configurations (API keys, certs, etc.)
    load_cjconf()

    # Apply system config to module-level globals (includes CJTRADE_API_HOST/PORT)
    _apply_config(cfg)

    log.info(
        f"System config loaded: {broker} | "
        f"window={cfg.bb_window_size} | "
    )

    # Prepare broker client — merge API keys (from config) with connection params (from cfg)
    username = config.get('username', 'user000')
    config["state_file"] = f"./{broker}_{username}.json"
    config["mirror_db_path"] = f"./data/{broker}_{username}.db"

    # Create broker client based on type
    if broker == 'arenax':
        config['api_key'] = "testkey123"
        config['arenax_host'] = cfg.remote_host
        config['arenax_port'] = cfg.remote_port
        client = AccountClient(BrokerType.ARENAX, **config)
    elif broker == 'sinopac':
        client = AccountClient(BrokerType.SINOPAC, **config)
    else:
        log.error(f"Unsupported broker type: {broker}")
        return

    try:
        client.connect()
        log.info(f"Connected to {broker} broker")
    except ConnectionError as e:
        print(f"Cannot connect to {broker} broker: {e}")
        exit(1)

    system = TradingSystem(client)

    initial_symbols = system.get_watch_symbols()
    if not initial_symbols:
        log.warning("⚠️  No positions found. System will monitor positions as they are created.")

    tasks = [
        asyncio.create_task(system.monitor_prices(),       name="price_monitor"),
        asyncio.create_task(system.analyze_signals(),      name="signal_analysis"),
        asyncio.create_task(system.generate_llm_report(),  name="llm_report"),
        asyncio.create_task(system.execute_orders(),       name="order_executor"),
        asyncio.create_task(system.display_time(),         name="time_display"),
        asyncio.create_task(run_api_server(system),        name="api_server"),
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
    _sim_modes = ('backtest', 'demo')
    log.info(f"Mode: {'BACKTEST (' + str(BACKTEST_DURATION_DAYS) + ' days)' if LAUNCH_MODE in _sim_modes else LAUNCH_MODE}")
    print("CJTrade System is about to launch", end=" ")
    countdown = 8
    for i in range(countdown, 0, -1):
        print(f"...", end="", flush=True)
        await asyncio.sleep(1)

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
                        choices=['backtest', 'paper', 'demo', 'real'],
                        help="Backtest mode: backtest, paper, demo or real")
    args = parser.parse_args()

    cfg = build_system_config(args.broker, args.mode)
    asyncio.run(async_main(cfg=cfg, broker=args.broker))
