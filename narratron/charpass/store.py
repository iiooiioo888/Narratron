"""本機角色護照版本庫：每次寫入保留最近 5 版。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from narratron.charpass.schema import (
    LEGACY_MANIFEST_SIDECAR,
    LEGACY_READABLE_SIDECAR,
    LOCAL_CURRENT_FILE,
    MAX_STORED_VERSIONS,
    READABLE_SIDECAR,
    READABLE_SIDECAR_HINT,
    is_json_charpass,
    strip_local_sidecar,
)


def sidecar_manifest(manifest: dict) -> dict:
    """本機可讀 JSON 專用：在 manifest 前加入 IDE 提示，不寫回 ZIP。"""
    return {
        "_local": {
            "hint": READABLE_SIDECAR_HINT,
            "format": "json",
            "spec": "docs/charpass.md",
        },
        **manifest,
    }


class CharpassStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path("data") / "charpasses"

    def entity_dir(self, entity_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in entity_id)
        return self.root / (safe or "unknown")

    def write(self, entity_id: str, blob: bytes, filename: str | None = None) -> Path:
        folder = self.entity_dir(entity_id)
        history = folder / "history"
        history.mkdir(parents=True, exist_ok=True)
        current = folder / LOCAL_CURRENT_FILE
        if current.is_file():
            archive_blob = self._archive_blob(folder, current.read_bytes())
            next_index = self._next_history_index(history)
            (history / f"{next_index:03d}.charpass").write_bytes(archive_blob)
        (folder / "filename.txt").write_text(filename or LOCAL_CURRENT_FILE, encoding="utf-8")
        self._write_local_current(folder, blob)
        self._remove_legacy_sidecars(folder)
        self._prune(folder)
        return current

    def write_manifest(self, entity_id: str, manifest: dict) -> Path:
        """寫入本機可讀 JSON 護照（自動加上 `_local` 提示）。"""
        cleaned = strip_local_sidecar(dict(manifest))
        blob = json.dumps(sidecar_manifest(cleaned), ensure_ascii=False, indent=2).encode("utf-8")
        return self.write(entity_id, blob)

    def read_current(self, entity_id: str) -> bytes | None:
        """讀取目前護照；本機 JSON 會即時打包成 ZIP 供 API／匯出使用。"""
        current = self.entity_dir(entity_id) / LOCAL_CURRENT_FILE
        if not current.is_file():
            return None
        data = current.read_bytes()
        if is_json_charpass(data):
            return self.pack_current(entity_id)
        return data

    def read_current_manifest(self, entity_id: str) -> dict | None:
        """讀取本機可讀 manifest（含 `_local` 提示）。"""
        current = self.entity_dir(entity_id) / LOCAL_CURRENT_FILE
        if not current.is_file():
            return None
        data = current.read_bytes()
        if not is_json_charpass(data):
            exported = self.export_readable(entity_id)
            if exported is None:
                return None
            return json.loads(exported.read_text(encoding="utf-8"))
        return json.loads(data.decode("utf-8"))

    def pack_current(self, entity_id: str) -> bytes | None:
        """把本機 JSON + 資產目錄打包成 ZIP `.charpass` 位元組。"""
        folder = self.entity_dir(entity_id)
        current = folder / LOCAL_CURRENT_FILE
        if not current.is_file():
            return None
        data = current.read_bytes()
        if is_json_charpass(data):
            return self._pack_local_folder(folder, data)
        return data

    def export_readable(self, entity_id: str) -> Path | None:
        """確保本機 `current.charpass` 為可讀 JSON；舊 ZIP 會自動轉換。"""
        folder = self.entity_dir(entity_id)
        current = folder / LOCAL_CURRENT_FILE
        if not current.is_file():
            legacy = self.readable_sidecar_path(folder)
            if legacy.is_file() and legacy != current:
                return self._migrate_legacy_sidecar(folder, legacy)
            return None
        data = current.read_bytes()
        if is_json_charpass(data):
            return current
        return self._write_local_current(folder, data)

    def readable_sidecar_path(self, folder: Path) -> Path:
        """本機可讀護照路徑（新：`current.charpass` JSON；相容舊 sidecar）。"""
        current = folder / LOCAL_CURRENT_FILE
        if current.is_file() and is_json_charpass(current.read_bytes()):
            return current
        for name in (LEGACY_READABLE_SIDECAR, LEGACY_MANIFEST_SIDECAR):
            legacy = folder / name
            if legacy.is_file():
                return legacy
        return current

    def list_versions(self, entity_id: str) -> list[Path]:
        folder = self.entity_dir(entity_id)
        history_dir = folder / "history"
        history = sorted(history_dir.glob("*.charpass")) if history_dir.is_dir() else []
        current = folder / LOCAL_CURRENT_FILE
        if current.is_file():
            return [*history, current]
        return list(history)

    def write_assets(self, entity_id: str, assets: dict[str, bytes]) -> dict[str, Path]:
        """把 ZIP 內嵌資產寫到本機 `data/charpasses/{id}/`，回傳 zip 路徑 → 檔案。"""
        folder = self.entity_dir(entity_id)
        written: dict[str, Path] = {}
        for name, blob in assets.items():
            rel = Path(str(name).replace("\\", "/"))
            parts = [part for part in rel.parts if part not in {"", ".", ".."}]
            if not parts:
                continue
            dest = folder.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            written[name] = dest
        return written

    def write_json(self, entity_id: str, relative_path: str, payload: Any) -> Path:
        """把 JSON 檔寫入角色資料夾下的指定相對路徑。"""
        folder = self.entity_dir(entity_id)
        rel = Path(str(relative_path).replace("\\", "/"))
        parts = [part for part in rel.parts if part not in {"", ".", ".."}]
        if not parts:
            raise ValueError("relative_path must not be empty")
        dest = folder.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dest

    def migrate_entity(self, entity_id: str) -> Path | None:
        """將舊 ZIP `current.charpass` 或 sidecar 轉為本機 JSON 格式。"""
        folder = self.entity_dir(entity_id)
        exported = self.export_readable(entity_id)
        if exported is not None:
            self._remove_legacy_sidecars(folder)
        return exported

    def migrate_all(self) -> int:
        if not self.root.is_dir():
            return 0
        count = 0
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir():
                continue
            if self.migrate_entity(folder.name):
                count += 1
        return count

    def _next_history_index(self, history: Path) -> int:
        indexes: list[int] = []
        for path in history.glob("*.charpass"):
            try:
                indexes.append(int(path.stem))
            except ValueError:
                continue
        return (max(indexes) + 1) if indexes else 1

    def _write_local_current(self, folder: Path, blob: bytes) -> Path | None:
        """寫入本機可讀 JSON `current.charpass`；輸入可為 ZIP 或 JSON。"""
        try:
            from narratron.charpass.container import CharpassReader

            unpacked = CharpassReader().read(blob)
        except Exception:
            return None
        if unpacked.assets:
            self.write_assets(folder.name, unpacked.assets)
        sidecar = sidecar_manifest(unpacked.manifest)
        manifest_path = folder / LOCAL_CURRENT_FILE
        manifest_path.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def _migrate_legacy_sidecar(self, folder: Path, legacy: Path) -> Path | None:
        try:
            manifest = json.loads(legacy.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(manifest, dict):
            return None
        manifest_path = folder / LOCAL_CURRENT_FILE
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if legacy != manifest_path:
            legacy.unlink(missing_ok=True)
        return manifest_path

    def _archive_blob(self, folder: Path, data: bytes) -> bytes:
        if is_json_charpass(data):
            packed = self._pack_local_folder(folder, data)
            if packed is not None:
                return packed
        return data

    def _pack_local_folder(self, folder: Path, json_data: bytes) -> bytes | None:
        try:
            manifest = json.loads(json_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict):
            return None
        manifest = strip_local_sidecar(manifest)
        assets = self._collect_local_assets(folder)
        from narratron.charpass.container import CharpassPacker

        return CharpassPacker().pack(manifest, assets).data

    def _collect_local_assets(self, folder: Path) -> dict[str, bytes]:
        assets: dict[str, bytes] = {}
        for sub in ("assets", "thumb", "causal"):
            subdir = folder / sub
            if not subdir.is_dir():
                continue
            for path in subdir.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(folder).as_posix()
                assets[rel] = path.read_bytes()
        return assets

    def _remove_legacy_sidecars(self, folder: Path) -> None:
        for name in (LEGACY_READABLE_SIDECAR, LEGACY_MANIFEST_SIDECAR):
            legacy = folder / name
            if legacy.is_file() and legacy.name != LOCAL_CURRENT_FILE:
                legacy.unlink(missing_ok=True)

    def _prune(self, folder: Path) -> None:
        current = folder / LOCAL_CURRENT_FILE
        history_dir = folder / "history"
        history = sorted(history_dir.glob("*.charpass")) if history_dir.is_dir() else []
        keep_history = MAX_STORED_VERSIONS - (1 if current.is_file() else 0)
        drop = history[:-keep_history] if keep_history > 0 else history
        for path in drop:
            path.unlink(missing_ok=True)
