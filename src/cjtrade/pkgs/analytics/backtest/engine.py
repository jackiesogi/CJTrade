"""
pkgs/analytics/backtest/engine.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Vectorised (one-shot) backtest engine.

Receives a pre-fetched list of Kbar objects, runs a BaseStrategy over them
bar-by-bar with a simulated account, and returns a BacktestResult – all in
memory, no HTTP, no time progression.

Usage
-----
    from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
    from my_strategy import BollingerStrategy

    engine = BacktestEngine(
        kbars=kbars,          # List[Kbar] for one symbol
        symbol="2330",
        initial_balance=1_000_000,
        params={"bb_window": 20, "bb_min_width_pct": 0.01},
    )
    result = engine.run(BollingerStrategy())
    BacktestReport(result).full_report()

Multi-symbol
------------
    For multi-symbol backtests, pass a merged & time-sorted list of Kbar
    objects with different .symbol attributes and set symbol=None.
    The engine will split them internally.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs.models.backtest import BacktestResult
from cjtrade.pkgs.models.kbar import Kbar
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs.strategy.base_strategy import Fill
from cjtrade.pkgs.strategy.base_strategy import Signal
from cjtrade.pkgs.strategy.base_strategy import StrategyContext

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# _TaggedKbar – Kbar + symbol (Kbar model has no symbol field)
# ---------------------------------------------------------------------------

class _TaggedKbar:
    """Thin wrapper that attaches a symbol to a plain Kbar."""
    __slots__ = ("timestamp", "open", "high", "low", "close", "volume", "symbol")

    def __init__(self, kbar: Kbar, symbol: str) -> None:
        self.timestamp = kbar.timestamp
        self.open      = kbar.open
        self.high      = kbar.high
        self.low       = kbar.low
        self.close     = kbar.close
        self.volume    = kbar.volume
        self.symbol    = symbol

# Taiwan stock exchange commission constants
_COMMISSION_RATE   = 0.001425   # 0.1425% per side
_TRANSACTION_TAX   = 0.003      # 0.3% on sell only
_MIN_COMMISSION    = 20.0       # TWD minimum commission


def _calc_buy_cost(price: float, qty: int) -> float:
    """Total cash needed to buy qty lots at price (including commission)."""
    value = price * qty * 1000          # 1 lot = 1000 shares
    commission = max(value * _COMMISSION_RATE, _MIN_COMMISSION)
    return round(value + commission, 0)


def _calc_sell_proceeds(price: float, qty: int) -> float:
    """Net cash received from selling qty lots at price (after tax + commission)."""
    value = price * qty * 1000
    commission = max(value * _COMMISSION_RATE, _MIN_COMMISSION)
    tax = value * _TRANSACTION_TAX
    return round(value - commission - tax, 0)


# ---------------------------------------------------------------------------
# Simulated account (internal to engine)
# ---------------------------------------------------------------------------

class _SimAccount:
    """Minimal simulated brokerage account used by the engine."""

    def __init__(self, initial_balance: float) -> None:
        self.balance = float(initial_balance)
        self.initial_balance = float(initial_balance)
        # {symbol: {'quantity': int, 'avg_cost': float}}
        self._positions: Dict[str, Dict] = {}
        self.fill_history: List[Dict] = []

    # ------------------------------------------------------------------
    # Position access
    # ------------------------------------------------------------------

    def positions_list(self, price_map: Dict[str, float]) -> List[Dict]:
        result = []
        for sym, pos in self._positions.items():
            if pos["quantity"] <= 0:
                continue
            price = price_map.get(sym, pos["avg_cost"])
            market_value = price * pos["quantity"] * 1000
            result.append({
                "symbol":        sym,
                "quantity":      pos["quantity"],
                "avg_cost":      pos["avg_cost"],
                "current_price": price,
                "market_value":  round(market_value, 2),
                "unrealized_pnl": round((price - pos["avg_cost"]) * pos["quantity"] * 1000, 2),
            })
        return result

    def equity(self, price_map: Dict[str, float]) -> float:
        pos_value = sum(
            price_map.get(sym, p["avg_cost"]) * p["quantity"] * 1000
            for sym, p in self._positions.items()
            if p["quantity"] > 0
        )
        return round(self.balance + pos_value, 2)

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def buy(self, symbol: str, qty: int, price: float,
            timestamp: datetime, reason: str = "") -> Optional[Fill]:
        if qty <= 0:
            return None
        cost = _calc_buy_cost(price, qty)
        if cost > self.balance:
            log.debug(f"[Engine] BUY rejected – insufficient balance "
                      f"({self.balance:,.0f} < {cost:,.0f})")
            return None

        self.balance -= cost
        pos = self._positions.setdefault(symbol, {"quantity": 0, "avg_cost": 0.0})
        total_shares = (pos["quantity"] + qty) * 1000
        total_cost   = pos["quantity"] * pos["avg_cost"] * 1000 + qty * price * 1000
        pos["quantity"] += qty
        pos["avg_cost"]  = round(total_cost / total_shares, 2)

        fill = Fill(symbol=symbol, action="BUY", quantity=qty,
                    price=price, timestamp=timestamp, reason=reason,
                    commission=round(max(price*qty*1000*_COMMISSION_RATE, _MIN_COMMISSION), 2))
        self._record_fill(fill)
        return fill

    def sell(self, symbol: str, qty: int, price: float,
             timestamp: datetime, reason: str = "") -> Optional[Fill]:
        pos = self._positions.get(symbol)
        if not pos or pos["quantity"] < qty or qty <= 0:
            log.debug(f"[Engine] SELL rejected – no / insufficient position in {symbol}")
            return None

        proceeds = _calc_sell_proceeds(price, qty)
        self.balance += proceeds
        pos["quantity"] -= qty
        if pos["quantity"] == 0:
            pos["avg_cost"] = 0.0

        fill = Fill(symbol=symbol, action="SELL", quantity=qty,
                    price=price, timestamp=timestamp, reason=reason,
                    commission=round(max(price*qty*1000*_COMMISSION_RATE, _MIN_COMMISSION), 2))
        self._record_fill(fill)
        return fill

    def _record_fill(self, fill: Fill) -> None:
        self.fill_history.append({
            "time":       fill.timestamp.isoformat(),
            "symbol":     fill.symbol,
            "action":     fill.action,
            "quantity":   fill.quantity,
            "price":      fill.price,
            "commission": fill.commission,
            "reason":     fill.reason,
        })


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """One-shot backtest engine.

    Parameters
    ----------
    kbars : list[Kbar]
        Pre-fetched bars, sorted ascending by timestamp.
        May contain multiple symbols – the engine splits them automatically.
    symbol : str, optional
        If provided, filter kbars to only this symbol before running.
        Leave as None to pass all symbols to the strategy.
    initial_balance : float
        Starting cash in TWD.
    params : dict, optional
        Passed verbatim as ``ctx.params`` to every strategy call.
    session_id : str, optional
        Stored in the returned BacktestResult for traceability.
    """

    def __init__(
        self,
        kbars: List[Kbar],
        symbol: Optional[str] = None,
        initial_balance: float = 1_000_000.0,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> None:
        # Kbar doesn't carry a symbol field; we attach one via a thin wrapper
        # so the engine and strategy can always read bar.symbol.
        if symbol:
            kbars = [_TaggedKbar(k, symbol) for k in kbars]
        else:
            # Caller must have passed TaggedKbar or objects that already have .symbol
            pass
        self.kbars = sorted(kbars, key=lambda k: k.timestamp)
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.params = params or {}
        self.session_id = session_id
        self._account = _SimAccount(initial_balance)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, strategy: BaseStrategy) -> BacktestResult:
        """Run the strategy over all bars and return a BacktestResult."""
        if not self.kbars:
            raise ValueError("kbars list is empty – nothing to backtest.")

        account    = self._account
        price_map: Dict[str, float] = {}   # latest price per symbol
        price_hist: Dict[str, List[float]] = {}
        equity_curve: List[Dict] = []

        # Initial context (before first bar)
        init_ctx = StrategyContext(
            timestamp=self.kbars[0].timestamp,
            balance=account.balance,
            equity=account.initial_balance,
            positions=[],
            price_history={},
            bar_index=0,
            params=self.params,
        )
        strategy.on_start(init_ctx)

        for idx, bar in enumerate(self.kbars):
            sym = bar.symbol

            # Update price map
            price_map[sym] = bar.close
            price_hist.setdefault(sym, []).append(bar.close)

            # Build context
            ctx = StrategyContext(
                timestamp=bar.timestamp,
                balance=account.balance,
                equity=account.equity(price_map),
                positions=account.positions_list(price_map),
                price_history={s: list(v) for s, v in price_hist.items()},
                bar_index=idx,
                params=self.params,
            )

            # Ask strategy for signals
            signals: List[Signal] = strategy.on_bar(bar, ctx) or []

            # Execute signals
            for sig in signals:
                if sig.action == "BUY":
                    fill = account.buy(sig.symbol, sig.quantity, sig.price,
                                       bar.timestamp, reason=sig.reason)
                    if fill:
                        strategy.on_fill(fill, ctx)
                elif sig.action == "SELL":
                    fill = account.sell(sig.symbol, sig.quantity, sig.price,
                                        bar.timestamp, reason=sig.reason)
                    if fill:
                        strategy.on_fill(fill, ctx)

            # Record equity point (once per minute, deduped)
            minute_key = bar.timestamp.replace(second=0, microsecond=0).isoformat()
            if not equity_curve or equity_curve[-1]["time"] != minute_key:
                equity_curve.append({
                    "time":  minute_key,
                    "value": account.equity(price_map),
                })

        # Final context
        final_ctx = StrategyContext(
            timestamp=self.kbars[-1].timestamp,
            balance=account.balance,
            equity=account.equity(price_map),
            positions=account.positions_list(price_map),
            price_history={s: list(v) for s, v in price_hist.items()},
            bar_index=len(self.kbars) - 1,
            params=self.params,
        )
        strategy.on_end(final_ctx)

        log.info(
            f"[BacktestEngine] Finished – {len(self.kbars)} bars, "
            f"{len(account.fill_history)} fills, "
            f"equity {account.initial_balance:,.0f} → {account.equity(price_map):,.0f}"
        )

        return BacktestResult(
            initial_balance=account.initial_balance,
            final_balance=account.balance,
            equity_curve=equity_curve,
            fill_history=account.fill_history,
            session_id=self.session_id,
            start_time=self.kbars[0].timestamp.isoformat() if self.kbars else None,
        )
