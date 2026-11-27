# Connect to a broker

In this page you start the pretend broker, ArenaX, and connect to it from
Python. At the end you will have printed your (pretend) account balance.

You need two terminal windows: one runs ArenaX, the other runs your code.

## Step 1: start ArenaX

In the first terminal, inside the `CJTrade` folder:

```sh
uv run arenaxd
```

This starts the ArenaX server in its default `demo` mode. It:

1. picks a trading day 11 to 20 days in the past,
2. downloads that period's 1-minute prices from Yahoo Finance (no account
   needed) and keeps them in the price cache,
3. opens a fresh pretend account with NT$100,000,
4. listens for connections on `127.0.0.1:8801`, your own computer only.

Expected output, after a few seconds (shortened; your dates will differ):

```text
[INFO][...] ArenaX.server: market data: yfinance
[INFO][...] ArenaX.backend.demo: market time: ... mock_current_time=2026-11-13 09:00:00 ... playback_speed=120.0 ...
[INFO][...] ArenaX.server: starting on 127.0.0.1:8801, backend=demo
[INFO][...] ArenaX.backend.state: fresh account
[INFO][...] ArenaX.backend: sim env started
```

`mock_current_time` is ArenaX's simulated "now", and `playback_speed=120.0`
means one real second is two market minutes. Leave this terminal running.

??? question "I see `[ERROR] yfinance: ... possibly delisted; no price data found`"
    Yahoo has no bars for some of the days ArenaX asked about, usually a
    weekend or a holiday. ArenaX carries on with the days it did get. As long
    as you reach `sim env started`, it is fine.

## Step 2: connect from Python

In the second terminal, save this as `hello.py` and run it with
`uv run python hello.py`:

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print("broker:", client.get_broker_name())
print("balance:", client.get_balance())
print("positions:", client.get_positions())
print("market time:", client.get_market_time()["mock_current_time"])

client.disconnect()
```

Line by line:

- `AccountClient(BrokerType.ARENAX, ...)` chooses the broker. The rest of
  your code is the same for every broker. `testkey123` is the key every
  ArenaX server accepts out of the box.
- `connect()` opens the session. Always pair it with `disconnect()`.
- `get_balance()` is your cash, `get_positions()` the shares you hold.
- `get_market_time()` asks ArenaX what time it is in its simulated market.

Expected output:

```text
broker: arenax (8801)
balance: 100000.0
positions: []
market time: 2026-11-13 09:24:43.668600
```

A fresh account has NT$100,000 and no shares. Run it again a few seconds
later and the market time has moved on: the simulated clock keeps running
while ArenaX is up.

!!! note "The account lives as long as the server"
    Disconnecting and connecting again keeps the same balance and positions.
    Restarting `arenaxd` opens a fresh account on a new random day.

??? question "`connect()` fails with `Connection refused`"
    ArenaX is not running, or not yet ready. Check the first terminal shows
    `sim env started`, then try again. See
    [Troubleshooting](troubleshooting.md) for other errors.

## Sinopac (a real broker)

When you are ready for a real account, the only change is how you create the
client. You need the `sinopac` extra and the API key, secret and certificate
from [Sinopac's API portal](https://ai.sinotrade.com.tw/python/Main/index.aspx#pag4):

```python
client = AccountClient(
    BrokerType.SINOPAC,
    api_key="...", secret_key="...",
    ca_path="/path/to/Sinopac.pfx", ca_passwd="...",
    simulation=True,      # Sinopac's sandbox: orders are not real
)
client.connect()
```

!!! danger "`simulation=False` is your real account"
    With `simulation=False` every order is a real order with real money.
    Keep `simulation=True` until your code has run correctly on ArenaX and
    on the sandbox.

Rather than writing secrets in code, put them in a settings file; see
[Configuration and paths](../reference/config.md).

Next: [Account and orders](account-and-orders.md).
