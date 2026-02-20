## Design order filling callback mechanism

Think of cjtrade shell usage.

Will need callback (notification) when:
1. Order filled.
2. Price subscription.

### Mock Env
Potential issue:
1. If mock env is with playback speed 120x, how to ensure the fill match in real time? -> Maybe refer to the lazy fill method, but instead, checking from last check(or last second) to current datetime
2. How to design the real-time callback mechanism to a single loop program when all of the other function and object does not have an independent life?

### Sinopac
1. register a callback to the provided method and wrap it with `register_price_callback()` / `register_fill_callback()`
2. `register_price_callback()` may be used to get streaming market data (set period) or set price alert (set fixed price).
3. In streaming data scenario, maybe we put each tick / each minute data into a shared buffer and then do aggregation later.
4. In real-time technical analysis scenario, we also need to put the analytics method at the end of the handler? (But it is always better to avoid calculation in the handler)

#### On tick callback
```python
from shioaji import QuoteSTKv1, TickSTKv1, Exchange

tick_data_queue = []

def my_tick_cb(exchange: Exchange, tick:TickSTKv1):
    print(f"Exchange: {exchange}, Tick: {tick}")
    price_buf.push(tick)

# Register the tick callback using shioaji
api.quote.set_on_tick_stk_v1_callback(my_tick_cb)   # On tick
```

#### On quote callback
```python
from shioaji import QuoteSTKv1, TickSTKv1, Exchange

quote_data_queue = []

def my_quote_cb(exchange: Exchange, quote:QuoteSTKv1):
    print(f"Exchange: {exchange}, Quote: {quote}")
    price_buf.push(quote)

# Register the quote callback using shioaji
api.quote.set_on_quote_stk_v1_callback(my_quote_cb)  # On quote
```