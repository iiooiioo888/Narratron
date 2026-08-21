# Timeline — 時軌

| 項目 | 值 |
| :--- | :--- |
| 英文代號 | `Timeline` |
| 中文名 | 時軌 |
| 狀態 | Alpha Q1 已通 |
| 上游 | `Pad` |
| 下游 | `Dashboard` |

## 職責

以時間軸呈現 `Director` 拆出的 `shots`（分鏡、鏡頭語言、時序節奏）。創作者在此檢視與調整鏡頭順序，但不繞過 `Keeper` 的因果守護。

## 凍結契約

- 畫面代號必須是 `Timeline`。
- 分鏡資料來源是 State Vault 表 `shots`，不是前端私有 state。
