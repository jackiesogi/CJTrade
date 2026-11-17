# Built-in strategies

Class-based strategies for the oneshot backtester and the engine's bots.
Parameters are passed as `params={"<prefix>__<name>": value}`.

!!! warning
    Window parameters are counted in bars, so the same value means a
    different strategy on 1m and on 1d bars. See
    [Strategy parameters](strategy-parameters.md) for the presets per
    interval.

::: cjtrade.pkgs.strategy.bb

::: cjtrade.pkgs.strategy.adx

::: cjtrade.pkgs.strategy.dca

::: cjtrade.pkgs.strategy.donchian

::: cjtrade.pkgs.strategy.snr

::: cjtrade.pkgs.strategy.baseline_0050
