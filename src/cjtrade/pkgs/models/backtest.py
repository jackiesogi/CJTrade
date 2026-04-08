from dataclasses import dataclass
from dataclasses import field
from typing import Dict
from typing import List
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    """Immutable snapshot of a completed backtest session.

    Attributes
    ----------
    initial_balance : float
        Starting cash before any trades.
    final_balance : float
        Remaining cash at session end (excludes unrealised position value).
    equity_curve : list[dict]
        Minute-resolution portfolio value recorded by the client.
        Each entry: {"time": "2024-06-14T09:01:00", "value": 1_234_567.0}
    fill_history : list[dict]
        Every executed trade, already filtered to this session by the client.
        Each entry: {"time", "symbol", "action", "quantity", "price",
                     "session_id", ...}
    session_id : str, optional
        Opaque identifier the client stamped on every order it placed.
        Used to isolate this run's fills from the server's global fill_history.
    start_time : str, optional
        ISO timestamp of when the client started this backtest session.
    """

    initial_balance: float
    final_balance: float
    equity_curve: List[Dict]
    fill_history: List[Dict]
    session_id: Optional[str] = None
    start_time: Optional[str] = None

    # ------------------------------------------------------------------
    # Core conversion
    # ------------------------------------------------------------------
    def to_equity_series(self) -> "pd.Series":
        """Return equity_curve as a minute-resolution pd.Series."""
        if not self.equity_curve:
            return pd.Series(dtype=float)
        idx = pd.to_datetime([e["time"] for e in self.equity_curve])
        vals = [e["value"] for e in self.equity_curve]
        return pd.Series(vals, index=idx, name="equity")

    def to_daily_equity(self) -> "pd.Series":
        """Resample minute equity to daily (last value of each trading day)."""
        minute_eq = self.to_equity_series()
        if minute_eq.empty:
            return minute_eq
        return minute_eq.resample("1D").last().dropna()

    def to_returns(self) -> "pd.Series":
        """Returns pd.Series suitable for quantstats.

        Uses daily returns when the backtest spans multiple calendar days.
        Falls back to minute-level returns (annualised at 270 trading days ×
        270 minutes/day) for single-day or intraday backtests.
        """
        daily = self.to_daily_equity()
        if len(daily) >= 2:
            return daily.pct_change().dropna()
        # Single-day fallback: use minute resolution
        minute_eq = self.to_equity_series()
        if minute_eq.empty:
            return minute_eq
        return minute_eq.pct_change().dropna()

    @property
    def _returns_periods_per_year(self) -> int:
        """Annualisation factor matching the resolution of to_returns()."""
        daily = self.to_daily_equity()
        if len(daily) >= 2:
            return 252          # daily
        return 252 * 270        # minute (270 min/trading day)

    # ------------------------------------------------------------------
    # quantstats helpers
    # ------------------------------------------------------------------
    def to_quantstats(self):
        """Run quantstats full report.  Requires ``quantstats`` to be installed."""
        try:
            import quantstats as qs
        except ImportError:
            raise ImportError("pip install quantstats")
        returns = self.to_returns()
        if returns.empty:
            raise ValueError("equity_curve is empty – did the backtest run to completion?")
        qs.reports.full(returns, periods_per_year=self._returns_periods_per_year)

    def sharpe(self) -> float:
        import quantstats as qs
        return qs.stats.sharpe(self.to_returns(), periods=self._returns_periods_per_year)

    def annual_return(self) -> float:
        import quantstats as qs
        return qs.stats.cagr(self.to_returns(), periods_per_year=self._returns_periods_per_year)

    def max_drawdown(self) -> float:
        import quantstats as qs
        return qs.stats.max_drawdown(self.to_returns())

    # ------------------------------------------------------------------
    # Per-day drill-down
    # ------------------------------------------------------------------
    def trades_on(self, date: str) -> List[Dict]:
        """Return all fills that occurred on ``date`` (e.g. '2024-06-14')."""
        return [f for f in self.fill_history if f.get("time", "").startswith(date)]

    def daily_summary(self) -> "pd.DataFrame":
        """DataFrame with one row per calendar day.

        Columns: date, equity, daily_return, n_trades, traded_value
        """
        daily_eq = self.to_daily_equity()
        daily_ret = daily_eq.pct_change()

        fills_df = pd.DataFrame(self.fill_history) if self.fill_history else pd.DataFrame()

        rows = []
        for ts, eq in daily_eq.items():
            date_str = ts.strftime("%Y-%m-%d")
            ret = daily_ret.get(ts, float("nan"))
            if not fills_df.empty and "time" in fills_df.columns:
                day_fills = fills_df[fills_df["time"].str.startswith(date_str)]
                n_trades = len(day_fills)
                traded_value = (day_fills["price"] * day_fills["quantity"].abs()).sum() \
                    if not day_fills.empty else 0.0
            else:
                n_trades, traded_value = 0, 0.0
            rows.append({
                "date": date_str,
                "equity": eq,
                "daily_return": round(ret, 6) if ret == ret else None,
                "n_trades": n_trades,
                "traded_value": round(traded_value, 2),
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, path: str) -> None:
        """Serialise to a pickle file."""
        import pickle
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "BacktestResult":
        """Deserialise from a pickle file."""
        import pickle
        with open(path, "rb") as f:
            return pickle.load(f)
