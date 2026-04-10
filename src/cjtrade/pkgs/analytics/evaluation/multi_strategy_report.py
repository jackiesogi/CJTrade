"""
pkgs/analytics/evaluation/multi_strategy_report.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Multi-strategy comparison report generator.

Run multiple strategies on the same kbars and generate side-by-side
comparison reports using quantstats.

Usage
-----
    from cjtrade.pkgs.analytics.evaluation.multi_strategy_report import MultiStrategyBacktestReport
    from cjtrade.pkgs.strategy.dca_monthly import DCA_Monthly
    from cjtrade.pkgs.strategy.example_strategy import BollingerStrategy

    msr = MultiStrategyBacktestReport(kbars, initial_balance=1_000_000, params={...})
    msr.add_strategy("DCA_Monthly", DCA_Monthly())
    msr.add_strategy("BollingerBands", BollingerStrategy())
    msr.run()
    msr.compare_summary()
    msr.save_comparison_html("comparison.html")
"""
from __future__ import annotations

import logging
import os
import webbrowser
from typing import Dict
from typing import List
from typing import Optional
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from cjtrade.pkgs.models.backtest import BacktestResult
    from cjtrade.pkgs.strategy.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class MultiStrategyBacktestReport:
    """Run multiple strategies on the same kbars and generate side-by-side comparison report.

    Attributes
    ----------
    kbars : list
        Pre-fetched list of _TaggedKbar objects (time-sorted, all symbols).
    initial_balance : float
        Starting cash for each strategy.
    params : dict
        Shared parameters passed to all strategies.
    _strategies : dict
        Map of strategy_name → strategy instance.
    _results : dict
        Map of strategy_name → BacktestResult.
    _returns_series : dict
        Map of strategy_name → returns pd.Series.
    """

    def __init__(self, kbars: List, initial_balance: float = 1_000_000.0,
                 params: Optional[Dict] = None) -> None:
        self.kbars = kbars
        self.initial_balance = initial_balance
        self.params = params or {}
        self._strategies: Dict[str, "BaseStrategy"] = {}
        self._results: Dict[str, "BacktestResult"] = {}
        self._returns_series: Dict[str, pd.Series] = {}

    def add_strategy(self, name: str, strategy: "BaseStrategy") -> None:
        """Register a strategy to be tested.

        Parameters
        ----------
        name : str
            Display name for this strategy (e.g., "DCA_Monthly", "BollingerBands").
        strategy : BaseStrategy
            Strategy instance to run.
        """
        self._strategies[name] = strategy
        log.info(f"[MultiStrategyBacktestReport] Added strategy: {name}")

    def run(self) -> None:
        """Run all registered strategies on the same kbars."""
        from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
        import uuid

        if not self._strategies:
            raise ValueError("No strategies registered. Use add_strategy() first.")

        log.info(f"[MultiStrategyBacktestReport] Running {len(self._strategies)} strategies...")
        for name, strategy in self._strategies.items():
            log.info(f"  → Running {name}...")
            session_id = str(uuid.uuid4())
            engine = BacktestEngine(
                kbars=self.kbars,
                symbol=None,
                initial_balance=self.initial_balance,
                params=self.params,
                session_id=session_id,
            )
            result = engine.run(strategy)
            self._results[name] = result
            self._returns_series[name] = result.to_returns()
            pnl = result.final_balance - result.initial_balance
            log.info(
                f"  ✓ {name} completed – {len(result.fill_history)} fills, "
                f"PnL={pnl:+.2f}"
            )

    def compare_summary(self) -> None:
        """Print a comparison table of all strategies' key metrics to stdout."""
        if not self._results:
            raise ValueError("No results to compare. Call run() first.")

        qs = self._require_qs()

        print("\n" + "=" * 130)
        print("  MULTI-STRATEGY COMPARISON")
        print("=" * 130)

        # Header
        header = (
            f"{'Strategy':<20} | "
            f"{'PnL':>15} | "
            f"{'PnL %':>10} | "
            f"{'Sharpe':>10} | "
            f"{'CAGR':>10} | "
            f"{'Max DD':>10} | "
            f"{'Fills':>8} | "
            f"{'Equity Pts':>12}"
        )
        print(header)
        print("-" * 130)

        for name, result in self._results.items():
            pnl = result.final_balance - result.initial_balance
            pnl_pct = pnl / result.initial_balance * 100 if result.initial_balance else 0.0
            returns = self._returns_series[name]

            if returns.empty:
                sharpe, cagr, mdd = float('nan'), float('nan'), float('nan')
            else:
                try:
                    p = result._returns_periods_per_year
                    sharpe = float(qs.stats.sharpe(returns, periods=p))
                    cagr = float(qs.stats.cagr(returns, periods=p))
                    mdd = float(qs.stats.max_drawdown(returns))
                except Exception as e:
                    log.warning(f"Error computing metrics for {name}: {e}")
                    sharpe, cagr, mdd = float('nan'), float('nan'), float('nan')

            row = (
                f"{name:<20} | "
                f"{pnl:>15,.2f} | "
                f"{pnl_pct:>+10.2f} | "
                f"{sharpe:>10.4f} | "
                f"{cagr*100:>+10.2f}% | "
                f"{mdd*100:>+10.2f}% | "
                f"{len(result.fill_history):>8} | "
                f"{len(result.equity_curve):>12}"
            )
            print(row)
        print("=" * 130 + "\n")

    def save_comparison_html(self, path: str = "comparison.html",
                             open_browser: bool = True) -> str:
        """Save a multi-strategy HTML comparison report.

        Parameters
        ----------
        path : str
            Output HTML file path. Default: "comparison.html"
        open_browser : bool
            If True (default), open the saved file in the default browser.

        Returns
        -------
        str
            Absolute path to the saved HTML file.
        """
        if not self._results:
            raise ValueError("No results to compare. Call run() first.")

        qs = self._require_qs()

        # Build custom HTML comparison table
        html_parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "  <meta charset='utf-8'>",
            "  <title>Multi-Strategy Comparison</title>",
            "  <style>",
            "    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 30px; background-color: #f5f5f5; }",
            "    .container { max-width: 1400px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }",
            "    h1 { color: #333; text-align: center; margin-bottom: 30px; }",
            "    table { border-collapse: collapse; width: 100%; margin-bottom: 30px; }",
            "    th, td { border: 1px solid #ddd; padding: 14px; text-align: right; }",
            "    th { background-color: #2c3e50; color: white; font-weight: bold; text-align: left; }",
            "    td:first-child { text-align: left; font-weight: bold; color: #2c3e50; }",
            "    tr:nth-child(even) { background-color: #f9f9f9; }",
            "    tr:hover { background-color: #f0f0f0; }",
            "    .positive { color: #27ae60; font-weight: bold; }",
            "    .negative { color: #e74c3c; font-weight: bold; }",
            "    .neutral { color: #34495e; }",
            "    .summary { margin-top: 30px; padding: 15px; background-color: #ecf0f1; border-left: 4px solid #2c3e50; }",
            "    .summary h3 { margin-top: 0; color: #2c3e50; }",
            "  </style>",
            "</head>",
            "<body>",
            "  <div class='container'>",
            "    <h1>📊 Multi-Strategy Comparison Report</h1>",
            "    <table>",
            "      <tr>",
            "        <th>Strategy</th>",
            "        <th>PnL (TWD)</th>",
            "        <th>PnL %</th>",
            "        <th>Sharpe Ratio</th>",
            "        <th>CAGR %</th>",
            "        <th>Max Drawdown %</th>",
            "        <th>Fills</th>",
            "        <th>Equity Points</th>",
            "      </tr>"
        ]

        best_pnl_name = max(self._results.keys(),
                            key=lambda n: self._results[n].final_balance - self._results[n].initial_balance)
        best_sharpe_name = None
        best_sharpe = float('-inf')

        for name, result in self._results.items():
            returns = self._returns_series[name]
            if not returns.empty:
                try:
                    p = result._returns_periods_per_year
                    sharpe = float(qs.stats.sharpe(returns, periods=p))
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_sharpe_name = name
                except Exception:
                    pass

        for name, result in self._results.items():
            pnl = result.final_balance - result.initial_balance
            pnl_pct = pnl / result.initial_balance * 100 if result.initial_balance else 0.0
            returns = self._returns_series[name]

            if returns.empty:
                sharpe, cagr, mdd = float('nan'), float('nan'), float('nan')
            else:
                try:
                    p = result._returns_periods_per_year
                    sharpe = float(qs.stats.sharpe(returns, periods=p))
                    cagr = float(qs.stats.cagr(returns, periods=p))
                    mdd = float(qs.stats.max_drawdown(returns))
                except Exception as e:
                    log.warning(f"Error computing metrics for {name}: {e}")
                    sharpe, cagr, mdd = float('nan'), float('nan'), float('nan')

            pnl_class = "positive" if pnl >= 0 else "negative"
            cagr_class = "positive" if cagr >= 0 else "negative"
            mdd_class = "negative" if mdd < 0 else "neutral"
            sharpe_class = "positive" if sharpe > 1.0 else ("neutral" if sharpe > 0 else "negative")

            is_best_pnl = " ⭐" if name == best_pnl_name else ""
            is_best_sharpe = " ⭐" if name == best_sharpe_name else ""

            html_parts.append(
                f"      <tr>"
                f"        <td><strong>{name}{is_best_pnl}</strong></td>"
                f"        <td class='{pnl_class}'>{pnl:>12,.2f}</td>"
                f"        <td class='{pnl_class}'>{pnl_pct:>+9.2f}%</td>"
                f"        <td class='{sharpe_class}'>{sharpe:>13.4f}{is_best_sharpe}</td>"
                f"        <td class='{cagr_class}'>{cagr*100:>+9.2f}%</td>"
                f"        <td class='{mdd_class}'>{mdd*100:>+15.2f}%</td>"
                f"        <td>{len(result.fill_history):>8}</td>"
                f"        <td>{len(result.equity_curve):>15}</td>"
                f"      </tr>"
            )

        html_parts.extend([
            "    </table>",
            "    <div class='summary'>",
            "      <h3>📈 Legend</h3>",
            "      <p>⭐ = Best in that category</p>",
            "      <p><span class='positive'>Green</span> = Positive result</p>",
            "      <p><span class='negative'>Red</span> = Negative result</p>",
            "      <p>Sharpe Ratio > 1.0 is generally considered good.</p>",
            "      <p>CAGR = Compound Annual Growth Rate (annualized return).</p>",
            "    </div>",
            "  </div>",
            "</body>",
            "</html>"
        ])

        html_content = "\n".join(html_parts)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)

        abs_path = os.path.abspath(path)
        print(f"[MultiStrategyBacktestReport] HTML saved → {abs_path}")
        if open_browser:
            webbrowser.open(f"file://{abs_path}")
        return abs_path

    def compare_returns_overlay(self, path: str = "compare_returns.html",
                                 open_browser: bool = True) -> str:
        """Generate overlaid returns chart using plotly for direct comparison.

        Plots daily returns % for each strategy on the same chart so you can
        directly compare their volatility and drawdowns side-by-side.

        Parameters
        ----------
        path : str
            Output HTML file path.
        open_browser : bool
            If True, open the file in the default browser.

        Returns
        -------
        str
            Absolute path to the saved HTML file.
        """
        try:
            import plotly.graph_objects as go
        except ImportError:
            raise ImportError("plotly not installed – run: pip install plotly")

        if not self._results:
            raise ValueError("No results to compare. Call run() first.")

        fig = go.Figure()
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        for idx, (name, returns_series) in enumerate(self._returns_series.items()):
            if returns_series.empty:
                continue
            color = colors[idx % len(colors)]
            fig.add_trace(go.Scatter(
                x=returns_series.index,
                y=returns_series.values * 100,  # convert to percentage
                mode="lines",
                name=name,
                line=dict(color=color, width=2.5),
                hovertemplate=f"<b>{name}</b><br>Date: %{{x|%Y-%m-%d}}<br>Return: %{{y:.3f}}%<extra></extra>",
            ))

        fig.update_layout(
            title="Daily Returns Comparison",
            xaxis_title="Date",
            yaxis_title="Daily Return (%)",
            hovermode="x unified",
            template="plotly_white",
            height=700,
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)", bordercolor="black", borderwidth=1),
        )

        fig.write_html(path)
        abs_path = os.path.abspath(path)
        print(f"[MultiStrategyBacktestReport] Returns overlay chart saved → {abs_path}")

        if open_browser:
            webbrowser.open(f"file://{abs_path}")

        return abs_path

    def compare_cumulative_equity_overlay(self, path: str = "compare_equity.html",
                                          open_browser: bool = True) -> str:
        """Generate overlaid cumulative equity chart using plotly.

        Plots the equity curve for each strategy on the same chart, normalized
        to the initial balance so you can see relative performance.

        Parameters
        ----------
        path : str
            Output HTML file path.
        open_browser : bool
            If True, open the file in the default browser.

        Returns
        -------
        str
            Absolute path to the saved HTML file.
        """
        try:
            import plotly.graph_objects as go
        except ImportError:
            raise ImportError("plotly not installed – run: pip install plotly")

        if not self._results:
            raise ValueError("No results to compare. Call run() first.")

        fig = go.Figure()
        colors = ["#1f77b4", "#ffe100", "#00d500", "#d40000", "#956bbc", "#8c564b"]

        for idx, (name, result) in enumerate(self._results.items()):
            eq_series = result.to_equity_series()
            if eq_series.empty:
                continue
            color = colors[idx % len(colors)]
            fig.add_trace(go.Scatter(
                x=eq_series.index,
                y=eq_series.values,
                mode="lines",
                name=name,
                line=dict(color=color, width=2.5),
                hovertemplate=f"<b>{name}</b><br>Date: %{{x|%Y-%m-%d}}<br>Equity: NT$%{{y:,.0f}}<extra></extra>",
            ))

        fig.update_layout(
            title="Cumulative Equity Comparison",
            xaxis_title="Date",
            yaxis_title="Equity (TWD)",
            hovermode="x unified",
            template="plotly_white",
            height=700,
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)", bordercolor="black", borderwidth=1),
        )

        fig.write_html(path)
        abs_path = os.path.abspath(path)
        print(f"[MultiStrategyBacktestReport] Equity overlay chart saved → {abs_path}")

        if open_browser:
            webbrowser.open(f"file://{abs_path}")

        return abs_path

    def _require_qs(self):
        try:
            import quantstats as qs
            return qs
        except ImportError:
            raise ImportError("quantstats not installed – run: pip install quantstats")
