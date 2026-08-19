# Pad — 寫板

| 項目 | 值 |
| :--- | :--- |
| 英文代號 | `Pad` |
| 中文名 | 寫板 |
| 狀態 | 僅文件（畫面實作不在本階段） |
| 下游 | `Timeline`；並經 API 閘道進入 `Parser` |

## 職責

創作者輸入劇本與關鍵指令的入口。寫板產出的文本成為 `AgentState.script`，由 `Parser` 提取角色、道具、場景並初始化 `State Vault`。

## 凍結契約

- 畫面代號必須是 `Pad`，禁止 `Editor`、`ScriptBox`。
- 不在前端直接呼叫模型；一律走 API 閘道。
- 不在本階段建立 React/Vue 專案。
