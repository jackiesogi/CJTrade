import shioaji as sj
from datetime import datetime
from typing import Any, Dict, List
import json
import os
from pathlib import Path
import math

from cjtrade.brokers.base_broker_api import *
from cjtrade.models.order import *
from cjtrade.models.product import *
from cjtrade.models.rank_type import *
from cjtrade.models.quote import BidAsk
from cjtrade.db.db_api import *
from ._internal_func import _from_sinopac_result, _to_sinopac_order, _to_sinopac_product, _from_sinopac_snapshot, _to_sinopac_ranktype, _from_sinopac_bidask, _from_sinopac_kbar

# Since the conversion from sj to cj loses information, we need to keep a mapping
# between cj Order IDs and sj Order objects to track order status
cj_sj_order_map = {}

class SinopacBrokerAPI(BrokerAPIBase):
    def __init__(self, **config: Any):
        super().__init__(**config)

        # Check required config parameters
        required_params = ['api_key', 'secret_key', 'ca_path', 'ca_passwd']
        for param in required_params:
            if param not in config:
                raise ValueError(f"SinopacBrokerAPI needs: {param}")

        self.api_key = config['api_key']
        self.secret_key = config['secret_key']
        self.ca_path = config['ca_path']
        self.ca_password = config['ca_passwd']
        self.simulation = config.get('simulation', True)
        self._connected = False

        # db connection
        self.user = config.get('user', 'user001')
        self.db = config.get('mirror_db_path', f'./data/sinopac_{self.user}.db')

        self.api = sj.Shioaji(simulation=self.simulation)

        # TODO: Trade history for accurate tax calculation
        # self.trade_history_path = config.get('trade_history_path', '.sinopac_trade_history.json')
        # self.trade_history = {}  # {symbol: [{"shares": 1000, "price": 100, "date": "2026-01-01", "side": "buy"}]}


    def connect(self) -> bool:
        if self._connected:  # Avoid reconnecting
            return True
        try:
            # self._load_trade_history()

            self.api.login(
                api_key=self.api_key,
                secret_key=self.secret_key,
            )
            self.api.activate_ca(
                ca_path=self.ca_path,
                ca_passwd=self.ca_password,
            )
            self._connected = True

            self.db = connect_sqlite(database=self.db)
            prepare_cjtrade_tables(conn=self.db)

            # self._sync_positions_with_broker()
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self._connected = False
            return False


    def disconnect(self) -> None:
        if self._connected:
            try:
                self.api.logout()
                print("Sinopac broker disconnected")
                self.db.close()
                print("Local mirror DB disconnected")
            except Exception as e:
                print(f"Error disconnecting Sinopac broker: {e}")
            finally:
                self._connected = False


    def is_connected(self) -> bool:
        return self._connected


    def get_positions(self) -> List[Position]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Get position (inventory) via shioaji api (in shares)
            positions = self.api.list_positions(unit=sj.constant.Unit.Share)
            result = []

            for pos in positions:
                # Convert to standard Position format
                position = Position(
                    symbol=pos.code,
                    quantity=pos.quantity,
                    avg_cost=pos.price,
                    current_price=pos.last_price,
                    market_value=pos.quantity * pos.last_price,
                    unrealized_pnl=pos.pnl
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


    def get_bid_ask(self, product: Product, intraday_odd: bool = False) -> BidAsk:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        sinopac_product = _to_sinopac_product(self.api, product)
        received_bidask = []

        def quote_callback(exchange, bidask):
            received_bidask.append(bidask)

        self.api.quote.set_on_bidask_stk_v1_callback(quote_callback)

        subscribe_kwargs = {
            "quote_type": sj.constant.QuoteType.BidAsk,
            "version": sj.constant.QuoteVersion.v1
        }
        if intraday_odd:
            subscribe_kwargs["intraday_odd"] = True

        self.api.quote.subscribe(sinopac_product, **subscribe_kwargs)

        import time
        timeout = 5
        start = time.time()
        while not received_bidask and (time.time() - start) < timeout:
            time.sleep(0.1)

        self.api.quote.unsubscribe(sinopac_product, **subscribe_kwargs)

        if not received_bidask:
            # TODO: Consider raising exception/error here
            print(f"No bid/ask data received for {product.symbol}")
            return None

        return _from_sinopac_bidask(received_bidask[-1])


    # Return close prices for given products at any time
    def get_snapshots(self, products: List[Product]) -> List[Snapshot]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        sinopac_products = [_to_sinopac_product(self.api, p) for p in products]
        sinopac_snapshots = self.api.snapshots(sinopac_products)
        cj_snapshots = []
        for snapshot in sinopac_snapshots:
            cj_snapshot = _from_sinopac_snapshot(snapshot)
            cj_snapshots.append(cj_snapshot)
        return cj_snapshots


    # start: str in "YYYY-MM-DD" format
    # end: str in "YYYY-MM-DD" format (exclusive - will not include this date)
    # interval: str (e.g. 1m/3m/5m/15m/30m/1h/1d)
    def get_kbars(self, product: Product, start: str, end: str, interval: str = "1m"):
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        # Convert end date from exclusive to inclusive for Shioaji API
        from datetime import datetime, timedelta
        end_date = datetime.strptime(end, '%Y-%m-%d')
        adjusted_end_date = end_date - timedelta(days=1)
        adjusted_end = adjusted_end_date.strftime('%Y-%m-%d')

        sinopac_product = _to_sinopac_product(self.api, product)

        # Always fetch 1-minute data from Shioaji (only supported interval)
        kbars_1m = self.api.kbars(contract=sinopac_product, start=start, end=adjusted_end)
        base_kbars = _from_sinopac_kbar(kbars_1m)

        # If requesting 1m data, return as-is
        if interval == "1m":
            return base_kbars

        # For other intervals, use internal aggregation
        try:
            from ._internal_func import _aggregate_kbars
            return _aggregate_kbars(base_kbars, interval)
        except ValueError as e:
            raise ValueError(f"Interval '{interval}' not supported: {e}") from e
        kbars = self.api.kbars(contract=sinopac_product, start=start, end=adjusted_end)
        return _from_sinopac_kbar(kbars)


    def get_market_movers(self, top_n: int = 10,
                          by: RankType = RankType.PRICE_PERCENTAGE_CHANGE,
                          ascending: bool = True) -> Dict[str, Snapshot]:

        if not self._connected:
            raise ConnectionError("Not connected to broker")
        try:
            sj_rank_type = _to_sinopac_ranktype(by)
            movers = self.api.scanners(
                scanner_type=sj_rank_type,
                ascending=ascending,
                count=top_n
            )  # Returns a List[shioaji.data.ChangePercentRank]
            codes = [mover.code for mover in movers]
            names = [mover.name for mover in movers]
            cj_snapshots = self.get_snapshots([Product(symbol=code) for code in codes])
            result = {}
            for i, cj_snapshot in enumerate(cj_snapshots):
                cj_snapshot.name = names[i]  # Add name info
                result[cj_snapshot.name] = cj_snapshot
            return result
        except Exception as e:
            raise ValueError(f"Cannot get market movers from Sinopac: {e}") from e




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

            # Maintain local records
            insert_new_order_to_db(conn=self.db, order=order)
            return order_result

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Order failed: {e}",
                metadata={},
                linked_order=""
            )

    # TODO: Update status to db
    def cancel_order(self, order_id: str) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            # Update status to get latest order information
            self.api.update_status(self.api.stock_account)

            # Try to get from our mapping first
            sinopac_trade = cj_sj_order_map.get(order_id)

            # If not in our mapping, search in list_trades
            if sinopac_trade is None:
                trades = self.api.list_trades()
                for trade in trades:
                    if hasattr(trade, 'status') and hasattr(trade.status, 'id'):
                        if trade.status.id == order_id:
                            sinopac_trade = trade
                            # Update the mapping for future use
                            cj_sj_order_map[order_id] = trade
                            break

            # If still not found, return error
            if sinopac_trade is None:
                return OrderResult(
                    status=OrderStatus.FAILED,
                    message=f"Order {order_id} not found",
                    metadata={"broker": "sinopac"},
                    linked_order=order_id
                )

            # Cancel the order
            self.api.cancel_order(sinopac_trade)

            # Update status again to get the cancelled status
            self.api.update_status(self.api.stock_account)
            update_order_status_to_db(conn=self.db, oid=order_id, status='CANCELLED')

            return _from_sinopac_result(sinopac_trade)

        except Exception as e:
            return OrderResult(
                status=OrderStatus.FAILED,
                message=f"Failed to cancel order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order=order_id
            )



    # TODO: Re-Design the `Order` and `OrderResult`
    # TODO: We commit all placed orders in Sinopac at once but only return one result here???
    def commit_order_legacy(self, order_id: str) -> OrderResult:
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

    # Better version of commit_order()
    # Commit all staged(placed) order and return each of
    # the OrderResult as a List
    def commit_order(self) -> List[OrderResult]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")
        try:
            # Update status to refresh all trade information
            self.api.update_status(self.api.stock_account)

            res = []
            for cj, sj in cj_sj_order_map.items():
                if sj.status.status not in [sj.constant.OrderStatus.Filled,
                                            sj.constant.OrderStatus.Cancelled,
                                            sj.constant.OrderStatus.Rejected]:
                    res.append(_from_sinopac_result(sj))
                    update_order_status_to_db(conn=self.db, oid=cj, status='COMMITTED')

            print("--------- Order committed ----------")
            print(res)
            return res

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to commit order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order='N/A'
            )


    def get_broker_name(self) -> str:
        return "sinopac"

    # TODO: Decouple from sj API/objects, use cj internal class instead
    # This is quite important since other equivalent feature have been
    # abstracted in cjtrade-based dataclass. (Don't simply use List[Dict])
    def list_orders(self) -> List[Dict]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status()  # Refresh status
            trades = self.api.list_trades()

            orders = []
            for trade in trades:
                # TODO: Currently `list_trades()` to `list_orders()` loses too much info
                # Need to redesign the data structure later
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
            # TODO: Consider raising exception/error here
            logger.error(f"list_orders() exception: {e}")
            return []


    ##### SIMPLE HIGH-LEVEL METHODS #####
    # Simple API with default config
    def buy_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
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
        # return self.commit_order(temp.linked_order)
        return self.commit_order()


    def sell_stock(self, symbol: str, quantity: int, price: float, intraday_odd: bool = True) -> OrderResult:
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
        # return self.commit_order(temp.linked_order)
        return self.commit_order()


    ##### TODO: TRADE HISTORY MANAGEMENT #####
    # def _load_trade_history(self):
    #     """Load trade history from local file"""
    #     try:
    #         if os.path.exists(self.trade_history_path):
    #             with open(self.trade_history_path, 'r', encoding='utf-8') as f:
    #                 self.trade_history = json.load(f)
    #             print(f"Loaded trade history from {self.trade_history_path}")
    #         else:
    #             self.trade_history = {}
    #             print(f"No existing trade history found, starting fresh")
    #     except Exception as e:
    #         print(f"Failed to load trade history: {e}")
    #         self.trade_history = {}

    # def _save_trade_history(self):
    #     """Save trade history to local file"""
    #     try:
    #         with open(self.trade_history_path, 'w', encoding='utf-8') as f:
    #             json.dump(self.trade_history, f, indent=2, ensure_ascii=False)
    #         print(f"Saved trade history to {self.trade_history_path}")
    #     except Exception as e:
    #         print(f"Failed to save trade history: {e}")

    # def _sync_positions_with_broker(self):
    #     """Sync local trade history with broker positions
    #     If broker has positions not in our history, add them with current info
    #     """
    #     try:
    #         positions = self.api.list_positions()
    #         for pos in positions:
    #             symbol = pos.code
    #             shares = pos.quantity * 1000

    #             if symbol not in self.trade_history:
    #                 # New position not in our history, add it
    #                 self.trade_history[symbol] = [{
    #                     "shares": shares,
    #                     "price": pos.price,
    #                     "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #                     "side": "buy",
    #                     "note": "synced_from_broker"
    #                 }]
    #                 print(f"Added {symbol} to trade history from broker sync")

    #         self._save_trade_history()
    #     except Exception as e:
    #         print(f"Failed to sync positions with broker: {e}")

    # def _get_cost_basis(self, symbol: str, shares: int, fallback_price: float) -> float:
    #     """Calculate cost basis from trade history
    #     If no history available, use fallback price from broker
    #     """
    #     if symbol in self.trade_history and self.trade_history[symbol]:
    #         # Calculate weighted average cost from trade history
    #         total_cost = 0
    #         total_shares = 0

    #         for trade in self.trade_history[symbol]:
    #             if trade.get("side") == "buy":
    #                 trade_shares = trade.get("shares", 0)
    #                 trade_price = trade.get("price", 0)
    #                 total_cost += trade_shares * trade_price
    #                 total_shares += trade_shares

    #         if total_shares > 0:
    #             return total_cost

    #     # Fallback to broker's average price
    #     return shares * fallback_price

    # def record_trade(self, symbol: str, shares: int, price: float, side: str):
    #     """Record a trade in history for accurate cost tracking
    #     Call this after each successful trade execution

    #     Args:
    #         symbol: Stock symbol
    #         shares: Number of shares (not contracts)
    #         price: Execution price per share
    #         side: 'buy' or 'sell'
    #     """
    #     if symbol not in self.trade_history:
    #         self.trade_history[symbol] = []

    #     self.trade_history[symbol].append({
    #         "shares": shares,
    #         "price": price,
    #         "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #         "side": side
    #     })

    #     self._save_trade_history()
    #     print(f"Recorded {side} {shares} shares of {symbol} at {price}")