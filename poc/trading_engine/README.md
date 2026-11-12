Run:
```sh
old="$(lsof -i :8802 | grep -i python | awk '{print $2}')"
if [ -n "$old" ]; then
    printf 'existing: %s\n' "$old"
    echo "$old" | xargs kill -9 2>/dev/null
else
    echo "No existing server"
fi

AX_BACKTEST_PLAYBACK_SPEED=60.0 uv run arenaxd --backend=backtest > /dev/null 2>&1 &
pid=$!

sleep 15

uv run python poc/trading_engine/main2.py

if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
fi
```
