# 載入策略檔

用 authoring 模組寫的檔案如何被檢查、載入和執行。

!!! danger
    `load()` 和 `collect_params()` 會用完整的 builtins 執行檔案。只載入你信任的檔案。

::: cjtrade.pkgs.strategy.user_strategy
