# 內建策略

給 oneshot 回測和 engine 的 bot 使用的 class 型策略。參數用 `params={"<前綴>__<名稱>": 值}` 傳入。

!!! warning
    窗口類參數以 K 棒數計算，所以同一個值在 1m 和 1d 上是不同的策略。各 interval 的預設值見[策略參數](strategy-parameters.md)。

::: cjtrade.pkgs.strategy.bb

::: cjtrade.pkgs.strategy.adx

::: cjtrade.pkgs.strategy.dca

::: cjtrade.pkgs.strategy.donchian

::: cjtrade.pkgs.strategy.snr

::: cjtrade.pkgs.strategy.baseline_0050
