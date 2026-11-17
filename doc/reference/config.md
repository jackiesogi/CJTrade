# Configuration and paths

Where settings are read from and where user data is written.

!!! warning
    `load_supported_config_files()` writes into `os.environ` for the whole
    process (first source wins), and the `paths` helpers create directories
    the first time they are asked.

::: cjtrade.pkgs.config.config_loader

::: cjtrade.pkgs.paths
