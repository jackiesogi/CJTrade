Run:
```sh
AX_BACKTEST_PLAYBACK_SPEED=60.0 uv run arenaxd --backend=backtest > /dev/null 2>&1 &
pid=$!
sleep 15
uv run python poc/trading_engine/main.py
kill $pid
```
