"""
Example strategy using beginner API

This demonstrates how users would write strategies with the Pine Script-like API.
"""
from cjtrade.pkgs.api.beginner import *

# ============ Setup Phase ============
def setup():
    """Optional initialization - called once at start"""
    print("Strategy initialized")
    # You can set default symbol here if needed
    set_current_symbol("2330")


# ============ Main Strategy Logic ============
def strategy(kbar):
    """
    Main strategy function called for each K-bar.

    Args:
        kbar: Current Kbar object with OHLCV data

    Returns:
        Order object if action taken, None if hold
    """
    # Get current price
    current = kbar.close

    # Calculate indicators using ta namespace
    ema_short = ta.ema(kbar.closes, 12)
    ema_long = ta.ema(kbar.closes, 26)
    rsi = ta.rsi(kbar.closes, 14)

    # Trading logic
    if ema_short[-1] > ema_long[-1] and rsi[-1] < 30:
        print(f"🟢 BUY signal: EMA cross above, RSI oversold")
        return buy(qty=100)

    elif ema_short[-1] < ema_long[-1] and rsi[-1] > 70:
        print(f"🔴 SELL signal: EMA cross below, RSI overbought")
        return sell(qty=100)

    return None


# ============ Advanced Features (Optional) ============
def on_position_changed(position):
    """Called whenever position changes"""
    print(f"Position update: {position.symbol} {position.quantity} @ {position.current_price}")


def on_system_end():
    """Called at end of backtest/trading session"""
    print("System finished")
    # You could output final stats here
    final_equity = get_total_equity()
    final_cash = get_balance()
    print(f"Final equity: {final_equity:.2f}, Cash: {final_cash:.2f}")


# ============ For Direct Testing ============
if __name__ == "__main__":
    # Test the strategy
    setup()

    # Simulate a few kbars
    import numpy as np

    # Create test data
    closes = np.array([100, 101, 102, 103, 104, 105, 104, 103, 102, 101, 100, 99])
    kbar = Kbar(
        symbol="2330",
        date="2025-01-15",
        open=100,
        high=105,
        low=99,
        close=101,
        volume=1000000,
        closes=closes.tolist(),
    )

    order = strategy(kbar)
    if order:
        print(f"Strategy returned: {order}")
    else:
        print("Strategy returned: Hold")
