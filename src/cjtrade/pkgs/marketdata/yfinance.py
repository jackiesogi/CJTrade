"""YFinanceMarketData: free bars from Yahoo Finance."""
from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from typing import List

from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import in_window
from cjtrade.pkgs.marketdata.base import INTERVAL_MINUTES
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import MarketDataUnavailable
from cjtrade.pkgs.marketdata.base import TimeLike
from cjtrade.pkgs.marketdata.base import to_window
from cjtrade.pkgs.models.kbar import Kbar

_YF_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "60m", "1d": "1d"}


def _taipei(index):
    """Naive Asia/Taipei timestamps from a yfinance index."""
    import pandas as pd
    index = pd.DatetimeIndex(index)
    if index.tz is not None:
        index = index.tz_convert("Asia/Taipei").tz_localize(None)
    return index


class YFinanceMarketData(MarketData):
    """Bars from Yahoo Finance. No account or key needed.

    Tries ``<symbol>.TW`` (listed) first, then ``<symbol>.TWO`` (OTC).
    Bars are converted to the MarketData conventions: raw prices
    (``auto_adjust=False``), intraday bars stamped at their close, daily bars
    at 09:00, volume in lots.

    Warnings
    --------
    Makes network calls to an unofficial API. Yahoo only keeps recent
    intraday history (about 30 days of 1m bars, 60 days of 5m-30m, two years
    of 1h), so older intraday windows come back empty.
    """

    name = "yfinance"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(intervals=frozenset(_YF_INTERVAL))

    def _download(self, ticker: str, start: datetime, end: datetime, interval: str):
        import yfinance as yf
        try:
            return yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval=_YF_INTERVAL[interval],
                auto_adjust=False,
                progress=False,
            )
        except Exception as e:                           # noqa: BLE001
            raise MarketDataUnavailable(f"yfinance: {e}") from e

    def get_kbars(self, symbol: str, start: TimeLike, end: TimeLike,
                  interval: str = "1m") -> List[Kbar]:
        self.require_interval(interval)
        start_dt, end_dt = to_window(start, end)
        if end_dt <= start_dt:
            return []
        data = None
        for ticker in (f"{symbol}.TW", f"{symbol}.TWO"):
            data = self._download(ticker, start_dt, end_dt, interval)
            if data is not None and not data.empty:
                break
        if data is None or data.empty:
            return []

        width = INTERVAL_MINUTES.get(interval)
        bars = []
        for ts, row in zip(_taipei(data.index), data.itertuples(index=False)):
            fields = dict(zip(data.columns.get_level_values(0), row))
            ts = ts.to_pydatetime()
            if width is None:                             # daily
                stamp = ts.replace(hour=9, minute=0, second=0, microsecond=0)
            else:                                         # yfinance stamps the start
                stamp = ts + timedelta(minutes=width)
                close = ts.replace(hour=13, minute=30, second=0, microsecond=0)
                stamp = min(stamp, close) if ts < close else stamp
            bars.append(Kbar(
                timestamp=stamp,
                open=round(float(fields["Open"]), 2),
                high=round(float(fields["High"]), 2),
                low=round(float(fields["Low"]), 2),
                close=round(float(fields["Close"]), 2),
                volume=int(round(float(fields["Volume"]) / 1000)),
                symbol=symbol,
            ))
        return in_window(bars, start_dt, end_dt)
