"""查看 `.charpass` 角色護照內容，或將 manifest 匯出為可讀 JSON。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from narratron.charpass.container import CharpassReader
from narratron.charpass.exceptions import CharpassError
from narratron.charpass.schema import READABLE_SIDECAR
from narratron.charpass.store import CharpassStore, sidecar_manifest


def _resolve_charpass_path(path: Path) -> Path:
    if path.is_dir():
        candidate = path / "current.charpass"
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"目錄內找不到 current.charpass：{path}")
    if not path.is_file():
        raise FileNotFoundError(f"找不到檔案：{path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查看 Narratron `.charpass` 角色護照")
    parser.add_argument(
        "path",
        type=Path,
        help=".charpass 檔案，或 data/charpasses/{entity_id} 目錄",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=f"寫入 sidecar 路徑（預設：同目錄 {READABLE_SIDECAR} 或 stdout）",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="只印到 stdout，不寫檔",
    )
    parser.add_argument("--key", default="", help="L1/L2/L3 容器解密金鑰")
    args = parser.parse_args(argv)

    charpass_path = _resolve_charpass_path(args.path)
    blob = charpass_path.read_bytes()
    key = args.key or None
    try:
        unpacked = CharpassReader().read(blob, key=key)
    except CharpassError as exc:
        print(f"無法讀取 {charpass_path}: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(sidecar_manifest(unpacked.manifest), ensure_ascii=False, indent=2) + "\n"
    if args.stdout:
        sys.stdout.write(text)
        return 0

    output = args.output
    if output is None:
        output = charpass_path.parent / READABLE_SIDECAR
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"已寫入 {output}")
    if unpacked.assets:
        print(f"內嵌資產 {len(unpacked.assets)} 個（僅 manifest 已匯出）")
    if unpacked.warnings:
        print("警告：", "; ".join(unpacked.warnings))
    return 0


def export_all_store(root: Path | None = None) -> int:
    store = CharpassStore(root)
    if not store.root.is_dir():
        print(f"找不到版本庫：{store.root}", file=sys.stderr)
        return 1
    count = 0
    for folder in sorted(store.root.iterdir()):
        if not folder.is_dir():
            continue
        entity_id = folder.name
        if store.export_readable(entity_id):
            count += 1
            print(f"已匯出 {folder / READABLE_SIDECAR}")
    print(f"共匯出 {count} 份 {READABLE_SIDECAR}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--all":
        raise SystemExit(export_all_store())
    raise SystemExit(main())
