"""
pkgs/analytics/evaluation/quantstats.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thin facade around BacktestResult → quantstats.

Usage (in cjtrade_system_arenax.py):
--------------------------------------
    from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport

    report = BacktestReport(result)
    report.summary()           # print key stats to stdout
    report.full_report()       # open quantstats HTML report
    report.save_html("out.html")
    report.save_csv("out.csv")
"""
from __future__ import annotations

import logging
import warnings
from typing import Optional
from typing import TYPE_CHECKING

# Suppress matplotlib font-not-found warnings that flood the log when
# quantstats renders charts on Linux systems without Arial installed.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

if TYPE_CHECKING:
    from cjtrade.pkgs.models.backtest import BacktestResult


# ---------------------------------------------------------------------------
# One-liner convenience functions (import & call, no class needed)
# ---------------------------------------------------------------------------

def quick_report(result: "BacktestResult", output: str = "html",
                 path: Optional[str] = None) -> None:
    """Generate a quantstats report from a BacktestResult in one call.

    Parameters
    ----------
    result : BacktestResult
    output : "html" | "full" | "basic"
        "html"  → save HTML file (requires ``path``)
        "full"  → open full quantstats report in browser
        "basic" → print key metrics to stdout only
    path : str, optional
        File path for HTML output (used when output="html").
    """
    report = BacktestReport(result)
    if output == "html":
        report.save_html(path or f"backtest_{result.session_id[:8] if result.session_id else 'result'}.html")
    elif output == "full":
        report.full_report()
    else:
        report.summary()


# ---------------------------------------------------------------------------
# BacktestReport – main public class
# ---------------------------------------------------------------------------

class BacktestReport:
    """Wraps a BacktestResult and exposes reporting helpers.

    Example
    -------
    >>> report = BacktestReport(result)
    >>> report.summary()
    >>> report.save_html("report.html")
    """

    def __init__(self, result: "BacktestResult") -> None:
        self.result = result
        self._returns = None   # lazy

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def returns(self):
        """Daily returns pd.Series (cached)."""
        if self._returns is None:
            self._returns = self.result.to_returns()
        return self._returns

    def _require_qs(self):
        try:
            import quantstats as qs
            return qs
        except ImportError:
            raise ImportError("quantstats not installed – run: pip install quantstats")

    def _require_nonempty(self):
        if self.returns.empty:
            raise ValueError(
                "equity_curve is empty – did the backtest finish? "
                "Check _record_equity_point warnings in the log."
            )

    # ------------------------------------------------------------------
    # Text / stdout
    # ------------------------------------------------------------------

    def summary(self) -> None:
        """Print key performance metrics to stdout (no external deps)."""
        r = self.result
        pnl = r.final_balance - r.initial_balance
        pnl_pct = pnl / r.initial_balance * 100 if r.initial_balance else 0.0

        print("=" * 50)
        print("  Backtest Summary")
        print("=" * 50)
        print(f"  Session      : {r.session_id or 'N/A'}")
        print(f"  Start time   : {r.start_time or 'N/A'}")
        print(f"  Init balance : {r.initial_balance:>15,.2f}")
        print(f"  Final balance: {r.final_balance:>15,.2f}")
        print(f"  PnL          : {pnl:>+15,.2f}  ({pnl_pct:+.2f}%)")
        print(f"  Total fills  : {len(r.fill_history)}")
        print(f"  Equity pts   : {len(r.equity_curve)}")

        if not self.returns.empty:
            try:
                qs = self._require_qs()
                p = self.result._returns_periods_per_year
                sharpe = qs.stats.sharpe(self.returns, periods=p)
                # quantstats.stats.cagr() accepts 'periods' for annualisation in some versions
                # prefer 'periods' to remain compatible across quantstats versions
                cagr   = qs.stats.cagr(self.returns, periods=p)
                mdd    = qs.stats.max_drawdown(self.returns)
                label  = "minute" if p > 252 else "daily"
                print(f"  Sharpe ratio : {sharpe:.4f}  ({label} resolution, annualised)")
                print(f"  CAGR         : {cagr*100:.2f}%")
                print(f"  Max drawdown : {mdd*100:.2f}%")
            except ImportError:
                pass   # quantstats optional; basic stats already printed
        print("=" * 50)

    def metrics(self) -> dict:
        """Return key metrics as a plain dict (suitable for logging/JSON)."""
        r = self.result
        pnl = r.final_balance - r.initial_balance
        base = {
            "session_id":      r.session_id,
            "initial_balance": r.initial_balance,
            "final_balance":   r.final_balance,
            "pnl":             round(pnl, 2),
            "pnl_pct":         round(pnl / r.initial_balance * 100, 4) if r.initial_balance else 0.0,
            "n_fills":         len(r.fill_history),
            "n_equity_pts":    len(r.equity_curve),
        }
        if not self.returns.empty:
            try:
                qs = self._require_qs()
                p = r._returns_periods_per_year
                base["sharpe"]       = round(float(qs.stats.sharpe(self.returns, periods=p)), 4)
                base["cagr"]         = round(float(qs.stats.cagr(self.returns, periods=p)), 4)
                base["max_drawdown"] = round(float(qs.stats.max_drawdown(self.returns)), 4)
            except ImportError:
                pass
        return base

    # ------------------------------------------------------------------
    # quantstats report wrappers
    # ------------------------------------------------------------------

    def full_report(self, path: str = None, open_browser: bool = True, title: str = None) -> str:
        """Save a full quantstats HTML tearsheet and optionally open it in the browser.

        Parameters
        ----------
        path : str, optional
            Output HTML file path.  Defaults to ``backtest_<session>.html``.
        open_browser : bool
            If True (default), open the saved file in the default browser.
        title : str, optional
            Custom title to display at the top of the HTML report (e.g., strategy name).
            If None, defaults to "Strategy Tearsheet".

        Returns
        -------
        str
            Absolute path to the saved HTML file.
        """
        import os, webbrowser
        qs = self._require_qs()
        self._require_nonempty()
        if path is None:
            sid = (self.result.session_id or "result")[:8]
            path = f"backtest_{sid}.html"

        # Use provided title or default
        report_title = title or "Strategy Tearsheet"

        qs.reports.html(
            self.returns,
            output=path,
            periods_per_year=self.result._returns_periods_per_year,
            title=report_title,
        )

        abs_path = os.path.abspath(path)
        print(f"[BacktestReport] HTML saved → {abs_path}")
        if open_browser:
            webbrowser.open(f"file://{abs_path}")
        return abs_path

    def basic_report(self) -> None:
        """Print a compact quantstats report to stdout."""
        qs = self._require_qs()
        self._require_nonempty()
        qs.reports.basic(self.returns)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_html(self, path: str) -> None:
        """Save a full quantstats HTML report to ``path``."""
        return self.full_report(path=path, open_browser=False)

    def save_csv(self, path: str) -> None:
        """Save daily_summary() as a CSV to ``path``."""
        df = self.result.daily_summary()
        df.to_csv(path, index=False)
        print(f"[BacktestReport] CSV saved → {path}")
