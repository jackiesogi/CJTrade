"""Market data: where prices come from, separate from where orders go.

```python
from cjtrade.pkgs.marketdata import Cached, Fallback, FinMindMarketData, YFinanceMarketData

market = Cached(Fallback([FinMindMarketData(), YFinanceMarketData()]))
bars = market.get_kbars("2330", "2025-01-01", "2025-07-01", "1d")
```

See :mod:`cjtrade.pkgs.marketdata.base` for the conventions every source
follows. Sources that need an optional SDK or a broker session
(``SinopacMarketData``, ``ArenaXMarketData``) are imported from their own
modules.
"""
from cjtrade.pkgs.marketdata.aggregate import aggregate
from cjtrade.pkgs.marketdata.aggregate import bars_from_ticks
from cjtrade.pkgs.marketdata.base import Capabilities
from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.base import MarketDataError
from cjtrade.pkgs.marketdata.base import MarketDataUnavailable
from cjtrade.pkgs.marketdata.base import UnsupportedRequest
from cjtrade.pkgs.marketdata.cache import PriceCache
from cjtrade.pkgs.marketdata.compose import Cached
from cjtrade.pkgs.marketdata.compose import Fallback
from cjtrade.pkgs.marketdata.factory import from_names
from cjtrade.pkgs.marketdata.finmind import FinMindMarketData
from cjtrade.pkgs.marketdata.offline import OfflineMarketData
from cjtrade.pkgs.marketdata.yfinance import YFinanceMarketData

__all__ = [
    "MarketData", "Capabilities",
    "MarketDataError", "UnsupportedRequest", "MarketDataUnavailable",
    "Fallback", "Cached", "PriceCache",
    "FinMindMarketData", "YFinanceMarketData", "OfflineMarketData",
    "aggregate", "bars_from_ticks", "from_names",
]
