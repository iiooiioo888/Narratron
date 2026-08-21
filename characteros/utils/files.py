"""原子寫入輔助：先寫暫存檔再 rename，避免中途 crash 留下半成品。"""

from __future__ import annotations

from pathlib import Path


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """把文字寫入 path；同目錄先寫 `.tmp` 再 replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(text, encoding=encoding)
        finally:
            tmp.unlink(missing_ok=True)
