# 本機角色護照版本庫

每個角色目錄（例如 `character-卡爾/`）包含：

| 檔案 | 用途 |
| :--- | :--- |
| **`current.charpass`** | **本機 L0 可讀 JSON，請在 IDE 開此檔** |
| `filename.txt` | 匯出檔名（如 `卡爾_9ae91e.charpass`） |
| `history/` | 最近 5 版 ZIP 二進位快照（匯出／備份用） |
| `assets/`、`thumb/` | 內嵌資產（若有） |

本機 `current.charpass` 是可讀 JSON；透過 API 匯出或寫入 `history/` 時會自動打包成 ZIP 二進位。

手動解包或遷移舊 ZIP：

```bash
python scripts/inspect_charpass.py data/charpasses/character-卡爾
python scripts/inspect_charpass.py --all
```

規格：[`docs/charpass.md`](../../docs/charpass.md)
