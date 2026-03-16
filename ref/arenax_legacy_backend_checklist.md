## Legacy Backend 功能檢查表（對照用）

| 類別 | 功能/行為 | Legacy 有 | 新版需確認 | Notes |
|---|---|---|---|---|
| Historical | `real_account` 可選 | ☐ | ☐ | 無 real_account → yfinance |
| Historical | `market` 建立（MockMarket） | ☐ | ☐ | 資料來源切換 |
| Historical | `playback_speed` 初始化 | ☐ | ☐ | `set_playback_speed` |
| Historical | `set_historical_time(days_back)` | ☐ | ☐ | days_back 隨機、可用性檢查 |
| Historical | `num_days_preload` / `skip_data_preload` | ☐ | ☐ | preload 行為 |
| Historical | `login()` -> sync account | ☐ | ☐ | real 或 mock file |
| Historical | `logout()` -> save state | ☐ | ☐ | 交易/狀態寫檔 |
| Historical | `snapshot()` | ☐ | ☐ | 時間推進 + price |
| Historical | `kbars()` | ☐ | ☐ | yfinance 下載 |
| Historical | `place_order()` + `commit_order()` | ☐ | ☐ | 下單流程 |
| Historical | `cancel_order()` | ☐ | ☐ | 取消流程 |
| Historical | `_check_if_any_order_filled()` | ☐ | ☐ | 撮合核心 |
| Historical | `_update_position_prices()` | ☐ | ☐ | 價格更新 |
| Historical | `_sync_with_real_account()` | ☐ | ☐ | 同步餘額/持倉 |
| Historical | `_sync_with_mock_account_file()` | ☐ | ☐ | 讀檔 + 回補狀態 |
| Historical | `_aggregate_kbars_internal()` | ☐ | ☐ | 不支援 interval 聚合 |
| PaperTrade | `real_account` 必要 | ☐ | ☐ | 連線來源 |
| PaperTrade | `market = RealMarket` | ☐ | ☐ | realtime |
| PaperTrade | `_kbar_buffer` | ☐ | ☐ | fill detection |
| PaperTrade | `login()/logout()` | ☐ | ☐ | 同步 account |
| PaperTrade | `snapshot()/kbars()` | ☐ | ☐ | 即時行情 |
| PaperTrade | `place_order()/commit_order()` | ☐ | ☐ | 模擬成交 |
| PaperTrade | `_check_if_any_order_filled()` | ☐ | ☐ | 撮合核心 |
| None (你新增) | 使用 yfinance | N/A | ☐ | 你目前新增 |
| None (你新增) | `set_historical_time` | N/A | ☐ | 行為等同 historical |
| None (你新增) | `num_days_preload` | N/A | ☐ | preload 邏輯 |

# ji
☑
