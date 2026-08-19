# CharacterOS

Narratron 的角色控制子系統。目錄名 = Python 套件名：`characteros/`。

**One ID, Infinite Evolutions.**

一個「唯讀、可演化、高擴展」的 AI 角色資產管理後端。

凍結代號是 `CharacterOS`，禁止別名見 [`docs/naming.md`](../docs/naming.md)。

## 專案狀態

- **版本**: v1.0.0-sprint1
- **階段**: Sprint 1（基礎設施與核心資料層）
- **目標**: 建立資料庫、定義 ORM、實現最基礎的唯讀查詢

## 快速啟動

### 前置需求

- Docker & Docker Compose
- 或 Python 3.11+（本地開發）

### 使用 Docker Compose（基礎設施）

CharacterOS API 與 Narratron 共用根目錄 `docker-compose.yml` 的 Postgres；專用庫名為 `characteros`（與 State Vault 的 `narratron_vault` 分離）。API 埠為 **8001**，避開 Chroma 的 8000 與閘道的 8080。

```bash
# 在 repo 根目錄執行

# 1. 複製環境設定檔
cp .env.example .env

# 2. 啟動 Postgres / Redis / Chroma（會建立 characteros 庫並套用 DDL）
docker compose up -d

# 3. 安裝依賴並啟動 CharacterOS（勿另裝舊版 FastAPI，會與根目錄衝突）
pip install -e ".[dev,infra,characteros]"
uvicorn characteros.main:app --reload --host 0.0.0.0 --port 8001

# 4. 訪問 API 文件
open http://localhost:8001/docs
```

### 本地開發（已有 Postgres）

```bash
# 在 repo 根目錄執行

# 1. 安裝依賴
pip install -e ".[dev,infra,characteros]"

# 2. 建立 characteros 庫並執行 DDL
#    psql -U narratron -d characteros -f characteros/migrations/schema.sql

# 3. 設定環境變數（勿覆寫 State Vault 的 DATABASE_URL）
export CHARACTEROS_DATABASE_URL="postgresql://narratron:narratron@localhost:5432/characteros"

# 4. 啟動開發伺服器
uvicorn characteros.main:app --reload --host 0.0.0.0 --port 8001

# 5. 訪問 API 文件
open http://localhost:8001/docs
```

## API 端點

| 方法 | 路徑 | 功能 | 回應碼 |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | API 基本資訊 | 200 |
| `GET` | `/health` | 健康檢查 | 200 / 503 |
| `GET` | `/api/v1/characters` | 列出所有角色 | 200 |
| `GET` | `/api/v1/characters/{id}` | 取得角色完整檔案 | 200 / 404 |
| `GET` | `/api/v1/characters/{id}/variant` | 請求變體生成 | 200 / 202 / 404 |
| `GET` | `/api/v1/characters/{id}/variants` | 列出角色所有變體 | 200 / 404 |
| `POST` | `/api/v1/characters/{id}/images` | 依角色風格呼叫第三方生圖 | 200 / 404 / 502 |
| `GET` | `/api/v1/imaging/providers` | 列出生圖 provider | 200 |
| `POST` | `/api/v1/imaging/generate` | 依護照組 prompt 並生圖 | 200 / 404 / 502 |
| `GET` | `/api/v1/admin/queue-stats` | 佇列統計（管理用） | 200 |
| `GET` | `/api/v1/admin/metrics` | 系統指標（管理用） | 200 |
| `GET` | `/api/v1/admin/imaging-config` | 讀取生圖設定（含 key 狀態） | 200 |
| `PUT` | `/api/v1/admin/imaging-config` | 更新生圖 endpoint/model/api key | 200 |

## 測試範例

### 1. 健康檢查

```bash
curl http://localhost:8001/health
```

### 2. 取得角色列表

```bash
curl http://localhost:8001/api/v1/characters
```

### 3. 取得角色完整資訊（林默，ID=1）

```bash
curl http://localhost:8001/api/v1/characters/1 | jq
```

### 4. 請求變體生成（80 歲的林默）

```bash
# 首次請求：回傳 202 Accepted（排入佇列）
curl -i "http://localhost:8001/api/v1/characters/1/variant?age=80"

# 再次請求：若已生成完成，回傳 200 OK + 變體資訊
curl "http://localhost:8001/api/v1/characters/1/variant?age=80"
```

### 5. 依角色風格生圖（預設 `null` provider，只組 prompt 不打網路）

```bash
# 列出可插拔 provider
curl http://localhost:8001/api/v1/imaging/providers

# 從本機護照組提示詞（卡爾）
curl -X POST http://localhost:8001/api/v1/imaging/generate \
  -H "Content-Type: application/json" \
  -d '{"entity_id":"character-卡爾","purpose":"identity","provider":"null"}'
```

環境變數 `CHARACTEROS_IMAGE_GEN_PROVIDER=http|openai|wan` 可改打第三方 API；HTTP 契約見 `characteros/imaging/providers/http_webhook.py`。

### 5.1 設定 WAN 生圖介面（百煉原生 API）

預設模型與 workspace 根網址（compatible-mode 會自動換算為原生 endpoint）：

- model: `wan2.7-image-pro`
- base_url: `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- 實際請求：`…/api/v1/services/aigc/multimodal-generation/generation`（**非** OpenAI `/images/generations`）

**API Key 入口** — 管理 API（寫入 DB + 可選同步 `.env`）：

```bash
# 讀取目前設定（不回傳 key 明文，只回 has_api_key）
curl http://localhost:8001/api/v1/admin/imaging-config

# 設定 WAN + API Key
curl -X PUT http://localhost:8001/api/v1/admin/imaging-config \
  -H "Content-Type: application/json" \
  -d '{
    "provider":"wan",
    "base_url":"https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "model":"wan2.7-image-pro",
    "api_key":"<YOUR_API_KEY>",
    "persist_env": true
  }'
```

`persist_env: false` 時僅寫入資料庫，不修改 `.env`。

或用環境變數（啟動時載入；若 DB 已有設定則以 DB 為準）：

- `CHARACTEROS_IMAGE_GEN_PROVIDER`
- `CHARACTEROS_OPENAI_IMAGES_BASE_URL`
- `CHARACTEROS_OPENAI_IMAGES_MODEL`
- `CHARACTEROS_IMAGE_GEN_API_KEY`（亦相容 `OPENAI_API_KEY`）

### 6. 查詢不存在的角色（應回傳 404）

```bash
curl -i http://localhost:8001/api/v1/characters/999
```

## 專案結構

```
characteros/                 # 與 gui/、narratron/ 相同：目錄名 = Python 套件名
├── __init__.py
├── main.py                  # FastAPI 應用入口
├── models/
│   ├── __init__.py
│   ├── database.py          # 資料庫連線配置
│   ├── orm.py               # SQLAlchemy ORM 模型
│   └── schema.py            # Pydantic 驗證模式（單數，對齊 narratron/vault/schema.py）
├── routers/
│   ├── __init__.py
│   ├── characters.py        # 角色 API 路由
│   ├── imaging.py           # 第三方生圖路由
│   ├── admin.py             # 管理 API 路由
│   └── health.py            # 健康檢查路由
├── imaging/
│   ├── base.py              # ImageGenProvider 契約
│   ├── registry.py          # provider 註冊
│   └── providers/           # null / http / openai
├── services/
│   ├── __init__.py
│   ├── characters.py        # 角色查詢服務
│   ├── evolution.py         # 演化引擎
│   ├── imaging.py           # 生圖編排（組 prompt → provider → 寫回護照）
│   └── queue.py             # 佇列管理
├── utils/
│   ├── __init__.py
│   └── hash.py              # 變體指紋
├── migrations/
│   └── schema.sql           # 資料庫 DDL
├── requirements.txt         # 僅 CharacterOS 專用依賴（其餘見根目錄 pyproject.toml）
└── README.md                # 本檔案
```

基礎設施（Postgres 初始化）在 repo 根目錄：`docker-compose.yml`、`docker/init-characteros.sh`。

## Sprint 1 驗收標準

- [x] 可透過 `docker compose up` 啟動 Postgres，並建立 `characteros` 庫
- [x] 執行 `GET /api/v1/characters/1` 能正確回傳林默的完整 `.charpass` JSON
- [x] 執行 `GET /api/v1/characters/999` 回傳 `404 Not Found`
- [x] 執行 `GET /api/v1/characters/1/variant?age=80` 首次回傳 `202 Accepted` + `queue_id`
- [x] 同一請求重複發送多次，只寫入一筆 pending 記錄（冪等性保護）

## 資料庫架構

### 三層儲存設計

1. **character_cores**: 角色核心身份（不可變）
   - UUID、名稱、性別光譜、基準年齡、身份錨點

2. **character_profiles**: 專案檔案（可版本化）
   - 版本號、啟用狀態、完整 Manifest (JSONB)

3. **character_variants**: 變體快取（演化結果）
   - Variant Hash、演化參數、狀態（pending/ready/failed）

詳細 DDL 請參考 `characteros/migrations/schema.sql`。

## 下一步（Sprint 2）

- [ ] 實作 Redis 分散式鎖
- [ ] 優化佇列管理（優先級排序）
- [ ] Profile 版本變更時的快取失效機制
- [ ] 更多演化規則（情緒、場景、傷痕）

## 授權

與主專案相同：Proprietary。禁止另標 MIT，以免與根目錄 `pyproject.toml` 衝突。
