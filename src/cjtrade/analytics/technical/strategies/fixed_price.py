import asyncio

from cjtrade.analytics.technical.models import *

class FixedPriceStrategy:
    """A simple fixed price strategy based on OHLCV data."""

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
        if self._should_buy(state):
            print(f"!!!!!! Buy signal generated at price: {state.close}")
            return Signal(action=SignalAction.BUY, reason=f"Price reached buy target of {self.buy_target_price}")
        elif self._should_sell(state):
            print(f"!!!!!! Sell signal generated at price: {state.close}")
            return Signal(action=SignalAction.SELL, reason=f"Price reached sell target of {self.sell_target_price}")
        else:
            return Signal(action=SignalAction.HOLD, reason="Price not at target")


# import time
# from typing import Union

# import shioaji as sj

# class StopOrderExcecutor:
#     def __init__(self, api: sj.Shioaji) -> None:
#         self.api = api
#         self._stop_orders = {}

#     def on_quote(
#         self, quote: Union[sj.BidAskFOPv1, sj.BidAskSTKv1, sj.TickFOPv1, sj.TickSTKv1]
#     ) -> None:
#         code = quote.code
#         if code in self._stop_orders:
#             for stop_order in self._stop_orders[code]:
#                 if stop_order['executed']:
#                     continue
#                 if hasattr(quote, "ask_price"):
#                     price = 0.5 * float(
#                         quote.bid_price[0] + quote.ask_price[0]
#                     )  # mid price
#                 else:
#                     price = float(quote.close)  # Tick

#                 is_execute = False
#                 if stop_order["stop_price"] >= stop_order["ref_price"]:
#                     if price >= stop_order["stop_price"]:
#                         is_execute = True

#                 elif stop_order["stop_price"] < stop_order["ref_price"]:
#                     if price <= stop_order["stop_price"]:
#                         is_execute = True

#                 if is_execute:
#                     self.api.place_order(stop_order["contract"], stop_order["pending_order"])
#                     stop_order['executed'] = True
#                     stop_order['ts_executed'] = time.time()
#                     print(f"execute stop order: {stop_order}")
#                 else:
#                     self._stop_orders[code]

#     def add_stop_order(
#         self,
#         contract: sj.contracts.Contract,
#         stop_price: float,
#         order: sj.order.Order,
#     ) -> None:
#         code = contract.code
#         snap = self.api.snapshots([contract])[0]
#         # use mid price as current price to avoid illiquidity
#         ref_price = 0.5 * (snap.buy_price + snap.sell_price)
#         stop_order = {
#             "code": contract.code,
#             "stop_price": stop_price,
#             "ref_price": ref_price,
#             "contract": contract,
#             "pending_order": order,
#             "ts_create": time.time(),
#             "executed": False,
#             "ts_executed": 0.0
#         }

#         if code not in self._stop_orders:
#             self._stop_orders[code] = []
#         self._stop_orders[code].append(stop_order)
#         print(f"add stop order: {stop_order}")

#     def get_stop_orders(self) -> dict:
#         return self._stop_orders

#     def cancel_stop_order_by_code(self, code: str) -> None:
#         if code in self._stop_orders:
#             _ = self._stop_orders.pop(code)

#     def cancel_stop_order(self, stop_order: dict) -> None:
#         code = stop_order["code"]
#         if code in self._stop_orders:
#             self._stop_orders[code].remove(stop_order)
#             if len(self._stop_orders[code]) == 0:
#                 self._stop_orders.pop(code)

#     def cancel_all_stop_orders(self) -> None:
#         self._stop_orders.clear()
