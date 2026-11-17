# 永豐金轉接層

`AccountClient(BrokerType.SINOPAC)` 背後的 `shioaji` 轉接層，需要安裝 `sinopac` extra。

!!! danger "真實委託"
    除非 `simulation=True`，否則 `place_order`、`cancel_order`、`buy_stock` 和 `sell_stock` 都會作用在你的真實帳戶上。

::: cjtrade.pkgs.brokers.sinopac.sinopac_broker_api.SinopacBrokerAPI
