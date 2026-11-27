"""Conversions between CJTrade models and the fubon_neo SDK's objects.

Written against fubon_neo 2.5.0 and the field lists in Fubon's documentation
(https://www.fbs.com.tw/TradeAPI/docs/trading/library/python/EnumMatrix).

Two properties of the SDK shape this module:

- Its enums (``BSAction.Buy``, ``MarketType.Common``, ...) are unhashable, so
  they cannot be dict keys. ``enum_name()`` reduces one to its member name
  (``"Buy"``), which is what the lookups here are keyed on.
- An ``Order`` is write-only: its fields cannot be read back. What was sent is
  known from the CJTrade ``Order`` it was built from, and what the broker did
  with it from the ``OrderResult`` objects the SDK returns.

Quantities: a CJTrade ``Order`` counts shares for ``OrderLot.IntraDayOdd`` and
lots of 1,000 shares for ``OrderLot.Common``; Fubon always counts shares.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Optional

from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderResult
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.position import Position
from cjtrade.pkgs.models.quote import BidAsk
from cjtrade.pkgs.models.quote import Snapshot
from cjtrade.pkgs.models.trade import Trade
from fubon_neo.constant import BSAction
from fubon_neo.constant import MarketType
from fubon_neo.constant import OrderType as FubonOrderType
from fubon_neo.constant import PriceType as FubonPriceType
from fubon_neo.constant import TimeInForce
from fubon_neo.sdk import Order as FubonOrder

BROKER = "fubon"
LOT_SIZE = 1000
# user_def is at most 10 characters, letters and digits only.
USER_DEF_LEN = 10


def enum_name(value: Any) -> str:
    """``BSAction.Buy`` -> ``"Buy"``; a plain string passes through; None -> ``""``."""
    if value is None:
        return ""
    return str(value).rsplit(".", 1)[-1]


# ── CJTrade -> Fubon ────────────────────────────────────────────────────────

def _market_type(order: Order):
    return MarketType.IntradayOdd if order.order_lot == OrderLot.IntraDayOdd else MarketType.Common


def to_fubon_quantity(order: Order) -> int:
    """Shares, as Fubon counts them."""
    if order.order_lot == OrderLot.Common:
        return int(order.quantity) * LOT_SIZE
    return int(order.quantity)


def validate_order(order: Order) -> Optional[str]:
    """Why Fubon would refuse `order`, or None. Checked before anything is sent.

    The rules are Fubon's market-type table: odd lots take 1-999 shares, ROD
    only, and no market price; board lots take 1-499 lots.
    """
    if order.order_type == OrderType.GTC:
        return "GTC orders are not supported by Fubon"
    if order.action not in (OrderAction.BUY, OrderAction.SELL):
        return f"unsupported action {order.action}"
    if order.quantity is None or int(order.quantity) <= 0:
        return "quantity must be positive"
    if order.order_lot == OrderLot.IntraDayOdd:
        if not 1 <= int(order.quantity) <= 999:
            return "an odd-lot order takes 1 to 999 shares"
        if order.order_type != OrderType.ROD:
            return "odd-lot orders are ROD only"
        if order.price_type == PriceType.MKT:
            return "odd-lot orders cannot be market orders"
    elif not 1 <= int(order.quantity) <= 499:
        return "a board-lot order takes 1 to 499 lots"
    if order.price_type == PriceType.LMT and (order.price is None or float(order.price) <= 0):
        return "a limit order needs a positive price"
    return None


def price_text(price: float) -> str:
    """Fubon takes the price as a string: ``66.5`` -> ``"66.5"``, ``1000.0`` -> ``"1000"``."""
    text = f"{float(price):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def user_def_for(order: Order) -> str:
    """A short tag sent with the order, so the broker's reports can be matched
    to it even before the order map is written. The first 10 hex characters of
    the CJTrade id."""
    return "".join(c for c in order.id if c.isalnum())[:USER_DEF_LEN]


def to_fubon_order(order: Order) -> FubonOrder:
    """Build the SDK ``Order`` for a CJTrade order. Call ``validate_order`` first."""
    market = order.price_type == PriceType.MKT
    return FubonOrder(
        buy_sell=BSAction.Buy if order.action == OrderAction.BUY else BSAction.Sell,
        symbol=order.product.symbol,
        price=None if market else price_text(order.price),
        quantity=to_fubon_quantity(order),
        market_type=_market_type(order),
        price_type=FubonPriceType.Market if market else FubonPriceType.Limit,
        time_in_force={OrderType.ROD: TimeInForce.ROD, OrderType.IOC: TimeInForce.IOC,
                       OrderType.FOK: TimeInForce.FOK}[order.order_type],
        order_type=FubonOrderType.Stock,
        user_def=user_def_for(order),
    )


# ── Fubon -> CJTrade ────────────────────────────────────────────────────────

# OrderResult.status, from Fubon's "委託單狀態" table.
STATUS_PRE_ORDER = 0          # 預約單
STATUS_SENDING = (4, 8)       # sent to the back end / in transit
STATUS_TIMEOUT = 9            # 連線逾時: the outcome is unknown
STATUS_ACCEPTED = 10          # 委託成功
STATUS_CANCELLED = 30         # 未成交刪單成功
STATUS_PARTIAL_CANCELLED = 40  # 部分成交，剩餘取消
STATUS_FILLED = 50            # 完全成交
STATUS_FAILED = 90            # 失敗
# Modify / cancel failures in an active report (改價失敗, 改量失敗, 刪單失敗):
# the order itself is unchanged, so its state comes from its quantities.
STATUS_CHANGE_FAILED = (19, 29, 39)

FINAL_STATUSES = (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


def _by_quantity(result: Any) -> OrderStatus:
    filled = int(getattr(result, "filled_qty", 0) or 0)
    working = int(getattr(result, "after_qty", 0) or 0)
    if filled and working and filled >= working:
        return OrderStatus.FILLED
    return OrderStatus.PARTIAL if filled else OrderStatus.COMMITTED_WAIT_MATCHING


def to_cj_status(result: Any) -> OrderStatus:
    """The CJTrade status of a Fubon OrderResult.

    ``after_qty`` is the order's working quantity including what has filled,
    so an accepted order with ``0 < filled_qty < after_qty`` is PARTIAL. A
    partial fill whose rest was cancelled (40) is CANCELLED; ``filled_qty``
    still says how much traded.
    """
    code = getattr(result, "status", None)
    if code is None:
        return OrderStatus.UNKNOWN
    code = int(code)
    if code == STATUS_PRE_ORDER:
        return OrderStatus.COMMITTED_WAIT_MARKET_OPEN
    if code in STATUS_SENDING:
        return OrderStatus.PLACED
    if code == STATUS_TIMEOUT:
        return OrderStatus.UNKNOWN
    if code == STATUS_ACCEPTED or code in STATUS_CHANGE_FAILED:
        return _by_quantity(result)
    if code in (STATUS_CANCELLED, STATUS_PARTIAL_CANCELLED):
        return OrderStatus.CANCELLED
    if code == STATUS_FILLED:
        return OrderStatus.FILLED
    if code == STATUS_FAILED:
        return OrderStatus.REJECTED
    return OrderStatus.UNKNOWN


def is_odd_lot(result: Any) -> bool:
    return enum_name(getattr(result, "market_type", None)) in ("IntradayOdd", "Odd", "EmgOdd")


def to_cj_quantity(result: Any, shares: Optional[int]) -> int:
    """Fubon shares -> the CJTrade order's unit (lots for board-lot orders)."""
    shares = int(shares or 0)
    return shares if is_odd_lot(result) else shares // LOT_SIZE


def to_cj_action(value: Any) -> str:
    return {"Buy": OrderAction.BUY.value, "Sell": OrderAction.SELL.value}.get(enum_name(value), "N/A")


def to_cj_result(result: Any, cj_order_id: str = "", message: str = "") -> OrderResult:
    """An OrderResult in CJTrade's terms. The broker's ids and quantities go in
    ``metadata``; ``linked_order`` is the CJTrade order id."""
    return OrderResult(
        status=to_cj_status(result),
        message=message or (getattr(result, "error_message", None) or ""),
        metadata={
            "broker": BROKER,
            "seq_no": getattr(result, "seq_no", None),
            "order_no": getattr(result, "order_no", None),
            "fubon_status": getattr(result, "status", None),
            "filled_qty": getattr(result, "filled_qty", None),
            "filled_money": getattr(result, "filled_money", None),
            "after_qty": getattr(result, "after_qty", None),
            "after_price": getattr(result, "after_price", None),
            "last_time": getattr(result, "last_time", None),
        },
        linked_order=cj_order_id,
    )


def to_cj_trade(result: Any, cj_order_id: str) -> Trade:
    """A ``Trade`` row for ``list_orders()``, in CJTrade's spellings."""
    price_type = enum_name(getattr(result, "after_price_type", None) or getattr(result, "price_type", None))
    price = getattr(result, "after_price", None)
    if price is None:
        price = getattr(result, "price", None)
    return Trade(
        id=cj_order_id or "N/A",
        symbol=str(getattr(result, "stock_no", "") or "N/A"),
        action=to_cj_action(getattr(result, "buy_sell", None)),
        quantity=to_cj_quantity(result, getattr(result, "after_qty", None)
                                or getattr(result, "quantity", None)),
        price=float(price or 0.0),
        status=to_cj_status(result).value,
        order_type=enum_name(getattr(result, "time_in_force", None)) or "N/A",
        price_type=PriceType.MKT.value if price_type == "Market" else PriceType.LMT.value,
        order_lot=OrderLot.IntraDayOdd.value if is_odd_lot(result) else OrderLot.Common.value,
        order_datetime=f"{getattr(result, 'date', '') or ''} {getattr(result, 'last_time', '') or ''}".strip(),
        deals=1 if int(getattr(result, "filled_qty", 0) or 0) else 0,
        ordno=str(getattr(result, "order_no", "") or "N/A"),
    )


def to_number(value: Any) -> float:
    """Fubon sends some amounts as strings (``balance: "666666"``)."""
    if value is None or value == "":
        return 0.0
    return float(str(value).replace(",", ""))


def to_cj_positions(unrealized: list) -> list[Position]:
    """Positions from ``accounting.unrealized_gains_and_loses()``, one per symbol.

    Rows of the same symbol (cash and margin, for instance) are summed.
    ``current_price`` is derived from cost and unrealised P&L, which Fubon
    computes net of estimated fees, so it is approximate.
    """
    merged: dict[str, dict] = {}
    for row in unrealized or []:
        symbol = str(getattr(row, "stock_no", "") or "")
        qty = int(getattr(row, "tradable_qty", 0) or 0)
        if not symbol or qty <= 0:
            continue
        cost = to_number(getattr(row, "cost_price", 0))
        pnl = to_number(getattr(row, "unrealized_profit", 0)) - to_number(getattr(row, "unrealized_loss", 0))
        m = merged.setdefault(symbol, {"qty": 0, "cost": 0.0, "pnl": 0.0})
        m["qty"] += qty
        m["cost"] += cost * qty
        m["pnl"] += pnl
    out = []
    for symbol, m in merged.items():
        avg_cost = m["cost"] / m["qty"]
        value = m["cost"] + m["pnl"]
        out.append(Position(symbol=symbol, quantity=m["qty"], avg_cost=round(avg_cost, 4),
                            current_price=round(value / m["qty"], 4),
                            market_value=round(value, 2), unrealized_pnl=round(m["pnl"], 2)))
    return out


def to_cj_snapshot(quote: Any, now: Optional[datetime] = None) -> Snapshot:
    """A ``Snapshot`` from ``stock.query_symbol_quote()``.

    Fubon's quote has no average price or last trade side, so those are 0 and
    BUY, as the note says. Volumes are in lots, as everywhere in CJTrade.
    """
    last = to_number(getattr(quote, "last_price", 0))
    return Snapshot(
        symbol=str(getattr(quote, "symbol", "")),
        exchange=str(getattr(quote, "market", "") or "TSE"),
        timestamp=now or datetime.now(),
        open=to_number(getattr(quote, "open_price", 0)),
        close=last,
        high=to_number(getattr(quote, "high_price", 0)),
        low=to_number(getattr(quote, "low_price", 0)),
        volume=int(getattr(quote, "total_volume", 0) or 0),
        average_price=0.0,
        action=OrderAction.BUY,
        buy_price=to_number(getattr(quote, "bid_price", 0)),
        buy_volume=int(getattr(quote, "bid_volume", 0) or 0),
        sell_price=to_number(getattr(quote, "ask_price", 0)),
        sell_volume=int(getattr(quote, "ask_volume", 0) or 0),
        additional_note="fubon query_symbol_quote: average_price and action are not provided",
    )


def to_cj_bidask(quote: Any, now: Optional[datetime] = None) -> BidAsk:
    """Best bid and ask only: ``query_symbol_quote`` does not carry five levels."""
    return BidAsk(
        symbol=str(getattr(quote, "symbol", "")),
        datetime=now or datetime.now(),
        bid_price=[to_number(getattr(quote, "bid_price", 0))],
        bid_volume=[int(getattr(quote, "bid_volume", 0) or 0)],
        ask_price=[to_number(getattr(quote, "ask_price", 0))],
        ask_volume=[int(getattr(quote, "ask_volume", 0) or 0)],
    )
