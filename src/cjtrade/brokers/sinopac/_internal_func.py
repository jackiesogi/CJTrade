import shioaji as sj
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from cjtrade.brokers.broker_base import *
from cjtrade.models.order import *
from cjtrade.models.product import *

##### Cjtrade -> Shioaji #####
# Note that price_type may need to support futures and options.
PRICE_TYPE_MAP = {
    PriceType.LMT: sj.constant.StockPriceType.LMT,
    PriceType.MKT: sj.constant.StockPriceType.MKT,
    # PriceType.STOP: sj.constant.StockPriceType.STOP,  # Not available in shioaji
}

EXCHANGE_MAP = {
    Exchange.TSE: sj.constant.Exchange.TSE,
    # Exchange.NYSE: sj.constant.Exchange.NYSE,
    # Exchange.NASDAQ: sj.constant.Exchange.NASDAQ,
}

ORDER_TYPE_MAP = {
    OrderType.ROD: sj.constant.OrderType.ROD,
    OrderType.IOC: sj.constant.OrderType.IOC,
    OrderType.FOK: sj.constant.OrderType.FOK,
}

ACTION_MAP = {
    OrderAction.BUY: sj.constant.Action.Buy,
    OrderAction.SELL: sj.constant.Action.Sell,
}

STATUS_MAP = {
    sj.constant.Status.PendingSubmit: OrderStatus.SUBMITTED,
    sj.constant.Status.PreSubmitted: OrderStatus.SUBMITTED,
    sj.constant.Status.Submitted: OrderStatus.ACCEPTED,
    sj.constant.Status.Filled: OrderStatus.FILLED,
    sj.constant.Status.PartFilled: OrderStatus.PARTIAL,
    sj.constant.Status.Cancelled: OrderStatus.REJECTED,
}

ORDER_LOT_MAP = {
    OrderLot.IntraDayOdd: sj.constant.StockOrderLot.IntradayOdd,
    OrderLot.Common: sj.constant.StockOrderLot.Common,
}


def _to_sinopac_order(api, order: Order) -> sj.Order:
    try:
        action = ACTION_MAP[order.action]
        price_type = PRICE_TYPE_MAP[order.price_type]
        order_type = ORDER_TYPE_MAP[order.order_type]
        order_lot = ORDER_LOT_MAP[order.order_lot]
    except KeyError as e:
        raise ValueError(f"Unsupported order field: {e.args[0]}") from e

    return sj.Order(
        price=order.price,
        quantity=order.quantity,
        action=action,
        price_type=price_type,
        order_type=order_type,
        order_lot=order_lot,
        account=api.stock_account
    )


# sj.contracts.Contracts.Stocks["2330"]
def _to_sinopac_product(api, product: Product):
    """Convert CJTrade Product to Shioaji Contract"""
    try:
        # Get contracts from the API instance
        contracts = getattr(api.Contracts, product.type.value)
        return contracts[product.symbol]
    except (AttributeError, KeyError) as e:
        raise ValueError(
            f"Cannot resolve Sinopac contract: "
            f"{product.type}.{product.exchange}.{product.symbol}"
        ) from e


def _from_sinopac_result(result) -> OrderResult:
    cj_status = STATUS_MAP.get(result.status.status, OrderStatus.REJECTED)

    return OrderResult(
        id=result.status.id,
        status=cj_status,
        # message=getattr(result, "msg", ""),
        message="",
        metadata={
            "broker": "sinopac",
            "raw_status": result.status,
            "deals": getattr(result.status, "deals", []),
        }
    )

##### INTERNAL METHODS END #####