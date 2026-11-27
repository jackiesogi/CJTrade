# 元大轉接層

`AccountClient(BrokerType.YUANTA)` 背後的 Spark API 轉接層。需要 `yuanta` 選用套件、.NET 8 以及元大的 Spark API 檔案。連線方式見[實盤券商](../get-started/live-brokers.md#yuanta)。

!!! warning "測試中（testing in progress），使用風險請自行承擔"
    尚未在元大帳戶上執行過。設定 `environment="PROD"` 時，`place_order`、`cancel_order`、`buy_stock` 和 `sell_stock` 會作用在你的正式帳戶上。

::: cjtrade.pkgs.brokers.yuanta.yuanta_broker_api.YuantaBrokerAPI

::: cjtrade.pkgs.brokers.yuanta._internal_func
    options:
      members: [to_cj_status, to_cj_status_from_report, validate_order, fill_stock_order, to_cj_positions, to_cj_snapshot]
