"""
apps/cjtrade_system/cjtrade_oneshot_backtest.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
One-shot (vectorised) backtest runner.

Fetches historical kbars from the ArenaX server in one HTTP call,
runs a BaseStrategy over them in-memory with BacktestEngine, then
saves and opens a full BacktestReport – all done in seconds.

Usage
-----
    # From the repo root:
    CJSYS_STATE_FILE=arenax_CJ.json  \\
    CJSYS_WATCH_LIST=2330             \\
    uv run python -m cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest

    # Or from Python:
    from cjtrade.apps.cjtrade_system.cjtrade_oneshot_backtest import run_oneshot
    run_oneshot(symbol="2330", start="2023-01-01", end="2024-01-01")

Environment / config keys
-------------------------
    CJSYS_WATCH_LIST               comma-separated symbols (first one used)
    CJSYS_ONESHOT_DURATION_DAYS    number of trading days to backtest (default: 5)
                                   used to pick a random start date unless
                                   CJSYS_ONESHOT_START is explicitly set.
                                   The random window is at least 1.5× duration so
                                   indicator warm-up data is always available.
    CJSYS_ONESHOT_START            ISO date override, e.g. 2023-01-01
                                   (takes precedence over CJSYS_ONESHOT_DURATION_DAYS)
    CJSYS_ONESHOT_END              ISO date, e.g. 2024-01-01  (default: today)
    CJSYS_ONESHOT_INTERVAL         kbar interval, default 1d
    CJSYS_ONESHOT_INITIAL_BALANCE  starting cash (default: 1_000_000)
    CJSYS_BB_WINDOW_SIZE           Bollinger window  (default: 20)
    CJSYS_BB_MIN_WIDTH_PCT         Bollinger min band width (default: 0.01)
    CJSYS_RISK_MAX_POSITION_PCT    max position size as fraction (default: 0.05)
"""
from __future__ import annotations

import logging
import os
import random
import uuid
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.analytics.evaluation.multi_strategy_report import MultiStrategyBacktestReport
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
from cjtrade.pkgs.brokers.arenax.arenax_middleware import ArenaXMiddleWare
from cjtrade.pkgs.strategy.adx import ADXAdaptiveStrategy
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.baseline_0050 import BaselineStrategy
from cjtrade.pkgs.strategy.bb import BollingerStrategy
from cjtrade.pkgs.strategy.dca import DCA_Monthly
from cjtrade.pkgs.strategy.donchian import DonchianBreakoutStrategy
from cjtrade.pkgs.strategy.parameters.manager import ParameterManager
from cjtrade.pkgs.strategy.snr import SupportResistanceStrategy
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_oneshot(
    symbol: Union[str, List[str], None] = None,
    start: Optional[str] = None,
    duration_days: int = 365,
    interval: str = "1d",
    initial_balance: float = 1_000_000.0,
    strategy: Optional[BaseStrategy] = None,
    params: Optional[Dict[str, Any]] = None,
    report_path: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    # cfg = _load_config()

    if symbol is None:
        raise ValueError("No symbol provided. Pass symbol=...")

    if isinstance(symbol, str):
        symbols: List[str] = [s.strip() for s in symbol.split(",") if s.strip()]
    else:
        symbols = [s.strip() for s in symbol if s.strip()]
    today = datetime.now().date()

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    else:
        min_days_ago = duration_days + 7
        max_days_ago = 365 * 5  # Allow up to 5 years of historical data

        if max_days_ago <= min_days_ago:
            max_days_ago = min_days_ago + 30

        random_offset = random.randint(min_days_ago, max_days_ago)
        start_dt = today - timedelta(days=random_offset)

    end_dt = start_dt + timedelta(days=duration_days)

    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()

    log.info(f"[OneShot] Time Range: {start_str} to {end_str} ({duration_days} days)")

    # Load parameters using ParameterManager
    strategy = strategy or BollingerStrategy()
    strategy_name = getattr(strategy, 'long_name', getattr(strategy, 'name', 'Unknown'))

    param_config = ParameterManager.load_params(
        interval=interval,
        strategy_name=strategy_name,
        user_overrides=params
    )

    log.info(f"[OneShot] Parameters: {param_config.params_hash} (interval={interval}, strategy={strategy_name})")
    merged_params = param_config.params

    sym_label = ",".join(symbols)

    # 4. Fetch kbars
    mw = ArenaXMiddleWare()
    all_kbars = []

    for sym in symbols:
        raw_bars = mw.get_kbars(sym, start_str, end_str, interval)
        if not raw_bars:
            log.warning(f"[OneShot] No kbars for {sym} [{start_str} - {end_str}], skipping.")
            continue

        sym_kbars = [_make_tagged_kbar(b, sym) for b in raw_bars]
        all_kbars.extend(sym_kbars)

    if not all_kbars:
        raise RuntimeError(f"No kbars found for {sym_label} in range {start_str} - {end_str}")

    all_kbars.sort(key=lambda k: k.timestamp)

    session_id = str(uuid.uuid4())
    engine = BacktestEngine(
        kbars=all_kbars,
        symbol=None,
        initial_balance=initial_balance,
        params=merged_params,
        session_id=session_id,
    )
    result = engine.run(strategy)

    # 6. Report
    safe_label = sym_label.replace(",", "_")
    html_path = report_path or f"oneshot_{safe_label}_{session_id[:8]}.html"
    report = BacktestReport(result)
    report.summary()
    strategy_title = getattr(strategy, 'name', 'UnnamedStrategy')
    report.full_report(path=html_path, open_browser=open_browser, title=f"Backtest Report: {strategy_title}")

def run_compare_strategies(
    symbol: Union[str, List[str], None] = None,
    start: Optional[str] = None,
    duration_days: int = 365,
    interval: str = "1d",
    initial_balance: float = 1_000_000.0,
    strategies: Optional[dict] = None,
    params: Optional[Dict[str, Any]] = None,
    report_path: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    """Run multiple strategies on the same kbars and generate comparison report.

    Parameters
    ----------
    symbol : str | list[str]
        Ticker(s), e.g. "2330" or ["2330", "0050"]
    start : str, optional
        Start date YYYY-MM-DD (default: random based on duration)
    duration_days : int
        Number of trading days to backtest
    interval : str
        Kbar interval, e.g. "1m" or "1d" (default: "1m")
    initial_balance : float
        Starting cash for each strategy (default: 1,000,000)
    strategies : dict
        Map of strategy_name → strategy_instance, e.g.
        {"DCA_Monthly": DCA_Monthly(), "BollingerBands": BollingerStrategy()}
    params : dict
        Shared parameters passed to all strategies
    report_path : str, optional
        Output HTML file path
    open_browser : bool
        Open result in default browser (default: True)
    """
    # cfg = _load_config()

    if symbol is None:
        raise ValueError("No symbol provided. Pass symbol=...")

    if isinstance(symbol, str):
        symbols: List[str] = [s.strip() for s in symbol.split(",") if s.strip()]
    else:
        symbols = [s.strip() for s in symbol if s.strip()]

    today = datetime.now().date()

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    else:
        min_days_ago = duration_days + 7
        max_days_ago = 365 * 6  # Allow up to 6 years of historical data
        # max_days_ago = 365 * 25   # since we support yf as fallback

        if max_days_ago <= min_days_ago:
            max_days_ago = min_days_ago + 30

        random_offset = random.randint(min_days_ago, max_days_ago)
        start_dt = today - timedelta(days=random_offset)

    end_dt = start_dt + timedelta(days=duration_days)

    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()

    log.info(f"[CompareStrategies] Time Range: {start_str} to {end_str} ({duration_days} days)")

    if not strategies:
        strategies = {
            "DCA_Monthly": DCA_Monthly(),
            "BollingerBands": BollingerStrategy(),
        }

    # Separate baseline strategy from other strategies
    baseline_symbol = "0050"
    baseline_strategy = None
    test_strategies = {}

    # Automatically identify baseline strategy by name (e.g. "Baseline_0050")
    for strat_name, strat_instance in strategies.items():
        if "baseline" in strat_name.lower():
            baseline_strategy = strat_instance
            log.info(f"[CompareStrategies] Identified baseline strategy: {strat_name}")
        else:
            test_strategies[strat_name] = strat_instance

    # Fetch kbars for test symbols
    test_symbols = symbols.copy()  # Keep original symbols for test strategies
    mw = ArenaXMiddleWare()
    test_kbars = []

    for sym in test_symbols:
        raw_bars = mw.get_kbars(sym, start_str, end_str, interval)
        if not raw_bars:
            log.warning(f"[CompareStrategies] No kbars for {sym} [{start_str} - {end_str}], skipping.")
            continue

        sym_kbars = [_make_tagged_kbar(b, sym) for b in raw_bars]
        test_kbars.extend(sym_kbars)

    # Fetch kbars for baseline symbol if baseline strategy exists
    baseline_kbars = []
    if baseline_strategy:
        raw_bars = mw.get_kbars(baseline_symbol, start_str, end_str, interval)
        if raw_bars:
            baseline_kbars = [_make_tagged_kbar(b, baseline_symbol) for b in raw_bars]
            log.info(f"[CompareStrategies] Fetched {len(baseline_kbars)} kbars for baseline symbol {baseline_symbol}")
        else:
            log.warning(f"[CompareStrategies] No kbars for baseline {baseline_symbol}, skipping baseline strategy")
            baseline_strategy = None

    # Merge all kbars
    all_kbars = test_kbars + baseline_kbars

    if not all_kbars:
        raise RuntimeError(f"No kbars found for {','.join(test_symbols)} in range {start_str} - {end_str}")

    all_kbars.sort(key=lambda k: k.timestamp)

    # Prepare final strategies dict
    final_strategies = test_strategies.copy()
    if baseline_strategy:
        final_strategies["Baseline_0050"] = baseline_strategy

    sym_label = ",".join(test_symbols)
    if baseline_strategy:
        sym_label += f",{baseline_symbol}(baseline)"

    # Load parameters using ParameterManager
    strategy_name = list(final_strategies.keys())[0] if final_strategies else "Unknown"
    param_config = ParameterManager.load_params(
        interval=interval,
        strategy_name=strategy_name,
        user_overrides=params
    )

    log.info(f"[CompareStrategies] Parameters: {param_config.params_hash} (interval={interval})")
    final_params = param_config.params

    # Run comparison
    multi_report = MultiStrategyBacktestReport(
        kbars=all_kbars,
        initial_balance=initial_balance,
        params=final_params,
    )

    for strat_name, strat_instance in final_strategies.items():
        multi_report.add_strategy(strat_name, strat_instance)

    multi_report.run()
    multi_report.compare_summary()

    # Save comparison HTML
    safe_label = sym_label.replace(",", "_")
    html_path = report_path or f"comparison_{safe_label}_{uuid.uuid4().hex[:8]}.html"
    multi_report.save_comparison_html(path=html_path, open_browser=False)

    # Save overlay charts (returns + equity)
    returns_overlay_path = f"compare_returns_{safe_label}_{uuid.uuid4().hex[:8]}.html"
    equity_overlay_path = f"compare_equity_{safe_label}_{uuid.uuid4().hex[:8]}.html"

    multi_report.compare_returns_overlay(path=returns_overlay_path, open_browser=False)
    multi_report.compare_cumulative_equity_overlay(path=equity_overlay_path, open_browser=False)

    # Generate individual quantstats full_report for each strategy
    print("\n" + "=" * 80)
    print("  Generating individual quantstats reports for each strategy...")
    print("=" * 80)

    for strat_name, result in multi_report._results.items():
        report = BacktestReport(result)
        # Generate individual HTML report with strategy name as title
        individual_html = f"fullreport_{strat_name}_{safe_label}_{uuid.uuid4().hex[:8]}.html"
        report.summary()
        report.full_report(path=individual_html, open_browser=open_browser, title=f"Backtest Report: {strat_name}")

    print("=" * 80)
    multi_report.compare_cumulative_equity_overlay(path=equity_overlay_path, open_browser=open_browser)


def _make_tagged_kbar(raw: dict, symbol: str):
    """Convert a raw kbar dict from the server into a tagged Kbar-like object."""
    from cjtrade.pkgs.analytics.backtest.engine import _TaggedKbar
    from cjtrade.pkgs.models.kbar import Kbar
    timestamp = datetime.strptime(
        raw["timestamp"], "%a, %d %b %Y %H:%M:%S GMT"
    )
    # print(timestamp)
    kb = Kbar(
        timestamp=datetime.fromisoformat(str(timestamp)),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=int(raw["volume"]),
    )
    return _TaggedKbar(kb, symbol)

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)-7s : %(message)s")

    ap = argparse.ArgumentParser(description="CJTrade one-shot backtest")
    ap.add_argument("--symbol",       default=None, help="Ticker(s), e.g. 2330 or 2330,0050")
    ap.add_argument("--start",        default=None, help="Optional: Start date YYYY-MM-DD (default: random)")
    ap.add_argument("--duration",     type=int, default=365, help="Duration in days (default: 365)")
    ap.add_argument("--interval",     choices=["1m", "5m", "1h", "1d"], default="1d",
                    help="Kbar interval (default: 1d)")
    ap.add_argument("--balance",      type=float, default=1_000_000.0, help="Initial balance (default: 1,000,000)")
    ap.add_argument("--params",       default=None,
                    help="Parameter overrides (format: 'key1:val1,key2:val2', e.g. 'bb__window_size:30,risk__max_position_pct:0.1')")
    ap.add_argument("--show-params",  action="store_true", help="Show parameter configuration and exit")
    ap.add_argument("--compare",      action="store_true", help="Compare multiple strategies")
    ap.add_argument("--no-browser",   action="store_true", help="Don't open browser")
    args = ap.parse_args()

    # Handle --show-params
    if args.show_params:
        print(ParameterManager.show_params(
            interval=args.interval,
            strategy_name="BollingerBands",  # Default, can be overridden
            user_overrides=args.params
        ))
        exit(0)

    if args.compare:
        run_compare_strategies(
            symbol=args.symbol,
            start=args.start,
            duration_days=args.duration,
            interval=args.interval,
            initial_balance=args.balance,
            params=args.params,
            strategies={
                "Support-Resistance": SupportResistanceStrategy(lookback_days=20),
                "BollingerBands": BollingerStrategy(),
                "Donchian": DonchianBreakoutStrategy(),
                "ADX_Adaptive": ADXAdaptiveStrategy(),
                "DCA_Monthly": DCA_Monthly(),
                "Baseline_0050": BaselineStrategy(),
            },
            open_browser=not args.no_browser,
        )
    else:
        run_oneshot(
            symbol=args.symbol,
            start=args.start,
            duration_days=args.duration,
            interval=args.interval,
            initial_balance=args.balance,
            params=args.params,
            open_browser=not args.no_browser,
        )

if __name__ == "__main__":
    main()
