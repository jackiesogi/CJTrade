"""Build a MarketData from source names, as configuration and CLIs spell them."""
from __future__ import annotations

from typing import Iterable
from typing import Optional
from typing import Union

from cjtrade.pkgs.marketdata.base import MarketData
from cjtrade.pkgs.marketdata.cache import PriceCache
from cjtrade.pkgs.marketdata.compose import Cached
from cjtrade.pkgs.marketdata.compose import Fallback

SOURCE_NAMES = ("sinopac", "finmind", "yfinance", "cache")


def parse_names(spec: Union[str, Iterable[str]]) -> list:
    """Split ``"finmind,yfinance"`` into names, rejecting unknown ones."""
    names = [n.strip().lower() for n in (spec.split(",") if isinstance(spec, str) else spec)]
    names = [n for n in names if n]
    unknown = [n for n in names if n not in SOURCE_NAMES]
    if unknown or not names:
        raise ValueError(f"unknown market data source(s) {unknown or spec!r}; "
                         f"choose from {', '.join(SOURCE_NAMES)}")
    return names


def from_names(spec: Union[str, Iterable[str]], *, sinopac=None,
               finmind_token: Optional[str] = None,
               cache: Optional[Union[PriceCache, bool]] = True,
               cache_path: Optional[str] = None) -> MarketData:
    """Build a MarketData from names, in order of preference.

    Parameters
    ----------
    spec : str or iterable of str
        ``"sinopac"``, ``"finmind"``, ``"yfinance"`` and ``"cache"``, e.g.
        ``"finmind,yfinance"``.
    sinopac : SinopacBrokerAPI or AccountClient, optional
        A connected Sinopac broker; required when ``"sinopac"`` is named.
    finmind_token : str, optional
        Defaults to the ``FINMIND_TOKEN`` setting.
    cache : bool or PriceCache, optional
        Put a price cache in front (default True). Pass a PriceCache to
        choose the file, or False for no cache.
    cache_path : str, optional
        Cache file when `cache` is True.

    Returns
    -------
    MarketData

    Raises
    ------
    ValueError
        An unknown name, or ``"sinopac"`` without a broker.

    Examples
    --------
    ```python
    market = from_names("finmind,yfinance")     # cached, FinMind first
    ```
    """
    sources: list = []
    for name in parse_names(spec):
        if name == "sinopac":
            if sinopac is None:
                raise ValueError("the 'sinopac' source needs a connected Sinopac broker")
            from cjtrade.pkgs.marketdata.sinopac import SinopacMarketData
            sources.append(SinopacMarketData(sinopac))
        elif name == "finmind":
            from cjtrade.pkgs.marketdata.finmind import FinMindMarketData
            sources.append(FinMindMarketData(token=finmind_token))
        elif name == "yfinance":
            from cjtrade.pkgs.marketdata.yfinance import YFinanceMarketData
            sources.append(YFinanceMarketData())
        elif name == "cache":
            sources.append(PriceCache(cache_path))
    source = sources[0] if len(sources) == 1 else Fallback(sources)
    if cache is False:
        return source
    store = cache if isinstance(cache, PriceCache) else PriceCache(cache_path)
    return Cached(source, store)
