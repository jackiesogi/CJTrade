# 技術指標

`ta`（`TALibWrapper` 的實例）包裝 TA-Lib。每個方法吃 NumPy 陣列、回傳等長的陣列，窗口湊滿之前是 `NaN`。authoring 模組有自己的 `ta`，只回傳最新一個值。

::: cjtrade.pkgs.analytics.technical.talib_wrapper
