import shioaji as sj
from datetime import datetime
from typing import Any, Dict, List

from cjtrade.brokers.broker_base import *
from cjtrade.models.order import *
from cjtrade.models.product import *
from ._internal_func import _from_sinopac_result, _to_sinopac_order, _to_sinopac_product, _from_sinopac_snapshot

# Since the conversion from sj to cj loses information, we need to keep a mapping
# between cj Order IDs and sj Order objects to track order status
cj_sj_order_map = {}

class SinopacBroker(BrokerInterface):
    def __init__(self, **config: Any):
        super().__init__(**config)

        # Check required config parameters
        required_params = ['api_key', 'secret_key', 'ca_path', 'ca_passwd']
        for param in required_params:
            if param not in config:
                raise ValueError(f"SinopacBroker needs: {param}")

        self.api_key = config['api_key']
        self.secret_key = config['secret_key']
        self.ca_path = config['ca_path']
        self.ca_password = config['ca_passwd']
        self.simulation = config.get('simulation', True)

        self.api = sj.Shioaji(simulation=self.simulation)


    def connect(self) -> bool:
        try:
            self.api.login(
                api_key=self.api_key,
                secret_key=self.secret_key,
            )
            self.api.activate_ca(
                ca_path=self.ca_path,
                ca_passwd=self.ca_password,
            )
            self._connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self._connected = False
            return False


    def disconnect(self) -> None:
        if self._connected:
            try:
                self.api.logout()
            except:
                pass
            finally:
                self._connected = False


    def is_connected(self) -> bool:
        return self._connected


    def get_positions(self) -> List[Position]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Get position (inventory) via shioaji api with stock_account
            positions = self.api.list_positions()
            result = []

            for pos in positions:
                # Convert to standard Position format
                position = Position(
                    symbol=pos.code,
                    quantity=pos.quantity,
                    avg_cost=pos.price,
                    current_price=pos.last_price,  # This comes from the position data
                    market_value=pos.quantity * pos.last_price,
                    unrealized_pnl=pos.pnl  # Unrealized P&L from shioaji
                )
                result.append(position)

            return result
        except Exception as e:
            print(f"Failed to get positions: {e}")
            return []


    def get_balance(self) -> float:
        """Get account balance"""
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        account_status = self.api.account_balance()
        return account_status.acc_balance


    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> Dict[str, Any]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Convert to Shioaji product
            sinopac_product = _to_sinopac_product(self.api, product)

            # First subscribe to get live quotes (this enables real-time data)
            subscribe_kwargs = {
                "quote_type": sj.constant.QuoteType.BidAsk,
                "version": sj.constant.QuoteVersion.v1
            }

            if intraday_odd:
                subscribe_kwargs["intraday_odd"] = True

            # Subscribe for real-time updates
            self.api.quote.subscribe(sinopac_product, **subscribe_kwargs)

            # Get current snapshot
            snapshots = self.api.snapshots([sinopac_product])

            if snapshots and len(snapshots) > 0:
                snapshot = snapshots[0]

                # Check for detailed bid/ask arrays first
                bid_price = list(snapshot.bid_price) if hasattr(snapshot, 'bid_price') and snapshot.bid_price else []
                ask_price = list(snapshot.ask_price) if hasattr(snapshot, 'ask_price') and snapshot.ask_price else []
                bid_volume = list(snapshot.bid_volume) if hasattr(snapshot, 'bid_volume') and snapshot.bid_volume else []
                ask_volume = list(snapshot.ask_volume) if hasattr(snapshot, 'ask_volume') and snapshot.ask_volume else []

                # If detailed arrays are empty, use simple buy/sell price
                if not bid_price and hasattr(snapshot, 'buy_price') and snapshot.buy_price:
                    bid_price = [snapshot.buy_price]
                if not ask_price and hasattr(snapshot, 'sell_price') and snapshot.sell_price:
                    ask_price = [snapshot.sell_price]
                if not bid_volume and hasattr(snapshot, 'buy_volume') and snapshot.buy_volume:
                    bid_volume = [snapshot.buy_volume]
                if not ask_volume and hasattr(snapshot, 'sell_volume') and snapshot.sell_volume:
                    ask_volume = [snapshot.sell_volume]

                result = {
                    "symbol": product.symbol,
                    "bid_price": bid_price,
                    "bid_volume": bid_volume,
                    "ask_price": ask_price,
                    "ask_volume": ask_volume,
                    "datetime": snapshot.datetime if hasattr(snapshot, 'datetime') else None,
                    "close": snapshot.close if hasattr(snapshot, 'close') else None,
                    "volume": snapshot.volume if hasattr(snapshot, 'volume') else None,
                    "change_price": snapshot.change_price if hasattr(snapshot, 'change_price') else None,
                    "change_rate": snapshot.change_rate if hasattr(snapshot, 'change_rate') else None,
                    "intraday_odd": intraday_odd
                }
                return result
            else:
                return {"error": f"No snapshot data available for {product.symbol}"}

        except Exception as e:
            return {"error": f"Failed to get bid/ask for {product.symbol}: {str(e)}"}


    def get_quotes(self, product: List[Product]) -> Dict[str, Quote]:
        pass
    #     if not self._connected:
    #         raise ConnectionError("Not connected to broker")

    #     try:

    # Return close prices for given products at any time
    def get_snapshot(self, products: List[Product]) -> List[Snapshot]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        sinopac_products = [_to_sinopac_product(self.api, p) for p in products]
        sinopac_snapshots = self.api.snapshots(sinopac_products)
        cj_snapshots = []
        for snapshot in sinopac_snapshots:
            cj_snapshot = _from_sinopac_snapshot(snapshot)
            cj_snapshots.append(cj_snapshot)
        return cj_snapshots


    def place_order(self, order: Order) -> OrderResult:
        """Place order"""
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            sinopac_product = _to_sinopac_product(self.api, order.product)
            sinopac_order = _to_sinopac_order(self.api, order)
            sinopac_trade = self.api.place_order(sinopac_product, sinopac_order)

            # Store mapping using shioaji order id, not cj order id
            sj_order_id = sinopac_trade.order.id
            cj_sj_order_map[sj_order_id] = sinopac_trade
            # print(f"--- place_order() -> {sinopac_trade}")

            order_result = _from_sinopac_result(sinopac_trade)
            order_result.linked_order = sj_order_id  # Use shioaji order id as linked_order
            return order_result

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Order failed: {e}",
                metadata={},
                linked_order=""
            )


    def cancel_order(self, order_id: str) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")
        sinopac_trade = cj_sj_order_map.get(order_id)
        self.api.cancel_order(sinopac_trade)
        return _from_sinopac_result(sinopac_trade)


    # TODO: Re-Design the `Order` and `OrderResult`
    def commit_order(self, order_id: str) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")
        try:
            # Update status to refresh all trade information
            self.api.update_status(self.api.stock_account)

            # In order to get the order result, we look up the mapping
            trade_obj = cj_sj_order_map.get(order_id)
            # print(f"--- commit_order() -> {trade_obj}")
            return _from_sinopac_result(trade_obj)

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to commit order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order=order_id
            )


    def get_broker_name(self) -> str:
        return "sinopac"

    # TODO: Decouple from sj API/objects, use cj internal class instead
    def list_orders(self) -> List[Dict]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status()  # Refresh status
            trades = self.api.list_trades()

            orders = []
            for trade in trades:
                order_info = {
                    'id': trade.status.id,
                    'symbol': getattr(trade.contract, 'code', 'N/A') if hasattr(trade, 'contract') else 'N/A',
                    'action': trade.order.action.value if hasattr(trade.order, 'action') else 'N/A',
                    'quantity': trade.order.quantity,
                    'price': trade.order.price,
                    'status': trade.status.status.value,
                    'order_type': trade.order.order_type.value if hasattr(trade.order, 'order_type') else 'N/A',
                    'price_type': trade.order.price_type.value if hasattr(trade.order, 'price_type') else 'N/A',
                    'order_lot': trade.order.order_lot.value if hasattr(trade.order, 'order_lot') else 'N/A',
                    'order_datetime': trade.status.order_datetime.strftime('%Y-%m-%d %H:%M:%S') if hasattr(trade.status, 'order_datetime') else 'N/A',
                    'deals': len(trade.status.deals) if hasattr(trade.status, 'deals') else 0,
                    'ordno': trade.order.ordno if hasattr(trade.order, 'ordno') else 'N/A'
                }
                orders.append(order_info)

            return orders

        except Exception as e:
            logger.error(f"list_orders() exception: {e}")
            return []


    ##### SIMPLE HIGH-LEVEL METHODS #####
    # Simple API with default config
    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,  # Assuming TSE for simplicity
            symbol=symbol
        )
        print(f"intraday_odd: {intraday_odd}")

        order = Order(
            product=product,
            action=OrderAction.BUY,
            price=price,
            quantity=quantity,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common
        )

        temp = self.place_order(order)
        return self.commit_order(temp.linked_order)


    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = False) -> OrderResult:
        product = Product(
            type=ProductType.STOCK,
            exchange=Exchange.TSE,
            symbol=symbol
        )

        order = Order(
            product=product,
            action=OrderAction.SELL,
            price=price,
            quantity=quantity,
            price_type=PriceType.LMT,
            order_type=OrderType.ROD,
            order_lot=OrderLot.IntraDayOdd if intraday_odd else OrderLot.Common
        )
        temp = self.place_order(order)
        return self.commit_order(temp.linked_order)