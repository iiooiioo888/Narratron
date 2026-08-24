"""原子寫入輔助：先寫暫存檔再 rename，避免中途 crash 留下半成品。"""

from __future__ import annotations

import errno
from collections.abc import Callable
from pathlib import Path


def is_no_space_error(exc: BaseException | None) -> bool:
    """磁碟空間不足（POSIX ENOSPC / Windows ERROR_DISK_FULL）。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError):
            disk_full_errnos = {errno.ENOSPC}
            if hasattr(errno, "EDQUOT"):
                disk_full_errnos.add(errno.EDQUOT)
            if current.errno in disk_full_errnos:
                return True
            if getattr(current, "winerror", None) == 112:
                return True
            message = str(current).lower()
            if "no space left" in message or "disk full" in message:
                return True
        current = current.__cause__ or current.__context__
    return False


def _write_atomic(path: Path, writer: Callable[[Path], None]) -> None:
    """同目錄先寫 `.tmp` 再 replace。磁碟滿時不二次寫入，並清掉暫存檔。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        writer(tmp)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    try:
        tmp.replace(path)
    except OSError as exc:
        if is_no_space_error(exc):
            tmp.unlink(missing_ok=True)
            raise
        # replace 失敗（非磁碟滿）：直接寫目標檔，再清暫存
        try:
            writer(path)
        finally:
            tmp.unlink(missing_ok=True)


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """把文字原子寫入 path。"""
    _write_atomic(path, lambda target: target.write_text(text, encoding=encoding))


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """把位元組原子寫入 path。"""
    _write_atomic(path, lambda target: target.write_bytes(payload))
