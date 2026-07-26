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

from typing import Protocol, Callable, List, Dict, Any
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models import Product, Snapshot

CJD_PORT = 5000
CJD_HOST = "localhost"

# Location should be cjtrade/pkgs/models/datatsource.py
# TODO: even though sinopac provide data source as part of the shioaji
#       package, but for trading system clean design, we have to split
#       data source as a different dependency. Ideally, the `ds` should
#       be initialized (configured) by the caller.
class IDataSource(Protocol):
    def __init__(self):
        pass

    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        ...

    def get_kbars(self, product: Product, start: str, end: str, interval: str):
        ...

    # def get_market_movers(self, top_n: int = 10, by: RankType = RankType.PRICE_PERCENTAGE_CHANGE, ascending: bool = True) -> Dict[str, float]:
    #     ...


# Location should be cjtrade/pkgs/models/
class SinopacDatasourceAapter(IDataSource):
    def __init__(self, bkr: AccountClient):
        super().__init__()

    def get_snapshots(self, products):
        return super().get_snapshots(products)

    def get_snapshots(self, products):
        return super().get_snapshots(products)


# Dependency Injection:
#   AccountClient, for order placing and account status
#   Datasource, for kbar price source of truth
#   RiskModel, for risk management
#   CostModel, for tax calculation
class CJTradeDaemon:
    def __init__(self, bkr: AccountClient, data: IDataSource):
        self.port = CJD_PORT
        self.host = CJD_HOST
        self.bkr  = bkr

    def run():
        while True:
            pass


# ==================== Trading System Class ====================
class TradingSystem:
    def __init__(self, client: AccountClient):
        self.client = client
        pass

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

    def mock_env_sleep(self, seconds: float) -> float:
        """Return sleep time scaled by playback speed"""
        return seconds / self.playback_speed

    async def dispatch_event_to_botworker(self, botworker, event):
        global SHUTDOWN
        log.info(f"dispatching event to botworker... (dispatcher -> {event} -> {botworker})")


    async def display_time(self):
        log.info("Time display started")

        while not SHUTDOWN:
            ts = self.current_time()

            time_str = ts.strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{'='*60}")
            print(f"Current Time: \033[93m{time_str}\033[0m")
            print(f"{'='*60}\n")

            await asyncio.sleep(self.mock_env_sleep(DISPLAY_TIME_INTERVAL))

    def _check():
        pass

    CHECK_INTERVAL = 1
    async def regular_check(self):
        log.info("do regular checks (time / price / market regime)")

        while not SHUTDOWN:
            try:
                self._check()
            except Exception as e:
                log.error(f"Order matching error: {e}")

            await asyncio.sleep(self.mock_env_sleep(self.CHECK_INTERVAL))


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


async def async_main(broker: str):
    global SHUTDOWN
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # TODO: Currently this is just a workaround
    global RESUME_TIME_AFTER_CLIENT_READY
    RESUME_TIME_AFTER_CLIENT_READY = False

    # Load broker/service configurations (API keys, certs, etc.)
    load_cjconf()

    # Apply system config to module-level globals (includes CJTRADE_API_HOST/PORT)
    # _apply_config(cfg)

    username = config.get('username', 'user000')
    config["state_file"] = f"./{broker}_{username}.json"
    config["mirror_db_path"] = f"./data/{broker}_{username}.db"

    # Create broker client based on type
    if broker == 'arenax':
        config['api_key'] = "testkey123"
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
        asyncio.create_task(system.monitor_prices(),               name="price_monitor"),
        asyncio.create_task(system.analyze_signals(),              name="signal_analysis"),
        asyncio.create_task(system.dispatch_event_to_botworker(),  name="order_executor"),
        asyncio.create_task(system.display_time(),                 name="time_display"),
        asyncio.create_task(system.regular_check(),                name="regular_check"),
        asyncio.create_task(run_api_server(system),                name="api_server"),
        # asyncio.create_task(system.trigger_order_matching(), name="order_matching"),
    ]

    os.system("clear")
    log.info("🏁 CJ Engine started")

    print("""
  ░██████      ░█████ ░██████████                       ░██                      
 ░██   ░██       ░██  ░██                                                        
░██              ░██  ░██         ░████████   ░████████ ░██░████████   ░███████  
░██              ░██  ░█████████  ░██    ░██ ░██    ░██ ░██░██    ░██ ░██    ░██ 
░██        ░██   ░██  ░██         ░██    ░██ ░██    ░██ ░██░██    ░██ ░█████████ 
 ░██   ░██ ░██   ░██  ░██         ░██    ░██ ░██   ░███ ░██░██    ░██ ░██        
  ░██████   ░██████   ░██████████ ░██    ░██  ░█████░██ ░██░██    ░██  ░███████  
                                                    ░██                          
                                              ░███████                           
                                                                                 
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
    # parser.add_argument("-m", "--data-source", type=str, default='backtest',
    #                     choices=['backtest', 'paper', 'demo', 'real'],
    #                     help="Backtest mode: backtest, paper, demo or real")
    args = parser.parse_args()

    asyncio.run(async_main(broker=args.broker))
