"""What happens to a resting order as time passes.

One class per OrderType, so "EOD cancel" stops being a special case: it is just
what ROD does when the session closes. Adding a time-in-force is a new class
plus a line in POLICIES — there is no if/else to extend.

Before this, `order_type` was never read anywhere except two
`if == GTC: raise NotImplementedError` guards. An IOC that did not fill
immediately rested forever, and the server's EOD sweep cancelled ROD, IOC and
FOK alike while its comment claimed to cancel only ROD.

Usage::

    from cjtrade.apps.ArenaX.time_in_force import policy_for, TIFContext

    decision = policy_for(order.order_type).on_no_fill(
        order, TIFContext(now=market_time, calendar=calendar)
    )
    if decision.cancel:
        backend.cancel_order(order.id)
"""
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderType


@dataclass(frozen=True)
class Decision:
    """Rest() to leave the order alone, Cancel(reason) to kill it."""
    cancel: bool
    reason: str = ""


def Rest() -> Decision:
    return Decision(cancel=False)


def Cancel(reason: str) -> Decision:
    return Decision(cancel=True, reason=reason)


@dataclass(frozen=True)
class TIFContext:
    now: datetime
    calendar: TradingCalendar


class TimeInForce(ABC):
    """Policy for one OrderType."""

    name: str = ""

    @abstractmethod
    def on_no_fill(self, order: Order, ctx: TIFContext) -> Decision:
        """Called once per matching pass for an order that did not fill."""
        ...

    def expires_at(self, order: Order,
                   calendar: TradingCalendar) -> Optional[datetime]:
        """Last moment this order may still fill, or None for no deadline.

        The matcher clamps its search window to this, which is what makes the
        deadline hold even when nothing swept the order. on_no_fill alone is
        not enough: it only runs when someone asks, and a replay driver steps
        from the last bar of one session straight to the first bar of the next,
        so the clock is never sitting between the close and the next open where
        a sweep would have noticed. Without the clamp, yesterday's ROD matches
        today's prices.
        """
        return None


class ROD(TimeInForce):
    """當日有效 — dies at the close of the session it was placed in."""

    name = "ROD"

    def expires_at(self, order: Order,
                   calendar: TradingCalendar) -> Optional[datetime]:
        # Keyed on the order's own day, not today: if the matching loop skips
        # past 13:30 (easy at high playback speed) the order must still expire
        # the next time anyone looks, rather than surviving into tomorrow.
        return calendar.close_of(order.order_lot, order.created_at)

    def on_no_fill(self, order: Order, ctx: TIFContext) -> Decision:
        expiry = self.expires_at(order, ctx.calendar)
        if ctx.now >= expiry:
            return Cancel(f"ROD expired at session close {expiry:%Y-%m-%d %H:%M}")
        return Rest()


class IOC(TimeInForce):
    """立即成交否則取消 — one matching pass, then gone.

    The caller runs the fill check before asking, so reaching on_no_fill
    already means "did not fill immediately".
    """

    name = "IOC"

    def on_no_fill(self, order: Order, ctx: TIFContext) -> Decision:
        return Cancel("IOC: no immediate fill")


class FOK(TimeInForce):
    """立即全部成交否則取消.

    Identical to IOC here, and will stay so until the matcher can report a
    partial quantity: ArenaX fills whole orders or nothing, so "all of it
    immediately" and "any of it immediately" cannot be told apart. Kept as its
    own class so the distinction has somewhere to live.
    """

    name = "FOK"

    def on_no_fill(self, order: Order, ctx: TIFContext) -> Decision:
        return Cancel("FOK: not filled in full immediately")


class GTC(TimeInForce):
    """長效單 — survives the close; only an explicit cancel or a fill ends it."""

    name = "GTC"

    def on_no_fill(self, order: Order, ctx: TIFContext) -> Decision:
        return Rest()


POLICIES = {
    OrderType.ROD: ROD(),
    OrderType.IOC: IOC(),
    OrderType.FOK: FOK(),
    OrderType.GTC: GTC(),
}

# Unknown order types rest rather than die: silently cancelling someone's order
# because we did not recognise a field is worse than leaving it working, and
# place_order already validates the enum at the HTTP boundary.
_DEFAULT = ROD()


def policy_for(order_type: OrderType) -> TimeInForce:
    return POLICIES.get(order_type, _DEFAULT)
