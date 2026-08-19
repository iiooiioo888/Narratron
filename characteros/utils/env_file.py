"""讀寫 repo 根目錄 .env（upsert 指定鍵，不影響其他行）。"""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """characteros 套件所在 repo 根目錄。"""
    return Path(__file__).resolve().parents[2]


def default_env_path() -> Path:
    return repo_root() / ".env"


def upsert_env_vars(
    updates: dict[str, str | None],
    *,
    env_path: Path | None = None,
) -> Path:
    """
    更新或插入環境變數。value 為 None 時移除該鍵。

    保留註解、空行與未提及的鍵。
    """
    path = env_path or default_env_path()
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    found: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key not in updates:
            new_lines.append(line)
            continue

        found.add(key)
        value = updates[key]
        if value is not None:
            new_lines.append(f"{key}={value}")

    for key, value in updates.items():
        if key not in found and value is not None:
            new_lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(new_lines)
    if content and not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return path
