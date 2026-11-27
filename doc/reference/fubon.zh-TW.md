# 富邦轉接層

`AccountClient(BrokerType.FUBON)` 背後的 `fubon_neo` 轉接層。需要安裝 `fubon` 選用套件。連線方式見[實盤券商](../get-started/live-brokers.md#fubon)。

!!! danger
    Fubon 沒有沙盒：`place_order`、`cancel_order`、`buy_stock` 和 `sell_stock` 會作用在你的正式帳戶上。

::: cjtrade.pkgs.brokers.fubon.fubon_broker_api.FubonBrokerAPI

::: cjtrade.pkgs.brokers.fubon._internal_func
    options:
      members: [to_cj_status, validate_order, to_fubon_order, to_cj_positions, to_cj_snapshot]
