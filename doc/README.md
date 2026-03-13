# Getting Started with CJTrade

CJTrade is a trading framework for Taiwan securities. Write strategies in a simple, Pine Script-like syntax and run them against real or mock brokers.

## Quick Start (Mock Broker)

### 1. Clone and Setup

```bash
git clone https://github.com/jackiesogi/cjtrade
cd cjtrade
uv sync
source .venv/bin/activate  # Linux/macOS
```

### 2. Generate Config

```bash
bash scripts/gen_config.sh mock
```

### 3. Write Your First Strategy

Create `my_strategy.py`:

```python
from cjtrade.pkgs.api.beginner import *

def setup():
    set_current_symbol("2330")

def strategy(kbar):
    ema_12 = ta.ema(kbar.closes, 12)
    ema_26 = ta.ema(kbar.closes, 26)

    if ema_12[-1] > ema_26[-1]:
        return buy(qty=100)
    elif ema_12[-1] < ema_26[-1]:
        return sell(qty=100)

    return None
```

### 4. Backtest

```bash
uv run system --broker=mock
```

---

## Using Real Broker (Sinopac)

### 1. Get API Credentials

Visit: https://ai.sinotrade.com.tw/python/Main/index.aspx

### 2. Generate Config

```bash
bash scripts/gen_config.sh sinopac
```

Edit `sinopac_system.cjconf` and add your credentials:

```
API_KEY=your_api_key
SECRET_KEY=your_secret_key
CA_CERT_PATH=/path/to/cert
CA_PASSWORD=your_cert_password
```

### 3. Backtest

```bash
uv run system --broker=sinopac
```

### 4. Live Trading (Optional)

Set simulation mode before trading:

```bash
export SIMULATION=y  # Paper trading
uv run system --broker=sinopac
```

Remove `SIMULATION` for real trading:

```bash
uv run system --broker=sinopac
```

---

## Interactive Shell

Explore API and market data interactively:

```bash
uv run cjtrade --broker=mock
```

Available commands:
- `buy <symbol> <price> <qty>` - Place buy order
- `sell <symbol> <price> <qty>` - Place sell order
- `ohlcv <symbol>` - Get latest OHLCV
- `lspos` - List positions
- `lsodr` - List orders
- `help` - Show all commands

---

## API Documentation

See [API.md](API.md) for complete Beginner API reference.

### Common Functions

**Trading:**
- `buy(qty, price=None, symbol=None)` - Buy shares
- `sell(qty, price=None, symbol=None)` - Sell shares

**Info:**
- `get_balance()` / `cash()` - Available cash
- `get_positions()` / `positions()` - Current holdings
- `get_current_price(symbol)` / `snapshot_price(symbol)` - Latest price
- `get_kbars(symbol, start, end, interval)` - Historical K-bars

**Technical Analysis:**
- `ta.ema(prices, period)` - Exponential Moving Average
- `ta.sma(prices, period)` - Simple Moving Average
- `ta.bb(prices, period)` - Bollinger Bands
- `ta.rsi(prices, period)` - RSI
- `ta.macd(prices)` - MACD
- `ta.stoch(high, low, close)` - Stochastic

---

## Strategy Structure

### Basic Template

```python
from cjtrade.pkgs.api.beginner import *

def setup():
    """Initialize once at startup"""
    set_current_symbol("2330")

def strategy(kbar):
    """Called for each K-bar"""
    # Your trading logic here
    if some_condition:
        return buy(qty=100)
    return None

def on_position_changed(position):
    """Optional: Called when position changes"""
    pass

def on_system_end():
    """Optional: Called at end of backtest"""
    pass
```

### Full Example

```python
from cjtrade.pkgs.api.beginner import *

def setup():
    set_current_symbol("2330")
    print(f"Starting capital: {equity()}")

def strategy(kbar):
    # Calculate indicators
    ema_short = ta.ema(kbar.closes, 12)
    ema_long = ta.ema(kbar.closes, 26)
    rsi = ta.rsi(kbar.closes, 14)

    # Entry signal
    if ema_short[-1] > ema_long[-1] and rsi[-1] < 30:
        return buy(qty=100)

    # Exit signal
    if ema_short[-1] < ema_long[-1] and rsi[-1] > 70:
        return sell(qty=100)

    return None

def on_position_changed(position):
    print(f"{position.symbol}: {position.quantity} @ {position.current_price}")

def on_system_end():
    print(f"Final equity: {equity()}")
```

---

## Configuration

### Environment Variables

```bash
# Mock broker (no credentials needed)
export BROKER=mock

# Sinopac (requires credentials)
export API_KEY=your_key
export SECRET_KEY=your_secret
export CA_CERT_PATH=/path/to/cert
export CA_PASSWORD=cert_password

# Paper trading (Sinopac only)
export SIMULATION=y

# Watch list
export WATCH_LIST=2330,0050,2454
```

### Config File Format

Create `cjtrade.cjconf`:

```ini
[broker]
type=sinopac

[credentials]
API_KEY=your_key
SECRET_KEY=your_secret
CA_CERT_PATH=/path/to/cert
CA_PASSWORD=password

[trading]
SIMULATION=y
WATCH_LIST=2330,0050
```

---

## Backtest Modes

### Mock Broker
- No real credentials needed
- Fast simulation
- Perfect for development
- Use: `uv run system --broker=mock`

### Realistic Mode
- Uses historical YahooFinance data
- More realistic price movements
- Good for testing
- Use: `uv run system --broker=realistic`

### Sinopac (Real)
- Real broker connection
- Paper trading or live trading
- Use: `uv run system --broker=sinopac`

---

## Understanding Results

After backtesting, you'll see:

```
Initial Balance: 500,000 TWD
Final Equity: 575,000 TWD
Total Return: 15%

Buy Expenditure: 2,500,000 TWD
Sell Income: 2,480,000 TWD
Net Cash Flow: -20,000 TWD

Realized P&L: +45,000 TWD
Unrealized P&L: +30,000 TWD

Total Trades: 42
Win Rate: 65%
```

---

## Common Issues

### "No symbol specified" Error
Set default symbol:
```python
set_current_symbol("2330")
```

Or pass explicitly:
```python
buy(qty=100, symbol="2330")
```

### "Import cjtrade not found"
Ensure you've activated the virtual environment:
```bash
source .venv/bin/activate
```

### Order not placed
Check:
1. Sufficient cash balance
2. Valid symbol
3. Valid quantity
4. Market hours (if using real broker)

---

## Next Steps

1. **Learn the API**: Read [API.md](API.md)
2. **Try Examples**: Check `example_strategy.py`
3. **Backtest**: Develop and test your strategy with mock broker
4. **Live Trade**: Configure Sinopac and trade live
5. **Advanced**: Explore `cjtrade.core` for more control

---

## Support

- Documentation: `/doc`
- Examples: `/ref/example_strategy.py`
- Issues: GitHub Issues
- Tests: `/tests`

---

## Brokers Supported

- **Mock**: For development and testing
- **YahooFinance**: For realistic historical backtesting
- **Sinopac**: For real trading on Taiwan securities

---

## Roadmap

- [ ] Strategy GUI Editor
- [ ] Advanced LLM-based analysis
- [ ] Multi-symbol orchestration
- [ ] Performance profiling tools
- [ ] Cloud deployment support

---

## License

See LICENSE file

---

## Contributing

Contributions welcome! See CONTRIBUTING.md
