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
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.brokers.arenax.arenax_middleware import ArenaXMiddleWare
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
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
# Built-in default strategy: Bollinger Bands (mirrors cjtrade_system_arenax)
# ---------------------------------------------------------------------------

class _BollingerStrategy(BaseStrategy):
    """Simple Bollinger-band mean-reversion strategy.

    Buys when price touches lower band, sells when it touches upper band.
    Keeps at most one position (no pyramiding).
    """
    name = "BollingerBands"

    def on_start(self, ctx):
        p = ctx.params
        self._window   = int(p.get("bb_window_size",      20))
        self._min_bw   = float(p.get("bb_min_width_pct",  0.01))
        self._max_pct  = float(p.get("risk_max_position_pct", 0.05))
        log.info(f"[{self.name}] window={self._window} min_bw={self._min_bw*100:.2f}%")

    def on_bar(self, bar, ctx):
        prices = ctx.prices(bar.symbol)
        if len(prices) < self._window:
            return []

        import numpy as np
        arr    = np.array(prices[-self._window:], dtype=float)
        middle = arr.mean()
        std    = arr.std(ddof=1)
        upper  = middle + 2 * std
        lower  = middle - 2 * std
        bw     = (upper - lower) / middle if middle > 0 else 0

        if bw < self._min_bw:
            return []

        price = bar.close
        if price <= lower and not ctx.has_position(bar.symbol):
            qty = ctx.calc_qty(price, self._max_pct)
            if qty > 0:
                return [type("Signal", (), {
                    "action": "BUY", "symbol": bar.symbol,
                    "quantity": qty, "price": price,
                    "reason": f"BB lower touch (bw={bw*100:.2f}%)",
                    "meta": {},
                })]

        elif price >= upper and ctx.has_position(bar.symbol):
            qty = ctx.position_qty(bar.symbol)
            return [type("Signal", (), {
                "action": "SELL", "symbol": bar.symbol,
                "quantity": qty, "price": price,
                "reason": f"BB upper touch (bw={bw*100:.2f}%)",
                "meta": {},
            })]

        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_oneshot(
    symbol: Union[str, List[str], None] = None,
    # start: Optional[str]    = None,
    # end: Optional[str]      = None,
    interval: str           = "1m",
    initial_balance: float  = 1_000_000.0,
    strategy: Optional[BaseStrategy] = None,
    params: Optional[dict]  = None,
    report_path: Optional[str] = None,
    open_browser: bool      = True,
) -> None:
    """Fetch kbars, run strategy, save HTML report.

    Parameters
    ----------
    symbol : str | list[str] | None
        Single ticker ('2330'), comma-separated string ('2330,0050,2317'),
        or a list (['2330', '0050']).
        Defaults to CJSYS_WATCH_LIST env / config value.
    start / end : str
        Date range, e.g. '2023-01-01'.  Defaults to last 1 year.
    interval : str
        Kbar interval ('1m', '5m', '1d', …).  Default '1m'.
    initial_balance : float
        Starting cash in TWD (shared across all symbols).
    strategy : BaseStrategy, optional
        Defaults to the built-in Bollinger strategy.
    params : dict, optional
        Forwarded to strategy as ctx.params.  Overrides config values.
    report_path : str, optional
        Where to save the HTML report.  Auto-named if omitted.
    open_browser : bool
        Open the report in the default browser after saving.
    """
    cfg = _load_config()

    # ------------------------------------------------------------------
    # Resolve symbol list
    # ------------------------------------------------------------------
    if symbol is None:
        watch = cfg.get("cjsys_watch_list", "")
        symbol = watch if watch else None
    if not symbol:
        raise ValueError("No symbol provided. Set CJSYS_WATCH_LIST or pass symbol=...")

    # Normalise to list[str]
    if isinstance(symbol, str):
        symbols: List[str] = [s.strip() for s in symbol.split(",") if s.strip()]
    else:
        symbols = [s.strip() for s in symbol if s.strip()]

    if not symbols:
        raise ValueError("symbol list is empty after parsing.")

    # ------------------------------------------------------------------
    # Resolve date range
    # ------------------------------------------------------------------
    today = datetime.now().date()

    # if end is None:
    #     end = cfg.get("cjsys_oneshot_end", today.isoformat())

    # CJSYS_ONESHOT_START takes priority; otherwise derive from duration
    start = None
    explicit_start = start or cfg.get("cjsys_oneshot_start", "")
    if explicit_start:
        start = explicit_start
    else:
        # Duration-based random start:
        #   pick end – (random window) as start, where window ≥ 1.5 × duration
        #   so indicator warm-up data is always available.
        duration_days = int(cfg.get("cjsys_oneshot_duration_days", 5))
        duration_days = int(cfg.get("cjsys_backtest_duration_days", 5))
        # calendar days = trading days × ~1.4 (weekends/holidays); add 50% buffer
        min_calendar = int(duration_days * 1.4 * 1.5)
        # Allow going back up to ~5 years (1825 days) so we have enough history
        max_calendar = max(min_calendar + 30, 365 * 5)
        days_back = random.randint(min_calendar, max_calendar)
        # end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        start = (today - timedelta(days=days_back)).isoformat()
        end = (datetime.fromisoformat(start) + timedelta(days=duration_days)).date().isoformat()
        log.info(
            f"[OneShot] duration={duration_days} trading days → "
            f"random window={days_back} calendar days → start={start}"
        )

    # Resolve initial balance
    if initial_balance == 1_000_000.0:
        initial_balance = float(cfg.get("cjsys_oneshot_initial_balance", 1_000_000.0))

    # Resolve strategy params
    merged_params = {
        "bb_window_size":        int(cfg.get("cjsys_bb_window_size", 20)),
        "bb_min_width_pct":      float(cfg.get("cjsys_bb_min_width_pct", 0.01)),
        "risk_max_position_pct": float(cfg.get("cjsys_risk_max_position_pct", 0.05)),
    }
    if params:
        merged_params.update(params)

    strategy = strategy or _BollingerStrategy()

    sym_label = ",".join(symbols)
    log.info(f"[OneShot] symbols=[{sym_label}]  {start} → {end}  interval={interval}")
    log.info(f"[OneShot] initial_balance={initial_balance:,.0f}  strategy={strategy.name}")

    # ------------------------------------------------------------------
    # 1. Fetch kbars from ArenaX server (one request per symbol)
    # ------------------------------------------------------------------
    mw = ArenaXMiddleWare()
    all_kbars = []

    for sym in symbols:
        raw_bars = mw.get_kbars(sym, start, end, interval)
        if not raw_bars:
            log.warning(f"[OneShot] No kbars for {sym} [{start} – {end}], skipping.")
            continue

        sym_kbars = [
            _make_tagged_kbar(b, sym)
            for b in raw_bars
        ]
        log.info(
            f"[OneShot] {sym}: {len(sym_kbars)} bars  "
            f"({sym_kbars[0].timestamp.date()} – {sym_kbars[-1].timestamp.date()})"
        )
        all_kbars.extend(sym_kbars)

    if not all_kbars:
        raise RuntimeError(
            f"No kbars returned for any symbol [{sym_label}] [{start} – {end}]. "
            "Is the ArenaX server running?"
        )

    # Sort merged list by timestamp (engine also sorts, but be explicit)
    all_kbars.sort(key=lambda k: k.timestamp)

    # ------------------------------------------------------------------
    # 2. Run engine
    # ------------------------------------------------------------------
    session_id = str(uuid.uuid4())
    engine = BacktestEngine(
        kbars=all_kbars,
        symbol=None,          # already tagged with .symbol per bar
        initial_balance=initial_balance,
        params=merged_params,
        session_id=session_id,
    )
    result = engine.run(strategy)

    # ------------------------------------------------------------------
    # 3. Save result + open report
    # ------------------------------------------------------------------
    safe_label = sym_label.replace(",", "_")
    pkl_path = f"oneshot_{safe_label}_{session_id[:8]}.pkl"
    result.save(pkl_path)
    log.info(f"[OneShot] BacktestResult saved → {pkl_path}")

    report = BacktestReport(result)
    report.summary()

    html_path = report_path or f"oneshot_{safe_label}_{session_id[:8]}.html"
    report.full_report(path=html_path, open_browser=open_browser)


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

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-7s : %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ap = argparse.ArgumentParser(description="CJTrade one-shot backtest")
    ap.add_argument("--symbol",   default=None, help="Ticker(s), e.g. 2330  or  2330,0050,2317")
    # ap.add_argument("--start",    default=None, help="Start date YYYY-MM-DD")
    ap.add_argument("--duration", type=int, default=5, help="Duration in days")
    ap.add_argument("--interval", default="1m", help="Kbar interval (default: 1m)")
    ap.add_argument("--balance",  type=float, default=1_000_000.0, help="Initial balance")
    ap.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = ap.parse_args()

    # if start is not provided, choose a random day between((today - duration * 1.5), (today - duration * 1.5) + duration)
    # if args.start is None:
    #     today = datetime.now().date()
    #     min_calendar = int(args.duration * 1.4 * 1.5)
    #     max_calendar = max(min_calendar + 30, 365 * 5)
    #     days_back = random.randint(min_calendar, max_calendar)
    #     end_dt = today
    #     start = (end_dt - timedelta(days=days_back)).isoformat()
    #     log.info(
    #         f"[OneShot] duration={args.duration} trading days → "
    #         f"random window={days_back} calendar days → start={start}"
    #     )
    #     args.start = start

    run_oneshot(
        symbol=args.symbol,
        # start=args.start,
        # end=args.end,
        interval=args.interval,
        initial_balance=args.balance,
        open_browser=not args.no_browser,
    )
