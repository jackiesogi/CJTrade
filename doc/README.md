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

1. Create `src/cjtrade/test_ema.py`:

```sh
touch src/cjtrade/test_ema.py
```

2. Write your custom strategy:

```python
from cjtrade.pkgs.api.beginner import *

# Custom strategy using EMA(Exponential Moving Average) crossover
def strategy(kbar):
    ema_12 = ta.ema(kbar.closes, 12)
    ema_26 = ta.ema(kbar.closes, 26)

    if ema_12[-1] > ema_26[-1]:
        return "BUY"
    elif ema_12[-1] < ema_26[-1]:
        return "SELL"

    return "HOLD"

if __name__ == "__main__":
    # Get historical K-bar data from 2026-01-01 to 2026-03-01 for TSMC (2330)
    kbar_data = get_kbar_series("2330", start="2026-01-01", end="2026-03-01")

    # Generate one-time signal
    signal = strategy(kbar_data)

    # Print the signal for the last K-bar
    print(f"symbol={kbar_data.symbol} close={kbar_data.close:.2f} signal={signal}")

    # You can also do the real order placing if you have a real client set up
    if signal == "BUY":
        set_current_symbol("2330")  # set global symbol
        buy(qty=100)                # shares
```

Buy default, beginner api will only set up a mock account for you,
so you don't need to worry about money loss.

3. Run the program

```sh
uv run python src/cjtrade/test_ema.py
```

and you'll see something like:
```sh
symbol=2330 close=1995.00 signal=BUY
```


:warning: Beginner API is under active development and this doc might be out-of-date at anytime! If you want to use stable API, please directly refer to the source code in `src/cjtrade/pkgs` for all packages used to develop CJTrade, or refer to `src/cjtrade/apps` to see how the apps call this packages.
