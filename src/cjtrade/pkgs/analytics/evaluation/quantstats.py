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
        # PnL now includes both realized (balance change) and unrealized (position value)
        final_equity = r.final_equity if r.final_equity is not None else r.final_balance
        pnl = final_equity - r.initial_balance
        pnl_pct = pnl / r.initial_balance * 100 if r.initial_balance else 0.0

        # uPnL = unrealized PnL = position value
        unrealized_pnl = final_equity - r.final_balance
        unrealized_pnl_pct = unrealized_pnl / r.initial_balance * 100 if r.initial_balance else 0.0

        # rPnL = realized PnL = balance change only
        realized_pnl = r.final_balance - r.initial_balance

        print("=" * 50)
        print("  Backtest Summary")
        print("=" * 50)
        print(f"  Session      : {r.session_id or 'N/A'}")
        print(f"  Start time   : {r.start_time or 'N/A'}")
        print(f"  Init balance : {r.initial_balance:>15,.2f}")
        print(f"  Final balance: {r.final_balance:>15,.2f}")
        print(f"  Final equity : {final_equity:>15,.2f}")
        print(f"  PnL (Total)  : {pnl:>+15,.2f}  ({pnl_pct:+.2f}%)")
        print(f"  rPnL         : {realized_pnl:>+15,.2f}")
        print(f"  uPnL         : {unrealized_pnl:>+15,.2f}  ({unrealized_pnl_pct:+.2f}%)")
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

        # Round-trip analysis (summary only; full table via print_round_trips())
        try:
            rts = self.result.compute_round_trips()
            if rts:
                wins   = [rt for rt in rts if rt.pnl > 0]
                losses = [rt for rt in rts if rt.pnl <= 0]
                avg_pnl  = sum(rt.pnl for rt in rts) / len(rts)
                avg_hold = sum(rt.holding_days for rt in rts) / len(rts)
                win_rate = len(wins) / len(rts) * 100
                print(f"  Round trips  : {len(rts)}  (win {len(wins)} / loss {len(losses)},  win rate {win_rate:.1f}%)")
                print(f"  Avg PnL/trip : {avg_pnl:>+,.2f}")
                print(f"  Avg hold days: {avg_hold:.1f}")
        except Exception:
            pass

        print("=" * 50)

    def print_round_trips(self) -> None:
        """Print every round-trip (entry→exit) in a compact table.

        Uses the same FIFO matching as BacktestResult.compute_round_trips().
        Format mirrors the full-simulation trade history for easy comparison.
        """
        try:
            rts = self.result.compute_round_trips()
        except Exception as e:
            print(f"  (round-trip computation failed: {e})")
            return

        if not rts:
            print("  No round trips found.")
            return

        wins   = [rt for rt in rts if rt.pnl > 0]
        losses = [rt for rt in rts if rt.pnl <= 0]
        total_pnl = sum(rt.pnl for rt in rts)

        print()
        print("=" * 80)
        print(f"  Round-Trip History  ({len(rts)} trades,  "
              f"win {len(wins)} / loss {len(losses)},  "
              f"total PnL {total_pnl:+,.2f})")
        print("=" * 80)
        print(f"  {'#':>3}  {'Symbol':<8}  {'Entry Date':<12}  {'Entry $':>9}  "
              f"{'Exit Date':<12}  {'Exit $':>9}  {'Qty':>6}  {'PnL':>10}  {'Days':>5}")
        print("  " + "-" * 76)
        for i, rt in enumerate(rts, 1):
            icon = "🟢" if rt.pnl > 0 else "🔴"
            entry_date = rt.entry_time[:10] if rt.entry_time else "?"
            exit_date  = rt.exit_time[:10]  if rt.exit_time  else "?"
            print(f"  {i:>3}  {rt.symbol:<8}  {entry_date:<12}  {rt.entry_price:>9.2f}  "
                  f"{exit_date:<12}  {rt.exit_price:>9.2f}  {rt.quantity:>6}  "
                  f"{rt.pnl:>+10.2f}  {rt.holding_days:>4}d  {icon}")
        print("=" * 80)
        print()

    def metrics(self) -> dict:
        """Return key metrics as a plain dict (suitable for logging/JSON)."""
        r = self.result
        final_equity = r.final_equity if r.final_equity is not None else r.final_balance
        pnl = final_equity - r.initial_balance
        unrealized_pnl = final_equity - r.final_balance
        realized_pnl = r.final_balance - r.initial_balance

        base = {
            "session_id":      r.session_id,
            "initial_balance": r.initial_balance,
            "final_balance":   r.final_balance,
            "final_equity":    round(final_equity, 2),
            "pnl":             round(pnl, 2),
            "pnl_pct":         round(pnl / r.initial_balance * 100, 4) if r.initial_balance else 0.0,
            "realized_pnl":    round(realized_pnl, 2),
            "unrealized_pnl":  round(unrealized_pnl, 2),
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

        # Inject round-trip table after quantstats saves the HTML
        self._inject_round_trips_html(path)

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
    # Round-trip HTML injection
    # ------------------------------------------------------------------

    def _inject_round_trips_html(self, path: str) -> None:
        """Append a round-trip table to the quantstats HTML file."""
        try:
            rts = self.result.compute_round_trips()
        except Exception:
            return
        if not rts:
            return

        wins   = sum(1 for rt in rts if rt.pnl > 0)
        losses = sum(1 for rt in rts if rt.pnl <= 0)
        total_pnl = sum(rt.pnl for rt in rts)
        win_rate  = wins / len(rts) * 100

        rows = "\n".join(
            f"<tr>"
            f"<td>{rt.symbol}</td>"
            f"<td>{rt.entry_time[:16]}</td>"
            f"<td style='text-align:right'>{rt.entry_price:,.2f}</td>"
            f"<td>{rt.exit_time[:16]}</td>"
            f"<td style='text-align:right'>{rt.exit_price:,.2f}</td>"
            f"<td style='text-align:right'>{rt.quantity:,}</td>"
            f"<td style='text-align:right;color:{'green' if rt.pnl>0 else 'crimson'}'>{rt.pnl:+,.2f}</td>"
            f"<td style='text-align:right'>{rt.holding_days}</td>"
            f"</tr>"
            for rt in rts
        )

        html_block = f"""
<div style="font-family:Arial,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px">
  <h2 style="border-bottom:2px solid #444;padding-bottom:6px">Round-Trip Trade Analysis</h2>
  <p style="color:#555">
    {len(rts)} completed round trips &nbsp;|&nbsp;
    <span style="color:green">&#9650; {wins} wins</span> &nbsp;
    <span style="color:crimson">&#9660; {losses} losses</span> &nbsp;|&nbsp;
    Win rate: <b>{win_rate:.1f}%</b> &nbsp;|&nbsp;
    Total PnL: <b style="color:{'green' if total_pnl>=0 else 'crimson'}">{total_pnl:+,.2f}</b>
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead>
      <tr style="background:#f0f0f0;text-align:left">
        <th style="padding:6px 10px">Symbol</th>
        <th style="padding:6px 10px">Entry time</th>
        <th style="padding:6px 10px;text-align:right">Entry price</th>
        <th style="padding:6px 10px">Exit time</th>
        <th style="padding:6px 10px;text-align:right">Exit price</th>
        <th style="padding:6px 10px;text-align:right">Qty</th>
        <th style="padding:6px 10px;text-align:right">PnL</th>
        <th style="padding:6px 10px;text-align:right">Hold (days)</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>
"""

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Insert before closing </body>
            if "</body>" in content:
                content = content.replace("</body>", html_block + "\n</body>", 1)
            else:
                content += html_block
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning(f"[BacktestReport] Could not inject round-trip table: {e}")

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
