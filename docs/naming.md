# 命名凍結表

> 來源：[`whitepaper-v2.md`](whitepaper-v2.md) 附錄與第 2–4 部分。  
> 狀態：**已凍結**。程式、文件、API 路徑一律使用本表代號，禁止自創別名。

口號：*Every Frame Carries Its Past.*

---

## 1. 平台

| 代號 | 中文 | Python / 目錄 |
| :--- | :--- | :--- |
| `Narratron` | 敘事體 | 套件 `narratron` |

禁止：`Narrator`、`NarraTron`、`NarrativeTron`、`NT` 作為對外名稱。

---

## 2. 三大核心內核 (Trinity Core)

| 英文代號 | 中文名 | Python 類名 | 模組路徑 |
| :--- | :--- | :--- | :--- |
| `Logic Core` | 邏輯內核 | `LogicCore` | `narratron/core/logic_core.py` |
| `Causal Link` | 因果橋 | `CausalLink` | `narratron/core/causal_link.py` |
| `Compressor` | 壓縮器 | `Compressor` | `narratron/core/compressor.py` |

禁止：把 `Causal Link` 寫成 `PromptTranslator`、`PromptEngine`。  
禁止：把 `Compressor` 寫成 `Summarizer`、`TokenSaver`。

---

## 3. 五大智能體 (Agents)

LangGraph 節點名必須等於英文代號（大小寫一致）。

| 英文代號 | 中文名 | Python 類名 | 模組路徑 |
| :--- | :--- | :--- | :--- |
| `Parser` | 解析器 | `Parser` | `narratron/agents/parser.py` |
| `Director` | 調度器 | `Director` | `narratron/agents/director.py` |
| `Keeper` | 守護器 | `Keeper` | `narratron/agents/keeper.py` |
| `Runner` | 執行器 | `Runner` | `narratron/agents/runner.py` |
| `Muxer` | 合流器 | `Muxer` | `narratron/agents/muxer.py` |

**硬性禁止別名**

| 凍結代號 | 禁止寫成 |
| :--- | :--- |
| `Keeper` | Continuity Cop、ContinuityCop、Guard、Watcher |
| `Director` | Planner、Storyboarder、ShotSplitter |
| `Parser` | Extractor、Ingestor、ScriptReader |
| `Runner` | Generator、Worker、Executor |
| `Muxer` | Composer、Editor、PostProcessor |

口語「連續性警察」僅可用來描述 **P6 `Screener` 的產品角色**，不可作為類名、節點名或檔名。

---

## 4. 資料與記憶層 (State Vault)

| 英文代號 | 中文名 | Python / 基礎設施 |
| :--- | :--- | :--- |
| `State Vault` | 狀態庫 | `narratron/vault/`；PostgreSQL + JSONB |
| `Trace Log` | 痕跡日誌 | `narratron/vault/trace_log.py`；表 `trace_log` |
| 向量中樞 | Chroma | `narratron/vault/chroma.py` |
| 快取層 | Redis | `narratron/vault/redis_cache.py` |

凍結表名（欄位見 [`interfaces.md`](interfaces.md)）：

| 表名 | 內容 |
| :--- | :--- |
| `entities` | 角色 / 道具 / 場景 JSONB |
| `shots` | 分鏡 |
| `trace_log` | 因果痕跡 |
| `assets` | 參考圖資產庫 metadata |

禁止：`MemoryBank`、`WorldState`、`ContinuityDB` 作為庫名。

---

## 5. 13 大外掛（檔名 = 小寫代號）

| 編號 | 英文代號 | 中文名 | 檔名 | 觸發時機 |
| :--- | :--- | :--- | :--- | :--- |
| P1 | `Tracer` | 追跡 | `tracer.py` | 生成前 |
| P2 | `Fixer` | 固形 | `fixer.py` | 生成前 |
| P3 | `Forker` | 分岔 | `forker.py` | 生成前 |
| P4 | `Painter` | 調色 | `painter.py` | 生成前 |
| P5 | `Mover` | 擬動 | `mover.py` | 生成前/後 |
| P6 | `Screener` | 篩檢 | `screener.py` | 生成後 |
| P7 | `Router` | 路由 | `router.py` | 生成前 |
| P8 | `Recycler` | 重生 | `recycler.py` | 生成前 |
| P9 | `Player` | 配樂 | `player.py` | 生成後 |
| P10 | `Filter` | 濾聲 | `filter.py` | 生成後 |
| P11 | `Cropper` | 裁切 | `cropper.py` | 生成後 |
| P12 | `Exporter` | 轉檔 | `exporter.py` | 生成後 |
| P13 | `Maker` | 製本 | `maker.py` | 生成後 |

匯流排名稱必須是 `Plug-in Bus`（Python：`PluginBus`），禁止 `PluginHub`、`AddonSystem`。

### 同名消歧

白皮書在兩個分層都使用 `Player`，必須用命名空間區分，不可合併、不可改名：

| 層 | 代號 | 中文 | 路徑 |
| :--- | :--- | :--- | :--- |
| 用戶層 | `Player` | 播放器 | `frontend/player.md` |
| 外掛 P9 | `Player` | 配樂 | `narratron/plugins/player.py` → 類名 `Player` |

`Router` 同樣跨層：P7 外掛負責選池；算力枚舉本身叫 `Big Core` / `Mid Core` / `Alt Core` / `Light Core`，不可把外掛改名成 `PoolSelector`。

---

## 6. 硬體算力池

| 層級 | 代號 | 中文名 | Python 枚舉 |
| :--- | :--- | :--- | :--- |
| L0 | `Big Core` | 大核 | `HardwarePool.L0` / `BigCore` |
| L1 | `Mid Core` | 中核 | `HardwarePool.L1` / `MidCore` |
| L2 | `Alt Core` | 備核 | `HardwarePool.L2` / `AltCore` |
| L3 | `Light Core` | 輕核 | `HardwarePool.L3` / `LightCore` |

相關凍結代號：

| 代號 | 中文 | 路徑 |
| :--- | :--- | :--- |
| `Scheduler` | 排程器 | `narratron/hardware/scheduler.py` |
| `Tier Store` | 分層儲存 | `narratron/hardware/tier_store.py` |

禁止：`GPUPool`、`HeavyCore`、`BackupNPU` 作為層級名。

---

## 7. 用戶層畫面（本階段僅文件，無實作）

| 代號 | 中文 | 路徑 |
| :--- | :--- | :--- |
| `Pad` | 寫板 | `frontend/pad.md` |
| `Timeline` | 時軌 | `frontend/timeline.md` |
| `Dashboard` | 總覽 | `frontend/dashboard.md` |
| `Map` | 因果圖 | `frontend/map.md` |
| `Player` | 播放器 | `frontend/player.md` |

禁止：把 `Pad` 寫成 `Editor`、`ScriptBox`；把 `Map` 寫成 `GraphView`、`CausalGraph`（畫面代號必須是 `Map`）。

---

## 8. 模型農場 (Model Farm)

| 代號族 | 允許實作名 | 路徑 |
| :--- | :--- | :--- |
| FLUX / SDXL | `Flux` | `narratron/models/flux.py` |
| Wan2.1 / LTX | `Wan` | `narratron/models/wan.py` |
| Veo / Seedance | `Veo` | `narratron/models/veo.py` |
| ElevenLabs | `TTS` | `narratron/models/tts.py` |
| FFmpeg | `FFmpeg` | `narratron/models/ffmpeg.py` |

農場集合名稱必須是 `Model Farm`（Python：`ModelFarm`）。

---

## 9. 閘道

| 代號 | 中文 | 路徑 |
| :--- | :--- | :--- |
| API 閘道 | FastAPI | `narratron/api/` |

---

## 9.1 格式層（非智能體）

| 代號 | 中文 | 路徑 |
| :--- | :--- | :--- |
| `Character Passport` / `.charpass` | 角色護照 | `narratron/charpass/`；規格 [`docs/charpass.md`](charpass.md) |

禁止把此格式寫成智能體或第 14 個外掛。用戶層仍只有 Pad / Timeline / Dashboard / Map / Player；角色檢視是 Dashboard 子面板。

---

## 10. 路線圖才出現、本階段禁止建檔的名稱

下列名稱出現在白皮書第五部分，**尚未進入 Plug-in Matrix**，本 repo 不得提前建立模組檔，以免與 P1–P13 矩陣衝突：

| 名稱 | 階段 | 處理 |
| :--- | :--- | :--- |
| `Importer`（匯入器） | Beta Q3 | 文件可提及；不建 `importer.py` |
| 實體常識模擬器 | Gamma | 不建模組 |
| 個人化敘事引擎 / 個人化劇場引擎 | Gamma | 不建模組 |
| GNI（通用敘事智慧） | Gamma | 僅作為階段名 |

`.charpass` 導入邏輯放在 `narratron/charpass/`（`CharpassReader` / `CharpassPacker`），**不是** Beta `Importer`，禁止建 `importer.py`。

---

## 11. 速查（開發必備）

| 類別 | 代號 | 中文 |
| :--- | :--- | :--- |
| 平台 | `Narratron` | 敘事體 |
| 資料庫 | `State Vault` | 狀態庫 |
| 提示引擎 | `Causal Link` | 因果橋 |
| 質檢外掛 | `Screener` | 篩檢 |
| 路由外掛 | `Router` | 路由 |
| 頂級算力 | `Big Core` | 大核 |
| 執行智能體 | `Runner` | 執行器 |
| 因果壓縮 | `Compressor` | 壓縮器 |
| 格式 | `Character Passport` / `.charpass` | 角色護照（非智能體） |
