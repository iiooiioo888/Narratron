# Narratron 全面檢查報告

**審查日期**：2026-08-20  
**審查範圍**：全倉庫（Narratron Core + CharacterOS + GUI + 前端文件）  
**程式碼規模**：~21,590 行 Python，約 100+ 模組

---

## 一、架構總覽

Narratron 是一個 AI 影視級因果敘事生成平台，由兩個主要子系統構成：

| 子系統 | 職責 | 當前狀態 |
|--------|------|----------|
| **Narratron Core** | 劇本解析 (Parser) → 分鏡調度 (Director) → State Vault + Trace Log | Alpha Q1 可跑 |
| **CharacterOS** | 角色資產管理 (.charpass) → 生圖管線 → 佇列 worker | Sprint 1 可跑 |

**雙軌儲存架構**：PostgreSQL 可選，本機 JSON 自動降級（graceful degradation），設計合理。

---

## 二、🔴 嚴重問題（必須修復）

### 2.1 安全性問題

#### P0-1：CORS 全開
```python
# characteros/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ 生產環境應限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**風險**：任何網站都能呼叫 API，配合 `allow_credentials=True` 可導致 CSRF 攻擊。
**建議**：改為白名單制，至少限制為 `localhost` + 實際部署域名。

#### P0-2：API Key 明文傳輸
```python
# characteros/services/image_pipeline.py
evolution_params["_image_request"] = {
    "api_key": body.api_key,  # ⚠️ API Key 存入佇列 JSON
    ...
}
```
**風險**：API Key 被寫入 `data/charpasses/.characteros-queue.json` 明文檔，任何有檔案讀取權限的人都能取得。
**建議**：
- 佇列中只存 key 的 fingerprint/reference，不存明文
- 實際 key 從環境變數或安全儲存讀取

#### P0-3：面板 Header 保護薄弱
```python
# characteros/routers/characters.py
panel_header = request.headers.get("X-CharacterOS-Panel", "").strip().lower()
if panel_header != "enabled":
    raise HTTPException(status_code=403, ...)
```
**風險**：任何人都能加 `X-CharacterOS-Panel: enabled` header 繞過限制。
**建議**：改用 session token 或 CSRF token 驗證。

### 2.2 資料完整性問題

#### P0-4：佇列 JSON 檔非原子寫入
```python
# characteros/storage/local_queue.py
def _save(self, data: dict[str, Any]) -> None:
    self._path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
```
**風險**：若寫入中途 crash（斷電、kill -9），JSON 檔會損壞，所有佇列任務遺失。
**建議**：採用 write-to-temp-then-rename 模式（`CharpassStore` 已有此做法，應統一）。

#### P0-5：`CharpassStore.write_manifest` 的 `_archive_blob` 可能失敗無聲
```python
def _archive_blob(self, folder: Path, data: bytes) -> bytes:
    if is_json_charpass(data):
        packed = self._pack_local_folder(folder, data)
        if packed is not None:
            return packed
    return data  # fallback：直接返回原始 JSON bytes
```
**風險**：ZIP 打包失敗時靜默降級，歷史快照變成 JSON 而非 ZIP，後續 `_migrate_legacy_sidecar` 可能混淆。

---

## 三、🟠 使用者操作體驗問題（UX 優化重點）

### 3.1 GUI 面板（/admin/panel）

#### UX-1：1,800+ 行單一 HTML 檔案
`characteros/routers/panel.py` 將整個 GUI 面板（HTML + CSS + JS）寫在一個 Python 字串中。
- **問題**：無法 syntax highlighting、無法單元測試、無法版本 diff、開發體驗極差
- **建議**：抽離為 `characteros/static/panel.html`，用 `StaticFiles` 掛載

#### UX-2：角色清單無分頁且效能差
```python
# characteros/storage/local_characters.py
def list_characters(self, skip=0, limit=20, ...):
    for cid_str in sorted(entities.keys(), key=lambda x: int(cid_str)):
        manifest = self.store.read_current_manifest(entity_id)  # ⚠️ 每個角色都讀檔
```
**問題**：100 個角色 = 100 次磁碟 IO，清單載入緩慢。
**建議**：index 檔應缓存 name/tags/thumbnail 等摘要資訊，避免逐一讀取完整 manifest。

#### UX-3：年齡軸操作流程不直覺
目前流程：選角色 → 選 age_span → 按「建立 1–80 歲」→ 等待 → 手動接受 → 自動下一步。
- **問題**：
  - 使用者不知道「接受」是必要的（很多任務會卡在 `ready` 等 review）
  - 沒有「全部接受」按鈕
  - 年齡軸 1–80 歲 = 160 步，每步都要手動接受 = 災難
- **建議**：
  - 新增「自動接受所有」開關
  - 年齡軸預設 `auto_accept=True`（已生成的圖直接入庫）
  - 或提供「批次接受」功能

#### UX-4：錯誤訊息不友善
```python
raise HTTPException(
    status_code=501,
    detail=f"{agent} 實作待 {quarter}；禁止在本階段跑生成。",
)
```
**問題**：使用者看到 501 + 技術文字，不知道該怎麼辦。
**建議**：提供引導性錯誤訊息，例如「此功能尚未上線，預計 Q2 開放。請先使用 /parse 和 /direct。」

#### UX-5：生圖結果預覽區塊不明顯
圖片預覽在佇列表格下方，需要捲動才能看到。
- **建議**：生圖完成後自動彈出預覽 modal，或在「目前步驟」卡片直接顯示大圖。

#### UX-6：缺少 Loading 狀態與操作回饋
- 按下「生圖」後只有狀態列文字更新，無 spinner 或 progress bar
- 佇列自動刷新需要手動開啟（預設關閉）
- **建議**：生圖進行中顯示明確的 loading indicator，自動刷新預設開啟

### 3.2 CLI 體驗（characteros-cli）

#### UX-7：CLI 無互動模式
```bash
characteros-cli char show --entity-id character-卡爾 --path _style.character_style.visual.medium
```
**問題**：需要記住 entity-id 和 JSON 路徑，學習成本高。
**建議**：提供互動式 TUI（如 `rich` + `prompt_toolkit`），支援 Tab 自動補全。

#### UX-8：generate 命令已停用但仍在 help 中
```python
sp_generate = sub.add_parser("generate", help="（已停用）僅保留相容...")
```
**建議**：停用的命令應標記為 deprecated 或從 help 中隱藏。

### 3.3 Streamlit GUI（gui/streamlit_app.py）

#### UX-9：Streamlit GUI 與 CharacterOS 面板功能重疊
兩個 GUI 都能操作角色，但資料來源不同（Narratron API vs CharacterOS API），容易混淆。
- **建議**：統一為單一入口，或明確區分使用場景

#### UX-10：歷史載入 UX 不佳
```python
selected_run_id = st.sidebar.selectbox(
    "選擇一次運行",
    [f"{r.run_id[:8]} | {r.mode} | {r.created_at[:19]}" for r in runs],
)
```
**問題**：run_id 只顯示前 8 字元，多筆記錄難以區分。
**建議**：顯示劇本摘要（前 30 字元）+ 實體數量 + 時間。

---

## 四、🟡 程式碼品質問題

### 4.1 依賴管理

#### CQ-1：`pyproject.toml` 缺少 `python-dotenv`
```toml
# characteros/main.py 使用了 dotenv
from dotenv import load_dotenv
# 但 pyproject.toml 的 dependencies 中沒有 python-dotenv
```
只有 `characteros` optional-dependencies 有，但 `characteros/main.py` 是主入口。

#### CQ-2：`docker-compose.yml` 被 .gitignore 排除
```
# .gitignore
docker-compose.yml
```
**問題**：團隊成員 clone 後無法直接 `docker compose up`，違反 IaC 原則。
**建議**：移除此規則，或改用 `docker-compose.override.yml`（被 ignore 的那個）。

### 4.2 程式碼結構

#### CQ-3：測試暫存檔被提交到 repo
```
.pytest-tmp/   ← 應在 .gitignore
.tmp-pytest/   ← 應在 .gitignore
_tmp_queue_status.py  ← 臨時檔，不應在 repo
```
**建議**：加入 `.gitignore` 並從 repo 中移除。

#### CQ-4：Parser 和 Director 有大量重複的 regex
```python
# narratron/agents/parser.py
_SCENE_HEADING = re.compile(r"^(?:(?:INT|EXT|...).*$", re.I)
_SECTION = re.compile(r"^(角色|人物|...)[：:\s]*$", re.I)

# narratron/agents/director.py
_SCENE_HEADING = re.compile(r"^(?:(?:INT|EXT|...).*$", re.I)  # 完全相同
_SECTION = re.compile(r"^(角色|人物|...)[：:\s]*$", re.I)      # 完全相同
```
**建議**：抽取到 `narratron/parsing/patterns.py` 共用。

#### CQ-5：`_now()` 函數重複定義
`datetime.now(timezone.utc)` 至少在 5 個檔案中各自定義為 `_now()`。
**建議**：統一到 `narratron/utils/time.py`。

#### CQ-6：admin.py 過度長且職責混雜
`characteros/routers/admin.py` 包含 15+ 個端點，涵蓋佇列管理、worker 控制、設定管理、指標監控。
**建議**：拆分為 `admin_queue.py`、`admin_worker.py`、`admin_config.py`、`admin_metrics.py`。

### 4.3 錯誤處理

#### CQ-7：全域 Exception handler 吞掉 traceback
```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```
**問題**：雖然有 `exc_info=True`，但回傳給前端的 `detail` 完全不含有用資訊，除錯困難。
**建議**：開發模式下回傳更多資訊（用環境變數控制）。

#### CQ-8：SQLAlchemy session 管理不一致
部分路由使用 `Depends(get_db)` 自動管理 session，但 `startup_event` 中手動開關：
```python
db = SessionLocal()
try:
    settings.load_from_db(db)
finally:
    db.close()
```
**建議**：統一使用 context manager 或 dependency injection。

---

## 五、🟢 優化建議（提升開發效率與使用者滿意度）

### 5.1 快速見效的改動

| # | 改動 | 預估工時 | 影響 |
|---|------|----------|------|
| 1 | `.gitignore` 加入 `.pytest-tmp/` `.tmp-pytest/` `_tmp_*.py` | 5 min | 清理 repo |
| 2 | 移除 `.gitignore` 中的 `docker-compose.yml` | 5 min | 團隊可直接 docker up |
| 3 | CORS 改為白名單 | 15 min | 安全性 |
| 4 | 佇列 JSON 改為 atomic write | 30 min | 資料完整性 |
| 5 | 年齡軸預設 auto_accept | 1 hr | UX 大幅改善 |
| 6 | 新增「批次接受」API + 按鈕 | 2 hr | UX 大幅改善 |
| 7 | 錯誤訊息本地化 + 引導性 | 2 hr | UX |
| 8 | 抽離 panel.py 的 HTML 為獨立檔案 | 3 hr | 開發體驗 |

### 5.2 中期改進

| # | 改動 | 預估工時 | 影響 |
|---|------|----------|------|
| 9 | 角色清單 index 快取摘要 | 4 hr | 效能 |
| 10 | 統一 regex patterns 到共用模組 | 2 hr | 程式碼品質 |
| 11 | API Key 不存入佇列 JSON | 3 hr | 安全性 |
| 12 | admin.py 拆分 | 4 hr | 可維護性 |
| 13 | 新增 API integration tests | 8 hr | 品質保障 |
| 14 | Streamlit GUI 整合或棄用決策 | 4 hr | UX 一致性 |

### 5.3 長期建議

| # | 改動 | 影響 |
|---|------|------|
| 15 | 引入 OpenAPI 自動化測試（schemathesis） | API 合約保障 |
| 16 | 新增 CI/CD pipeline（GitHub Actions） | 自動化品質把關 |
| 17 | 前端從 inline HTML 遷移到 React/Vue SPA | 可維護性、效能 |
| 18 | 引入 WebSocket 即時推送佇列狀態 | UX 即時性 |

---

## 六、架構亮點（做得好的地方）

1. **雙軌儲存 graceful degradation**：PostgreSQL 不可用時自動降級到本機 JSON，zero-config 開發體驗優秀
2. **Causal Trace Log 設計**：每一步操作都有因果記錄，為後續「因果壓縮包」願景打好基礎
3. **Charpass 版本管理**：自動保留最近 5 版歷史快照，支援 ZIP ↔ JSON 雙向轉換
4. **年齡軸 pipeline 設計**：一次只處理一張圖，完成後自動入列下一步，避免 GPU 資源浪費
5. **Plugin 架構預留**：13 個 Plugin 介面已定義，為 Q2–Q4 擴展做好準備
6. **契約測試**：`test_contracts.py` 確保 API 回應格式穩定

---

## 七、優先順序建議（操作優化路線圖）

### 第一週：安全 + 資料完整性
1. 修復 CORS 白名單
2. API Key 不存入佇列 JSON
3. 佇列 JSON atomic write
4. 清理 repo（.gitignore + 移除暫存檔）

### 第二週：UX 核心改善
5. 年齡軸 auto_accept 預設
6. 新增「批次接受」功能
7. 錯誤訊息引導化
8. 生圖完成自動彈出預覽

### 第三週：開發體驗
9. 抽離 panel HTML 為獨立檔案
10. 統一 regex / _now() 等共用模組
11. admin.py 拆分

### 第四週：品質保障
12. 新增 integration tests
13. CI/CD pipeline
14. 角色清單效能優化
