"""CharacterOS CLI：測試生圖流程、設定與護照轉換。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from characteros.imaging.prompt import assemble_request
from characteros.imaging.registry import list_providers
from characteros.imaging.settings import settings
from characteros.models.database import SessionLocal
from narratron.charpass.store import CharpassStore


def _read_manifest(store: CharpassStore, entity_id: str) -> dict[str, Any]:
    manifest = store.read_current_manifest(entity_id)
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError(f"找不到可用護照：{entity_id}")
    return manifest


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_value(raw: str) -> Any:
    text = str(raw).strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lowered = text.lower()
        if lowered == "null":
            return None
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return raw


def _path_tokens(path: str) -> list[str]:
    tokens = [part.strip() for part in str(path).split(".") if part.strip()]
    if not tokens:
        raise ValueError("path 不可為空，例如：_style.character_style.visual.medium")
    return tokens


def _is_index(token: str) -> bool:
    return token.lstrip("-").isdigit()


def _walk_parent(root: Any, tokens: list[str], create_missing: bool) -> tuple[Any, str]:
    cur = root
    for i, token in enumerate(tokens[:-1]):
        if isinstance(cur, dict):
            nxt = cur.get(token)
            if nxt is None:
                if not create_missing:
                    raise KeyError(f"不存在路徑節點：{token}")
                next_token = tokens[i + 1]
                nxt = [] if _is_index(next_token) else {}
                cur[token] = nxt
            cur = nxt
            continue
        if isinstance(cur, list):
            if not _is_index(token):
                raise KeyError(f"list 節點必須用數字索引：{token}")
            idx = int(token)
            if idx < 0:
                raise KeyError("不支援負索引")
            if idx >= len(cur):
                if not create_missing:
                    raise KeyError(f"索引超出範圍：{idx}")
                while len(cur) <= idx:
                    cur.append({})
            cur = cur[idx]
            continue
        raise KeyError(f"無法繼續走訪路徑：{token}")
    return cur, tokens[-1]


def _get_value(root: Any, path: str) -> Any:
    cur = root
    for token in _path_tokens(path):
        if isinstance(cur, dict):
            if token not in cur:
                raise KeyError(f"不存在鍵：{token}")
            cur = cur[token]
            continue
        if isinstance(cur, list):
            if not _is_index(token):
                raise KeyError(f"list 節點必須用數字索引：{token}")
            idx = int(token)
            if idx < 0 or idx >= len(cur):
                raise KeyError(f"索引超出範圍：{idx}")
            cur = cur[idx]
            continue
        raise KeyError(f"無法讀取路徑：{path}")
    return cur


def _set_value(root: Any, path: str, value: Any) -> None:
    tokens = _path_tokens(path)
    parent, key = _walk_parent(root, tokens, create_missing=True)
    if isinstance(parent, dict):
        parent[key] = value
        return
    if isinstance(parent, list):
        if not _is_index(key):
            raise KeyError(f"list 節點必須用數字索引：{key}")
        idx = int(key)
        if idx < 0:
            raise KeyError("不支援負索引")
        while len(parent) <= idx:
            parent.append(None)
        parent[idx] = value
        return
    raise KeyError(f"無法設定路徑：{path}")


def _delete_value(root: Any, path: str) -> None:
    tokens = _path_tokens(path)
    parent, key = _walk_parent(root, tokens, create_missing=False)
    if isinstance(parent, dict):
        if key not in parent:
            raise KeyError(f"不存在鍵：{key}")
        del parent[key]
        return
    if isinstance(parent, list):
        if not _is_index(key):
            raise KeyError(f"list 節點必須用數字索引：{key}")
        idx = int(key)
        if idx < 0 or idx >= len(parent):
            raise KeyError(f"索引超出範圍：{idx}")
        del parent[idx]
        return
    raise KeyError(f"無法刪除路徑：{path}")


def cmd_providers(_: argparse.Namespace) -> int:
    _print_json(list_providers())
    return 0


def cmd_config_show(_: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        settings.load_from_db(db)
    finally:
        db.close()
    snap = settings.snapshot()
    _print_json(
        {
            "provider": snap.provider,
            "base_url": snap.base_url,
            "model": snap.model,
            "has_api_key": snap.has_api_key,
        }
    )
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        snap = settings.update(
            db,
            provider=args.provider,
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            clear_api_key=bool(args.clear_api_key),
            persist_env=bool(args.persist_env),
        )
    finally:
        db.close()

    _print_json(
        {
            "provider": snap.provider,
            "base_url": snap.base_url,
            "model": snap.model,
            "has_api_key": snap.has_api_key,
        }
    )
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    store = CharpassStore()
    manifest = _read_manifest(store, args.entity_id)
    request = assemble_request(
        manifest,
        purpose=args.purpose,
        extra=args.extra,
        n=max(1, int(args.n)),
        model=args.model or "",
    )
    _print_json(
        {
            "entity_id": args.entity_id,
            "purpose": request.purpose,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "ref_image_uris": request.ref_image_uris,
            "size": request.size,
            "model": request.model,
        }
    )
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    raise ValueError(
        "CLI 生圖已停用；請改用 GUI 面板 /admin/panel 的「生成圖片」按鈕。"
    )


def cmd_migrate(args: argparse.Namespace) -> int:
    store = CharpassStore()
    if args.all:
        count = store.migrate_all()
        _print_json({"migrated": count})
        return 0

    if not args.entity_id:
        raise ValueError("migrate 需要 --entity-id 或 --all")
    path = store.migrate_entity(args.entity_id)
    _print_json({"entity_id": args.entity_id, "path": str(path) if path else None})
    return 0


def cmd_char_show(args: argparse.Namespace) -> int:
    store = CharpassStore()
    manifest = _read_manifest(store, args.entity_id)
    if args.path:
        _print_json({"entity_id": args.entity_id, "path": args.path, "value": _get_value(manifest, args.path)})
    else:
        _print_json(manifest)
    return 0


def cmd_char_set(args: argparse.Namespace) -> int:
    store = CharpassStore()
    manifest = _read_manifest(store, args.entity_id)
    value = _parse_value(args.value)
    _set_value(manifest, args.path, value)
    store.write_manifest(args.entity_id, manifest)
    _print_json({"entity_id": args.entity_id, "updated_path": args.path, "value": value})
    return 0


def cmd_char_delete(args: argparse.Namespace) -> int:
    store = CharpassStore()
    manifest = _read_manifest(store, args.entity_id)
    _delete_value(manifest, args.path)
    store.write_manifest(args.entity_id, manifest)
    _print_json({"entity_id": args.entity_id, "deleted_path": args.path})
    return 0


def cmd_char_patch(args: argparse.Namespace) -> int:
    patch_path = Path(args.file)
    if not patch_path.is_file():
        raise ValueError(f"patch 檔案不存在：{patch_path}")
    patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
    if not isinstance(patch_data, dict):
        raise ValueError("patch 檔案必須是 JSON object")

    store = CharpassStore()
    manifest = _read_manifest(store, args.entity_id)
    for key, value in patch_data.items():
        _set_value(manifest, key, value)
    store.write_manifest(args.entity_id, manifest)
    _print_json({"entity_id": args.entity_id, "patched": sorted(patch_data.keys())})
    return 0


def cmd_char_init(args: argparse.Namespace) -> int:
    store = CharpassStore()
    existing = store.read_current_manifest(args.entity_id)
    if existing and not args.force:
        raise ValueError(f"角色已存在：{args.entity_id}（可加 --force 覆蓋）")
    base_name = args.name or args.entity_id
    manifest = {
        "schema": "https://narratron.dev/schemas/charpass/v1.json",
        "_mode": "full",
        "_meta": {
            "format": "charpass",
            "format_version": "1.0.0",
            "character_name": base_name,
            "entity_id": args.entity_id,
        },
        "_identity": {
            "name": base_name,
            "entity_id": args.entity_id,
            "species": "human",
        },
        "_style": {
            "character_style": {
                "visual": {
                    "medium": args.visual_medium or "",
                    "aesthetic": args.visual_aesthetic or "",
                    "keywords": [],
                },
                "art_prompt": {"positive": "", "negative": ""},
                "narrative": {"tone": "", "speech_pattern": "", "diction": ""},
                "consistency_notes": "",
            }
        },
        "_extensions": {"image_gen": {"provider": "", "model": "", "endpoint": "", "size": "1024x1024"}},
    }
    store.write_manifest(args.entity_id, manifest)
    _print_json({"entity_id": args.entity_id, "name": base_name, "created": True})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CharacterOS CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sp_providers = sub.add_parser("providers", help="列出可用生圖 provider")
    sp_providers.set_defaults(func=cmd_providers)

    sp_cfg_show = sub.add_parser("config-show", help="查看目前生圖設定")
    sp_cfg_show.set_defaults(func=cmd_config_show)

    sp_cfg_set = sub.add_parser("config-set", help="更新生圖設定（DB + 可選 .env）")
    sp_cfg_set.add_argument("--provider", default=None, help="null/http/openai/wan")
    sp_cfg_set.add_argument("--base-url", default=None, help="生圖 API Base URL")
    sp_cfg_set.add_argument("--model", default=None, help="預設模型")
    sp_cfg_set.add_argument("--api-key", default=None, help="生圖 API key")
    sp_cfg_set.add_argument(
        "--clear-api-key",
        action="store_true",
        help="清除已儲存 API key",
    )
    sp_cfg_set.add_argument(
        "--persist-env",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否同步寫入 .env（預設 true）",
    )
    sp_cfg_set.set_defaults(func=cmd_config_set)

    sp_prompt = sub.add_parser("prompt", help="依角色護照組提示詞")
    sp_prompt.add_argument("--entity-id", required=True, help="data/charpasses/{entity_id}")
    sp_prompt.add_argument("--purpose", default="identity", help="identity/outfit/expression/thumb")
    sp_prompt.add_argument("--extra", default="", help="額外提示詞")
    sp_prompt.add_argument("--n", type=int, default=1, help="預計生成張數")
    sp_prompt.add_argument("--model", default="", help="本次覆蓋模型")
    sp_prompt.set_defaults(func=cmd_prompt)

    sp_generate = sub.add_parser("generate", help="（已停用）僅保留相容；請改用 GUI 面板生圖")
    sp_generate.add_argument("--entity-id", required=True, help="data/charpasses/{entity_id}")
    sp_generate.add_argument("--purpose", default="identity", help="identity/outfit/expression/thumb")
    sp_generate.add_argument("--provider", default=None, help="null/http/openai/wan")
    sp_generate.add_argument("--extra", default="", help="額外提示詞")
    sp_generate.add_argument("--n", type=int, default=1, help="生成張數")
    sp_generate.add_argument("--model", default="", help="本次覆蓋模型")
    sp_generate.add_argument(
        "--persist",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="是否把結果寫回 data/charpasses/{entity_id}",
    )
    sp_generate.set_defaults(func=cmd_generate)

    sp_migrate = sub.add_parser("migrate", help="把舊二進位 .charpass 轉可讀 JSON")
    sp_migrate.add_argument("--entity-id", default=None, help="指定角色 ID")
    sp_migrate.add_argument("--all", action="store_true", help="轉換全部角色")
    sp_migrate.set_defaults(func=cmd_migrate)

    sp_char = sub.add_parser("char", help="角色護照編輯器（CLI）")
    sub_char = sp_char.add_subparsers(dest="char_command", required=True)

    sp_char_show = sub_char.add_parser("show", help="顯示角色護照或指定欄位")
    sp_char_show.add_argument("--entity-id", required=True, help="角色 ID")
    sp_char_show.add_argument("--path", default="", help="點路徑，例如 _style.character_style.visual.medium")
    sp_char_show.set_defaults(func=cmd_char_show)

    sp_char_set = sub_char.add_parser("set", help="設定角色欄位（值支援 JSON）")
    sp_char_set.add_argument("--entity-id", required=True, help="角色 ID")
    sp_char_set.add_argument("--path", required=True, help="點路徑，例如 _meta.description")
    sp_char_set.add_argument("--value", required=True, help='值，例如 "寫實風格"、123、true、["a","b"]')
    sp_char_set.set_defaults(func=cmd_char_set)

    sp_char_delete = sub_char.add_parser("delete", help="刪除角色欄位")
    sp_char_delete.add_argument("--entity-id", required=True, help="角色 ID")
    sp_char_delete.add_argument("--path", required=True, help="要刪除的點路徑")
    sp_char_delete.set_defaults(func=cmd_char_delete)

    sp_char_patch = sub_char.add_parser("patch", help="用 JSON 檔批次修改角色欄位")
    sp_char_patch.add_argument("--entity-id", required=True, help="角色 ID")
    sp_char_patch.add_argument("--file", required=True, help="JSON 檔，key=path, value=新值")
    sp_char_patch.set_defaults(func=cmd_char_patch)

    sp_char_init = sub_char.add_parser("init", help="初始化一個新角色護照")
    sp_char_init.add_argument("--entity-id", required=True, help="角色 ID")
    sp_char_init.add_argument("--name", default="", help="角色名稱（預設同 entity-id）")
    sp_char_init.add_argument("--visual-medium", default="", help="視覺媒介，如 cinematic realism")
    sp_char_init.add_argument("--visual-aesthetic", default="", help="視覺美術風格")
    sp_char_init.add_argument("--force", action="store_true", help="已存在時覆蓋")
    sp_char_init.set_defaults(func=cmd_char_init)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
