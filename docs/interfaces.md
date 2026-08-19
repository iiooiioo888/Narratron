# 介面契約

> 實作位置：`narratron/`  
> 原則：可 `import`。Alpha Q1 已通 `State Vault` / `Parser` / `Director`。除 `Router` 預設回傳 `Mid Core` 與 Q1 上述模組外，生成相關方法仍為 stub。

本文對應 Python Protocol / Pydantic 模型。權威程式碼優於本文；兩者衝突時以程式 + [`naming.md`](naming.md) 為準，並應修正文件。

---

## 1. Agent State（LangGraph）

模組：`narratron.agents.state.AgentState`

五智能體共用同一份狀態，節點順序凍結為：

```
Parser → Director → Keeper → Runner → Muxer
```

| 欄位 | 型別 | 寫入者 | 說明 |
| :--- | :--- | :--- | :--- |
| `script` | `str` | API / `Parser` 讀取 | 原始劇本 |
| `entities` | `list[Entity]` | `Parser` | 角色 / 道具 / 場景 |
| `shots` | `list[Shot]` | `Director` | 分鏡與鏡頭語言 |
| `traces` | `list[TraceRecord]` | `Keeper` | 因果履歷（對應 Trace Log） |
| `assets` | `list[Asset]` | `Parser` / `Runner` | 參考圖資產 metadata |
| `prompt` | `str` | `Keeper` | 經 Causal Link + Compressor 後的提示 |
| `selected_pool` | `HardwarePool` | P7 `Router` | 預設 `L1` / `Mid Core` |
| `media_uris` | `list[str]` | `Runner` | 生成資產 URI（本階段不填） |
| `mux_uri` | `str \| None` | `Muxer` | 合流成品 URI |

### 智能體方法

| 類 | 方法 | 輸入 → 輸出 | 備註 |
| :--- | :--- | :--- | :--- |
| `Parser` | `parse(state) -> AgentState` | 劇本 → 初始化 Vault 實體、Trace Log、參考圖 | Alpha Q1 已通 |
| `Director` | `direct(state) -> AgentState` | 實體 → 分鏡與鏡頭語言 | Alpha Q1 已通；無實體時先呼叫 Parser |
| `Keeper` | `keep(state) -> AgentState` | 分鏡 + Trace → 不斷檔 prompt；呼叫 Tracer / Screener 介面 | stub（Q2） |
| `Runner` | `run(state) -> AgentState` | prompt → Model Farm + Plugin Bus | stub（Q3） |
| `Muxer` | `mux(state) -> AgentState` | 媒體 URI → FFmpeg / Light Core | stub（Q4） |

圖編譯：`narratron.agents.graph.build_graph()` 可 import；invoke 到 `Keeper` 仍會觸發 stub。

---

## 2. State Vault schema

模組：`narratron.vault.schema`

預設 `VAULT_BACKEND=memory`。設為 `postgres` 時連 PostgreSQL JSONB（DDL：`docker/init-vault.sql`，執行時 `PostgresStore.ensure_schema()`）。表名與 JSONB 欄位凍結如下。

### `entities`

| 欄位 | 型別 | 說明 |
| :--- | :--- | :--- |
| `id` | `str` | 主鍵 |
| `kind` | `EntityKind` | `character` / `prop` / `scene`（角色/道具/場景） |
| `name` | `str` | 顯示名 |
| `payload` | `dict` | JSONB 全量狀態（傷痕、材質、位置等） |
| `created_at` | `datetime` | 建立時間 |

### `shots`

| 欄位 | 型別 | 說明 |
| :--- | :--- | :--- |
| `id` | `str` | 主鍵 |
| `scene_id` | `str` | 對應 scene 實體 |
| `order` | `int` | 時序 |
| `camera_language` | `str` | 鏡頭語言 |
| `duration_ms` | `int` | 時長 |
| `payload` | `dict` | JSONB 補充（節奏、情緒張力等） |

### `trace_log`

| 欄位 | 型別 | 說明 |
| :--- | :--- | :--- |
| `id` | `str` | 主鍵 |
| `entity_id` | `str` | 被追蹤實體 |
| `shot_id` | `str \| None` | 可選分鏡 |
| `happened_at` | `datetime` | 故事內時間 |
| `cause` | `str` | 前因 |
| `effect` | `str` | 後果 |
| `payload` | `dict` | JSONB 補充 |

Python 模型名：`TraceRecord`（對應表 `trace_log`）。儲存介面類名：`TraceLog`。

### `assets`

| 欄位 | 型別 | 說明 |
| :--- | :--- | :--- |
| `id` | `str` | 主鍵 |
| `entity_id` | `str \| None` | 可選綁定實體 |
| `kind` | `str` | 例如 `reference_image` |
| `uri` | `str` | 儲存位置 |
| `metadata` | `dict` | JSONB |

`StateVault` / `TraceLog` 已通讀寫（記憶體或 Postgres）。`Chroma` / `Redis` 提供本機層；compose 服務供 Q1 驗收切換。

`StateVault.register_reference_image(...)` 寫入 `assets`。劇本含 `參考圖：` 或 markdown 圖時，`Parser` 會呼叫 `queue_ip_adapter_finetune`（只寫佇列，不呼叫 GPU）。

---

## 3. Plug-in Bus

模組：`narratron.plugins.context`、`narratron.plugins.bus`

### `TriggerPhase`

| 枚舉 | 白皮書 |
| :--- | :--- |
| `PRE` | 生成前 |
| `POST` | 生成後 |

P5 `Mover` 的 `triggers = (PRE, POST)`。

### `PluginContext`

| 欄位 | 型別 |
| :--- | :--- |
| `shot_id` | `str` |
| `phase` | `TriggerPhase` |
| `prompt` | `str` |
| `entities` | `list[Entity]` |
| `traces` | `list[TraceRecord]` |
| `complexity` | `SceneComplexity`（人數/特效，供 Router） |
| `media_uri` | `str \| None`（生成後才有） |

### `PluginResult`

| 欄位 | 型別 |
| :--- | :--- |
| `passed` | `bool` |
| `prompt_delta` | `str \| None` |
| `flags` | `list[str]` |
| `metadata` | `dict` |

### `Plugin` Protocol

```python
class Plugin(Protocol):
    plugin_id: str    # P1 … P13
    code: str         # Tracer …
    name_zh: str
    triggers: tuple[TriggerPhase, ...]
    def run(self, context: PluginContext) -> PluginResult: ...
```

`PluginBus.dispatch(phase, context)` 依註冊表過濾觸發時機。除 `Router.run` 回傳 `{"pool": "MidCore"}` 外皆 stub。

---

## 4. Hardware Pool

模組：`narratron.hardware.pools`

```python
class HardwarePool(str, Enum):
    L0 = "BigCore"    # Big Core 大核
    L1 = "MidCore"    # Mid Core 中核
    L2 = "AltCore"    # Alt Core 備核
    L3 = "LightCore"  # Light Core 輕核
```

`select_pool(complexity: SceneComplexity) -> HardwarePool`  
目前固定回傳 `HardwarePool.L1`（中核）。複雜度切大核/備核的真實邏輯待 Alpha Q3。

`Scheduler`：Night Shift 介面 stub。  
`Tier Store`：熱 / 溫 / 冷層枚舉 stub。

---

## 5. Trinity Core

| 類 | 方法 | 契約 |
| :--- | :--- | :--- |
| `LogicCore` | `ensure_choice_driven(state) -> AgentState` | 禁止機械降神；stub |
| `CausalLink` | `translate(traces) -> str` | Trace Log → 動態視覺形容詞；stub |
| `Compressor` | `compress(antecedents: list[str]) -> str` | 多時間點前因 → 一句高密度描述；stub |

---

## 6. Model Farm

`ModelFarm.generate_*` 與各 adapter（`Flux` / `Wan` / `Veo` / `TTS` / `FFmpeg`）均 `NotImplementedError`。  
`FFmpeg` 綁定 `Light Core`；圖/片模型綁定 Big / Mid / Alt。

---

## 7. API 閘道

`GET /health` 可回傳平台名與 `phase: Alpha Q1`。  
`POST /parse`、`POST /direct` 已通（可 `persist: false` 不寫入預設 Vault）。  
`POST /keep`、`POST /run`、`POST /mux` 回 501。

角色護照（格式層，見 [`charpass.md`](charpass.md)）：

| 方法 | 路徑 | 說明 |
| :--- | :--- | :--- |
| `POST` | `/api/v1/characters/{char_id}/export` | 打包 `.charpass` |
| `POST` | `/api/v1/projects/{proj_id}/characters/import` | 導入護照 |
| `GET` | `/api/v1/characters/{char_id}/charpass` | Lite manifest |
| `POST` | `/api/v1/characters/{char_id}/charpass` | 只寫 `payload.charpass` |
| `DELETE` | `/api/v1/characters/{char_id}` | 有 traces 則 409，除非 `archive=true` |

環境變數見 [`.env.example`](../.env.example)，不含密鑰實值。
