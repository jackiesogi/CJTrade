# 希望可以把 cjtrade shell 的 BaseCommand 那些邏輯加入到 pkg 之中使之可以被重用

# 希望有一個新指令可以被整合到 cjtrade shell 方便操作：顯示近期的走勢（可選擇動態或靜態直接印出）

# 可以寫一個 APP 用途是可以快速手動測試 broker api
# 主要就是解決上面要自己寫import一堆東西
# 可以使用 form schema 的框架先給一個選單來選擇broker以及需要引入的 key file
# 然後用這個 app 寫成的測試檔案可以被這個 app 統一管理

# Sinopac API 目前這樣封裝在獨立檔案作place_order測試的時候其實非常危險
# 因為現在 app 裡面（cjtrade_shell）高度仰賴 db 裡面的 CJ_OrderMap 來紀錄原始的 sinopac id
# 也就是說如果用獨立檔案呼叫 place_order 除非 caller 有自行紀錄要 cancel 掉的 CJ order id
# 否則程式結束之後這個 id 就消失了（當然使用者還是可以利用 sinopac native api 來撈訂單資料 但這不應該是CJTrade User自己需要去做的 這樣就違反了abstraction的哲理）
# 應該要有一個方式在 place_order 之後不管使用者有沒有自行紀錄下來 電腦上的 local file 都要有紀錄一份 mapping？
