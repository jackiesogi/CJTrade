# ArenaX 用戶端

`ArenaXBrokerAPI_v2` 是 `AccountClient` 背後的 ArenaX 轉接層。`ArenaXMiddleWare` 是它底下的 HTTP client，也可以從 `client.control_plane` 取得；回放程式就是透過它移動模擬時鐘。

!!! warning
    每個方法都會對 ArenaX 伺服器發 HTTP 請求。連線錯誤會以 `None` 或空 list 回傳，不會丟出例外。

::: cjtrade.pkgs.brokers.arenax.arenax_broker_api

::: cjtrade.pkgs.brokers.arenax.arenax_middleware
