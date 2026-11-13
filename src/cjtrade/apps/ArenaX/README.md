# ArenaX (試煉場 券商模擬器)

![](img/arenax.png)

## Introduction

ArenaX is a simulated broker written for CJTrade.
It is a complete trading environment that behaves the way a real broker does, so
a client application cannot tell it apart from a paper trading service — the
same `AccountClient` code talks to both.

ArenaX provides:

- **Market data**
  Prices come from either a real broker API or yfinance, and are cached locally
  so a repeated run does not refetch them.

- **Price data playback**
  Time in the virtual market is under your control. You set where the timeline
  begins, how fast it advances, and you can pause it or step it yourself.

- **Order submission and matching**
  Orders are matched against the incoming market data, with commission, 證交稅
  and slippage applied, and with each order's time-in-force (ROD / IOC / FOK /
  GTC) deciding when it expires.

- **Portfolio management**
  Accounts, positions, balance and trade history are all tracked inside the
  simulation, and a run can be resumed from a saved account snapshot.

Together this lets you test strategies and client applications without
connecting to a real broker or risking real money.

## Modes

> :memo: Most of the **data** in this doc refers to **price data**.

There are 3 modes in ArenaX, categorised by their price data source and use
case. Each one ships its own `configs/<mode>.cjsys` and listens on its own port,
so two modes can run side by side without fighting over one.

| Mode | Price Data Source | Default port | Typical Use Case |
| ---- | ----------------- | ------------ | ---------------- |
| `demo` (default) | `yfinance` | 8801 | Lightweight simulation **WITHOUT** needing a broker account |
| `backtest` | Custom broker API | 8802 | Historical market replay for backtesting |
| `paper` | Custom broker API | 8803 | Paper trading with real-time market data |

```sh
uv run arenaxd --backend=backtest        # or demo / paper / real
```

:warning: `arenaxd` reads `AX_*` environment variables before its config file,
and `load_dotenv(override=False)` means whatever is already exported wins. A
stale `AX_HOST_PORT` from an earlier session will therefore silently keep the
backtest backend on the demo port. `unset AX_HOST_PORT AX_HOST_ADDRESS
AX_LAUNCH_MODE AX_STATE_FILE` before switching modes.

Starting the server and starting the simulated backend are two steps. The
process comes up first and then logs in and preloads price data, which takes
somewhere between a few seconds and a minute depending on the window. Until
that finishes, `/health` answers `"running": false` — poll it rather than
guessing with `sleep`.

## Test with the server admin shell

### Start the server first!

```sh
uv run arenaxd
```

![server](./img/server.png)

### Then open the admin shell

```sh
uv run aresh  # stands for "ARE"nax "SH"ell
```

![admin-shell](./img/admin_shell.png)

## RESTful API

Everything below assumes the default demo port. Change `8801` to match your
mode.

### Server and backend

1. Check health — also the readiness probe:
```sh
curl http://127.0.0.1:8801/health
```

2. Start the simulated backend:
```sh
curl -X PUT -H "Content-Type: application/json" \
  -d '{"running": true}' http://127.0.0.1:8801/api/v1/backend
```

3. Stop it again (the server process stays up):
```sh
curl -X PUT -H "Content-Type: application/json" \
  -d '{"running": false}' http://127.0.0.1:8801/api/v1/backend
```

4. Read the configuration the server and the backend are actually running with:
```sh
curl http://127.0.0.1:8801/api/v1/config
```

> `server_config` is the broker-side server's own config — listening address and
> port. `backend_config` is the core logic it runs: playback speed, backtest
> duration, cost model.

### Clock

5. Read the current market time:
```sh
curl http://127.0.0.1:8801/api/v1/clock
```

6. Set where the timeline BEGINS. This is not "jump to this moment": it snaps to
09:00, and unless told otherwise it also starts the clock and refetches the data
cache.
```sh
curl -X PUT -H "Content-Type: application/json" \
  -d '{"mock_init_time": "2026-03-20T00:00:00"}' \
  http://127.0.0.1:8801/api/v1/clock/origin
```

### Trading

A client opens a session first (`POST /api/v1/session`), and then uses:

| Route | Purpose |
| ----- | ------- |
| `GET /api/v1/account` | Balance and positions |
| `GET /api/v1/account/fills` | Fill history, filterable by session |
| `GET /api/v1/orders` | Everything resting or resolved |
| `POST /api/v1/orders` | Place one order |
| `GET /api/v1/orders/<id>` | One order's status |
| `DELETE /api/v1/orders/<id>` | Cancel it |
| `GET /api/v1/market/<symbol>/snapshot` | A quote: price, bid/ask, the day's range so far |
| `GET /api/v1/market/<symbol>/kbars` | Historical K-bars over a date range |
| `GET /api/v1/market/data-availability` | Which symbols and windows are actually on disk |

The full interactive spec is served by the process itself — open
`http://127.0.0.1:8801/docs` while it is running.

### Useful test scripts

1. Watch how fast time progresses inside the ArenaX virtual environment:
```sh
watch -n 3 -d --color "curl -s http://127.0.0.1:8801/api/v1/clock | jq ."
```

2. Print the backend and server config as it changes:
```sh
watch -n 3 -d --color "curl -s http://127.0.0.1:8801/api/v1/config | jq ."
```

## Development

### Current architecture
![architecture](./img/arch.png)
