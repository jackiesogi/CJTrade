#!/usr/bin/env python3
"""
Test for CJTrade Beginner API - my_strategy.py example

This test verifies that the example strategy from doc/README.md
can be imported and executed successfully.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pytest
from unittest.mock import Mock, patch, MagicMock
from cjtrade.pkgs.brokers.account_client import AccountClient
from cjtrade.pkgs.models import Kbar, Order, OrderType, Position, Product
from cjtrade.pkgs.api.beginner import (
    set_current_symbol,
    get_current_symbol,
    set_client,
    ta,
    buy,
    sell,
    get_balance,
    get_positions,
    get_current_price,
    equity,
    cash,
)


# ============ Test Strategy (from doc/README.md) ============
def setup():
    """Initialize once at startup"""
    set_current_symbol("2330")


def strategy(kbar):
    """Called for each K-bar"""
    # Calculate indicators
    ema_short = ta.ema(kbar.closes, 12)
    ema_long = ta.ema(kbar.closes, 26)
    rsi = ta.rsi(kbar.closes, 14)

    # Entry signal
    if ema_short[-1] > ema_long[-1] and rsi[-1] < 30:
        return buy(qty=100)

    # Exit signal
    if ema_short[-1] < ema_long[-1] and rsi[-1] > 70:
        return sell(qty=100)

    return None


def on_position_changed(position):
    """Optional: Called when position changes"""
    pass


def on_system_end():
    """Optional: Called at end of backtest"""
    pass


# ============ Unit Tests ============
class TestBeginnerAPI:
    """Test Beginner API functionality"""

    def setup_method(self):
        """Reset state before each test"""
        # Create mock client
        self.mock_client = Mock(spec=AccountClient)
        self.mock_client.get_balance.return_value = 500000.0
        self.mock_client.get_positions.return_value = []
        self.mock_client.get_snapshots.return_value = [Mock(close=150.5)]
        self.mock_client.buy_stock.return_value = Mock(order_id="123")
        self.mock_client.sell_stock.return_value = Mock(order_id="124")

        set_client(self.mock_client)

    def test_set_current_symbol(self):
        """Test setting default symbol"""
        set_current_symbol("2330")
        assert get_current_symbol() == "2330"

    def test_buy_with_default_symbol(self):
        """Test buy order with default symbol"""
        set_current_symbol("2330")
        result = buy(qty=100)

        assert result is not None
        self.mock_client.buy_stock.assert_called_once()
        call_args = self.mock_client.buy_stock.call_args
        assert call_args[0][0] == "2330"  # symbol
        assert call_args[1].get("quantity", call_args[1].get("qty")) == 100

    def test_buy_with_explicit_symbol(self):
        """Test buy order with explicit symbol"""
        result = buy(qty=50, symbol="0050")

        assert result is not None
        call_args = self.mock_client.buy_stock.call_args
        assert call_args[0][0] == "0050"

    def test_sell_order(self):
        """Test sell order"""
        set_current_symbol("2330")
        result = sell(qty=100)

        assert result is not None
        self.mock_client.sell_stock.assert_called_once()

    def test_get_balance(self):
        """Test balance query"""
        balance = get_balance()
        assert balance == 500000.0

    def test_get_balance_alias(self):
        """Test cash() alias"""
        balance = cash()
        assert balance == 500000.0

    def test_get_current_price(self):
        """Test price query"""
        price = get_current_price("2330")
        assert price == 150.5

    def test_ta_namespace(self):
        """Test that ta namespace is available"""
        assert hasattr(ta, 'ema')
        assert hasattr(ta, 'sma')
        assert hasattr(ta, 'bb')
        assert hasattr(ta, 'rsi')
        assert hasattr(ta, 'macd')


class TestStrategyExecution:
    """Test the example strategy from doc/README.md"""

    def setup_method(self):
        """Setup for each test"""
        self.mock_client = Mock(spec=AccountClient)
        self.mock_client.get_balance.return_value = 500000.0
        self.mock_client.buy_stock.return_value = Mock(order_id="123")
        self.mock_client.sell_stock.return_value = Mock(order_id="124")

        set_client(self.mock_client)

    def test_strategy_setup(self):
        """Test strategy setup phase"""
        setup()
        assert get_current_symbol() == "2330"

    def test_strategy_buy_signal(self):
        """Test strategy generates buy signal"""
        # Create test data: uptrend with RSI < 30
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]

        kbar = Mock(spec=Kbar)
        kbar.closes = closes
        kbar.close = 109.0

        with patch.object(ta, 'ema') as mock_ema, \
             patch.object(ta, 'rsi') as mock_rsi:

            # EMA short > EMA long (uptrend)
            mock_ema.side_effect = [
                [100.0, 103.0, 106.0, 109.0],  # ema_short
                [95.0, 98.0, 101.0, 104.0],    # ema_long
            ]
            # RSI < 30 (oversold)
            mock_rsi.return_value = [15.0]

            result = strategy(kbar)

            assert result is not None
            self.mock_client.buy_stock.assert_called_once()

    def test_strategy_sell_signal(self):
        """Test strategy generates sell signal"""
        # Create test data: downtrend with RSI > 70
        closes = [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0]

        kbar = Mock(spec=Kbar)
        kbar.closes = closes
        kbar.close = 101.0

        with patch.object(ta, 'ema') as mock_ema, \
             patch.object(ta, 'rsi') as mock_rsi:

            # EMA short < EMA long (downtrend)
            mock_ema.side_effect = [
                [101.0, 103.0, 105.0, 107.0],  # ema_short
                [106.0, 107.0, 108.0, 109.0],  # ema_long
            ]
            # RSI > 70 (overbought)
            mock_rsi.return_value = [75.0]

            result = strategy(kbar)

            assert result is not None
            self.mock_client.sell_stock.assert_called_once()

    def test_strategy_no_signal(self):
        """Test strategy holds when conditions not met"""
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]

        kbar = Mock(spec=Kbar)
        kbar.closes = closes
        kbar.close = 105.0

        with patch.object(ta, 'ema') as mock_ema, \
             patch.object(ta, 'rsi') as mock_rsi:

            # EMA short > long but RSI not < 30
            mock_ema.side_effect = [
                [102.0, 104.0, 105.0],
                [100.0, 101.0, 102.0],
            ]
            mock_rsi.return_value = [50.0]

            result = strategy(kbar)

            assert result is None

    def test_on_position_changed_callable(self):
        """Test that on_position_changed is callable"""
        mock_position = Mock(spec=Position)

        # Should not raise
        on_position_changed(mock_position)

    def test_on_system_end_callable(self):
        """Test that on_system_end is callable"""
        # Should not raise
        on_system_end()


class TestStrategyIntegration:
    """Integration test: simulate a simple backtest"""

    def test_simple_backtest_simulation(self):
        """Simulate running strategy on multiple kbars"""
        mock_client = Mock(spec=AccountClient)
        mock_client.get_balance.return_value = 500000.0
        mock_client.buy_stock.return_value = Mock(order_id="123")
        mock_client.sell_stock.return_value = Mock(order_id="124")

        set_client(mock_client)
        setup()

        # Create 5 kbars
        kbars = []
        for i in range(5):
            kbar = Mock(spec=Kbar)
            kbar.closes = list(range(100 + i*5, 110 + i*5))  # Rising trend
            kbar.close = 100 + (i+1) * 5
            kbars.append(kbar)

        orders = []
        with patch.object(ta, 'ema') as mock_ema, \
             patch.object(ta, 'rsi') as mock_rsi:

            for i, kbar in enumerate(kbars):
                # Simulate rising trend
                mock_ema.side_effect = [
                    [100.0 + j for j in range(5)],  # short
                    [95.0 + j for j in range(5)],   # long
                ]
                mock_rsi.return_value = [25.0]  # Oversold

                order = strategy(kbar)
                if order:
                    orders.append(order)

        # Should have generated at least one order
        assert len(orders) > 0
        on_system_end()


# ============ Run Tests ============
if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v", "--tb=short"])
