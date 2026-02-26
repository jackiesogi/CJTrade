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
from cjtrade.models.trade import *
from cjtrade.models.event import *
from cjtrade.models.quote import BidAsk
from cjtrade.db.db_api import *
from cjtrade.brokers.sinopac._internal_func import (
    _from_sinopac_result,
    _to_sinopac_order,
    _to_sinopac_product,
    _from_sinopac_snapshot,
    _to_sinopac_ranktype,
    _from_sinopac_bidask,
    _from_sinopac_kbar,
    _retrieve_sinopac_trade_by_cj_order_id,
    cj_sj_order_map  # Import the shared order map
)

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
        self.username = config.get('username', 'user999')
        self.db_path = config.get('mirror_db_path', f'./data/sinopac.db')
        self.db = None

        self.api = sj.Shioaji(simulation=self.simulation)

        # TODO: Trade history for accurate tax calculation
        # self.trade_history_path = config.get('trade_history_path', '.sinopac_trade_history.json')
        # self.trade_history = {}  # {symbol: [{"shares": 1000, "price": 100, "date": "2026-01-01", "side": "buy"}]}

        # Callbacks
        self._shioaji_callback_registered = False
        self._fill_callbacks = []
        self._fill_callbacks = []
        # Not sure if we will use them:
        self._order_callbacks = []
        self._order_status_cache = {}  # {order_id: OrderStatus}


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

            self.db = connect_sqlite(database=self.db_path)
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


    # TODO: Finish this
    # def register_price_callback(self, cb_type: PriceCallbackType, callback, **kwargs):
    #     pass
        # If PriceCbType == TIME_PERIOD
        # if cb_type == PriceCallbackType.TIME_PERIOD:
        #     pass
        # elif cb_type == PriceCallbackType.PRICE_CHANGE:
        #     pass
        # else:
        #     raise ValueError(f"Unsupported PriceCallbackType: {cb_type}")


    def register_fill_callback(self, callback: FillCallback) -> None:
        self._fill_callbacks.append(callback)

        # Register Shioaji callback for the first time
        if not self._shioaji_callback_registered:
            self._setup_shioaji_order_callback()
            self._shioaji_callback_registered = True


    def register_order_callback(self, callback: OrderCallback) -> None:
        self._order_callbacks.append(callback)

        if not self._shioaji_callback_registered:
            self._setup_shioaji_order_callback()
            self._shioaji_callback_registered = True


    # Sinopac-specific method
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


    # TODO: Remove comments when it is stable
    def place_order(self, order: Order) -> OrderResult:
        """Place order
        1. Convert CJ Order -> Sinopac order + Sinopac contract (product)
        2. Store the mapping between CJ ID and Sinopac order obj through cj_sj_order_map (in-memory dict) and DB (permanent storage)
        3. Place order via Sinopac API
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            sinopac_product = _to_sinopac_product(self.api, order.product)
            sinopac_order = _to_sinopac_order(self.api, order)
            sinopac_trade = self.api.place_order(sinopac_product, sinopac_order)

            # Store mapping using shioaji order id, not cj order id
            sj_order_id = sinopac_trade.order.id
            cj_sj_order_map[order.id] = sinopac_trade
            insert_new_ordermap_item_to_db(conn=self.db, cj_order_id=order.id, bkr_order_id=sj_order_id, broker='sinopac')  # Store mapping in DB

            order_result = _from_sinopac_result(sinopac_trade)
            order_result.linked_order = order.id

            # Maintain local records
            insert_new_order_to_db(conn=self.db, username=self.username, order=order)
            return order_result

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Order failed: {e}",
                metadata={},
                linked_order=""
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
            print(cj_sj_order_map)
            # TODO: Not only check in-mem but also check in DB
            from ._internal_func import STATUS_MAP

            for c, s in cj_sj_order_map.items():
                if s.status.status not in [sj.constant.Status.Submitted,
                                           sj.constant.Status.Cancelled,
                                           sj.constant.Status.Failed,
                                           sj.constant.Status.Filled]:
                    # Map actual Shioaji status to CJ status
                    cj_status = STATUS_MAP.get(s.status.status, OrderStatus.UNKNOWN)
                    res.append(_from_sinopac_result(s))
                    update_order_status_to_db(conn=self.db, oid=c, status=cj_status.value)

            return res

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to commit order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order='N/A'
            )


    # TODO: Currently CJ ID is not permanently stored, so sometimes we cannot find the order to cancel.
    # We need to find a better way to store the mapping (e.g. store in DB permanently instead of in-memory dict)
    def cancel_order(self, order_id: str) -> OrderResult:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status(self.api.stock_account)
            trade_obj = _retrieve_sinopac_trade_by_cj_order_id(api=self.api, db_conn=self.db, cj_order_id=order_id)

            if trade_obj is None:
                raise Exception(f"Order with ID {order_id} not found")

            if trade_obj.status.status in [sj.constant.Status.Filled, sj.constant.Status.Cancelled, sj.constant.Status.Failed]:
                raise Exception(f"Cannot be cancelled because it is already {trade_obj.status.status}")

            self.api.cancel_order(trade_obj)
            self.api.update_status(self.api.stock_account)
            update_order_status_to_db(conn=self.db, oid=order_id, status='CANCELLED')

            return _from_sinopac_result(trade_obj)

        except Exception as e:
            return OrderResult(
                status=OrderStatus.REJECTED,
                message=f"Failed to cancel order: {str(e)}",
                metadata={"broker": "sinopac", "error": str(e)},
                linked_order=order_id
            )


    # NOTE: Decouple from sj API/objects, use cj internal obj (`Trade`) instead
    # This is quite important since other equivalent feature have been
    # abstracted in cjtrade-based dataclass. (Don't simply use List[Dict])
    def list_orders(self) -> List[Trade]:
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        try:
            self.api.update_status()  # Refresh status
            trades = self.api.list_trades()

            orders = []

            for trade in trades:
                # Convert Sinopac status to CJ status
                from ._internal_func import STATUS_MAP
                cj_status = STATUS_MAP.get(trade.status.status, OrderStatus.UNKNOWN)

                order_info = Trade(
                    # id=trade.status.id,
                    # id=cj_order_id,
                    id=get_cj_order_id_from_db(conn=self.db, bkr_order_id=trade.status.id) or 'N/A',
                    symbol=getattr(trade.contract, 'code', 'N/A') if hasattr(trade, 'contract') else 'N/A',
                    action=trade.order.action.value if hasattr(trade.order, 'action') else 'N/A',
                    quantity=trade.order.quantity,
                    price=trade.order.price,
                    status=cj_status.value,  # Use converted CJ status
                    order_type=trade.order.order_type.value if hasattr(trade.order, 'order_type') else 'N/A',
                    price_type=trade.order.price_type.value if hasattr(trade.order, 'price_type') else 'N/A',
                    order_lot=trade.order.order_lot.value if hasattr(trade.order, 'order_lot') else 'N/A',
                    order_datetime=trade.status.order_datetime.strftime('%Y-%m-%d %H:%M:%S') if hasattr(trade.status, 'order_datetime') else 'N/A',
                    deals=len(trade.status.deals) if hasattr(trade.status, 'deals') else 0,
                    ordno=trade.order.ordno if hasattr(trade.order, 'ordno') else 'N/A'
                )

                orders.append(order_info)

            return orders

        except Exception as e:
            # TODO: Consider raising exception/error here
            print(f"list_orders() exception: {e}")
            return []


    def get_broker_name(self) -> str:
        return "sinopac"


    ##### SIMPLE HIGH-LEVEL METHODS (START) #####
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
        return self.commit_order()
    ##### SIMPLE HIGH-LEVEL METHODS (END) #####

    ##### INTERNAL METHODS (START) #####
    def _setup_shioaji_order_callback(self):

        def shioaji_order_status_callback(stat, msg):
            """Shioaji native callback
            Args:
                stat: shioaji.order.OrderState 对象
                    - status: Status enum (PendingSubmit, Submitted, Filled, etc.)
                    - id
                    - order_datetime
                    - deals: list of deal details
                    - deal_price
                    - deal_quantity
                msg: message string
            """
            try:
                # 1. Convert exchange operation type to CJ status
                # Note: stat.operation.op_type is from exchange (different from stat.status)
                from ._internal_func import OPERATION_TYPE_MAP

                # OrderState can be accessed as dict or object, handle both
                if isinstance(stat, dict):
                    op_type = stat.get('operation', {}).get('op_type', '')
                    sj_order_id = stat.get('order', {}).get('id', '')
                    stat_status = stat.get('status', None)
                else:
                    op_type = getattr(getattr(stat, 'operation', None), 'op_type', '')
                    sj_order_id = getattr(getattr(stat, 'order', None), 'id', '')
                    stat_status = getattr(stat, 'status', None)

                cj_status = OPERATION_TYPE_MAP.get(op_type, OrderStatus.UNKNOWN)

                # For deal events, check if it's partial or full fill
                if op_type == 'Deal' and stat_status:
                    # Use stat.status to distinguish PARTIAL vs FILLED
                    from ._internal_func import STATUS_MAP
                    detailed_status = STATUS_MAP.get(stat_status, OrderStatus.FILLED)
                    if detailed_status in [OrderStatus.PARTIAL, OrderStatus.FILLED]:
                        cj_status = detailed_status

                # 2. Get CJ order_id from DB
                cj_order_id = get_cj_order_id_from_db(conn=self.db, bkr_order_id=sj_order_id)
                if not cj_order_id:
                    return  # Ignore if not found

                # 3. Get the complete trade object (including contract information)
                trade_obj = _retrieve_sinopac_trade_by_cj_order_id(api=self.api, db_conn=self.db, cj_order_id=cj_order_id)
                if not trade_obj:
                    return  # Ignore if not found

                # 4. Extract order information
                symbol = getattr(trade_obj.contract, 'code', 'N/A') if hasattr(trade_obj, 'contract') else 'N/A'
                action = getattr(trade_obj.order, 'action', None)
                quantity = getattr(trade_obj.order, 'quantity', 0)
                price = getattr(trade_obj.order, 'price', 0.0)

                # Convert action
                from cjtrade.models.order import OrderAction
                if action == sj.constant.Action.Buy:
                    cj_action = OrderAction.BUY
                elif action == sj.constant.Action.Sell:
                    cj_action = OrderAction.SELL
                else:
                    cj_action = None

                # 5. Get old status (for detecting changes)
                old_status = self._order_status_cache.get(cj_order_id, OrderStatus.PLACED)

                # 6. 创建 OrderEvent
                # Helper to safely get stat values (stat can be dict or object)
                def get_stat_value(key, default=None):
                    if isinstance(stat, dict):
                        return stat.get(key, default)
                    return getattr(stat, key, default)

                order_event = OrderEvent(
                    event_type=EventType.ORDER_STATUS_CHANGE,
                    timestamp=datetime.now(),
                    order_id=cj_order_id,
                    symbol=symbol,
                    action=cj_action,
                    quantity=quantity,
                    price=price,
                    old_status=old_status,
                    new_status=cj_status,
                    filled_quantity=get_stat_value('deal_quantity', 0),
                    filled_price=get_stat_value('deal_price', None),
                    message=msg,
                    broker_raw_data={
                        'sj_order_id': sj_order_id,
                        'sj_status': str(stat_status) if stat_status else 'UNKNOWN',
                        'sj_msg': msg,
                        'op_type': op_type
                    }
                )

                # 7. Update status cache
                self._order_status_cache[cj_order_id] = cj_status

                # 8. Trigger order callbacks
                for callback in self._order_callbacks:
                    try:
                        callback(order_event)
                    except Exception as e:
                        print(f"Error in order callback: {e}")
                        import traceback
                        traceback.print_exc()

                # 9. If it's a fill event, trigger fill callbacks
                if cj_status in [OrderStatus.FILLED, OrderStatus.PARTIAL]:
                    deal_quantity = get_stat_value('deal_quantity', 0)
                    deal_price = get_stat_value('deal_price', 0.0)

                    fill_event = FillEvent(
                        timestamp=datetime.now(),
                        order_id=cj_order_id,
                        symbol=symbol,
                        action=cj_action,
                        filled_quantity=deal_quantity,
                        filled_price=deal_price,
                        filled_value=deal_quantity * deal_price,
                        total_filled_quantity=deal_quantity,  # TODO: Accumulated quantity
                        remaining_quantity=quantity - deal_quantity,
                        order_status=cj_status,
                        deal_id=sj_order_id,
                        broker_raw_data={'deals': get_stat_value('deals', [])}
                    )

                    for callback in self._fill_callbacks:
                        try:
                            callback(fill_event)
                        except Exception as e:
                            print(f"Error in fill callback: {e}")
                            import traceback
                            traceback.print_exc()

                # 10. Update database status
                update_order_status_to_db(conn=self.db, oid=cj_order_id, status=cj_status.value)

            except Exception as e:
                print(f"Error in Shioaji callback handler: {e}")
                import traceback
                traceback.print_exc()

        # Callback function registration
        self.api.set_order_callback(shioaji_order_status_callback)
        print("✅ Shioaji order callback registered")

    ##### INTERNAL METHODS (END) #####

if __name__ == "__main__":
    from cjtrade.core.account_client import AccountClient, BrokerType
    from cjtrade.models.order import Order, OrderAction, PriceType, OrderType
    from cjtrade.models.product import Product, Exchange
    from dotenv import load_dotenv
    import time

    load_dotenv()

    client = AccountClient(
        BrokerType.SINOPAC,
        api_key=os.environ.get("API_KEY", ""),
        secret_key=os.environ.get("SECRET_KEY", ""),
        ca_path=os.environ.get("CA_CERT_PATH", ""),
        ca_passwd=os.environ.get("CA_PASSWORD", ""),
        simulation=False
    )
    client.connect()

    # api = sj.Shioaji(simulation=False)
    # api.login(
    #     api_key=os.environ.get("API_KEY", ""),
    #     secret_key=os.environ.get("SECRET_KEY", ""),
    # )
    # api.activate_ca(
    #     ca_path=os.environ.get("CA_CERT_PATH", ""),
    #     ca_passwd=os.environ.get("CA_PASSWORD", ""),
    # )

    # def order_cb(stat, msg):
    #     print('Below is my order callback !!!!!')
    #     print(stat, msg)

    # api.set_order_callback(order_cb)

    # contract = api.Contracts.Stocks.TSE.TSE2890
    # order = api.Order(
    #     price=16,
    #     quantity=1,
    #     action=sj.constant.Action.Buy,
    #     price_type=sj.constant.StockPriceType.LMT,
    #     order_type=sj.constant.OrderType.ROD,
    #     order_lot=sj.constant.StockOrderLot.IntradayOdd,
    #     custom_field="test",
    #     account=api.stock_account
    # )
    # trade = api.place_order(contract, order)
    # time.sleep(10)
    # api.cancel_order(trade)

    # print(f"\n⏳ 等待訂單狀態變化（Ctrl+C 退出）...")
    # try:
    #     while True:
    #         time.sleep(1)
    # except KeyboardInterrupt:
    #     print(f"\n👋 斷開連接")
    #     api.logout()

    # # 2. 定义 callback 函数
    def on_fill(event: FillEvent):
        print(f"\n🎉 订单成交！")
        print(f"  订单ID: {event.order_id}")
        print(f"  商品: {event.symbol}")
        print(f"  方向: {event.action.value}")
        print(f"  成交数量: {event.filled_quantity}")
        print(f"  成交价格: {event.filled_price}")
        print(f"  成交金额: {event.filled_value}")
        print(f"  订单状态: {event.order_status.value}")

        if event.is_complete_fill():
            print(f"  ✅ 订单完全成交")
        else:
            print(f"  ⏳ 部分成交，剩余 {event.remaining_quantity}")

    def on_order_change(event: OrderEvent):
        print(f"\n📝 订单状态变化")
        print(f"  订单ID: {event.order_id}")
        print(f"  {event.old_status.value} → {event.new_status.value}")

        if event.is_rejected():
            print(f"  ❌ 拒绝原因: {event.message}")
        elif event.is_cancelled():
            print(f"  ⚠️ 订单已取消")

    # 3. 注册 callback
    client.register_fill_callback(on_fill)
    client.register_order_callback(on_order_change)

    # 4. 下单测试
    order = Order(
        product=Product(
            symbol="0050",  # 台积电
            exchange=Exchange.TSE
        ),
        action=OrderAction.BUY,
        price=50.0,
        quantity=1,
        order_lot=OrderLot.IntraDayOdd,
        price_type=PriceType.LMT,
        order_type=OrderType.ROD
    )

    print(f"\n📮 下单: 买进 {order.product.symbol} x{order.quantity} @ {order.price}")
    result = client.place_order(order)
    print(f"  下单结果: {result.status.value}")

    if result.status == OrderStatus.PLACED:
        print(f"\n📤 提交订单")
        commit_results = client.commit_order()
        for res in commit_results:
            print(f"  提交结果: {res.status.value}")

    # 5. 保持程序运行，等待 callback 触发
    print(f"\n⏳ 等待订单成交（Ctrl+C 退出）...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n👋 断开连接")
        client.disconnect()
