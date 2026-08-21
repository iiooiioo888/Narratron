from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class GuiRun:
    run_id: str
    created_at: str
    mode: str  # "parse" | "direct"
    script: str
    persist: bool
    state: dict[str, Any]


def _history_path() -> Path:
    base = Path.home() / ".narratron"
    return base / "gui_history.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_runs() -> list[GuiRun]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    runs: list[GuiRun] = []
    for item in raw.get("runs", []):
        try:
            runs.append(
                GuiRun(
                    run_id=str(item["run_id"]),
                    created_at=str(item["created_at"]),
                    mode=str(item["mode"]),
                    script=str(item["script"]),
                    persist=bool(item["persist"]),
                    state=dict(item["state"]),
                )
            )
        except Exception:
            continue
    # newest first
    return sorted(runs, key=lambda r: r.created_at, reverse=True)


def save_runs(runs: list[GuiRun]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "runs": [
            {
                "run_id": r.run_id,
                "created_at": r.created_at,
                "mode": r.mode,
                "script": r.script,
                "persist": r.persist,
                "state": r.state,
            }
            for r in runs
        ]
    }
    tmp = path.with_name(f"{path.name}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(text, encoding="utf-8")
        finally:
            tmp.unlink(missing_ok=True)


def create_run_id() -> str:
    return uuid4().hex


def append_run(*, mode: str, script: str, persist: bool, state: dict[str, Any]) -> GuiRun:
    run = GuiRun(
        run_id=create_run_id(),
        created_at=_now_iso(),
        mode=mode,
        script=script,
        persist=persist,
        state=state,
    )
    runs = load_runs()
    runs.insert(0, run)
    save_runs(runs)
    return run

