# 表單

`FormEngine` 依 TOML 檔的定義，透過終端機、zenity 或本機網頁詢問問題，並記住答案。

!!! warning
    web renderer 會在 `127.0.0.1` 啟動 HTTP 伺服器並開啟瀏覽器；答案存在 `paths.form_state_dir()` 底下。

::: cjtrade.pkgs.ui.engine

::: cjtrade.pkgs.ui.schema
