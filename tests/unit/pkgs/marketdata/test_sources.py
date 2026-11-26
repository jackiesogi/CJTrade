"""Each source turns its vendor's format into the MarketData conventions.

HTTP and yfinance are replaced at the boundary. The FinMind payloads are the
shapes the live API returned when this was written.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest
from cjtrade.pkgs.marketdata import Cached
from cjtrade.pkgs.marketdata import Fallback
from cjtrade.pkgs.marketdata import FinMindMarketData
from cjtrade.pkgs.marketdata import from_names
from cjtrade.pkgs.marketdata import MarketDataUnavailable
from cjtrade.pkgs.marketdata import UnsupportedRequest
from cjtrade.pkgs.marketdata import YFinanceMarketData
from cjtrade.pkgs.marketdata.arenax import ArenaXMarketData
from cjtrade.pkgs.marketdata.sinopac import SinopacMarketData
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.models.tick import TickSide

PLAN_GATE = {"msg": "Your level is register. Please update your user level. Detail "
                    "information:https://finmindtrade.com/analysis/#/Sponsor/sponsor",
             "status": 400}


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


@pytest.fixture
def finmind(monkeypatch):
    """A FinMindMarketData whose HTTP answers come from `routes[dataset]`."""
    import requests
    routes, calls = {}, []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(dict(params))
        answer = routes[params["dataset"]]
        return FakeResponse(answer(params) if callable(answer) else answer)

    monkeypatch.setattr(requests, "get", fake_get)
    source = FinMindMarketData(token="t")
    source.routes, source.calls = routes, calls
    return source


class TestFinMind:
    def test_daily_bars_follow_the_conventions(self, finmind):
        finmind.routes["TaiwanStockPrice"] = {"status": 200, "msg": "success", "data": [
            {"date": "2025-09-01", "stock_id": "2330", "Trading_Volume": 23022319,
             "Trading_money": 1, "open": 1150.0, "max": 1165.0, "min": 1145.0,
             "close": 1165.0, "spread": 5.0, "Trading_turnover": 41416}]}
        (bar,) = finmind.get_kbars("2330", "2025-09-01", "2025-09-02", "1d")
        assert bar.timestamp == datetime(2025, 9, 1, 9, 0)
        assert (bar.open, bar.high, bar.low, bar.close) == (1150, 1165, 1145, 1165)
        assert bar.volume == 23022, "daily volume is shares; bars carry lots"
        assert finmind.calls[0]["end_date"] == "2025-09-01", "end is exclusive"

    def test_a_plan_gated_dataset_is_unsupported_and_stops_being_advertised(self, finmind):
        finmind.routes["TaiwanStockKBar"] = PLAN_GATE
        assert finmind.supports("1m")
        with pytest.raises(UnsupportedRequest):
            finmind.get_kbars("2330", "2025-09-01", "2025-09-02", "1m")
        assert not finmind.supports("1m")
        assert finmind.supports("1d")

    def test_minute_bars_are_shifted_to_their_close_and_aggregate(self, finmind):
        finmind.routes["TaiwanStockKBar"] = {"status": 200, "data": [
            {"date": "2025-09-01", "minute": f"09:0{i}:00", "stock_id": "2330",
             "open": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "close": 10.5 + i,
             "volume": 3} for i in range(5)]}
        bars = finmind.get_kbars("2330", "2025-09-01", "2025-09-02", "1m")
        assert bars[0].timestamp == datetime(2025, 9, 1, 9, 1)
        (five,) = finmind.get_kbars("2330", "2025-09-01", "2025-09-02", "5m")
        assert five.timestamp == datetime(2025, 9, 1, 9, 5) and five.volume == 15

    def test_ticks_carry_their_side(self, finmind):
        finmind.routes["TaiwanStockPriceTick"] = {"status": 200, "data": [
            {"date": "2020-01-02", "stock_id": "2330", "deal_price": 333.0, "volume": 15,
             "Time": "09:00:15.686", "TickType": 1}]}
        (tick,) = finmind.get_ticks("2330", "2020-01-02")
        assert tick.side is TickSide.BUY and tick.price == 333.0
        assert tick.timestamp == datetime(2020, 1, 2, 9, 0, 15, 686000)

    def test_an_outage_is_unavailable_not_empty(self, finmind):
        finmind.routes["TaiwanStockPrice"] = {"status": 402, "msg": "request limit"}
        with pytest.raises(MarketDataUnavailable):
            finmind.get_kbars("2330", "2025-09-01", "2025-09-02", "1d")

    def test_an_unknown_symbol_is_empty(self, finmind):
        finmind.routes["TaiwanStockPrice"] = {"status": 200, "msg": "success", "data": []}
        assert finmind.get_kbars("9999999", "2025-09-01", "2025-09-02", "1d") == []


class TestYFinance:
    def frame(self, index, volume=2_500):
        cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Adj Close", "Volume"],
                                           ["2330.TW"]])
        rows = [[10.0, 11.0, 9.0, 10.5, 10.4, volume] for _ in index]
        return pd.DataFrame(rows, index=pd.DatetimeIndex(index), columns=cols)

    def test_intraday_bars_are_moved_to_their_close(self, monkeypatch):
        import yfinance
        monkeypatch.setattr(yfinance, "download", lambda *a, **k: self.frame(
            pd.date_range("2026-03-02 01:00", periods=2, freq="1min", tz="UTC")))
        bars = YFinanceMarketData().get_kbars("2330", "2026-03-02", "2026-03-03", "1m")
        assert [b.timestamp for b in bars] == [datetime(2026, 3, 2, 9, 1), datetime(2026, 3, 2, 9, 2)]
        assert bars[0].volume == 2, "yfinance volume is shares; bars carry lots"
        assert bars[0].close == 10.5, "raw close, not the adjusted one"

    def test_daily_bars_are_stamped_at_09_00(self, monkeypatch):
        import yfinance
        monkeypatch.setattr(yfinance, "download",
                            lambda *a, **k: self.frame(["2026-03-02"]))
        (bar,) = YFinanceMarketData().get_kbars("2330", "2026-03-02", "2026-03-03", "1d")
        assert bar.timestamp == datetime(2026, 3, 2, 9, 0)

    def test_an_otc_symbol_falls_back_to_two(self, monkeypatch):
        import yfinance
        asked = []

        def download(ticker, **k):
            asked.append(ticker)
            return self.frame([] if ticker.endswith(".TW") else ["2026-03-02"])

        monkeypatch.setattr(yfinance, "download", download)
        assert YFinanceMarketData().get_kbars("6488", "2026-03-02", "2026-03-03", "1d")
        assert asked == ["6488.TW", "6488.TWO"]


class FakeBroker:
    def __init__(self, bars):
        self.bars, self.calls = bars, []

    def get_kbars(self, product, start, end, interval):
        self.calls.append((product.symbol, start, end, interval))
        return self.bars

    def get_snapshots(self, products):
        return [p.symbol for p in products]


def test_sinopac_asks_for_1m_with_an_exclusive_end_and_aggregates():
    bars = [Kbar(datetime(2026, 3, 2, 9, m), 1, 1, 1, 1, 1, "2330") for m in range(1, 11)]
    broker = FakeBroker(bars)
    out = SinopacMarketData(broker).get_kbars("2330", "2026-03-02", "2026-03-03", "5m")
    assert broker.calls == [("2330", "2026-03-02", "2026-03-03", "1m")]
    assert [b.timestamp.minute for b in out] == [5, 10]


def test_arenax_asks_its_server_for_the_exact_half_open_window():
    bars = [Kbar(datetime(2026, 3, 2, 9, 1), 1, 1, 1, 1, 1, "2330"),
            Kbar(datetime(2026, 3, 3, 9, 1), 1, 1, 1, 1, 1, "2330")]
    broker = FakeBroker(bars)
    out = ArenaXMarketData(broker).get_kbars("2330", "2026-03-02", "2026-03-03", "1m")
    assert broker.calls == [("2330", "2026-03-02T00:00:00", "2026-03-03T00:00:00", "1m")]
    assert len(out) == 1


class TestFromNames:
    def test_names_become_a_cached_fallback(self, tmp_path):
        market = from_names("finmind,yfinance", cache_path=str(tmp_path / "p.db"))
        assert isinstance(market, Cached) and isinstance(market.source, Fallback)
        assert [s.name for s in market.source.sources] == ["finmind", "yfinance"]

    def test_sinopac_needs_a_broker(self):
        with pytest.raises(ValueError):
            from_names("sinopac", cache=False)

    def test_an_unknown_name_is_refused(self):
        with pytest.raises(ValueError):
            from_names("bloomberg", cache=False)
