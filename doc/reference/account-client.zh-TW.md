# AccountClient

使用者唯一需要面對的券商 API。同一組呼叫可以用在 ArenaX 和永豐，用 `BrokerType` 選擇券商。

!!! danger
    使用 `BrokerType.SINOPAC` 且 `simulation=False` 時，下單相關的方法會作用在真實帳戶上。

::: cjtrade.pkgs.brokers.account_client.AccountClient

::: cjtrade.pkgs.brokers.account_client.BrokerType

::: cjtrade.pkgs.brokers.account_client.AccountState
