"""容器成員 SHA-256。排除 `_meta.checksum` 與 `signature.sig`。"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

CHECKSUM_PREFIX = "sha256:"
EXCLUDED_MEMBERS = frozenset({"signature.sig"})


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def strip_manifest_checksum(manifest_bytes: bytes) -> bytes:
    data = json.loads(manifest_bytes.decode("utf-8"))
    if isinstance(data, dict):
        meta = data.get("_meta")
        if isinstance(meta, dict):
            meta = dict(meta)
            meta.pop("checksum", None)
            data = dict(data)
            data["_meta"] = meta
    return canonical_json(data)


def member_digest_bytes(name: str, payload: bytes) -> bytes:
    if name == "manifest.json":
        payload = strip_manifest_checksum(payload)
    return f"{name}\n".encode("utf-8") + payload


def compute_checksum(members: Mapping[str, bytes]) -> str:
    hasher = hashlib.sha256()
    for name in sorted(members):
        if name in EXCLUDED_MEMBERS:
            continue
        hasher.update(member_digest_bytes(name, members[name]))
    return f"{CHECKSUM_PREFIX}{hasher.hexdigest()}"


def parse_checksum(value: str) -> str:
    text = value.strip()
    if text.startswith(CHECKSUM_PREFIX):
        return text[len(CHECKSUM_PREFIX) :]
    return text


def checksums_equal(left: str, right: str) -> bool:
    return parse_checksum(left).lower() == parse_checksum(right).lower()
