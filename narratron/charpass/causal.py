"""套用 `evolution_log[].changes` 的 `+` / `-` / `→` 增量，維護 snapshot。"""

from __future__ import annotations

import copy
import re
from typing import Any

_CHANGE_LINE = re.compile(
    r"^\s*([+\-]|→|->)\s+(\S+)(?:\s+(.+))?\s*$",
    re.UNICODE,
)
_PATH_TOKEN = re.compile(r"([^.\[\]]+)(?:\[(\d+|\*)\])?")


def parse_change(change: str | dict[str, Any]) -> tuple[str, str, Any]:
    if isinstance(change, dict):
        op = str(change.get("op") or "+")
        path = str(change.get("path") or "")
        return _norm_op(op), path, change.get("value")
    match = _CHANGE_LINE.match(str(change))
    if not match:
        return "+", "", str(change)
    return _norm_op(match.group(1)), match.group(2), _coerce_value(match.group(3))


def _norm_op(op: str) -> str:
    if op in {"→", "->"}:
        return "→"
    if op == "-":
        return "-"
    return "+"


def _coerce_value(raw: str | None) -> Any:
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if text.lower() == "null":
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _iter_changes(changes: Any) -> list[tuple[str, str, Any]]:
    parsed: list[tuple[str, str, Any]] = []
    if isinstance(changes, dict) and "op" in changes and "path" in changes:
        parsed.append(parse_change(changes))
        return parsed
    if isinstance(changes, dict):
        for path, value in changes.items():
            if isinstance(value, list):
                for item in value:
                    parsed.append(_parse_patch_value(str(path), item))
            else:
                parsed.append(_parse_patch_value(str(path), value))
        return parsed
    if isinstance(changes, list):
        for item in changes:
            parsed.append(parse_change(item))
        return parsed
    if changes:
        parsed.append(parse_change(changes))
    return parsed


def _parse_patch_value(path: str, value: Any) -> tuple[str, str, Any]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("+") and not text.startswith("+ "):
            return "+", path, _coerce_value(text[1:])
        if text.startswith("-") and "→" not in text and "->" not in text:
            return "-", path, _coerce_value(text[1:])
        if "→" in text:
            return "→", path, _coerce_value(text.split("→", 1)[1])
        if "->" in text:
            return "→", path, _coerce_value(text.split("->", 1)[1])
        parsed = parse_change(text)
        if parsed[1]:
            return parsed
        return "→", path, _coerce_value(text)
    return "→", path, value


def _split_path(path: str) -> list[tuple[str, str | None]]:
    tokens: list[tuple[str, str | None]] = []
    for match in _PATH_TOKEN.finditer(path):
        tokens.append((match.group(1), match.group(2)))
    return tokens


def _ensure_container(parent: Any, key: str, index: str | None) -> Any:
    if not isinstance(parent, dict):
        return parent
    if index is None:
        if key not in parent or parent[key] is None:
            parent[key] = {}
        return parent[key]
    current = parent.get(key)
    if not isinstance(current, list):
        current = []
        parent[key] = current
    if index == "*":
        return current
    pos = int(index)
    while len(current) <= pos:
        current.append({})
    return current[pos]


def _get_parent_nodes(root: dict[str, Any], path: str) -> list[tuple[Any, str]]:
    tokens = _split_path(path)
    if not tokens:
        return [(root, "")]
    nodes: list[Any] = [root]
    for key, index in tokens[:-1]:
        next_nodes: list[Any] = []
        for node in nodes:
            child = _ensure_container(node, key, index)
            if isinstance(child, list) and index == "*":
                if not child:
                    child.append({})
                next_nodes.extend(child)
            else:
                next_nodes.append(child)
        nodes = next_nodes
    last_key, last_index = tokens[-1]
    parents: list[tuple[Any, str]] = []
    for node in nodes:
        if last_index is None:
            parents.append((node, last_key))
            continue
        if last_index == "*":
            container = _ensure_container(node, last_key, "*")
            if isinstance(container, list):
                for idx, _item in enumerate(container):
                    parents.append((container, str(idx)))
            continue
        container = _ensure_container(node, last_key, last_index)
        if isinstance(node, dict) and isinstance(node.get(last_key), list):
            parents.append((node[last_key], last_index))
        else:
            parents.append((container, last_key))
    return parents


def apply_change(snapshot: dict[str, Any], change: str | dict[str, Any] | tuple[str, str, Any]) -> dict[str, Any]:
    target = copy.deepcopy(snapshot)
    if isinstance(change, tuple):
        op, path, value = change
    else:
        op, path, value = parse_change(change)
    if not path:
        return target
    for parent, key in _get_parent_nodes(target, path):
        _apply_at(parent, key, op, value)
    return target


def _apply_at(parent: Any, key: str, op: str, value: Any) -> None:
    if isinstance(parent, list) and key.isdigit():
        idx = int(key)
        while len(parent) <= idx:
            parent.append(None)
        if op == "-":
            if 0 <= idx < len(parent):
                parent.pop(idx)
            return
        parent[idx] = value
        return
    if not isinstance(parent, dict):
        return
    current = parent.get(key)
    if op == "+":
        if current is None:
            parent[key] = [value] if value is not None else []
        elif isinstance(current, list):
            if value not in current:
                current.append(value)
        elif isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
        else:
            parent[key] = value
        return
    if op == "-":
        if isinstance(current, list) and value in current:
            parent[key] = [item for item in current if item != value]
        elif current == value or value is None:
            parent.pop(key, None)
        return
    parent[key] = value


def apply_evolution_log(
    snapshot: dict[str, Any] | None,
    log: list[Any] | None,
) -> dict[str, Any]:
    state = copy.deepcopy(snapshot or {})
    for entry in log or []:
        changes: Any
        if isinstance(entry, dict):
            changes = entry.get("changes") or []
        else:
            changes = getattr(entry, "changes", []) or []
        for change in _iter_changes(changes):
            state = apply_change(state, change)
    return state


def refresh_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    causal = manifest.setdefault("_causal", {})
    if not isinstance(causal, dict):
        causal = {}
        manifest["_causal"] = causal
    log = causal.get("evolution_log") or []
    snapshot = apply_evolution_log(
        causal.get("current_state_snapshot") or {},
        log,
    )
    scenes = [
        item.get("scene", item.get("scene_index"))
        for item in log
        if isinstance(item, dict) and item.get("scene", item.get("scene_index")) is not None
    ]
    if scenes:
        snapshot.setdefault("as_of_scene", max(int(item) for item in scenes if item is not None))
    causal["current_state_snapshot"] = snapshot
    return manifest


def offset_scene_index(manifest: dict[str, Any], offset: int) -> dict[str, Any]:
    if not offset:
        return manifest
    causal = manifest.get("_causal")
    if not isinstance(causal, dict):
        return manifest
    log = causal.get("evolution_log") or []
    updated: list[Any] = []
    for entry in log:
        if isinstance(entry, dict):
            item = dict(entry)
            for key in ("scene", "scene_index", "heal_scene", "revert_scene"):
                if isinstance(item.get(key), int):
                    item[key] = item[key] + offset
            updated.append(item)
        else:
            updated.append(entry)
    causal["evolution_log"] = updated
    snapshot = causal.get("current_state_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("as_of_scene"), int):
        snapshot["as_of_scene"] = snapshot["as_of_scene"] + offset
    return manifest
