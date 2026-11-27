# AccountClient

The one broker API a user sees. The same calls work against ArenaX,
Sinopac and Fubon; the broker is chosen with `BrokerType`. See
[Live brokers](../get-started/live-brokers.md).

!!! danger
    With `BrokerType.SINOPAC` and `simulation=False`, or with
    `BrokerType.FUBON` (which has no sandbox), order methods act on a real
    account.

::: cjtrade.pkgs.brokers.account_client.AccountClient

::: cjtrade.pkgs.brokers.account_client.BrokerType

::: cjtrade.pkgs.brokers.account_client.AccountState
