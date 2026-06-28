# CJTrade System

Two mode: `full_simulation` and `oneshot`.

If you want to test it out, see the README in project root.

Basically, we use wrapper script to launch this trading system:

For `full_simulation`, we replay historical market price data in high playback speed and sample the price and aggregate to kbar periodically and simulate the full broker backend for order matching, which is much **more exciting** when doing backtesting. However, higher playback speed may cause time-related inaccuracies and lead to **non-deterministic** and **non-reproducible** backtest result.

```sh
bash poc/backtest_full_simulation.sh
```

For `oneshot`, we gather all kbar data at once before backtest starts, and match the order kbar-by-kbar. It produce much more faster and deterministic backtest result.

```sh
bash poc/backtest.sh
```
