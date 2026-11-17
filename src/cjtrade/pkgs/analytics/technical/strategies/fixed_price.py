import asyncio

from cjtrade.pkgs.analytics.technical.models import *

class FixedPriceStrategy:
    """A simple fixed price strategy based on OHLCV data.

    Parameters
    ----------
    buy_target_price : float
        BUY when the close is at or below this price.
    sell_target_price : float
        SELL when the close is at or above this price.
    """

    def __init__(self, buy_target_price: float, sell_target_price: float):
        self.buy_target_price = buy_target_price
        self.sell_target_price = sell_target_price

    def _should_buy(self, state: OHLCVState) -> bool:
        return state.close <= self.buy_target_price

    def _should_sell(self, state: OHLCVState) -> bool:
        return state.close >= self.sell_target_price

    # async def start(self, market_data_stream) -> None:
    #     async for state in market_data_stream:
    #         self.on_market_state(state)

    def evaluate(self, state: OHLCVState) -> Signal:
        """Return a BUY, SELL or HOLD signal for `state`.

        The buy check runs first, so BUY wins if both targets are hit.
        Prints a line when a BUY or SELL signal is produced.
        """
        if self._should_buy(state):
            print(f"!!!!!! Buy signal generated at price: {state.close}")
            return Signal(action=SignalAction.BUY, reason=f"Price reached buy target of {self.buy_target_price}")
        elif self._should_sell(state):
            print(f"!!!!!! Sell signal generated at price: {state.close}")
            return Signal(action=SignalAction.SELL, reason=f"Price reached sell target of {self.sell_target_price}")
        else:
            return Signal(action=SignalAction.HOLD, reason="Price not at target")
