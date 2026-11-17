# Order Callback Test Plan (Sinopac / CJTrade `AccountClient`)

> **Goal**: Cover every callback-related code path in `SinopacBrokerAPI` and
> `AccountClient` while spending the **absolute minimum real money**.
>
> **Constraint**: Sinopac does not fire order callbacks in simulation mode and
> has no replay/sandbox.  Every scenario therefore requires a real order during
> market hours (09:00 – 13:30 TWN).
>
> **Cost strategy**: Use `IntraDayOdd` (零股盤中) lots.  A single odd-lot share
> of a cheap liquid stock (e.g. 2890 永豐金, ~31 TWD/share) costs ≈ 31 TWD
> plus a negligible commission.  By using odd lots we can test all transitions
> with as few as **3 order placements** (≈ 93 TWD total, mostly recoverable by
> actually being filled and then selling).

---

## Layer Map – what is being tested

```
AccountClient.register_order_callback()
    └─► SinopacBrokerAPI.register_order_callback()
            └─► SinopacBrokerAPI._setup_shioaji_order_callback()
                    └─► shioaji_order_status_callback(stat, msg)
                            ├─ OrderState path  (Submit / Update / Cancel)
                            └─ StockDeal path   (Fill)
                                    └─► OrderEvent  →  user callback(event)
```

Key properties verified per scenario:

| Property | Field |
|---|---|
| Callback is invoked at all | `on_order_change` called |
| `event.order_id` maps to correct CJ order | DB lookup |
| `event.old_status` / `event.new_status` | status transition |
| `event.action` | BUY / SELL |
| `event.symbol` | contract code |
| `event.quantity` / `event.price` | order parameters |
| `event.filled_quantity` / `event.filled_price` | fill data |
| `event.is_filled()` / `event.is_completely_filled()` | helpers |
| `event.is_cancelled()` / `event.is_rejected()` | helpers |
| DB status is updated after callback | `get_cj_order_id_from_db` |

---

## Pre-conditions (run once before any scenario)

1. Market is **open** (09:00 – 13:30 Mon–Fri, not a holiday).
2. `system.cjconf` is populated with valid `API_KEY`, `SECRET_KEY`,
   `CA_CERT_PATH`, `CA_PASSWORD`.
3. CA is activated (`sinopac_broker_api.connect()` succeeds).
4. Account has at least **500 TWD** of buying power (enough for 3 odd-lot
   orders of 2890 at ~31 TWD each plus fees).
5. For the SELL scenarios, account holds at least **1 odd-lot share of 2890**
   (can be acquired via TC-01 or bought beforehand).

---

## Scenario Table

| ID | Trigger mechanism | Callback `stat` | Expected `new_status` | Real cost |
|---|---|---|---|---|
| TC-01 | Place order far below market | `OrderState.StockOrder` (Submit) | `SUBMITTED` / `COMMITTED_WAIT_MATCHING` | ~31 TWD (refundable – cancelled in TC-02) |
| TC-02 | Cancel order via `client.cancel_order()` | `OrderState.StockOrder` (Cancel) | `CANCELLED` | 0 (order from TC-01 not filled) |
| TC-03 | Quantity update via external tool | `OrderState.StockOrder` (Update) | current status unchanged, qty reduced | 0 |
| TC-04 | Place BUY order at/above ask price to force fill | `OrderState.StockDeal` | `FILLED` | ~31 TWD (you own the share) |
| TC-05 | Place SELL order to unwind TC-04 position | `OrderState.StockDeal` | `FILLED` | ~31 TWD (recovered from TC-04) |
| TC-06 | Register a second callback; trigger cancel | any | both callbacks invoked | reuse TC-02 order |

---

## Detailed Steps

### TC-01 – Order Placement (SUBMIT callback)

**Purpose**: Verify that `_setup_shioaji_order_callback` correctly handles the
`OrderState.StockOrder` path for a freshly placed order, and that
`event.order_id` is correctly resolved from the DB.

**Setup script** (adapt `sinopac_broker_api.py` `__main__` block):

```python
client.register_order_callback(on_order_change)

order = Order(
    product=Product(symbol="2890", exchange=Exchange.TSE),
    action=OrderAction.BUY,
    price=1.0,           # Far below market → will NOT fill immediately
    quantity=1,
    order_lot=OrderLot.IntraDayOdd,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD
)
result = client.place_order(order)
# Keep alive for ≥ 5 seconds to receive callback
```

**Expected callback sequence**:

```
OrderEvent {
    event_type  = ORDER_STATUS_CHANGE
    old_status  = PLACED
    new_status  = SUBMITTED  (or COMMITTED_WAIT_MATCHING)
    action      = BUY
    symbol      = "2890"
    quantity    = 1
    price       = 1.0
    filled_qty  = 0
}
```

**Pass criteria**:
- [ ] `on_order_change` is called at least once within 10 s.
- [ ] `event.order_id` matches the CJ order ID returned by `place_order()`.
- [ ] `event.new_status != PLACED` (broker acknowledged the order).
- [ ] `event.filled_quantity == 0`.
- [ ] DB row for the order has been updated (verify with `client.list_orders()`).

---

### TC-02 – Cancel via `AccountClient.cancel_order()` (CANCEL callback)

**Purpose**: Verify `msg['operation']['op_type'] == 'Cancel'` path and that
`event.is_cancelled()` returns `True`.

**Prerequisite**: TC-01 completed; order is still open (not filled).

```python
cancel_result = client.cancel_order(order_id_from_tc01)
# Keep alive for ≥ 5 seconds
```

**Expected callback**:

```
OrderEvent {
    new_status  = CANCELLED
    is_cancelled() = True
}
```

**Pass criteria**:
- [ ] Callback fired within 10 s of `cancel_order()`.
- [ ] `event.is_cancelled()` returns `True`.
- [ ] `client.list_orders()` shows CANCELLED status.
- [ ] DB status updated to `CANCELLED`.

---

### TC-03 – Quantity Update via External Tool (UPDATE callback)

**Purpose**: Verify that an order modified **externally** (e.g. Sinopac mobile
app or `test_sinopac_api_update_qty.py`) still triggers the registered
callback, mapping correctly back to the CJ order ID.

**Prerequisite**: A paper open order exists (place another far-below-market order
before this test; **do not cancel it**).

**Steps**:

1. Place a BUY 3-share odd-lot order at price 1.0.
2. Register callback, keep process running.
3. Using the **Sinopac mobile app**, reduce quantity by 1 (i.e. change to 2).
4. Observe callback output.

**Expected callback**:

```
OrderEvent {
    new_status  = SUBMITTED (quantity changed, still open)
    quantity    = 2         # updated
}
```

**Pass criteria**:
- [ ] Callback is triggered.
- [ ] `event.quantity` reflects the updated quantity.
- [ ] No erroneous FILLED/CANCELLED status.

> 💡 Alternatively, use `tests/test_sinopac_api_update_qty.py` instead of the
> mobile app to make this reproducible without manual interaction.

**Clean up**: Cancel the order after observation.

---

### TC-04 – Fill (FILL callback via `StockDeal` path)

**Purpose**: Verify the `stat.name == 'StockDeal'` branch, `event.is_filled()`,
`event.filled_price`, and `event.filled_quantity`.

**Cost**: ~31 TWD.  You will own 1 odd-lot share of 2890 afterwards.

> **Tip**: Check the ask price with `client.get_bid_ask(product)` just before
> placing.  Set `price` to `ask_price[0]` to maximise fill probability.

```python
bid_ask = client.get_bid_ask(Product(symbol="2890", exchange=Exchange.TSE),
                              intraday_odd=True)
ask = bid_ask.ask_price[0]

order = Order(
    product=Product(symbol="2890", exchange=Exchange.TSE),
    action=OrderAction.BUY,
    price=ask,
    quantity=1,
    order_lot=OrderLot.IntraDayOdd,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD
)
client.register_order_callback(on_order_change)
result = client.place_order(order)
# Keep alive until fill or timeout (max 2 min)
```

**Expected callback sequence**:

```
# 1. Submit event
OrderEvent { new_status = SUBMITTED, filled_qty = 0 }

# 2. Fill event  (may come as one or split into partial fills)
OrderEvent {
    event_type          = ORDER_STATUS_CHANGE
    new_status          = FILLED
    is_filled()         = True
    is_completely_filled() = True    (for qty=1)
    filled_quantity     = 1
    filled_price        ≈ ask
    filled_value        = 1 * filled_price
}
```

**Pass criteria**:
- [ ] At least one callback with `event.is_filled() == True`.
- [ ] `event.filled_quantity == 1`.
- [ ] `event.filled_price > 0`.
- [ ] DB status updated to `FILLED`.
- [ ] `broker_raw_data['op_type'] == 'Deal'`.

---

### TC-05 – Sell Filled Position (SELL FILL callback)

**Purpose**: Verify the SELL side of the fill path and clean up the position
acquired in TC-04.  Also confirms `event.action == OrderAction.SELL`.

**Prerequisite**: TC-04 completed; account holds 1 odd-lot share of 2890.

> ⚠️ Odd-lot SELL orders must be placed via `order_lot=OrderLot.IntraDayOdd`
> during intraday odd-lot session (09:00–13:30).

```python
bid = client.get_bid_ask(...).bid_price[0]

order = Order(
    product=Product(symbol="2890", exchange=Exchange.TSE),
    action=OrderAction.SELL,
    price=bid,          # bid side to get filled
    quantity=1,
    order_lot=OrderLot.IntraDayOdd,
    price_type=PriceType.LMT,
    order_type=OrderType.ROD
)
result = client.place_order(order)
```

**Expected callback**:

```
OrderEvent {
    action      = SELL
    new_status  = FILLED
    is_filled() = True
}
```

**Pass criteria**: same as TC-04 but `event.action == OrderAction.SELL`.

---

### TC-06 – Multiple Callbacks Registered

**Purpose**: Verify that **all** registered callbacks are invoked when multiple
callbacks are registered via repeated calls to `register_order_callback()`.

```python
results = []

def cb_a(event): results.append(('A', event.new_status))
def cb_b(event): results.append(('B', event.new_status))

client.register_order_callback(cb_a)
client.register_order_callback(cb_b)

# Trigger any status change (e.g. place + cancel a far-below-market order)
order = Order(...)   # price=1.0, qty=1 as in TC-01
result = client.place_order(order)
time.sleep(5)
client.cancel_order(result.linked_order)
time.sleep(5)

assert any(tag == 'A' for tag, _ in results), "cb_a was not called"
assert any(tag == 'B' for tag, _ in results), "cb_b was not called"
```

**Pass criteria**:
- [ ] Both `cb_a` and `cb_b` invoked for every status change.
- [ ] Order of invocation is registration order.
- [ ] Exception in one callback does not prevent the other from being called
  (see `try/except` loop in `_setup_shioaji_order_callback`).

---

## Exception / Error Path Tests (offline, no real orders needed)

These can be run with a **mock** or by directly calling the internal callback
function with fabricated `stat`/`msg` payloads.

| ID | Scenario | Expected behaviour |
|---|---|---|
| TE-01 | `msg` is `None` | No crash; callback not triggered |
| TE-02 | `sj_order_id` not in DB | `⚠️ CJ order_id not found` logged; user callback not called |
| TE-03 | User callback raises an exception | Exception printed + traceback; **other callbacks still run** |
| TE-04 | `stat.name` is an unknown string | Falls to `OrderState` path; `cj_status = UNKNOWN` |
| TE-05 | `seqno` not found in `cj_sj_order_map` or `list_trades()` | `⚠️ Cannot find order` logged; early return |

### How to unit-test these offline

```python
# Directly invoke the internal callback with a fake payload
api = SinopacBrokerAPI(...)
api._setup_shioaji_order_callback()     # registers internal handler

# Grab the registered handler via monkey-patch / closure inspection,
# or expose it as api._shioaji_callback for testing:
fake_stat = types.SimpleNamespace(name='StockOrder')
fake_msg  = None                        # TE-01

api._shioaji_callback(fake_stat, fake_msg)   # should not crash
```

---

## Execution Order & Cost Summary

```
Day 1 (single market session, ~30 min of actual testing)
─────────────────────────────────────────────────────────
09:05  TC-01  Place far-below-market BUY  (qty=1, price=1.0)   ─┐ ~0 TWD
09:06  TC-02  Cancel it                                          ─┘
09:10  TC-03  Place 3-share order; update qty via app            ─► ~0 TWD (cancel after)
09:30  TC-04  Place BUY at ask to fill                           ─► ~31 TWD spent
09:35  TC-05  Sell the filled share                              ─► ~31 TWD recovered
              (net cost: spread + commission ≈ 0.1–1 TWD)
─────────────────────────────────────────────────────────
TC-06: piggyback on TC-01/TC-02 timing, no extra cost
TE-01…TE-05: offline, no cost
─────────────────────────────────────────────────────────
Total real spend: ≈ 1–5 TWD (spread + minimum commission)
```

---

## Checklist

- [ ] TC-01 passed
- [ ] TC-02 passed
- [ ] TC-03 passed
- [ ] TC-04 passed
- [ ] TC-05 passed
- [ ] TC-06 passed
- [ ] TE-01 … TE-05 passed (offline)

---

## References

- Existing manual test notes: `sinopac_broker_api.py` `__main__` block comments
- Callback implementation: `SinopacBrokerAPI._setup_shioaji_order_callback()`
- Event model: `src/cjtrade/pkgs/models/event.py` — `OrderEvent`
- Quantity update helper: `tests/test_sinopac_api_update_qty.py`
- `AccountClient.register_order_callback()` → `src/cjtrade/pkgs/brokers/account_client.py`
