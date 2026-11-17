# 設定與路徑

設定從哪裡讀取，以及使用者資料寫到哪裡。

!!! warning
    `load_supported_config_files()` 會寫入整個 process 的 `os.environ`（先載入的來源優先），`paths` 的函式第一次被呼叫時會建立目錄。

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
