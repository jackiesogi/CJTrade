# ArenaX client

`ArenaXBrokerAPI_v2` is the ArenaX adapter behind `AccountClient`.
`ArenaXMiddleWare` is the HTTP client underneath it, also reachable as
`client.control_plane`; it is how a replay driver moves the simulated clock.

!!! warning
    Every method makes an HTTP call to the ArenaX server. Transport errors
    come back as `None` or an empty list rather than an exception.

::: cjtrade.pkgs.brokers.arenax.arenax_broker_api

::: cjtrade.pkgs.brokers.arenax.arenax_middleware
