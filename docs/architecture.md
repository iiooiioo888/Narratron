# 架構對照：白皮書分層 → 本 repo

> 白皮書：[`whitepaper-v2.md`](whitepaper-v2.md) §2.1  
> 介面契約：[`interfaces.md`](interfaces.md)  
> 命名：[`naming.md`](naming.md)

本階段狀態標記：

| 標記 | 意義 |
| :--- | :--- |
| **介面已凍結** | 路徑、類名、輸入輸出已鎖定，可 `import` |
| **Alpha Q1 已通** | 可跑讀寫或劇本拆解，不呼叫模型 API |
| **實作待後續季** | 函式 body 為 stub（`NotImplementedError`） |
| **僅文件** | 無程式實作 |

---

## 1. 用戶層 (Frontend - UI)

```
Pad → Timeline → Dashboard → Map → Player
```

| 白皮書節點 | 中文 | 本 repo 路徑 | 狀態 |
| :--- | :--- | :--- | :--- |
| `Pad` | 寫板 | [`frontend/pad.md`](../frontend/pad.md) | 僅文件 |
| `Timeline` | 時軌 | [`frontend/timeline.md`](../frontend/timeline.md) | 僅文件 |
| `Dashboard` | 總覽 | [`frontend/dashboard.md`](../frontend/dashboard.md) | 僅文件 |
| `Map` | 因果圖 | [`frontend/map.md`](../frontend/map.md) | 僅文件 |
| `Player` | 播放器 | [`frontend/player.md`](../frontend/player.md) | 僅文件 |

入口說明：[`frontend/README.md`](../frontend/README.md)

寫板經 API 閘道進入後端，對應邊：`Pad --> API`。

---

## 2. 閘道與編排層 (Gateway & Agents)

```
API → Parser → Director → Keeper → Runner → Muxer
```

| 白皮書節點 | 中文 | 本 repo 路徑 | 狀態 |
| :--- | :--- | :--- | :--- |
| API 閘道 | FastAPI | [`narratron/api/app.py`](../narratron/api/app.py) | Alpha Q1 已通（`/health` `/parse` `/direct`） |
| `Parser` | 解析器 | [`narratron/agents/parser.py`](../narratron/agents/parser.py) | Alpha Q1 已通 |
| `Director` | 調度器 | [`narratron/agents/director.py`](../narratron/agents/director.py) | Alpha Q1 已通 |
| `Keeper` | 守護器 | [`narratron/agents/keeper.py`](../narratron/agents/keeper.py) | 介面已凍結 / 實作待 Q2 |
| `Runner` | 執行器 | [`narratron/agents/runner.py`](../narratron/agents/runner.py) | 介面已凍結 / 實作待 Q3 |
| `Muxer` | 合流器 | [`narratron/agents/muxer.py`](../narratron/agents/muxer.py) | 介面已凍結 / 實作待 Q4 |

LangGraph 編排入口：[`narratron/agents/graph.py`](../narratron/agents/graph.py)  
共享狀態：[`narratron/agents/state.py`](../narratron/agents/state.py)

`Director <--> SQL & Vec & Cache`：調度器透過 [`narratron/vault/state_vault.py`](../narratron/vault/state_vault.py) 讀寫狀態庫。  
`Keeper -.-> Screener & Tracer`：守護器只呼叫外掛介面，不直連 CV / 創傷年表演算法。

---

## 3. 資料與記憶層 (State Vault)

| 白皮書節點 | 中文 | 本 repo 路徑 | 基礎設施 |
| :--- | :--- | :--- | :--- |
| 狀態庫 PostgreSQL+JSONB | `State Vault` | [`narratron/vault/state_vault.py`](../narratron/vault/state_vault.py)、[`schema.py`](../narratron/vault/schema.py) | `docker-compose.yml` → `postgres`；DDL [`docker/init-vault.sql`](../docker/init-vault.sql) |
| 向量中樞 Chroma | Vec | [`narratron/vault/chroma.py`](../narratron/vault/chroma.py) | 本機索引；compose `chroma` |
| 快取層 Redis | Cache | [`narratron/vault/redis_cache.py`](../narratron/vault/redis_cache.py) | 本機 dict；compose `redis` |
| 痕跡日誌 Trace Log | Trace | [`narratron/vault/trace_log.py`](../narratron/vault/trace_log.py) | 與 Vault 同庫、表 `trace_log` |

---

## 4. 三大核心內核

| 白皮書模組 | 中文 | 本 repo 路徑 | 狀態 |
| :--- | :--- | :--- | :--- |
| `Logic Core` | 邏輯內核 | [`narratron/core/logic_core.py`](../narratron/core/logic_core.py) | 介面已凍結 / 實作待 Q2 |
| `Causal Link` | 因果橋 | [`narratron/core/causal_link.py`](../narratron/core/causal_link.py) | 介面已凍結 / 實作待 Q2 |
| `Compressor` | 壓縮器 | [`narratron/core/compressor.py`](../narratron/core/compressor.py) | 介面已凍結 / 實作待 Q2 |

---

## 5. 外掛匯流排 (Plug-in Bus)

匯流排：[`narratron/plugins/bus.py`](../narratron/plugins/bus.py)  
契約：[`narratron/plugins/context.py`](../narratron/plugins/context.py)  
註冊表：[`narratron/plugins/registry.py`](../narratron/plugins/registry.py)

架構圖僅繪出部分外掛；完整 P1–P13 均已建檔：

| 編號 | 代號 | 中文 | 路徑 | 觸發 |
| :--- | :--- | :--- | :--- | :--- |
| P1 | `Tracer` | 追跡 | [`narratron/plugins/tracer.py`](../narratron/plugins/tracer.py) | 生成前 |
| P2 | `Fixer` | 固形 | [`narratron/plugins/fixer.py`](../narratron/plugins/fixer.py) | 生成前 |
| P3 | `Forker` | 分岔 | [`narratron/plugins/forker.py`](../narratron/plugins/forker.py) | 生成前 |
| P4 | `Painter` | 調色 | [`narratron/plugins/painter.py`](../narratron/plugins/painter.py) | 生成前 |
| P5 | `Mover` | 擬動 | [`narratron/plugins/mover.py`](../narratron/plugins/mover.py) | 生成前/後 |
| P6 | `Screener` | 篩檢 | [`narratron/plugins/screener.py`](../narratron/plugins/screener.py) | 生成後 |
| P7 | `Router` | 路由 | [`narratron/plugins/router.py`](../narratron/plugins/router.py) | 生成前 |
| P8 | `Recycler` | 重生 | [`narratron/plugins/recycler.py`](../narratron/plugins/recycler.py) | 生成前 |
| P9 | `Player` | 配樂 | [`narratron/plugins/player.py`](../narratron/plugins/player.py) | 生成後 |
| P10 | `Filter` | 濾聲 | [`narratron/plugins/filter.py`](../narratron/plugins/filter.py) | 生成後 |
| P11 | `Cropper` | 裁切 | [`narratron/plugins/cropper.py`](../narratron/plugins/cropper.py) | 生成後 |
| P12 | `Exporter` | 轉檔 | [`narratron/plugins/exporter.py`](../narratron/plugins/exporter.py) | 生成後 |
| P13 | `Maker` | 製本 | [`narratron/plugins/maker.py`](../narratron/plugins/maker.py) | 生成後 |

`Router` stub **允許回傳預設 `Mid Core`**（見計畫：介面可跑選池，不可跑生成）。其餘外掛 `run()` 皆為 `NotImplementedError`。

---

## 6. 硬體算力池 (Hardware Pools)

| 白皮書節點 | 層級 | 本 repo | 狀態 |
| :--- | :--- | :--- | :--- |
| 大核 H100/A100 | L0 `Big Core` | [`narratron/hardware/pools.py`](../narratron/hardware/pools.py) | 介面已凍結 |
| 中核 4090/5090 | L1 `Mid Core` | 同上 | 介面已凍結；`Router` 預設回傳此池 |
| 備核 昇騰 | L2 `Alt Core` | 同上 | 介面已凍結 / 實作待 Q3–Beta |
| 輕核 CPU | L3 `Light Core` | 同上 | 介面已凍結；`Muxer` 對應此池 |
| `Scheduler` | 分時排程 | [`narratron/hardware/scheduler.py`](../narratron/hardware/scheduler.py) | 介面已凍結 / 實作待 Q3 |
| `Tier Store` | 分層儲存 | [`narratron/hardware/tier_store.py`](../narratron/hardware/tier_store.py) | 介面已凍結 / 實作待 Q4 |

邊：`Runner --> Big & Mid & Alt --> Wan & Veo`；`Muxer --> Light --> FFmpeg`。

---

## 7. 模型農場 (Model Farm)

| 白皮書節點 | 路徑 | 狀態 |
| :--- | :--- | :--- |
| `Model Farm` 集合 | [`narratron/models/farm.py`](../narratron/models/farm.py) | 介面已凍結 |
| FLUX/SDXL | [`narratron/models/flux.py`](../narratron/models/flux.py) | Q1：IP-Adapter **僅排隊**；`generate()` 待 Q3 |
| Wan2.1/LTX | [`narratron/models/wan.py`](../narratron/models/wan.py) | 介面已凍結 / 實作待 Q3 |
| Veo/Seedance | [`narratron/models/veo.py`](../narratron/models/veo.py) | 介面已凍結 / 實作待 Beta |
| ElevenLabs TTS | [`narratron/models/tts.py`](../narratron/models/tts.py) | 介面已凍結 / 實作待 Q4 |
| FFmpeg | [`narratron/models/ffmpeg.py`](../narratron/models/ffmpeg.py) | 介面已凍結 / 實作待 Q4 |

本階段 **禁止** 呼叫任何模型 `generate()` API。生成相關套件僅列於 `pyproject.toml` optional extra `generate`。IP-Adapter 微調只寫入 `assets` 佇列紀錄。

---

## 8. 套件目錄總覽

```
narratron/
  api/          # API 閘道 FastAPI
  agents/       # Parser, Director, Keeper, Runner, Muxer
  core/         # Logic Core, Causal Link, Compressor
  vault/        # State Vault, Trace Log, Chroma, Redis
  plugins/      # Plug-in Bus + P1–P13
  hardware/     # Big/Mid/Alt/Light Core + Scheduler + Tier Store
  models/       # Model Farm 介面（FLUX/Wan/Veo/TTS/FFmpeg）
  charpass/     # Character Passport（.charpass 格式層，非智能體）
frontend/       # Pad / Timeline / Dashboard / Map / Player 僅文件
```

角色護照規格：[`docs/charpass.md`](charpass.md)。Dashboard 角色檢視為總覽子面板。程式：[`narratron/charpass/`](../narratron/charpass/)。

根目錄基礎設施：[`docker-compose.yml`](../docker-compose.yml)（PostgreSQL、Redis、Chroma）；Vault DDL：[`docker/init-vault.sql`](../docker/init-vault.sql)。

---

## 9. 資料流（凍結）

1. `Pad` 送出劇本 → API 閘道。
2. `Parser` 提取角色 / 道具 / 場景，初始化 `State Vault`。
3. `Director` 拆分鏡、寫入 `shots`，讀寫 Vault / Vec / Cache。
4. `Keeper` 讀取 `Trace Log`，經 `Causal Link` + `Compressor` 組提示；呼叫 `Tracer`（生成前）與 `Screener`（生成後）。
5. `Runner` 經 `Plugin Bus` 跑生成前外掛（含 `Router` 選池），再呼叫 `Model Farm`。
6. `Muxer` 在 `Light Core` 上以 FFmpeg 合流；生成後外掛（`Player` 配樂、`Filter`、`Cropper`、`Exporter`、`Maker`）於此段觸發。
