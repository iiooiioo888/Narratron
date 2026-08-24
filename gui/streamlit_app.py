from __future__ import annotations

import json
from typing import Any

import httpx
import streamlit as st
from pyvis.network import Network
from streamlit.components.v1 import html as st_html

from gui.history_store import append_run, load_runs


API_DEFAULT = "http://localhost:8080"


def _client(api_base: str) -> httpx.Client:
    return httpx.Client(base_url=api_base, timeout=60.0)


def _api_call(api_base: str, *, mode: str, script: str, persist: bool) -> dict[str, Any]:
    endpoint = "/parse" if mode == "parse" else "/direct"
    with _client(api_base) as c:
        resp = c.post(endpoint, json={"script": script, "persist": persist})
        resp.raise_for_status()
        return resp.json()


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)


def _build_causal_graph(state: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    entities = state.get("entities") or []
    shots = state.get("shots") or []
    traces = state.get("traces") or []

    net = Network(height="650px", width="100%", directed=True, bgcolor="#0b0b10", font_color="white")

    # entity nodes
    for e in entities:
        kind = _safe_str(e.get("kind"))
        color = {
            "character": "#6aa6ff",
            "prop": "#9b7bff",
            "scene": "#3ddc97",
        }.get(kind, "#aaaaaa")
        net.add_node(
            e.get("id"),
            label=_safe_str(e.get("name")) or e.get("id"),
            group="entity",
            color=color,
            shape="dot",
            title=_safe_str(e.get("payload")),
        )

    # shot nodes
    for s in shots:
        order = s.get("order")
        camera_language = _safe_str(s.get("camera_language"))
        duration_ms = s.get("duration_ms")
        label = f"Shot {order}\n{camera_language}".strip()
        net.add_node(
            s.get("id"),
            label=label,
            group="shot",
            color="#ffcc66",
            shape="box",
            title=f"duration_ms={duration_ms}",
        )

    # trace nodes + edges
    for t in traces:
        trace_id = t.get("id")
        entity_id = t.get("entity_id")
        shot_id = t.get("shot_id")
        cause = _safe_str(t.get("cause"))
        effect = _safe_str(t.get("effect"))
        label = (cause or effect)[:60] or trace_id

        net.add_node(
            trace_id,
            label=label,
            group="trace",
            color="#ff6b6b",
            shape="ellipse",
            title=json.dumps({"cause": cause, "effect": effect, "payload": t.get("payload")}, ensure_ascii=False),
        )

        if entity_id:
            net.add_edge(trace_id, entity_id, title="entity")
        if shot_id:
            net.add_edge(trace_id, shot_id, title="shot")

    # advanced-ish layout: let pyvis physics do the real layout.
    net.set_options(
        """
        var options = {
          "nodes": { "borderWidth": 1, "size": 16, "font": { "size": 12 } },
          "edges": { "arrows": { "to": { "enabled": true, "scaleFactor": 0.5 } }, "smooth": true },
          "physics": {
            "enabled": true,
            "barnesHut": { "gravitationalConstant": -30000, "springLength": 95, "springConstant": 0.04 },
            "stabilization": { "iterations": 200 }
          }
        }
        """
    )

    # pyvis -> html string
    return net.generate_html(), entities, shots


def _page_shell() -> tuple[str, str]:
    st.set_page_config(page_title="Narratron GUI (Alpha Q1)", layout="wide")
    st.title("Narratron GUI (Alpha Q1)")

    api_base = st.sidebar.text_input("API Base", API_DEFAULT)
    st.session_state["__api_base"] = api_base
    runs = load_runs()
    run_id_to_state = {r.run_id: r for r in runs}

    mode = st.sidebar.radio("模式", ["新增", "歷史載入"], index=0)
    selected_run_id = None
    if mode == "歷史載入" and runs:
        selected_run_id = st.sidebar.selectbox(
            "選擇一次運行",
            [f"{r.run_id[:8]} | {r.mode} | {r.created_at[:19]}" for r in runs],
        )
        # find actual run by matching prefix (best-effort)
        prefix = selected_run_id.split("|")[0].strip()
        for r in runs:
            if r.run_id.startswith(prefix):
                state_obj = r
                break
        else:
            state_obj = None
        st.session_state["__history_state"] = state_obj.state if state_obj else None

    page = st.sidebar.radio("畫面", ["Pad", "Timeline", "Dashboard", "Map", "Player"], index=0)
    return api_base, page


def _inspector_for_trace(state: dict[str, Any]) -> None:
    traces = state.get("traces") or []
    if not traces:
        st.info("目前沒有 trace_log（Map/Inspector 沒資料）。")
        return

    trace_options = [f"{t.get('id')[:8]} | {t.get('cause')}" for t in traces]
    default_idx = 0
    selected = st.selectbox("Inspector：選擇一筆 trace_log", trace_options, index=default_idx)

    prefix = selected.split("|")[0].strip()
    trace = next((t for t in traces if str(t.get("id", "")).startswith(prefix)), traces[0])

    st.subheader("Trace Detail")
    st.json(trace)


def page_pad(api_base: str) -> None:
    st.subheader("Pad — 寫板")
    script = st.text_area("劇本", height=220, placeholder="貼上你的腳本…（建議包含：角色/道具/場景 + 分鏡文字）")
    persist = st.checkbox("persist（允許後端 State Vault 存活）", value=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Parse", disabled=not script.strip()):
            with st.spinner("呼叫 POST /parse …"):
                st.session_state["__current_state"] = _api_call(
                    api_base, mode="parse", script=script, persist=persist
                )
                st.session_state["__current_run"] = append_run(
                    mode="parse", script=script, persist=persist, state=st.session_state["__current_state"]
                ).run_id

    with col2:
        if st.button("Direct", disabled=not script.strip()):
            with st.spinner("呼叫 POST /direct …"):
                st.session_state["__current_state"] = _api_call(
                    api_base, mode="direct", script=script, persist=persist
                )
                st.session_state["__current_run"] = append_run(
                    mode="direct", script=script, persist=persist, state=st.session_state["__current_state"]
                ).run_id

    st.divider()
    if st.button("載入最近一次（從歷史）", disabled=not load_runs()):
        st.session_state["__current_state"] = load_runs()[0].state

    state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
    if state:
        st.success("已取得狀態。可切換到 Timeline / Dashboard / Map。")
    else:
        st.warning("尚未取得資料。請先在 Pad 提交 Parse 或 Direct。")


def page_timeline() -> None:
    st.subheader("Timeline — 時軌（shots）")
    state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
    if not state:
        st.info("先去 Pad 提交 / 或在 Sidebar 選擇歷史。")
        return

    shots = state.get("shots") or []
    if not shots:
        st.info("目前 shots 為空。通常是 Parse-only；請使用 Direct 生成 shots。")
        return

    shots_sorted = sorted(shots, key=lambda s: s.get("order", 0))
    shot_ids = [str(item.get("id") or "") for item in shots_sorted]
    selected_id = st.selectbox(
        "選擇 shot",
        shot_ids,
        index=0,
        format_func=lambda shot_id: next(
            (
                f"#{item.get('order')} | {item.get('camera_language')} | {shot_id}"
                for item in shots_sorted
                if str(item.get("id") or "") == shot_id
            ),
            shot_id,
        ),
    )
    shot = next(
        (item for item in shots_sorted if str(item.get("id") or "") == selected_id),
        shots_sorted[0],
    )

    st.subheader("Shot Detail")
    st.json(shot)

    traces = state.get("traces") or []
    shot_traces = [t for t in traces if t.get("shot_id") == shot.get("id")]
    st.subheader("該 shot 對應的 trace_log")
    if not shot_traces:
        st.info("此 shot 尚無 trace_log（可切到 Map/Inspector 檢視初始化痕跡）。")
    else:
        st.json(shot_traces)


def page_dashboard(api_base: str) -> None:
    st.subheader("Dashboard — 總覽（project-level）")
    state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
    if not state:
        st.info("先去 Pad 提交 / 或在 Sidebar 選擇歷史。")
        return

    entities = state.get("entities") or []
    shots = state.get("shots") or []
    traces = state.get("traces") or []
    assets = state.get("assets") or []

    by_kind: dict[str, int] = {}
    for e in entities:
        by_kind[str(e.get("kind"))] = by_kind.get(str(e.get("kind")), 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entities", len(entities))
    c2.metric("Shots", len(shots))
    c3.metric("Trace Records", len(traces))
    c4.metric("Assets", len(assets))

    st.divider()
    st.subheader("算力池（只讀）")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Big Core", "待機")
    p2.metric("Mid Core", "本階段選中")
    p3.metric("Alt Core", "待機")
    p4.metric("Light Core", "待機")
    st.caption("池名凍結自 P7 Router；本階段固定 Mid Core。")

    st.subheader("外掛觸發摘要")
    st.json(
        {
            "P7 Router": "Alpha Q1 可觸發（固定 Mid Core）",
            "其餘 P1–P13": "介面已凍結，執行待後續季",
            "P9 Player": "配樂外掛，與用戶層 Player 同名不同層",
        }
    )

    st.subheader("KPI 預留 · 連續性誤差")
    st.metric("continuity_error", "—")
    st.caption("Keeper（Alpha Q2）尚未回傳此欄位。")

    st.divider()
    st.subheader("Entities by kind")
    st.json(by_kind)

    st.subheader("目前後端階段提示")
    st.write("本 GUI 先對應 Alpha Q1：/parse /direct 可用；/mux /run /keep 目前會回 501。Player 會保留介面但不播放真實合成。")

    st.divider()
    st.subheader("角色護照（.charpass）")
    st.caption("Dashboard 子區塊，不是獨立畫面。導入／導出走 `/api/v1`。")
    characters = [e for e in entities if e.get("kind") == "character"]
    char_id = ""
    if characters:
        labels = [f"{c.get('name')} | {c.get('id')}" for c in characters]
        picked = st.selectbox("選擇角色", labels, index=0)
        prefix = picked.split("|")[-1].strip()
        character = next(
            (c for c in characters if str(c.get("id")) == prefix),
            characters[0],
        )
        char_id = str(character.get("id") or "")
        st.json((character.get("payload") or {}).get("charpass") or {"hint": "尚無 payload.charpass"})
    else:
        char_id = st.text_input("角色 ID（Vault 內 character id）", value="")
        st.info("目前 run 沒有角色時，可直接填 Vault 裡的 id。")

    col_a, col_b = st.columns(2)
    with col_a:
        if char_id and st.button("導出 .charpass"):
            with st.spinner("呼叫 POST /api/v1/characters/{id}/export …"):
                with _client(api_base) as client:
                    resp = client.post(
                        f"/api/v1/characters/{char_id}/export",
                        json={"format": "charpass", "mode": "full", "include_assets": True},
                    )
                    if resp.status_code >= 400:
                        st.error(resp.text)
                    else:
                        st.download_button(
                            "下載 .charpass",
                            data=resp.content,
                            file_name=f"{char_id}.charpass",
                            mime="application/x-narratron-charpass",
                        )
    with col_b:
        strategy = st.selectbox("衝突策略", ["create_new", "merge", "overwrite"], index=1)
        uploaded = st.file_uploader("導入 .charpass", type=["charpass"])
        if uploaded is not None and st.button("開始導入"):
            files = {"file": (uploaded.name, uploaded.getvalue(), "application/x-narratron-charpass")}
            data = {
                "conflict_strategy": strategy,
                "confirm": "true" if strategy == "overwrite" else "false",
            }
            with _client(api_base) as client:
                resp = client.post("/api/v1/projects/streamlit/characters/import", files=files, data=data)
                if resp.status_code >= 400:
                    st.error(resp.text)
                else:
                    st.success("導入完成")
                    st.json(resp.json())


def page_map() -> None:
    st.subheader("Map — 因果圖（Trace Log 視覺化，只讀）")
    state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
    if not state:
        st.info("先去 Pad 提交 / 或在 Sidebar 選擇歷史。")
        return

    html_str, entities, shots = _build_causal_graph(state)
    traces = state.get("traces") or []
    st.caption(f"節點：entities={len(entities)} / shots={len(shots)} / traces={len(traces)}")
    st_html(html_str, height=700, scrolling=True)
    st.divider()
    _inspector_for_trace(state)


def page_player() -> None:
    st.subheader("Player — 播放器")
    state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
    if not state:
        st.info("先去 Pad 提交 / 或在 Sidebar 選擇歷史。")
        return

    mux_uri = state.get("mux_uri")
    if mux_uri:
        st.success("已取得 mux_uri。")
        st.write(mux_uri)
        if str(mux_uri).startswith("http"):
            st.video(str(mux_uri))
        return

    st.warning("Muxer 尚未上線（POST /mux 仍為 501）。此畫面維持 Player 代號，以下先以分鏡序列播放。")
    shots = sorted(state.get("shots") or [], key=lambda item: item.get("order", 0))
    if not shots:
        st.info("目前沒有 shots。請先在 Pad 執行 Direct。")
        return

    labels = [
        f"#{item.get('order')} · {item.get('camera_language')} · {item.get('duration_ms')}ms"
        for item in shots
    ]
    picked = st.selectbox("分鏡序列", labels, index=0)
    prefix = picked.split("·")[0].replace("#", "").strip()
    shot = next((item for item in shots if str(item.get("order")) == prefix), shots[0])
    st.json(shot)
    total_ms = sum(int(item.get("duration_ms") or 0) for item in shots)
    st.caption(f"序列總長 {total_ms}ms · 合流成品待 Alpha Q4")


def main() -> None:
    api_base, page = _page_shell()

    # ensure containers exist
    left, right = st.columns([2, 1])
    with left:
        if page == "Pad":
            page_pad(api_base)
        elif page == "Timeline":
            page_timeline()
        elif page == "Dashboard":
            page_dashboard(api_base)
        elif page == "Map":
            page_map()
        elif page == "Player":
            page_player()

    with right:
        st.subheader("Inspector / 狀態")
        state = st.session_state.get("__current_state") or st.session_state.get("__history_state")
        if not state:
            st.info("無目前狀態。")
        else:
            st.write(f"mode(history/current)：{st.session_state.get('__current_run', 'unknown')}")
            st.write(f"shots={len(state.get('shots') or [])} traces={len(state.get('traces') or [])}")


if __name__ == "__main__":
    main()

