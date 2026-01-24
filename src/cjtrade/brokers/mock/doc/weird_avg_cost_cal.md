> The avg_cost seems quite weird, please check the simple weighted average calculation logic

Log:

```sh
> lspos
  symbol  quantity  avg_cost  current_price  market_value  unrealized_pnl
0   2357       500    497.44          516.0      258000.0          9280.0

Total Cost: 248,720.000
Market Value: 258,000.000
Total Unrealized PnL: 9,280.000 (+3.73%)
>
> date
Current datetime (mock time)
Sat Jan 24 01:25:15 AM CST 2026

    January 2026
Su Mo Tu We Th Fr Sa
             1  2  3
 4  5  6  7  8  9 10
11 12 13 14 15 16 17
18 19 20 21 22 23 24
25 26 27 28 29 30 31

>
> lsodr
=== Order List ===
Found 4 orders

Recent 5 orders:

Order 1:
  Order ID: 3971ee5dd8d5426a8790c1a3bdde4372
  Symbol: 2357
  Action: BUY
  Quantity: 800
  Price: 509.0
  Status: FILLED

Order 2:
  Order ID: 7865f4d828b44bfb93c96468e7eeecea
  Symbol: 2357
  Action: BUY
  Quantity: 100
  Price: 510.1
  Status: FILLED

Order 3:
  Order ID: c42d3dc3cc6d43f58ce5ff6cc910f0e8
  Symbol: 2357
  Action: BUY
  Quantity: 100
  Price: 510.1
  Status: FILLED

Order 4:
  Order ID: a204e372947d43e09ce3fec587b497b5
  Symbol: 2357
  Action: SELL
  Quantity: 500
  Price: 521.0
  Status: FILLED
>
```