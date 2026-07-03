"""Transaction cost model for Taiwan Stock Exchange.

Cost components:
  - Commission (手續費): 0.1425% per side, minimum NT$20, with broker discount
  - Transaction tax (證交稅): 0.3% on SELL only (0.1% for ETFs, symbol starts with "0")
  - Slippage: optional price adjustment to simulate market impact

Usage::

    from cjtrade.pkgs.models.cost import CostModel

    # Default: full-rate commission, standard tax, no slippage
    cm = CostModel()

    # Online broker at 六折 discount, with 0.05% slippage
    cm = CostModel(commission_discount=0.6, slippage_model="fixed_pct", slippage_pct=0.0005)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Taiwan tick-size table (TWSE rules)
# ---------------------------------------------------------------------------
def _tick_size(price: float) -> float:
    """Return the minimum price increment for a given stock price."""
    if price < 10:    return 0.01
    if price < 50:    return 0.05
    if price < 100:   return 0.10
    if price < 500:   return 0.50
    if price < 1000:  return 1.00
    return 5.00


# ---------------------------------------------------------------------------
# CostModel
# ---------------------------------------------------------------------------
@dataclass
class CostModel:
    """Parametrisable transaction-cost model for Taiwan stock trading.

    Attributes
    ----------
    commission_rate : float
        Statutory maximum rate: 0.1425% per side.
    commission_discount : float
        Broker discount multiplier (1.0 = no discount; 0.6 = 六折).
    min_commission : float
        Minimum charge per order in TWD (default NT$20).
    stock_tax_rate : float
        Transaction tax (證交稅) applied on SELL for ordinary stocks (0.3%).
    etf_tax_rate : float
        Transaction tax on SELL for ETFs (0.1%; symbols starting with ``"0"``).
    slippage_model : "none" | "fixed_pct" | "fixed_tick"
        ``"none"``       – no price adjustment (default for full-simulation).
        ``"fixed_pct"``  – price moves adversely by ``slippage_pct × price``.
        ``"fixed_tick"`` – price moves adversely by one Taiwan tick.
    slippage_pct : float
        Fractional slippage per side (used only when
        ``slippage_model == "fixed_pct"``).  Default 0.05%.
    """
    commission_rate:     float = 0.001425    # 0.1425%
    commission_discount: float = 1.0         # no discount
    min_commission:      float = 20.0        # NT$20 minimum

    stock_tax_rate: float = 0.003            # 0.3% SELL only
    etf_tax_rate:   float = 0.001            # 0.1% SELL only for ETFs

    slippage_model: Literal["none", "fixed_pct", "fixed_tick"] = "none"
    slippage_pct:   float = 0.0005           # 0.05%

    # ------------------------------------------------------------------
    def effective_rate(self) -> float:
        """Commission rate after applying the broker discount."""
        return self.commission_rate * self.commission_discount

    def calc_commission(self, value: float) -> float:
        """Return the commission for a trade of notional *value* TWD."""
        return round(max(value * self.effective_rate(), self.min_commission), 2)

    def calc_tax(self, value: float, side: str, symbol: str) -> float:
        """Return transaction tax for a trade.  Zero for BUY; non-zero for SELL."""
        if side != "SELL":
            return 0.0
        rate = self.etf_tax_rate if symbol.startswith("0") else self.stock_tax_rate
        return round(value * rate, 2)

    def apply_slippage(self, price: float, side: str) -> float:
        """Return *price* adjusted for slippage (adverse to the trader)."""
        if self.slippage_model == "none":
            return price
        if self.slippage_model == "fixed_pct":
            slip = price * self.slippage_pct
        elif self.slippage_model == "fixed_tick":
            slip = _tick_size(price)
        else:
            return price
        return round(price + slip if side == "BUY" else price - slip, 2)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def buy_total(
        self, price: float, qty: int, symbol: str = ""
    ) -> tuple[float, float, float, float]:
        """Return ``(adj_price, notional, commission, tax)`` for a BUY.

        *tax* is always ``0.0`` for BUY; included for API symmetry.
        *notional* is computed from the slippage-adjusted *adj_price*.
        """
        adj = self.apply_slippage(price, "BUY")
        notional = adj * qty
        comm = self.calc_commission(notional)
        return adj, notional, comm, 0.0

    def sell_total(
        self, price: float, qty: int, symbol: str = ""
    ) -> tuple[float, float, float, float]:
        """Return ``(adj_price, notional, commission, tax)`` for a SELL."""
        adj = self.apply_slippage(price, "SELL")
        notional = adj * qty
        comm = self.calc_commission(notional)
        tax  = self.calc_tax(notional, "SELL", symbol)
        return adj, notional, comm, tax
