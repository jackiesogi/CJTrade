# CJTrade Beginner API - 實現細節說明

## 核心概念：Global Namespace Management

### 1. 全局 Client 管理

```python
# 在 beginner.py 中
_global_client: Optional[AccountClient] = None

def _get_client() -> AccountClient:
    """Get or create the global client instance"""
    global _global_client
    if _global_client is None:
        _global_client = create_client()
    return _global_client
```

**作用**：
- 用戶第一次呼叫 `buy()` 或 `get_balance()` 時，自動建立 client
- 後續呼叫都重複使用同一個 client，無需用戶管理
- 用戶可透過 `set_client()` 手動設定（如用於測試）

---

### 2. Symbol Context（符號上下文）

```python
_current_symbol: Optional[str] = None

def set_current_symbol(symbol: str) -> None:
    global _current_symbol
    _current_symbol = symbol

def buy(qty: int, price: Optional[float] = None, symbol: Optional[str] = None):
    symbol = symbol or get_current_symbol()  # 優先用參數，其次用全局
    if not symbol:
        raise ValueError("No symbol specified...")
```

**用途**：
- 用戶可以 `set_current_symbol("2330")` 一次
- 之後 `buy(100)` 會自動用 "2330"
- 或者直接 `buy(100, symbol="2330")` 覆蓋

---

### 3. Aliases（別名）

```python
# 長名
buy(qty=100)
sell(qty=50)
get_balance()
get_total_equity()
get_positions()

# 短別名
buy_order(qty=100)      # buy 的別名
sell_order(qty=50)      # sell 的別名
cash()                  # get_balance() 的別名
equity()                # get_total_equity() 的別名
positions()             # get_positions() 的別名
kbars(symbol, s, e)     # get_kbars() 的別名
snapshot_price(symbol)  # get_current_price() 的別名
```

---

### 4. Namespace 暴露（via `__all__`）

```python
__all__ = [
    # 模型對象
    'Order', 'OrderType', 'Product', 'Kbar', 'Position',

    # 技術分析
    'ta',  # 完整的 ta.ema(), ta.sma() 等都可用

    # 函數
    'buy', 'sell', 'get_balance', 'get_positions', ...
    'buy_order', 'sell_order', 'cash', 'equity', ...  # 別名
]
```

當用戶做 `from cjtrade.api.beginner import *` 時，會取得 `__all__` 中的所有東西。

---

## 使用範例

### 最簡潔方式

```python
from cjtrade.api.beginner import *

set_current_symbol("2330")

def strategy(kbar):
    ema = ta.ema(kbar.closes, 12)
    if kbar.close > ema[-1]:
        return buy(qty=100)  # 自動用 "2330"
    return None
```

### 完整方式

```python
from cjtrade.api.beginner import *

def strategy(kbar):
    ema = ta.ema(kbar.closes, 12)
    if kbar.close > ema[-1]:
        return buy(qty=100, symbol="2330")  # 明確指定符號

    cash = get_balance()
    equity = get_total_equity()
    pos = get_positions()

    return None
```

### 用短別名

```python
from cjtrade.api.beginner import *

set_current_symbol("2330")

def strategy(kbar):
    ema = ta.ema(kbar.closes, 12)
    if kbar.close > ema[-1]:
        return buy_order(qty=100)  # 用 buy_order 別名

    print(f"Cash: {cash()}, Equity: {equity()}")  # 用短別名
    return None
```

---

## 如何整合到 CJTrade System

### 在 cjtrade_system.py 或策略執行器中

```python
from cjtrade.core.strategy_executor import StrategyExecutor
from cjtrade.api.beginner import set_client

# 建立 client
client = AccountClient(BrokerType.SINOPAC)

# 設定到 beginner API
set_client(client)

# 現在載入並執行用戶策略
executor = StrategyExecutor("./strategies/my_strategy.cj")
executor.run()
```

### 或者在策略檔案本身初始化

```python
# ~/.cjtrade/strategies/my_strategy.cj
from cjtrade.api.beginner import *

client = create_client(simulation=True)  # 建立模擬 client
set_current_symbol("2330")

def strategy(kbar):
    ema = ta.ema(kbar.closes, 12)
    if kbar.close > ema[-1]:
        return buy(qty=100)
    return None
```

---

## 優勢

1. **對用戶隱藏複雜性**
   - 不知道 AccountClient 細節
   - 不知道 broker 選擇邏輯
   - 就像 Pine Script 一樣簡潔

2. **但對 Python 開發者仍透明**
   - `ta` 是真實的 `TALibWrapper` 物件
   - `Order`, `Product` 是真實的類別
   - 可以 inspect、debug

3. **靈活**
   - 可以用全局 symbol 或每次傳參數
   - 可以手動設定 client 或自動建立
   - 別名提供多種風格

4. **IDE 友善**
   - `from cjtrade.api.beginner import *` 後，IDE 知道所有可用的東西
   - `ta.` 會自動完成
   - `buy()` 會顯示參數提示

---

## 潛在問題與解決

### Q: 如果用戶忘記 `set_current_symbol()` 呢？
A: `buy()` 會拋出有用的錯誤訊息：
```python
raise ValueError("No symbol specified. Set symbol via set_current_symbol() or pass it directly.")
```

### Q: 如果多個策略同時執行怎麼辦？
A: 使用全局 client 可能造成衝突。解決方案：
```python
# 方案 1：每個策略用不同的命名空間
exec(strategy_code, {"set_current_symbol": set_current_symbol, ...})

# 方案 2：建立獨立的 API 實例（而不是全局）
class StrategyAPI:
    def __init__(self, client):
        self.client = client

    def buy(self, qty, ...):
        # 用 self.client 而非全局
        ...
```

### Q: 如何追蹤誰呼叫了什麼？
A: 所有 `buy()`, `sell()`, `get_balance()` 都可以加 logging：
```python
def buy(qty, ...):
    import logging
    logging.info(f"BUY order: {qty} @ {get_current_symbol()}")
    # ...
```

---

## 檔案結構

```
cjtrade/
├── api/
│   ├── __init__.py           # 導出 beginner API
│   ├── beginner.py           # 用戶策略用的簡化 API
│   └── advanced.py           # （可選）完整 API
├── core/
│   ├── account_client.py
│   ├── cjtrade_system.py
│   └── strategy_executor.py  # 執行 .cj 檔案的執行器
└── ...
```

---

## 小結

**Namespace 管理的三層**：

1. **全局物件**（_global_client, _current_symbol）
   - 隱藏複雜性
   - 提供簡潔 API

2. **函數別名**（buy, buy_order, cash, equity）
   - 給不同風格的用戶
   - 不增加複雜性

3. **明確暴露**（__all__）
   - IDE 知道可用的東西
   - 清楚的 public API
   - 容易文檔化
