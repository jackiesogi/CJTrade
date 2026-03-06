## CJTrade Beginner API Reference

### Overview

The Beginner API provides a Pine Script-like interface for writing trading strategies. All functions are available in the `cjtrade.api.beginner` namespace.

```python
from cjtrade.api.beginner import *
```

---

## Context Management

### `set_client(client: AccountClient) -> None`

Manually set the global broker client instance.

**Parameters:**
- `client`: An AccountClient instance

**Example:**
```python
from cjtrade import AccountClient, BrokerType
from cjtrade.api.beginner import set_client

client = AccountClient(BrokerType.SINOPAC)
set_client(client)
```

---

### `set_current_symbol(symbol: str) -> None`

Set the default trading symbol for buy/sell operations.

**Parameters:**
- `symbol`: Stock symbol (e.g., "2330", "0050")

**Example:**
```python
set_current_symbol("2330")
buy(qty=100)  # Buys 100 shares of 2330
```

---

### `get_current_symbol() -> Optional[str]`

Get the currently set default symbol.

**Returns:** Current symbol or None if not set

---

### `create_client(broker_type: BrokerType = BrokerType.SINOPAC, simulation: bool = False) -> AccountClient`

Create and connect a broker client with environment configuration.

**Parameters:**
- `broker_type`: Broker type (default: SINOPAC)
- `simulation`: Use mock broker if True (default: False)

**Returns:** Connected AccountClient instance

**Requires environment variables:**
- `API_KEY`, `SECRET_KEY`, `CA_CERT_PATH`, `CA_PASSWORD` (for real brokers)

**Example:**
```python
client = create_client(simulation=True)  # Use mock broker
```

---

## Trading Operations

### `buy(qty: int, price: Optional[float] = None, symbol: Optional[str] = None, intraday_odd: bool = True) -> Optional[Order]`

Place a buy order.

**Parameters:**
- `qty`: Quantity to buy
- `price`: Order price (0 or None for market price)
- `symbol`: Stock symbol (uses current symbol if not specified)
- `intraday_odd`: Allow intraday odd lots (default: True)

**Returns:** Order object or None if failed

**Example:**
```python
buy(qty=100)  # Buy 100 shares at market price
buy(qty=50, price=150.5)  # Buy 50 shares at 150.5
```

---

### `sell(qty: int, price: Optional[float] = None, symbol: Optional[str] = None, intraday_odd: bool = True) -> Optional[Order]`

Place a sell order.

**Parameters:**
- `qty`: Quantity to sell
- `price`: Order price (0 or None for market price)
- `symbol`: Stock symbol (uses current symbol if not specified)
- `intraday_odd`: Allow intraday odd lots (default: True)

**Returns:** Order object or None if failed

**Example:**
```python
sell(qty=50)
sell(qty=100, price=152.0, symbol="2330")
```

---

## Information Queries

### `get_current_price(symbol: Optional[str] = None) -> Optional[float]`

Get the latest price for a symbol.

**Parameters:**
- `symbol`: Stock symbol (uses current symbol if not specified)

**Returns:** Current price or None if failed

**Example:**
```python
price = get_current_price("2330")
```

---

### `get_positions() -> List[Position]`

Get all current positions.

**Returns:** List of Position objects

**Position attributes:**
- `symbol`: Stock symbol
- `quantity`: Current quantity
- `avg_cost`: Average purchase cost
- `current_price`: Latest price
- `market_value`: Total position value
- `pnl`: Profit/loss

**Example:**
```python
positions = get_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.quantity} shares @ {pos.current_price}")
```

---

### `get_balance() -> float`

Get available cash balance.

**Returns:** Cash balance in TWD

**Example:**
```python
cash = get_balance()
print(f"Available cash: {cash}")
```

---

### `get_total_equity() -> float`

Get total equity (cash + position values).

**Returns:** Total equity in TWD

**Example:**
```python
equity = get_total_equity()
```

---

### `get_kbars(symbol: str, start: str, end: str, interval: str = "1m") -> Optional[List[Kbar]]`

Get K-bar data for a symbol.

**Parameters:**
- `symbol`: Stock symbol
- `start`: Start date (YYYY-MM-DD)
- `end`: End date (YYYY-MM-DD)
- `interval`: Time interval (1m, 5m, 15m, 1h, 1D, etc.)

**Returns:** List of Kbar objects or None if failed

**Kbar attributes:**
- `symbol`: Stock symbol
- `date`: Date/time
- `open`: Opening price
- `high`: Highest price
- `low`: Lowest price
- `close`: Closing price
- `volume`: Trading volume
- `closes`: Array of closing prices (for indicators)

**Example:**
```python
kbars = get_kbars("2330", "2025-01-01", "2025-01-31", "1D")
for kbar in kbars:
    print(f"{kbar.date}: {kbar.close}")
```

---

## Technical Analysis

### `ta` namespace

Access technical indicators via the `ta` object.

**Available methods:**
- `ta.ema(prices: List[float], period: int) -> List[float]` - Exponential Moving Average
- `ta.sma(prices: List[float], period: int) -> List[float]` - Simple Moving Average
- `ta.bb(prices: List[float], period: int) -> Tuple[List, List, List]` - Bollinger Bands (upper, middle, lower)
- `ta.rsi(prices: List[float], period: int) -> List[float]` - Relative Strength Index
- `ta.macd(prices: List[float], ...) -> Tuple[List, List, List]` - MACD (macd, signal, histogram)
- `ta.stoch(high: List, low: List, close: List, ...) -> Tuple[List, List]` - Stochastic (%K, %D)
- `ta.atr(high: List, low: List, close: List, period: int) -> List[float]` - Average True Range
- `ta.adx(high: List, low: List, close: List, period: int) -> List[float]` - Average Directional Index

**Example:**
```python
ema_12 = ta.ema(kbar.closes, 12)
ema_26 = ta.ema(kbar.closes, 26)
rsi = ta.rsi(kbar.closes, 14)

if kbar.close > ema_12[-1]:
    buy(qty=100)
```

---

## Aliases

Short aliases for common functions:

| Long Name | Alias |
|-----------|-------|
| `buy()` | `buy_order()` |
| `sell()` | `sell_order()` |
| `get_balance()` | `cash()` |
| `get_total_equity()` | `equity()` |
| `get_positions()` | `positions()` |
| `get_kbars()` | `kbars()` |
| `get_current_price()` | `snapshot_price()` |

**Example:**
```python
from cjtrade.api.beginner import *

print(f"Cash: {cash()}, Equity: {equity()}")
pos = positions()
```

---

## Core Models

### `Order`
Represents a trading order.

**Attributes:**
- `order_id`: Unique order ID
- `symbol`: Stock symbol
- `action`: BUY or SELL
- `quantity`: Order quantity
- `price`: Order price
- `status`: Order status (PENDING, FILLED, CANCELLED, etc.)

---

### `OrderType`
Enum for order types: BUY, SELL

---

### `Product`
Represents a tradeable security.

**Constructor:**
```python
product = Product(symbol="2330")
```

---

### `Position`
Represents a current holding.

**Key attributes:**
- `symbol`: Stock symbol
- `quantity`: Current quantity
- `avg_cost`: Average purchase cost
- `current_price`: Latest price
- `market_value`: Total position value

---

### `Kbar`
Represents OHLCV bar data.

**Key attributes:**
- `symbol`: Stock symbol
- `date`: Timestamp
- `open`, `high`, `low`, `close`: Price data
- `volume`: Trading volume
- `closes`: Array of closing prices for indicator calculation

---

## Strategy Template

```python
from cjtrade.api.beginner import *

# Optional: Initialize once at start
def setup():
    set_current_symbol("2330")
    print("Strategy initialized")

# Main strategy logic (called for each K-bar)
def strategy(kbar):
    ema_short = ta.ema(kbar.closes, 12)
    ema_long = ta.ema(kbar.closes, 26)
    rsi = ta.rsi(kbar.closes, 14)

    if ema_short[-1] > ema_long[-1] and rsi[-1] < 30:
        return buy(qty=100)

    elif ema_short[-1] < ema_long[-1] and rsi[-1] > 70:
        return sell(qty=100)

    return None

# Optional: Called when position changes
def on_position_changed(position):
    print(f"Position: {position.symbol} {position.quantity}")

# Optional: Called at end
def on_system_end():
    print(f"Final equity: {equity()}")
```

---

## Error Handling

All functions return None or raise exceptions on error. Check for None:

```python
price = get_current_price("2330")
if price is None:
    print("Failed to get price")
else:
    print(f"Current price: {price}")
```

For exceptions, wrap in try-except:

```python
try:
    order = buy(qty=100)
except ValueError as e:
    print(f"Order failed: {e}")
```
