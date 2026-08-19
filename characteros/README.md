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
| `GET` | `/api/v1/admin/queue-stats` | 佇列統計（管理用） | 200 |
| `GET` | `/api/v1/admin/metrics` | 系統指標（管理用） | 200 |

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

### 5. 查詢不存在的角色（應回傳 404）

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
│   ├── admin.py             # 管理 API 路由
│   └── health.py            # 健康檢查路由
├── services/
│   ├── __init__.py
│   ├── characters.py        # 角色查詢服務
│   ├── evolution.py         # 演化引擎
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
