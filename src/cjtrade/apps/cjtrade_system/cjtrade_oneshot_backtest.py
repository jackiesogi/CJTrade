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
from typing import List
from typing import Optional
from typing import Union

from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.analytics.evaluation.multi_strategy_report import MultiStrategyBacktestReport
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.brokers.arenax.arenax_middleware import ArenaXMiddleWare
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.bb_1m import BollingerStrategy
from cjtrade.pkgs.strategy.dca_1M import DCA_Monthly
from dotenv import load_dotenv

log = logging.getLogger(__name__)
load_dotenv()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _load_config() -> dict:
    # Try to read .cjsys file (same convention as the main system)
    cjsys_file = Path(__file__).parent / "configs" / "arenax_hist.cjsys"
    cfg: dict = {}
    if cjsys_file.exists():
        for line in cjsys_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip().lower()] = v.strip()

    # Environment variables override the file
    for key in ["cjsys_watch_list", "cjsys_oneshot_start", "cjsys_oneshot_end",
                "cjsys_oneshot_interval", "cjsys_oneshot_initial_balance",
                "cjsys_oneshot_duration_days",
                "cjsys_bb_window_size", "cjsys_bb_min_width_pct",
                "cjsys_risk_max_position_pct"]:
        val = os.environ.get(key.upper(), "")
        if val:
            cfg[key] = val

    return cfg

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_oneshot(
    symbol: Union[str, List[str], None] = None,
    start: Optional[str] = None,
    duration_days: int = 5,
    interval: str = "1m",
    initial_balance: float = 1_000_000.0,
    strategy: Optional[BaseStrategy] = None,
    params: Optional[dict] = None,
    report_path: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    cfg = _load_config()

    if symbol is None:
        watch = cfg.get("cjsys_watch_list", "")
        symbol = watch if watch else None
    if not symbol:
        raise ValueError("No symbol provided. Set CJSYS_WATCH_LIST or pass symbol=...")

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

    if initial_balance == 1_000_000.0:
        initial_balance = float(cfg.get("cjsys_oneshot_initial_balance", 1_000_000.0))

    merged_params = {
        "bb_window_size":        int(cfg.get("cjsys_bb_window_size", 20)),
        "bb_min_width_pct":      float(cfg.get("cjsys_bb_min_width_pct", 0.01)),
        "risk_max_position_pct": float(cfg.get("cjsys_risk_max_position_pct", 0.05)),
    }
    if params:
        merged_params.update(params)

    strategy = strategy or BollingerStrategy()
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
    report.full_report(path=html_path, open_browser=open_browser)

def run_compare_strategies(
    symbol: Union[str, List[str], None] = None,
    start: Optional[str] = None,
    duration_days: int = 5,
    interval: str = "1m",
    initial_balance: float = 1_000_000.0,
    strategies: Optional[dict] = None,
    params: Optional[dict] = None,
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
    cfg = _load_config()

    if symbol is None:
        watch = cfg.get("cjsys_watch_list", "")
        symbol = watch if watch else None
    if not symbol:
        raise ValueError("No symbol provided. Set CJSYS_WATCH_LIST or pass symbol=...")

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

    log.info(f"[CompareStrategies] Time Range: {start_str} to {end_str} ({duration_days} days)")

    if initial_balance == 1_000_000.0:
        initial_balance = float(cfg.get("cjsys_oneshot_initial_balance", 1_000_000.0))

    merged_params = {
        "bb_window_size":        int(cfg.get("cjsys_bb_window_size", 20)),
        "bb_min_width_pct":      float(cfg.get("cjsys_bb_min_width_pct", 0.01)),
        "risk_max_position_pct": float(cfg.get("cjsys_risk_max_position_pct", 0.05)),
    }
    if params:
        merged_params.update(params)

    if not strategies:
        strategies = {
            "DCA_Monthly": DCA_Monthly(),
            "BollingerBands": BollingerStrategy(),
        }

    sym_label = ",".join(symbols)

    # Fetch kbars
    mw = ArenaXMiddleWare()
    all_kbars = []

    for sym in symbols:
        raw_bars = mw.get_kbars(sym, start_str, end_str, interval)
        if not raw_bars:
            log.warning(f"[CompareStrategies] No kbars for {sym} [{start_str} - {end_str}], skipping.")
            continue

        sym_kbars = [_make_tagged_kbar(b, sym) for b in raw_bars]
        all_kbars.extend(sym_kbars)

    if not all_kbars:
        raise RuntimeError(f"No kbars found for {sym_label} in range {start_str} - {end_str}")

    all_kbars.sort(key=lambda k: k.timestamp)

    # Run comparison
    multi_report = MultiStrategyBacktestReport(
        kbars=all_kbars,
        initial_balance=initial_balance,
        params=merged_params,
    )

    for strat_name, strat_instance in strategies.items():
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
        # Generate individual HTML report
        individual_html = f"fullreport_{strat_name}_{safe_label}_{uuid.uuid4().hex[:8]}.html"
        report.summary()
        report.full_report(path=individual_html, open_browser=open_browser)

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

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)-7s : %(message)s")

    ap = argparse.ArgumentParser(description="CJTrade one-shot backtest")
    ap.add_argument("--symbol",   default=None, help="Ticker(s), e.g. 2330 or 2330,0050")
    ap.add_argument("--start",    default=None, help="Optional: Start date YYYY-MM-DD (default: random)")
    ap.add_argument("--duration", type=int,     default=5, help="Duration in days (default: 5)")
    ap.add_argument("--interval", default="1m", help="Kbar interval (default: 1m)")
    ap.add_argument("--balance",  type=float,   default=1_000_000.0, help="Initial balance")
    ap.add_argument("--compare",  action="store_true", help="Compare DCA_Monthly vs BollingerBands")
    ap.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = ap.parse_args()

    if args.compare:
        run_compare_strategies(
            symbol=args.symbol,
            start=args.start,
            duration_days=args.duration,
            interval=args.interval,
            initial_balance=args.balance,
            open_browser=not args.no_browser,
        )
    else:
        run_oneshot(
            symbol=args.symbol,
            start=args.start,
            duration_days=args.duration,
            interval=args.interval,
            initial_balance=args.balance,
            open_browser=not args.no_browser,
        )
