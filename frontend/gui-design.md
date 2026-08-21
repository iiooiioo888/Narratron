# GUI 第一版設計（文件版）

> 對應白皮書用戶層 §2.1：`Pad -> Timeline -> Dashboard -> Map -> Player`。
> 本文件定義畫面布局與互動邏輯。可執行實作：`frontend/webapp/` 與 `characteros/static/`。

## 1. 全域布局（App Shell）

1. 左側導航（Sidebar）
   - 顯示五個節點：`Pad`、`Timeline`、`Dashboard`、`Map`、`Player`
   - 目前階段狀態（例如：`Pad 已提交`、`Timeline 已生成 shots`）
   - 禁用未就緒節點（依 API 回傳的狀態/資源存在與否）

2. 中央主要內容區（Main Content）
   - 根據路由顯示單一畫面（一次只顯示一個：Pad/Timeline/…）
   - 需要時顯示基礎loading（例如 parse/direct 中）

3. 右側資訊/檢視區（Inspector，可選）
   - 顯示當前選中元素的詳細資訊
   - 共用條目：狀態碼、API 呼叫摘要、錯誤訊息（若有）

4. 頂部工具列（Top Bar）
   - 專案階段：Alpha Q1（或由後端回傳）
   - 主要操作按鈕（根據所在畫面不同而變）

## 2. 共用元件規格

1. `PrimaryButton`
   - 視情況顯示：`Parse` / `Direct` / `Refresh` / `Play`
   - 會在 API 呼叫期間鎖定並顯示進度

2. `ReadOnlyNotice`
   - 顯示「此畫面為只讀資料」提示（符合 `Timeline/Dashboard/Map/Player`）

3. `ErrorBanner`
   - 顯示 API 返回錯誤（例如契約不一致、缺少 shots、缺少 trace log）

4. `StatusPill`
   - 狀態展示：`queued / running / ok / stale / missing`

## 3. 畫面規格（依合約）

### 3.1 Pad — 寫板（上游入口）

對應檔案：`frontend/pad.md`

布局：
- 劇本輸入區（多行文字框）
- 關鍵指令區（可選：例如風格/目標/限制）
- 一組提交/推進按鈕：
  - `Parse`：把劇本送進 API 閘道（後端產出角色/道具/場景 + 初始化 State Vault）
  - `Direct`：在 parse 完成後，要求 Director 拆分鏡與鏡頭語言

互動規則：
- `Pad` 的輸入僅會改變「待解析文本」，不直接改任何 State Vault 表
- 成功後將解鎖 `Timeline` 與 `Dashboard`

輸入驗證（前端只做輕量檢查）：
- 空內容禁用按鈕
- 長度上限提示（例如 20k 字以內，具體數值待你定）

### 3.2 Timeline — 時軌（Shots 檢視/調整）

對應檔案：`frontend/timeline.md`

布局：
- shots 清單（時間排序）
- 每個 shot 的摘要欄位：
  - shot index
  - 主要鏡頭語言（依 Director 輸出）
  - 重要節奏標記（例如間隔/情緒強度，僅顯示）

互動規則：
- 預設只讀：資料來源是 `State Vault` 的 `shots`（不可繞過 Keeper）
- 若你要「調整順序」，可在之後用更明確的後端契約處理（本階段文件先以只讀為主）

Inspector：
- 點選 shot 顯示其詳細（對應 Map/Player 的關聯鍵）

### 3.3 Dashboard — 總覽（專案級面板）

對應檔案：`frontend/dashboard.md`

布局：
- 實體數量面板（角色/道具/場景數等）
- 分鏡進度（例如：shots 生成狀態）
- 算力池占用（`Big Core / Mid Core / Alt Core / Light Core`，只讀）
- 外掛觸發摘要（例如：P7/P9/P10…的執行狀態）
- Alpha Q1 KPI 預留面板：連續性誤差（待後端回傳欄位）

互動規則：
- 只讀刷新：`Refresh` 按鈕拉取最新狀態

### 3.4 Map — 因果圖（Trace Log 視覺化，只讀）

對應檔案：`frontend/map.md`

布局：
- 因果節點圖（節點= trace_log 記錄）
- 依類型著色：
  - 角色傷痕
  - 道具磨損
  - 環境累積變化

互動規則：
- 只讀：不得編輯節點或替換資料來源
- 點選節點：
  - Inspector 顯示該 trace_log 的「前因/後果關係」
  - 提供跳轉到對應 shot（若有鍵）

### 3.5 Player — 播放器（合成結果預覽）

對應檔案：`frontend/player.md`

布局：
- 影片預覽區
- 控制列：
  - Play / Pause
  - 進度條（顯示時間）
  - Refresh（重取最新合成結果）

資料來源：
- 只播 `Muxer` 合流後的成品（前端不負責 mux）

同名消歧：
- 此畫面是用戶層播放器；外掛 P9 的 `Player`（配樂）由後端產出音軌，前端只播放合成結果。

## 4. 與 API 閘道的最小互動集合（UI 需求摘要）

> 實際請求/回傳 schema 以你現有後端 `narratron/api` 為準；本文件只列「UI 需要哪些能力」。

1. `Pad`
   - `POST /parse`：提供劇本 -> 產出可用的 `shots` 前置資料 + 初始化 State Vault
2. `Timeline` / `Dashboard` / `Map`
   - `GET` 讀取狀態（例如 shots、trace_log、進度/KPI）
3. `Player`
   - `GET` 拉取/輪詢合成結果位置（例如影片 URL 或檔案路徑由後端提供）

## 5. 交付物清單（給你後續開工用）

1. `frontend/gui-design.md`（本文件）：GUI 規格基準
2. 每個畫面對應的「畫面資料字典」（下一步建議你做）：每欄位對應 State Vault/trace_log 的來源欄位
3. 一份「UI 狀態機」：`missing -> queued -> running -> ok -> stale`

