# 行情資料

以下範例假設已經有一個連線好的 `client`（見[連線到券商](connect.md)）。

## 最新報價

```python
from cjtrade.pkgs.models.product import Product

for snap in client.get_snapshots([Product("2330"), Product("0050")]):
    print(snap.symbol, snap.close, snap.volume)
```

Snapshot 是一筆報價，它的 `open`、`high`、`low` 是當天到目前為止的值，不是某一根
K 棒的。

## 歷史 K 棒

```python
kbars = client.get_kbars(Product("2330"), start="2025-01-01",
                         end="2025-10-01", interval="1d")

for k in kbars[-3:]:
    print(k.timestamp, k.open, k.high, k.low, k.close, k.volume)
```

interval 有 `1m`、`5m`、`1h` 和 `1d`；日期格式是 `YYYY-MM-DD`。

!!! warning
    該區間沒有資料時，`get_kbars` 會回傳空 list，不會報錯。在 ArenaX 上，不支援的
    interval 會默默退回 `1m`。

## 技術指標

`ta` 包裝 TA-Lib，吃的是陣列：

```python
import numpy as np
from cjtrade.pkgs.analytics.technical import ta

closes = np.array([k.close for k in kbars])
ema = ta.ema(closes, 12)
upper, middle, lower = ta.bb(closes, 20)
macd, signal, hist = ta.macd(closes)
print(ema[-1], upper[-1], macd[-1])
```

每個結果的長度都和輸入相同，窗口湊滿之前是 `NaN`。

下一步：[撰寫策略](strategy.md)。
