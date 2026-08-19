"""本機角色護照版本庫：每次寫入保留最近 5 版。"""

from __future__ import annotations

from pathlib import Path

from narratron.charpass.schema import MAX_STORED_VERSIONS


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
        current = folder / "current.charpass"
        if current.is_file():
            next_index = self._next_history_index(history)
            current.replace(history / f"{next_index:03d}.charpass")
        (folder / "filename.txt").write_text(filename or "current.charpass", encoding="utf-8")
        tmp = folder / "current.charpass.tmp"
        tmp.write_bytes(blob)
        tmp.replace(current)
        self._prune(folder)
        return current

    def read_current(self, entity_id: str) -> bytes | None:
        current = self.entity_dir(entity_id) / "current.charpass"
        if not current.is_file():
            return None
        return current.read_bytes()

    def list_versions(self, entity_id: str) -> list[Path]:
        folder = self.entity_dir(entity_id)
        history_dir = folder / "history"
        history = sorted(history_dir.glob("*.charpass")) if history_dir.is_dir() else []
        current = folder / "current.charpass"
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

    def _next_history_index(self, history: Path) -> int:
        indexes: list[int] = []
        for path in history.glob("*.charpass"):
            try:
                indexes.append(int(path.stem))
            except ValueError:
                continue
        return (max(indexes) + 1) if indexes else 1

    def _prune(self, folder: Path) -> None:
        current = folder / "current.charpass"
        history_dir = folder / "history"
        history = sorted(history_dir.glob("*.charpass")) if history_dir.is_dir() else []
        keep_history = MAX_STORED_VERSIONS - (1 if current.is_file() else 0)
        drop = history[:-keep_history] if keep_history > 0 else history
        for path in drop:
            path.unlink(missing_ok=True)
