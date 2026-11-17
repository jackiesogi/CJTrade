# Risk gate

Pre-trade controls the trading engine applies before an order reaches the
broker: a per-bot capital allocation, an order rate limit, a duplicate-order
window and a loss kill switch. Every control is off unless set.

::: cjtrade.pkgs.risk.pre_trade
