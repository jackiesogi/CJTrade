import json
import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
from cjtrade.apps.ArenaX.hist_backend import ArenaX_Backend_Historical
from cjtrade.apps.ArenaX.live_backend import ArenaX_Backend_PaperTrade
from cjtrade.apps.ArenaX.none_backend import ArenaX_Backend_None
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.quote import Snapshot


class TestArenaXBackendBasic(unittest.TestCase):
    @patch("cjtrade.apps.ArenaX.market_data.ArenaX_Market.fetching_available", return_value=True)
    def test_historical_login_loads_state_file(self, _mock_fetch):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tmp:
            state_path = tmp.name
            sample_state = {
                "balance": 12345.0,
                "fill_history": [
                    {
                        "id": "fill_1",
                        "order_id": "odr_1",
                        "symbol": "2330",
                        "action": "BUY",
                        "quantity": 10,
                        "price": 50.0,
                        "time": "t0",
                    },
                    {
                        "id": "fill_2",
                        "order_id": "odr_2",
                        "symbol": "2330",
                        "action": "SELL",
                        "quantity": -4,
                        "price": 60.0,
                        "time": "t1",
                    },
                ],
                "orders_placed": [
                    {
                        "id": "odr_3",
                        "symbol": "2330",
                        "action": "BUY",
                        "price": 55.0,
                        "quantity": 1,
                        "price_type": PriceType.LMT.value,
                        "order_type": OrderType.ROD.value,
                        "order_lot": OrderLot.IntraDayOdd.value,
                        "created_at": datetime.now().isoformat(),
                    }
                ],
                "orders_committed": [],
                "orders_filled": [],
                "orders_cancelled": [],
                "all_order_status": {},
            }
            json.dump(sample_state, tmp)

        backend = ArenaX_Backend_Historical(
            state_file=state_path,
            skip_data_preload=True,
            num_days_preload=3,
        )
        backend.login()

        self.assertEqual(backend.account_state.balance, 12345.0)
        self.assertEqual(len(backend.account_state.positions), 1)
        position = backend.account_state.positions[0]
        self.assertEqual(position.symbol, "2330")
        self.assertEqual(position.quantity, 6)
        self.assertEqual(position.avg_cost, 50.0)

        self.assertEqual(len(backend.account_state.orders_placed), 1)
        order = backend.account_state.orders_placed[0]
        self.assertEqual(order.action, OrderAction.BUY)
        self.assertEqual(order.price, 55.0)

    @patch("cjtrade.apps.ArenaX.market_data.ArenaX_Market.fetching_available", return_value=True)
    def test_none_backend_sets_market_time(self, _mock_fetch):
        backend = ArenaX_Backend_None(
            skip_data_preload=True,
            num_days_preload=2,
        )
        self.assertIsNotNone(backend.market.start_date)
        self.assertIsInstance(backend.market.start_date, datetime)

    def test_paper_trade_has_kbar_buffer(self):
        backend = ArenaX_Backend_PaperTrade()
        self.assertIsInstance(backend._kbar_buffer, dict)
        self.assertEqual(len(backend._kbar_buffer), 0)
        self.assertIsNotNone(backend.market)

    @patch("cjtrade.apps.ArenaX.market_data.ArenaX_Market.fetching_available", return_value=True)
    def test_list_positions_reconstructs_holdings(self, _mock_fetch):
        backend = ArenaX_Backend_Historical(
            skip_data_preload=True,
            num_days_preload=2,
        )
        backend.account_state.fill_history = [
            {
                "id": "fill_1",
                "order_id": "odr_1",
                "symbol": "2330",
                "action": "BUY",
                "quantity": 10,
                "price": 50.0,
                "time": "t0",
            },
            {
                "id": "fill_2",
                "order_id": "odr_2",
                "symbol": "2330",
                "action": "SELL",
                "quantity": -4,
                "price": 60.0,
                "time": "t1",
            },
        ]

        backend.snapshot = lambda symbol: Snapshot(
            symbol=symbol,
            exchange="TSE",
            timestamp=datetime.now(),
            open=50.0,
            close=55.0,
            high=56.0,
            low=49.0,
            volume=1000,
            average_price=55.0,
            action=OrderAction.BUY,
            buy_price=55.0,
            buy_volume=100,
            sell_price=55.5,
            sell_volume=100,
        )

        positions = backend.list_positions()
        self.assertEqual(len(positions), 1)
        position = positions[0]
        self.assertEqual(position.symbol, "2330")
        self.assertEqual(position.quantity, 6)
        self.assertEqual(position.avg_cost, 50.0)
        self.assertEqual(position.current_price, 55.0)

    @patch("cjtrade.apps.ArenaX.market_data.ArenaX_Market.fetching_available", return_value=True)
    def test_kbars_returns_expected_values(self, _mock_fetch):
        backend = ArenaX_Backend_None(skip_data_preload=True)
        idx = pd.date_range(start="2024-01-02 09:00", periods=2, freq="1min")
        df = pd.DataFrame(
            {
                "Open": [10.0, 11.0],
                "High": [12.0, 13.0],
                "Low": [9.5, 10.5],
                "Close": [11.0, 12.5],
                "Volume": [100, 200],
            },
            index=idx,
        )

        with patch("yfinance.download", return_value=df):
            kbars = backend.kbars("2330", "2024-01-02", "2024-01-03", "1m")

        self.assertEqual(len(kbars), 2)
        self.assertEqual(kbars[0].open, 10.0)
        self.assertEqual(kbars[1].close, 12.5)
        self.assertEqual(kbars[1].volume, 200)

    @patch("cjtrade.apps.ArenaX.market_data.ArenaX_Market.fetching_available", return_value=True)
    def test_snapshot_uses_preloaded_history(self, _mock_fetch):
        backend = ArenaX_Backend_None(skip_data_preload=True)
        start_date = datetime(2024, 1, 2, 9, 0, 0)
        backend.market.start_date = start_date

        idx = pd.date_range(start=start_date, periods=3, freq="1min")
        df = pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0],
                "High": [12.0, 13.0, 14.0],
                "Low": [9.0, 10.0, 11.0],
                "Close": [11.0, 12.0, 13.0],
                "Volume": [100, 200, 300],
            },
            index=idx,
        )
        backend.market.historical_data["2330"] = {
            "data": df,
            "timestamps": df.index.to_numpy(),
        }

        backend.market.get_market_time = lambda: {
            "real_current_time": start_date + timedelta(minutes=2),
            "real_init_time": start_date,
            "mock_init_time": start_date,
            "mock_current_time": start_date + timedelta(minutes=2),
            "time_offset": timedelta(minutes=2),
            "playback_speed": 1.0,
            "manual_time_offset": timedelta(0),
        }
        backend.market.adjust_to_market_hours = lambda dt: dt

        snapshot = backend.snapshot("2330")
        self.assertEqual(snapshot.symbol, "2330")
        self.assertEqual(snapshot.close, 13.0)
        self.assertEqual(snapshot.open, 10.0)
        self.assertEqual(snapshot.volume, 300)


if __name__ == "__main__":
    unittest.main()
