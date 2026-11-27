"""Conversions between CJTrade models and Yuanta Spark API objects.

Written against Yuanta's Spark API documentation
(https://www.yuanta.com.tw/file-repository/content/sparkapi_docs/). The
assembly's objects are read by attribute only, so these functions work on the
.NET objects pythonnet returns and on test doubles alike.

Units, as documented: an order's ``OrderQty`` counts lots for a board-lot order
(``APCode`` 0) and shares for an intraday odd-lot order (``APCode`` 4). Reports
(``AfterQty``, ``OkQty``, ``RealReport.OrderQty``) are documented as shares
(委託股數 / 成交股數). The status of an order is worked out from the ratio of
filled to working quantity, so it does not depend on that unit; only the
quantity shown for a board-lot order does.
"""
from __future__ import annotations

from datetime import date
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

BROKER = "yuanta"
LOT_SIZE = 1000
SUCCESS = ("0001", "00001")

AP_BOARD_LOT = 0
AP_ODD_LOT = 2           # after-hours odd lot
AP_INTRADAY_ODD = 4
AP_AFTER_HOURS = 7
ODD_AP_CODES = (AP_ODD_LOT, AP_INTRADAY_ODD, 99)

TRADE_NEW = 0
TRADE_CANCEL = 4

# BuySell, Time_in_force and PriceFlag in StockOrder.
SIDE = {OrderAction.BUY: "B", OrderAction.SELL: "S"}
TIF = {OrderType.ROD: "0", OrderType.IOC: "3", OrderType.FOK: "4"}
TIF_BACK = {"0": OrderType.ROD.value, "3": OrderType.IOC.value, "4": OrderType.FOK.value}
PRICE_LIMIT = " "
PRICE_MARKET = "M"

# Quote prices that mean "at market", not a price.
MARKET_SENTINELS = (999999999, -999999999)


# ── helpers ─────────────────────────────────────────────────────────────────

def text(value: Any) -> str:
    """A .NET string or char array as a Python string, stripped."""
    if value is None:
        return ""
    return str(value).strip()


def num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        v = float(str(value).replace(",", ""))
    except ValueError:
        return 0.0
    return 0.0 if v in MARKET_SENTINELS else v


def ydate(value: Any) -> str:
    """A TYuantaDate as ``yyyy/MM/dd``. The samples read both ``ushtYear`` and ``Year``."""
    if value is None:
        return ""
    y = getattr(value, "ushtYear", None) or getattr(value, "Year", None)
    m = getattr(value, "bytMon", None) or getattr(value, "Month", None)
    d = getattr(value, "bytDay", None) or getattr(value, "Day", None)
    if not (y and m and d):
        return text(value)
    return f"{int(y):04d}/{int(m):02d}/{int(d):02d}"


def ytime(value: Any) -> str:
    """A TYuantaTime as ``HH:MM:SS``."""
    if value is None:
        return ""
    h = getattr(value, "bytHour", None)
    if h is None:
        h = getattr(value, "Hour", None)
    m = getattr(value, "bytMin", None)
    if m is None:
        m = getattr(value, "Minute", None)
    s = getattr(value, "bytSec", None)
    if s is None:
        s = getattr(value, "Second", None)
    if h is None:
        return text(value)
    return f"{int(h):02d}:{int(m or 0):02d}:{int(s or 0):02d}"


def msg_ok(status: Any) -> bool:
    return text(getattr(status, "MsgCode", "")) in SUCCESS


def tag_for(order: Order) -> str:
    """``BasketNo``: up to 32 letters and digits. A CJTrade id is 32 hex digits,
    so the whole id travels with the order and comes back in every report."""
    return "".join(c for c in order.id if c.isalnum())[:32]


# ── CJTrade -> Yuanta ───────────────────────────────────────────────────────

def ap_code(order: Order) -> int:
    return AP_INTRADAY_ODD if order.order_lot == OrderLot.IntraDayOdd else AP_BOARD_LOT


def validate_order(order: Order) -> Optional[str]:
    """Why the exchange or Yuanta would refuse `order`, or None. Checked before sending.

    Intraday odd lots take 1 to 999 shares, ROD, limit price; board lots take
    1 to 499 lots.
    """
    if order.order_type == OrderType.GTC:
        return "GTC orders are not supported by Yuanta"
    if order.action not in SIDE:
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


def fill_stock_order(obj: Any, order: Order, account: str, identify: int,
                     today: Optional[date] = None) -> Any:
    """Set the fields of a Spark ``StockOrder`` for a new CJTrade order."""
    market = order.price_type == PriceType.MKT
    obj.Identify = int(identify)
    obj.Account = account
    obj.OrderNo = ""
    obj.TradeDate = (today or date.today()).strftime("%Y/%m/%d")
    obj.APCode = ap_code(order)
    obj.TradeKind = TRADE_NEW
    obj.OrderType = "0"                      # cash (現貨)
    obj.StkCode = order.product.symbol
    obj.BuySell = SIDE[order.action]
    obj.PriceFlag = PRICE_MARKET if market else PRICE_LIMIT
    obj.Price = 0.0 if market else float(order.price)
    obj.OrderQty = int(order.quantity)       # lots for APCode 0, shares for APCode 4
    obj.BasketNo = tag_for(order)
    obj.Time_in_force = TIF[order.order_type]
    return obj


def fill_cancel_order(obj: Any, report: Any, account: str, identify: int) -> Any:
    """Set the fields of a Spark ``StockOrder`` that cancels the order `report` describes."""
    obj.Identify = int(identify)
    obj.Account = account
    obj.OrderNo = text(getattr(report, "OrderNo", ""))
    obj.TradeDate = ydate(getattr(report, "TradeDate", None)) or date.today().strftime("%Y/%m/%d")
    obj.APCode = int(getattr(report, "APCode", AP_BOARD_LOT) or 0)
    obj.TradeKind = TRADE_CANCEL
    obj.OrderType = text(getattr(report, "OrderType", "0")) or "0"
    obj.StkCode = text(getattr(report, "CompanyNo", ""))
    obj.BuySell = text(getattr(report, "BS", ""))
    obj.PriceFlag = PRICE_LIMIT
    obj.Price = num(getattr(report, "Price", 0))
    obj.OrderQty = 0
    obj.BasketNo = text(getattr(report, "BasketNo", ""))
    obj.Time_in_force = text(getattr(report, "Time_in_Force", "0")) or "0"
    return obj


# ── Yuanta -> CJTrade ───────────────────────────────────────────────────────

# StkOrder.OrderStatus in GetOrderTradeReport.
ORDER_SENDING = 0
ORDER_PRE = 5
ORDER_FAILED = 10
ORDER_ACCEPTED = 20
ORDER_EXPIRED = 24
ORDER_STABILITY_EXPIRED = 25    # 價穩失效
ORDER_CANCELLED = 30

FINAL_STATUSES = (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


def by_quantity(filled: int, working: int) -> OrderStatus:
    if filled and working and filled >= working:
        return OrderStatus.FILLED
    return OrderStatus.PARTIAL if filled else OrderStatus.COMMITTED_WAIT_MATCHING


def to_cj_status(stk_order: Any) -> OrderStatus:
    """The CJTrade status of a ``StkOrder`` row of GetOrderTradeReport.

    Expired orders (24, and 25 for the price stabilisation measure) are
    CANCELLED: the exchange took them off the book. ``OkQty`` still says how
    much had filled.
    """
    code = getattr(stk_order, "OrderStatus", None)
    if code is None:
        return OrderStatus.UNKNOWN
    code = int(code)
    filled = int(getattr(stk_order, "OkQty", 0) or 0)
    working = int(getattr(stk_order, "AfterQty", 0) or 0)
    if code == ORDER_SENDING:
        return OrderStatus.PLACED
    if code == ORDER_PRE:
        return OrderStatus.COMMITTED_WAIT_MARKET_OPEN
    if code == ORDER_FAILED:
        return OrderStatus.REJECTED
    if code == ORDER_ACCEPTED:
        return by_quantity(filled, working)
    if code in (ORDER_EXPIRED, ORDER_STABILITY_EXPIRED, ORDER_CANCELLED):
        return OrderStatus.CANCELLED
    return OrderStatus.UNKNOWN


# RealReport.OrderStatus in RR_RealReport (rows of RptType 50, order reports).
RR_ACCEPTED = (0, 18)           # 委託成功, 委託收到
RR_FAILED = 1
RR_CANCELLED = (2, 4)           # 取消成功, 減量成功 (減量 to zero is a cancel)
RR_CHANGE_FAILED = (3, 5, 21)   # 取消/減量/改價失敗: the order is unchanged
RR_FILLED = 8
RR_EXPIRED = (24, 25)
RPT_STOCK_ORDER = 50
RPT_STOCK_FILL = 51


def to_cj_status_from_report(report: Any) -> Optional[OrderStatus]:
    """The status an order report (RptType 50) states outright, or None when the
    report does not settle it (a failed change, or an accepted order whose fills
    decide)."""
    code = getattr(report, "OrderStatus", None)
    if code is None:
        return None
    code = int(code)
    if code == RR_FAILED:
        return OrderStatus.REJECTED
    if code in RR_CANCELLED or code in RR_EXPIRED:
        return OrderStatus.CANCELLED
    if code == RR_FILLED:
        return OrderStatus.FILLED
    if code in RR_ACCEPTED:
        return OrderStatus.COMMITTED_WAIT_MATCHING
    return None


def is_odd_lot(row: Any) -> bool:
    return int(getattr(row, "APCode", AP_BOARD_LOT) or 0) in ODD_AP_CODES


def to_cj_quantity(row: Any, shares: Any) -> int:
    """Report shares -> the CJTrade order's unit (lots for a board-lot order)."""
    shares = int(shares or 0)
    return shares if is_odd_lot(row) else shares // LOT_SIZE


def to_cj_action(bs: Any) -> str:
    return {"B": OrderAction.BUY.value, "S": OrderAction.SELL.value}.get(text(bs), "N/A")


def broker_key(row: Any) -> Optional[str]:
    """``<yyyy/MM/dd>:<OrderNo>``: an order number is unique within a trading day."""
    order_no = text(getattr(row, "OrderNo", None) or getattr(row, "OrderNO", None))
    if not order_no:
        return None
    day = ydate(getattr(row, "TradeDate", None) or getattr(row, "OrderDate", None)) \
        or date.today().strftime("%Y/%m/%d")
    return f"{day}:{order_no}"


def to_cj_result(stk_order: Any, cj_order_id: str = "", message: str = "") -> OrderResult:
    return OrderResult(
        status=to_cj_status(stk_order),
        message=message or text(getattr(stk_order, "ErrorMessage", "")),
        metadata={
            "broker": BROKER,
            "order_no": text(getattr(stk_order, "OrderNo", "")),
            "yuanta_status": getattr(stk_order, "OrderStatus", None),
            "filled_qty": getattr(stk_order, "OkQty", None),
            "after_qty": getattr(stk_order, "AfterQty", None),
            "error_no": text(getattr(stk_order, "ErrorNo", "")),
        },
        linked_order=cj_order_id,
    )


def to_cj_trade(stk_order: Any, cj_order_id: str) -> Trade:
    flag = text(getattr(stk_order, "PriceFlag", ""))
    return Trade(
        id=cj_order_id or "N/A",
        symbol=text(getattr(stk_order, "CompanyNo", "")) or "N/A",
        action=to_cj_action(getattr(stk_order, "BS", "")),
        quantity=to_cj_quantity(stk_order, getattr(stk_order, "AfterQty", 0)),
        price=num(getattr(stk_order, "Price", 0)),
        status=to_cj_status(stk_order).value,
        order_type=TIF_BACK.get(text(getattr(stk_order, "Time_in_Force", "0")), "N/A"),
        price_type=PriceType.MKT.value if flag == "1" else PriceType.LMT.value,
        order_lot=OrderLot.IntraDayOdd.value if is_odd_lot(stk_order) else OrderLot.Common.value,
        order_datetime=f"{ydate(getattr(stk_order, 'AcceptDate', None))} "
                       f"{ytime(getattr(stk_order, 'AcceptTime', None))}".strip(),
        deals=1 if int(getattr(stk_order, "OkQty", 0) or 0) else 0,
        ordno=text(getattr(stk_order, "OrderNo", "")) or "N/A",
    )


def to_cj_positions(stores: Any) -> list[Position]:
    """Positions from GetStoreSummary's ``StkStoreList``, one per symbol (cash,
    margin and short rows of a symbol are summed)."""
    merged: dict[str, dict] = {}
    for row in stores or []:
        symbol = text(getattr(row, "StkCode", ""))
        qty = int(getattr(row, "StockQty", 0) or 0)
        if not symbol or qty <= 0:
            continue
        m = merged.setdefault(symbol, {"qty": 0, "cost": 0.0, "value": 0.0, "pnl": 0.0, "px": 0.0})
        avg = num(getattr(row, "Price", 0))
        m["qty"] += qty
        m["cost"] += avg * qty
        m["value"] += num(getattr(row, "MarketAmt", 0))
        m["pnl"] += num(getattr(row, "ReturnAmt", 0))
        m["px"] = num(getattr(row, "MarketPrice", 0)) or m["px"]
    out = []
    for symbol, m in merged.items():
        value = m["value"] or m["px"] * m["qty"]
        out.append(Position(symbol=symbol, quantity=m["qty"], avg_cost=round(m["cost"] / m["qty"], 4),
                            current_price=m["px"], market_value=round(value, 2),
                            unrealized_pnl=round(m["pnl"], 2)))
    return out


def to_cj_snapshot(row: Any, now: Optional[datetime] = None) -> Snapshot:
    """A ``Snapshot`` from a GetWatchListAll row. Volumes are in lots."""
    return Snapshot(
        symbol=text(getattr(row, "StkCode", "")),
        exchange="TSE",
        timestamp=now or datetime.now(),
        open=num(getattr(row, "OpenPrice", 0)),
        close=num(getattr(row, "DealPrice", 0)),
        high=num(getattr(row, "HighPrice", 0)),
        low=num(getattr(row, "LowPrice", 0)),
        volume=int(getattr(row, "TotalVol", 0) or 0),
        average_price=0.0,
        action=OrderAction.BUY if int(getattr(row, "VolFlag", 1) or 0) else OrderAction.SELL,
        buy_price=num(getattr(row, "BuyPrice", 0)),
        buy_volume=0,
        sell_price=num(getattr(row, "SellPrice", 0)),
        sell_volume=0,
        additional_note="yuanta GetWatchListAll: average_price and best-level volumes are not provided",
    )


def to_cj_bidask(row: Any, now: Optional[datetime] = None) -> BidAsk:
    """Best bid and ask only, from the quote table."""
    return BidAsk(symbol=text(getattr(row, "StkCode", "")), datetime=now or datetime.now(),
                  bid_price=[num(getattr(row, "BuyPrice", 0))], bid_volume=[0],
                  ask_price=[num(getattr(row, "SellPrice", 0))], ask_volume=[0])
