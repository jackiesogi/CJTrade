from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict
from typing import List

import pandas as pd
import shioaji as sj
from cjtrade.brokers.base_broker_api import *
from cjtrade.db.db_api import *
from cjtrade.models.kbar import *
from cjtrade.models.order import *
from cjtrade.models.product import *
from cjtrade.models.quote import BidAsk
from cjtrade.models.rank_type import *


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

# Shioaji constant.Status enumeration mapping (for list_trades, place_order result)
STATUS_MAP = {
    sj.constant.Status.PendingSubmit: OrderStatus.PLACED,
    sj.constant.Status.PreSubmitted: OrderStatus.COMMITTED_WAIT_MARKET_OPEN,
    sj.constant.Status.Submitted: OrderStatus.COMMITTED_WAIT_MATCHING,
    sj.constant.Status.Filled: OrderStatus.FILLED,
    sj.constant.Status.PartFilled: OrderStatus.PARTIAL,
    sj.constant.Status.Cancelled: OrderStatus.CANCELLED,
    sj.constant.Status.Failed: OrderStatus.REJECTED,
}

# OrderState.operation.op_type mapping (from exchange, used in callback)
# Ref: https://sinotrade.github.io/zh_TW/tutor/order/Stock/#order-deal-event
OPERATION_TYPE_MAP = {
    'New': OrderStatus.COMMITTED_WAIT_MATCHING,
    'Cancel': OrderStatus.CANCELLED,
    'Deal': OrderStatus.FILLED,
    'UpdateQty': OrderStatus.COMMITTED_WAIT_MATCHING,
    'UpdatePrice': OrderStatus.COMMITTED_WAIT_MATCHING,
    'Failed': OrderStatus.REJECTED,
}

ORDER_LOT_MAP = {
    OrderLot.IntraDayOdd: sj.constant.StockOrderLot.IntradayOdd,
    OrderLot.Common: sj.constant.StockOrderLot.Common,
}

# Since the conversion from sj to cj loses information, we need to keep a mapping
# between cj Order IDs and sj Order objects to track order status
cj_sj_order_map = {}

def _retrieve_sinopac_trade_by_cj_order_id(api, db_conn, cj_order_id: str):
    # Search trade object by CJ ID in cache
    sinopac_trade = cj_sj_order_map.get(cj_order_id)

    if sinopac_trade is not None:
        return sinopac_trade

    # Search sinopac trade id by CJ ID in DB (in db_api.py, should return None if not found)
    sj_id = get_bkr_order_id_from_db(conn=db_conn, cj_order_id=cj_order_id)

    if not sj_id:
        return None

    # Get sinopac trade object by sinopac trade id
    trades = api.list_trades()
    for trade in trades:
        if hasattr(trade, 'status') and hasattr(trade.status, 'id'):
            if trade.status.id == sj_id:
                sinopac_trade = trade
                cj_sj_order_map[cj_order_id] = trade
                break

    return sinopac_trade  # May be None if not found

def _from_sinopac_kbar(sj_kbar) -> List[Kbar]:
    """
    Note: Shioaji timestamps have an extra 8-hour offset,
    so we need to subtract 8 hours to get the correct Taiwan market time.
    """
    cj_kbars = []
    for i in range(len(sj_kbar.ts)):
        # Shioaji timestamp needs 8-hour adjustment for correct Taiwan time
        corrected_timestamp = sj_kbar.ts[i] / 1_000_000_000 - 8 * 3600
        taiwan_dt = datetime.fromtimestamp(corrected_timestamp)

        cj_kbars.append(
            Kbar(
                timestamp=taiwan_dt,
                open=sj_kbar.Open[i],
                high=sj_kbar.High[i],
                low=sj_kbar.Low[i],
                close=sj_kbar.Close[i],
                volume=sj_kbar.Volume[i]
            )
        )
    return cj_kbars


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
        order_lot=order_lot,
        broker='sinopac'
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
        # Handle timestamp - Shioaji timestamp needs 8-hour offset adjustment
        ts_value = getattr(sj_snapshot, 'ts', 0)
        if ts_value > 0:
            # Subtract 8-hour offset to get correct Taiwan time
            corrected_timestamp = ts_value / 1_000_000_000 - 8 * 3600
            taiwan_dt = datetime.fromtimestamp(corrected_timestamp)
        else:
            taiwan_dt = datetime.now()

        return Snapshot(
                symbol=getattr(sj_snapshot, 'code', getattr(sj_snapshot, 'symbol', '')),
                exchange=getattr(sj_snapshot, 'exchange', 'N/A'),
                timestamp=taiwan_dt,
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

# TODO: Consider whether to adopt original thought (for loop aggregation)
def _aggregate_kbars(kbars: List[Kbar], target_interval: str) -> List[Kbar]:
    """
    Aggregate 1-minute K-bars into higher timeframes for Sinopac broker.
    Special handling for daily intervals to ensure exactly one bar per trading day.
    """
    if not kbars:
        return []

    # Taiwan stock market specific intervals (4.5 hour trading session)
    interval_minutes = {
        "1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15,
        "20m": 20, "30m": 30, "45m": 45, "1h": 60, "90m": 90, "2h": 120,
        "1d": 270, "1w": 1350, "1M": 5400  # 270 = 4.5h trading day
    }

    if target_interval not in interval_minutes:
        raise ValueError(f"Unsupported interval: {target_interval}")

    target_mins = interval_minutes[target_interval]

    # If already at target interval, return as-is
    if target_mins == 1:
        return kbars

    # Special handling for daily and longer intervals
    if target_interval in ["1d", "1w", "1M"]:
        return _aggregate_by_trading_session(kbars, target_interval)

    # For intraday intervals, use standard time-based aggregation
    return _aggregate_by_time_windows(kbars, target_mins)


# TODO: Consider whether to adopt original thought (for loop aggregation)
def _aggregate_kbars(kbars: List[Kbar], target_interval: str) -> List[Kbar]:
    """
    Aggregate 1-minute K-bars into higher timeframes for Sinopac broker.
    Special handling for daily intervals to ensure exactly one bar per trading day.
    """
    if not kbars:
        return []

    # Taiwan stock market specific intervals (4.5 hour trading session)
    interval_minutes = {
        "1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15,
        "20m": 20, "30m": 30, "45m": 45, "1h": 60, "90m": 90, "2h": 120,
        "1d": 270, "1w": 1350, "1M": 5400  # 270 = 4.5h trading day
    }

    if target_interval not in interval_minutes:
        raise ValueError(f"Unsupported interval: {target_interval}")

    target_mins = interval_minutes[target_interval]

    # If already at target interval, return as-is
    if target_mins == 1:
        return kbars

    # Special handling for daily and longer intervals
    if target_interval in ["1d", "1w", "1M"]:
        return _aggregate_by_trading_session(kbars, target_interval)

    # For intraday intervals, use standard time-based aggregation
    return _aggregate_by_time_windows(kbars, target_mins)

# TODO: `replay 0050 100 1d` open does not match yesterday's close,
# need to verify the aggregation logic or inspect sinopac's data quality.
def _aggregate_by_trading_session(kbars: List[Kbar], interval: str) -> List[Kbar]:
    """
    Aggregate kbars by trading sessions (daily, weekly, monthly).
    Ensures exactly one bar per trading session regardless of data quality.
    """
    if not kbars:
        return []

    # Group kbars by trading date
    from collections import defaultdict
    daily_groups = defaultdict(list)

    for kbar in kbars:
        # Use date as key to group all kbars from same trading day
        date_key = kbar.timestamp.date()
        daily_groups[date_key].append(kbar)

    # Aggregate each trading day into single kbar
    daily_kbars = []
    for date, day_kbars in sorted(daily_groups.items()):
        if not day_kbars:
            continue

        # Sort by timestamp to ensure proper OHLC
        day_kbars.sort(key=lambda k: k.timestamp)

        # Create aggregated daily kbar
        daily_kbar = Kbar(
            timestamp=day_kbars[0].timestamp.replace(hour=9, minute=0, second=0),  # Market open time
            open=day_kbars[0].open,
            high=max(k.high for k in day_kbars),
            low=min(k.low for k in day_kbars),
            close=day_kbars[-1].close,
            volume=sum(k.volume for k in day_kbars)
        )
        daily_kbars.append(daily_kbar)

    # For weekly/monthly, further aggregate daily kbars
    if interval == "1d":
        return daily_kbars
    elif interval == "1w":
        return _aggregate_daily_to_weekly(daily_kbars)
    elif interval == "1M":
        return _aggregate_daily_to_monthly(daily_kbars)

    return daily_kbars


def _aggregate_daily_to_weekly(daily_kbars: List[Kbar]) -> List[Kbar]:
    """Aggregate daily kbars into weekly kbars."""
    if not daily_kbars:
        return []

    from collections import defaultdict
    weekly_groups = defaultdict(list)

    for kbar in daily_kbars:
        # Get week number (Monday = start of week)
        year, week, _ = kbar.timestamp.date().isocalendar()
        week_key = f"{year}-W{week:02d}"
        weekly_groups[week_key].append(kbar)

    weekly_kbars = []
    for week_key, week_kbars in sorted(weekly_groups.items()):
        if not week_kbars:
            continue

        week_kbars.sort(key=lambda k: k.timestamp)
        weekly_kbar = Kbar(
            timestamp=week_kbars[0].timestamp,
            open=week_kbars[0].open,
            high=max(k.high for k in week_kbars),
            low=min(k.low for k in week_kbars),
            close=week_kbars[-1].close,
            volume=sum(k.volume for k in week_kbars)
        )
        weekly_kbars.append(weekly_kbar)

    return weekly_kbars


def _aggregate_daily_to_monthly(daily_kbars: List[Kbar]) -> List[Kbar]:
    """Aggregate daily kbars into monthly kbars."""
    if not daily_kbars:
        return []

    from collections import defaultdict
    monthly_groups = defaultdict(list)

    for kbar in daily_kbars:
        # Group by year-month
        month_key = kbar.timestamp.strftime("%Y-%m")
        monthly_groups[month_key].append(kbar)

    monthly_kbars = []
    for month_key, month_kbars in sorted(monthly_groups.items()):
        if not month_kbars:
            continue

        month_kbars.sort(key=lambda k: k.timestamp)
        monthly_kbar = Kbar(
            timestamp=month_kbars[0].timestamp,
            open=month_kbars[0].open,
            high=max(k.high for k in month_kbars),
            low=min(k.low for k in month_kbars),
            close=month_kbars[-1].close,
            volume=sum(k.volume for k in month_kbars)
        )
        monthly_kbars.append(monthly_kbar)

    return monthly_kbars


def _aggregate_by_time_windows(kbars: List[Kbar], target_mins: int) -> List[Kbar]:
    """
    Aggregate kbars using fixed time windows for intraday intervals.
    """
    # Convert to pandas for efficient aggregation
    data = {
        'timestamp': [k.timestamp for k in kbars],
        'open': [k.open for k in kbars],
        'high': [k.high for k in kbars],
        'low': [k.low for k in kbars],
        'close': [k.close for k in kbars],
        'volume': [k.volume for k in kbars],
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)

    # Resample to target interval with OHLCV rules
    freq = f"{target_mins}min"  # Use 'min' instead of deprecated 'T'
    aggregated = df.resample(freq).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    # Convert back to Kbar objects
    result = []
    for timestamp, row in aggregated.iterrows():
        kbar = Kbar(
            timestamp=timestamp.to_pydatetime(),
            open=round(row['open'], 2),
            high=round(row['high'], 2),
            low=round(row['low'], 2),
            close=round(row['close'], 2),
            volume=int(row['volume'])
        )
        result.append(kbar)

    return result
##### INTERNAL METHODS END #####
