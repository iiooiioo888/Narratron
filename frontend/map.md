# Map — 因果圖

| 項目 | 值 |
| :--- | :--- |
| 英文代號 | `Map` |
| 中文名 | 因果圖 |
| 狀態 | Alpha Q1 已通 |
| 上游 | `Dashboard` |
| 下游 | `Player`（播放器） |

## 職責

視覺化 `Trace Log`：角色傷痕、道具磨損、環境累積變化的前因後果圖。每一節點對應 `trace_log` 一筆，而非「當下畫素快照」。

## 凍結契約

- 畫面代號必須是 `Map`，禁止 `GraphView`、`CausalGraph` 作為畫面名。
- 資料只讀自 `Trace Log` / `State Vault`。
