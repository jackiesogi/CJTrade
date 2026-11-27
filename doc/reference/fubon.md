# Fubon adapter

The `fubon_neo` adapter behind `AccountClient(BrokerType.FUBON)`. Needs the
`fubon` extra. See [Live brokers](../get-started/live-brokers.md#fubon) for
how to connect.

!!! danger
    Fubon has no sandbox: `place_order`, `cancel_order`, `buy_stock` and
    `sell_stock` act on your real account.

::: cjtrade.pkgs.brokers.fubon.fubon_broker_api.FubonBrokerAPI

::: cjtrade.pkgs.brokers.fubon._internal_func
    options:
      members: [to_cj_status, validate_order, to_fubon_order, to_cj_positions, to_cj_snapshot]
