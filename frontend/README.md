# 用戶層 (Frontend - UI)

本目錄對應白皮書 §2.1 用戶層。文件規格仍以本目錄為準，另提供一份可執行 Web GUI 原型於 `frontend/webapp/`。

資料流：

```
Pad（寫板）→ Timeline（時軌）→ Dashboard（總覽）→ Map（因果圖）→ Player（播放器）
Pad → API 閘道
```

| 代號 | 中文 | 說明檔 |
| :--- | :--- | :--- |
| `Pad` | 寫板 | [`pad.md`](pad.md) |
| `Timeline` | 時軌 | [`timeline.md`](timeline.md) |
| `Dashboard` | 總覽 | [`dashboard.md`](dashboard.md) |
| `Map` | 因果圖 | [`map.md`](map.md) |
| `Player` | 播放器 | [`player.md`](player.md) |

`Player`（播放器）與外掛 P9 `Player`（配樂）同名不同層，見 [`docs/naming.md`](../docs/naming.md)。

目前原型：

- `frontend/webapp/`：`React + Vite + TypeScript` GUI，含 `Pad / Timeline / Dashboard / Map / Player`
- 門面 App Shell：`characteros/static/index.html`（`http://localhost:8001/`）
- `Map` 使用圖形節點視覺化因果關係
- 支援前端本地多專案、多次 `parse/direct` 歷史持久化
- `Player` 在 Muxer 未上線時改播分鏡序列，不改名為 Preview / Viewer

仍禁止在本目錄放入與白皮書無關的畫面名（如 Editor、GraphView）。
