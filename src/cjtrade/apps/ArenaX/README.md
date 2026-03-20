# ArenaX (試煉場 券商模擬器)

![](img/arenax.png)

## Introduction

ArenaX is a simulated broker designed for CJTrade.
It provides a fully functional trading environment that mimics the behavior of a real broker, allowing client applications to interact with it as if they were connected to a live trading service.

ArenaX supports:

- **Market data streaming**
Price data can be obtained from either a custom broker API or yfinance.

- **Price data playback**
The progression of time in the virtual market can be controlled by the user, enabling accelerated or slowed-down playback for testing purposes.

- **Order submission and matching**
Orders submitted by the client are processed by ArenaX, which simulates order execution based on the incoming market data.

- **Portfolio management**
Users can create accounts and track positions, balances, and trade history within the simulated environment.

These capabilities allow developers and traders to test trading strategies and client applications without connecting to a real broker or risking real capital.

## Modes

>:memo: Most of the **data** in this doc refers to **price data**.

There are 3 modes in ArenaX, they are categorized by their "price data source" and "use case".

| Mode   | Price Data Source | Typical Use Case                                          |
| ------ | ----------------- | --------------------------------------------------------- |
| `live` | Custom broker API | Paper trading with real-time market data                  |
| `hist` | Custom broker API | Historical market replay for backtesting                  |
| `none` (default) | `yfinance`        | Lightweight simulation **WITHOUT** needing a broker account |


## Restful API

1. Check health:
```sh
curl http://127.0.0.1:8801/health
```

2. Start the server:
```sh
curl -X POST http://127.0.0.1:8801/control/start
```

3. Stop the server:
```sh
curl -X POST http://127.0.0.1:8801/control/stop
```

4. Get system time:
```sh
curl -X POST http://127.0.0.1:8801/control/get-time
```

5. Set system time
```sh
curl -X POST -H "Content-Type: application/json" -d '{"anchor_time": "2026-03-20T12:00:00", "days_back": 5}' http://127.0.0.1:8801/control/set-time
```

### Useful test script
1. Watch how fast time progress in ArenaX virtual enviroment
```sh
watch -n 3 -d --color "curl -s -X POST http://127.0.0.1:8801/control/get-time | jq ."
```

2. Print backend config and server config in real time
```sh
watch -n 3 -d --color "curl -s -X POST http://127.0.0.1:8801/control/get-config | jq ."
```

> Note that `server_config` refers to the ArenaX broker-side server config i.e. listening address / port, and `backend_config` refers to the core logic that this broker-side server runs i.e. playback speed, backtest duration.
