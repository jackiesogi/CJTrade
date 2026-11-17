# Connect to a broker

Everything in CJTrade goes through one object, `AccountClient`. You choose a
broker when you create it, and the rest of your code stays the same.

## ArenaX (simulated broker)

ArenaX is a simulated broker that comes with CJTrade, so you can try
everything without a brokerage account and without risking money.

**1. Start it** in its own terminal and leave it running:

```sh
uv run arenaxd
```

**2. Connect** to it from Python:

```python
from cjtrade.pkgs.brokers.account_client import AccountClient, BrokerType

client = AccountClient(BrokerType.ARENAX, api_key="testkey123")
client.connect()

print(client.get_broker_name(), client.get_balance())

client.disconnect()
```

That is all. If `connect()` fails, wait a few seconds and try again: ArenaX
loads price data before it accepts connections.

!!! note
    ArenaX replays real prices on its own fast-moving clock, so prices are
    different every time you start it.

## Sinopac (永豐金證券)

Install the `sinopac` extra, then pass your credentials:

```python
client = AccountClient(
    BrokerType.SINOPAC,
    api_key="...", secret_key="...",
    ca_path="/path/to/Sinopac.pfx", ca_passwd="...",
    simulation=True,      # Sinopac's sandbox
)
client.connect()
```

!!! danger "`simulation=False` is your real account"
    Every order you place is a real order. Try your code on ArenaX first.

Next: [Account and orders](account-and-orders.md).
