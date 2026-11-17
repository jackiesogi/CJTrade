# Sinopac adapter

The `shioaji` adapter behind `AccountClient(BrokerType.SINOPAC)`. Needs the
`sinopac` extra.

!!! danger "Real orders"
    Unless `simulation=True`, `place_order`, `cancel_order`, `buy_stock` and
    `sell_stock` act on your real account.

::: cjtrade.pkgs.brokers.sinopac.sinopac_broker_api.SinopacBrokerAPI
