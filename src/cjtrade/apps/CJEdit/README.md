# CJEdit

> A simple editing tool for quick strategy testing.

```sh
uv run python src/cjtrade/apps/CJEdit/main.py
```

It asks which app and broker you are writing against, writes the matching
imports into a scratch file for you, and opens an editor on it in the browser.
When you are done it prints the command that runs what you wrote, so the file
outlives the session and can be kept if it turns out to be worth keeping.

Intended for trying an idea out in a couple of minutes. A strategy you mean to
backtest belongs in a file written against
`cjtrade.pkgs.strategy.authoring`, which the trading engine can run directly.

![cjedit_1](./img/cjedit_1.png)

![cjedit_2](./img/cjedit_2.png)
