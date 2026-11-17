# AccountClient

The one broker API a user sees. The same calls work against ArenaX and
Sinopac; the broker is chosen with `BrokerType`.

!!! danger
    With `BrokerType.SINOPAC` and `simulation=False`, order methods act on a
    real account.

::: cjtrade.pkgs.brokers.account_client.AccountClient

::: cjtrade.pkgs.brokers.account_client.BrokerType

::: cjtrade.pkgs.brokers.account_client.AccountState
