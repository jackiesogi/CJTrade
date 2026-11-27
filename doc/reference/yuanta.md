# Yuanta adapter

The Spark API adapter behind `AccountClient(BrokerType.YUANTA)`. Needs the
`yuanta` extra, .NET 8 and Yuanta's Spark API files. See
[Live brokers](../get-started/live-brokers.md#yuanta) for how to connect.

!!! warning "Testing in progress: use at your own risk"
    Not yet run against a Yuanta account. With `environment="PROD"`,
    `place_order`, `cancel_order`, `buy_stock` and `sell_stock` act on your
    real account.

::: cjtrade.pkgs.brokers.yuanta.yuanta_broker_api.YuantaBrokerAPI

::: cjtrade.pkgs.brokers.yuanta._internal_func
    options:
      members: [to_cj_status, to_cj_status_from_report, validate_order, fill_stock_order, to_cj_positions, to_cj_snapshot]
