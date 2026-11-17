# Forms

`FormEngine` asks the questions declared in a TOML file, through a terminal,
zenity or a local web page, and remembers the answers.

!!! warning
    The web renderer starts an HTTP server on `127.0.0.1` and opens a
    browser; answers are saved under `paths.form_state_dir()`.

::: cjtrade.pkgs.ui.engine

::: cjtrade.pkgs.ui.schema
