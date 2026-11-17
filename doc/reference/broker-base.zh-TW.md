# 券商介面

`BrokerAPIBase` 是每個券商轉接層都要實作的介面。只有要新增券商時才需要它，其他情況一律透過 `AccountClient`。

::: cjtrade.pkgs.brokers.base_broker_api
