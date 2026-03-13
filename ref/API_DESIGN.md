# CJTrade 系統功能分類與 API 設計

## 📊 Tier 1：核心交易功能（直接暴露，給所有用戶）

這些是交易系統的最基本操作，用戶必須知道：

| 功能 | 類別 | 使用頻率 | 應該暴露的形式 |
|------|------|--------|-------------|
| **買股票** | Trading | ⭐⭐⭐⭐⭐ | `client.buy_stock(symbol, qty, price)` |
| **賣股票** | Trading | ⭐⭐⭐⭐⭐ | `client.sell_stock(symbol, qty, price)` |
| **查詢持倉** | Info | ⭐⭐⭐⭐⭐ | `client.get_positions()` |
| **查詢餘額** | Info | ⭐⭐⭐⭐⭐ | `client.get_balance()` |
| **獲得快照** | Info | ⭐⭐⭐⭐ | `client.get_snapshots([products])` |
| **K線資料** | Info | ⭐⭐⭐⭐⭐ | `client.get_kbars(product, start, end, interval)` |

---

## 📊 Tier 2：技術分析功能（通過 namespace 暴露，中等頻率）

這些是 Pine Script 風格的常用指標，需要簡潔 API：

| 功能 | 抽象化程度 | 細節程度 | 應該暴露形式 | 使用範例 |
|------|----------|--------|-----------|--------|
| **EMA** | 中 | 低 | `ta.ema(prices, period)` | `ema = ta.ema(kbars.closes, 12)` |
| **SMA** | 中 | 低 | `ta.sma(prices, period)` | `sma = ta.sma(kbars.closes, 20)` |
| **Bollinger Bands** | 中 | 低 | `ta.bb(prices, period)` | `upper, mid, lower = ta.bb(kbars.closes)` |
| **RSI** | 中 | 低 | `ta.rsi(prices, period)` | `rsi = ta.rsi(kbars.closes, 14)` |
| **MACD** | 中 | 低 | `ta.macd(prices)` | `macd, signal, hist = ta.macd(kbars.closes)` |
| **Stochastic** | 中 | 低 | `ta.stoch(high, low, close)` | `sk, sd = ta.stoch(kbars.highs, kbars.lows, kbars.closes)` |

---

## 📊 Tier 3：模型對象（通過類別暴露，必須了解，但用戶主要讀不寫）

| 對象 | 用途 | 應該暴露 | 使用場景 |
|------|------|--------|--------|
| **Product** | 股票代碼容器 | ✅ 必要 | `prod = Product(symbol="2330")` |
| **Order** | 訂單模型 | ✅ 必要 | 返回值來自 `place_order()` |
| **OrderType** | 訂單類型 enum | ✅ 必要 | `Order(type=OrderType.BUY)` |
| **Position** | 持倉資訊 | ✅ 必要 | 從 `get_positions()` 返回 |
| **Kbar** | K線資料 | ✅ 必要 | 從 `get_kbars()` 返回 |
| **Quote** | 行情快照 | ⚠️ 可選 | 內部使用，用戶很少直接操作 |
| **Trade** | 交易記錄 | ⚠️ 可選 | 回測報告中使用 |

---

## 📊 Tier 4：系統級功能（進階用戶用，部分隱藏）

| 功能 | 用途 | 應該暴露 | 應該隱藏的實現 |
|------|------|--------|------------|
| **TradingSystem** | 核心回測引擎 | ✅ 完整暴露（給想寫自己策略的人） | 內部 `_calculate_bollinger_bands_mock()` |
| **AccountClient** | Broker 抽象層 | ✅ 完整暴露 | 內部代理邏輯 |
| **BrokerAPI** (Sinopac/Mock) | 真實 broker 連線 | ❌ 隱藏（通過 AccountClient 用） | 直接實例化 API |
| **LLM 分析** | AI 市場分析 | ⚠️ 可選（給想要 AI 報告的人） | 細節實現 |
| **圖表工具** | 視覺化 | ⚠️ 可選 | 內部渲染邏輯 |

---

## 📊 Tier 5：內部實現（完全隱藏）

| 項目 | 原因 |
|------|------|
| `_mock_broker_backend.py` | 用戶不需要知道 mock broker 怎麼實現 |
| `_check_if_any_order_filled()` | 內部訂單匹配邏輯 |
| `_chart_base.py` | 圖表渲染細節 |
| 各個 broker 的內部實現 | 統一通過 AccountClient 訪問 |

---

## 🎯 四層 API 架構

```python
# ==== 層級 1：main entry point ====
from cjtrade import (
    # Tier 1: 核心（所有人都用）
    AccountClient, BrokerType,
    Product, Order, OrderType, Position, Kbar,

    # Tier 2: 技術分析（Pine Script 風格）
    ta,

    # Tier 3: 可選進階
    TradingSystem,
)

# ==== 層級 2：進階 API（給想自己擴展的人）====
from cjtrade.core import AccountClient, TradingSystem
from cjtrade.pkgs.models import *
from cjtrade.pkgs.analytics.technical import ta

# ==== 層級 3：完全 detail API（給系統開發者）====
from cjtrade.pkgs.brokers.sinopac import SinopacBrokerAPI
from cjtrade.pkgs.brokers.arenax import MockBrokerAPI
from cjtrade.pkgs.llm.gemini import GeminiClient
```

---

## 📋 具體的 API 層設計

### cjtrade/__init__.py（層級 1：最簡潔）

```python
"""CJTrade - Trading System for Taiwan Market"""

from cjtrade.core import AccountClient, BrokerType, TradingSystem
from cjtrade.pkgs.models import Product, Order, OrderType, Position, Kbar
from cjtrade.pkgs.analytics.technical import ta

__all__ = [
    # Core Trading
    'AccountClient', 'BrokerType', 'TradingSystem',
    # Models
    'Product', 'Order', 'OrderType', 'Position', 'Kbar',
    # Technical Analysis
    'ta',
]
```

### cjtrade/api/beginner.py（層級 1.5：給策略編寫用）

```python
"""
Beginner-friendly API for CJTrade Strategy Editor
This module provides convenience functions for users who want Pine Script-like experience
"""

from cjtrade import AccountClient, BrokerType, Order, OrderType, Product, Kbar, ta
from cjtrade.pkgs.chart import KbarChartClient, KbarChartType
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============ Helper Functions ============
def create_client(broker_type=BrokerType.SINOPAC, simulation=False):
    """Create a broker client with environment config"""
    config = {
        'api_key': os.getenv('API_KEY'),
        'secret_key': os.getenv('SECRET_KEY'),
        'ca_path': os.getenv('CA_CERT_PATH'),
        'ca_passwd': os.getenv('CA_PASSWORD'),
        'simulation': simulation,
    }
    client = AccountClient(broker_type, **config)
    client.connect()
    return client

def place_buy(client, symbol, qty, price=None):
    """Simplified buy order"""
    return client.buy_stock(symbol, qty, price if price else 0)

def place_sell(client, symbol, qty, price=None):
    """Simplified sell order"""
    return client.sell_stock(symbol, qty, price if price else 0)

def get_current_price(client, symbol):
    """Get the latest price for a symbol"""
    product = Product(symbol=symbol)
    snapshot = client.get_snapshots([product])[0]
    return snapshot.close

__all__ = [
    # Main objects
    'create_client', 'Order', 'OrderType', 'Product', 'Kbar', 'ta',
    # Helpers
    'place_buy', 'place_sell', 'get_current_price',
    # Visualization
    'KbarChartClient', 'KbarChartType',
]
```

---

## 🔍 該不該用 alias 或 preload？

### 答案：需要，但改進方式

| 特性 | 舊 preload.py | 新 api/beginner.py |
|------|-------------|------------------|
| 位置 | `scripts/preload.py` | `cjtrade/api/beginner.py` |
| 清晰度 | ❌ 藏在 scripts 裡 | ✅ 明確標示「給初學者」 |
| IDE 支持 | ⭐ | ⭐⭐⭐ |
| 文檔 | 需要另外寫 | 直接寫在 docstring |
| 易發現性 | 低（需要告訴用戶） | 高（清楚在 API 層） |
| 用途 | 不明確 | **明確：給策略編寫用** |

---

## 📚 三種用戶的使用方式

### Beginner（寫策略的非程式員）

```python
from cjtrade.pkgs.api.beginner import *

def strategy(kbar):
    ema = ta.ema(kbar.closes, 12)
    if kbar.close > ema[-1]:
        return buy(qty=100)
```

### Intermediate（熟悉 Python 的交易者）

```python
from cjtrade import AccountClient, BrokerType, ta, Product

client = AccountClient(BrokerType.SINOPAC)
products = [Product(symbol="2330"), Product(symbol="0050")]
snapshots = client.get_snapshots(products)

for snap in snapshots:
    print(f"{snap.symbol}: {snap.close}")
```

### Advanced（系統開發者）

```python
from cjtrade.core import TradingSystem, AccountClient
from cjtrade.pkgs.brokers.sinopac import SinopacBrokerAPI
from cjtrade.pkgs.models import Order, OrderType

client = AccountClient(BrokerType.SINOPAC)
system = TradingSystem(client)
system.run()  # 完整控制
```

---

## 🚀 最終建議

1. **建立 `cjtrade/api/` 目錄**
   ```
   cjtrade/api/
   ├── __init__.py
   ├── beginner.py    # Pine Script 風格，給策略編寫用
   └── advanced.py    # 完整 API（可選）
   ```

2. **改進 `cjtrade/__init__.py`**
   - 只 expose Tier 1-2 最常用的東西

3. **廢棄 `scripts/preload.py`**
   - 改用 `cjtrade.api.beginner`

4. **在每個模組加 `__init__.py`**（之前想做的）
   - 支持分層 import

這樣既有簡潔的 Pine Script 體驗，又不隱藏 Python 的細節。
