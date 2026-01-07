import shioaji as sj
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from cjtrade.brokers.broker_base import *
from cjtrade.models.order import *
from cjtrade.models.product import *
from cjtrade.models.rank_type import *
from cjtrade.models.quote import BidAsk


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

RANK_SCANNER_MAP = {
    RankType.PRICE_PERCENTAGE_CHANGE: sj.constant.ScannerType.ChangePercentRank,
    RankType.PRICE_CHANGE: sj.constant.ScannerType.ChangePriceRank,
    RankType.VOLUME: sj.constant.ScannerType.VolumeRank
    # sj also provide sj.constant.ScannerType.AmountRank
}

ACTION_MAP = {
    OrderAction.BUY: sj.constant.Action.Buy,
    OrderAction.SELL: sj.constant.Action.Sell,
}

STATUS_MAP = {
    sj.constant.Status.PendingSubmit: OrderStatus.STAGED,
    sj.constant.Status.PreSubmitted: OrderStatus.ON_THE_WAY,
    sj.constant.Status.Submitted: OrderStatus.COMMITTED,
    sj.constant.Status.Filled: OrderStatus.FILLED,
    sj.constant.Status.PartFilled: OrderStatus.PARTIAL,
    sj.constant.Status.Cancelled: OrderStatus.CANCELLED,
}

ORDER_LOT_MAP = {
    OrderLot.IntraDayOdd: sj.constant.StockOrderLot.IntradayOdd,
    OrderLot.Common: sj.constant.StockOrderLot.Common,
}


# sj_order + sj_contract = cj_order
def _from_sinopac_order(sj_order: sj.Order, sj_contract: sj.contracts.Contract) -> Order:
    try:
        action = next(key for key, value in ACTION_MAP.items() if value == sj_order.action)
        price_type = next(key for key, value in PRICE_TYPE_MAP.items() if value == sj_order.price_type)
        order_type = next(key for key, value in ORDER_TYPE_MAP.items() if value == sj_order.order_type)
        order_lot = next(key for key, value in ORDER_LOT_MAP.items() if value == sj_order.order_lot)
    except StopIteration as e:
        raise ValueError(f"Unsupported Shioaji order field: {e}") from e

    # Convert shioaji contract to cjtrade product
    product = _from_sinopac_product(sj_contract)

    return Order(
        product=product,
        action=action,
        price=sj_order.price,
        quantity=sj_order.quantity,
        price_type=price_type,
        order_type=order_type,
        order_lot=order_lot
    )


# class Snapshot:
#     symbol: str
#     exchange: str
#     timestamp: datetime.datetime
#     open: float
#     close: float
#     high: float
#     low: float
#     volume: int
#     average_price: float
#     action: OrderAction  # Buy/Sell/None
#     buy_price: float
#     buy_volume: int
#     sell_price: float
#     sell_volume: int
def _from_sinopac_snapshot(sj_snapshot) -> Snapshot:
    """Convert Shioaji Snapshot to CJTrade Quote"""
    try:
        return Snapshot(
                symbol=getattr(sj_snapshot, 'code', getattr(sj_snapshot, 'symbol', '')),
                exchange=getattr(sj_snapshot, 'exchange', 'N/A'),
                timestamp=datetime.datetime.fromtimestamp(getattr(sj_snapshot, 'ts', 0) / 1_000_000_000),
                open=getattr(sj_snapshot, 'open', 0.0),
                close=getattr(sj_snapshot, 'close', 0.0),
                high=getattr(sj_snapshot, 'high', 0.0),
                low=getattr(sj_snapshot, 'low', 0.0),
                volume=getattr(sj_snapshot, 'volume', 0),
                average_price=getattr(sj_snapshot, 'average_price', 0.0),
                action=OrderAction.BUY if getattr(sj_snapshot, 'tick_type', None)
                    == sj.constant.TickType.Buy else (
                        OrderAction.SELL if getattr(sj_snapshot, 'tick_type', None)
                        == sj.constant.TickType.Sell else 'N/A'
                    ),
                buy_price=getattr(sj_snapshot, 'buy_price', 0.0),
                buy_volume=getattr(sj_snapshot, 'buy_volume', 0),
                sell_price=getattr(sj_snapshot, 'sell_price', 0.0),
                sell_volume=getattr(sj_snapshot, 'sell_volume', 0),
                additional_note="all fields here are available"
        )
    except Exception as e:
        raise ValueError(f"Cannot convert Shioaji snapshot to Snapshot: {e}") from e


def _from_sinopac_product(sj_contract) -> Product:
    """Convert Shioaji Contract to CJTrade Product"""
    try:
        # Map shioaji security type to ProductType
        if hasattr(sj_contract, 'security_type'):
            security_type = sj_contract.security_type
            if hasattr(security_type, 'value'):
                security_type_value = security_type.value
            else:
                security_type_value = str(security_type)

            if security_type_value == 'STK':
                product_type = ProductType.STOCK
            else:
                product_type = ProductType.STOCK  # fallback
        else:
            product_type = ProductType.STOCK  # fallback

        # Map shioaji exchange to Exchange
        if hasattr(sj_contract, 'exchange'):
            exchange = sj_contract.exchange
            if hasattr(exchange, 'value'):
                exchange_value = exchange.value
            else:
                exchange_value = str(exchange)

            if exchange_value == 'TSE':
                cj_exchange = Exchange.TSE
            elif exchange_value == 'OTC':
                cj_exchange = Exchange.OTC
            else:
                cj_exchange = Exchange.TSE  # fallback
        else:
            cj_exchange = Exchange.TSE  # fallback

        # Get symbol/code
        symbol = getattr(sj_contract, 'code', getattr(sj_contract, 'symbol', ''))

        return Product(
            type=product_type,
            exchange=cj_exchange,
            symbol=symbol
        )
    except Exception as e:
        raise ValueError(f"Cannot convert Shioaji contract to Product: {e}") from e


def _from_sinopac_result(sj_result) -> OrderResult:
    if sj_result is None or not hasattr(sj_result, "status") or sj_result.status is None:
        return OrderResult(
            status=OrderStatus.UNKNOWN,
            message="Invalid or incomplete result from Shioaji API",
            metadata={
                "broker": "sinopac",
                "error": (
                    "null_result" if sj_result is None
                    else "no_status"
                ),
                "raw_result": str(sj_result) if sj_result is not None else None,
            },
            linked_order=""
        )

    cj_status = STATUS_MAP.get(sj_result.status.status, OrderStatus.UNKNOWN)

    return OrderResult(
        status=cj_status,
        message="",
        metadata={
            "broker": "sinopac",
            "raw_status": sj_result.status,
            "deals": getattr(sj_result.status, "deals", []),
        },
        linked_order=getattr(sj_result.status, "id", "")
    )

# Convert CJTrade Order to Shioaji Order
# cj_order - cj_product = sj_order (sj_order only contains the actions)
def _to_sinopac_order(api, cj_order: Order) -> sj.Order:
    try:
        action = ACTION_MAP[cj_order.action]
        price_type = PRICE_TYPE_MAP[cj_order.price_type]
        order_type = ORDER_TYPE_MAP[cj_order.order_type]
        order_lot = ORDER_LOT_MAP[cj_order.order_lot]
    except KeyError as e:
        raise ValueError(f"Unsupported order field: {e.args[0]}") from e

    return sj.Order(
        price=cj_order.price,
        quantity=cj_order.quantity,
        action=action,
        price_type=price_type,
        order_type=order_type,
        order_lot=order_lot
    )


# sj.contracts.Contracts.Stocks["2330"]
def _to_sinopac_product(api, cj_product: Product) -> sj.contracts.Contract:
    """Convert CJTrade Product to Shioaji Contract"""
    try:
        # Get contracts from the API instance
        contracts = getattr(api.Contracts, cj_product.type.value)
        return contracts[cj_product.symbol]
    except (AttributeError, KeyError) as e:
        raise ValueError(
            f"Cannot resolve Sinopac contract: "
            f"{cj_product.type}.{cj_product.exchange}.{cj_product.symbol}"
        ) from e


def _to_sinopac_ranktype(cj_rank_type: RankType) -> sj.constant.ScannerType:
    try:
        return RANK_SCANNER_MAP[cj_rank_type]
    except KeyError as e:
        raise ValueError(f"Unsupported rank type: {e.args[0]}") from e


def _from_sinopac_bidask(sj_bidask) -> BidAsk:
    return BidAsk(
        symbol=sj_bidask.code,
        datetime=sj_bidask.datetime,
        bid_price=[float(p) for p in sj_bidask.bid_price],
        bid_volume=list(sj_bidask.bid_volume),
        ask_price=[float(p) for p in sj_bidask.ask_price],
        ask_volume=list(sj_bidask.ask_volume)
    )

##### INTERNAL METHODS END #####