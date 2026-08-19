"""ZIP 打包 / 解包：`CharpassPacker` / `CharpassReader`。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from narratron.charpass import crypto
from narratron.charpass.checksum import checksums_equal, compute_checksum
from narratron.charpass.compat import check_version
from narratron.charpass.exceptions import (
    CharpassChecksumError,
    CharpassCryptoError,
    CharpassError,
)

CharpassContainerError = CharpassError
from narratron.charpass.schema import (
    FORMAT_EXTENSION,
    LITE_THRESHOLD_BYTES,
    CharpassManifest,
    EncryptionLevel,
    PackMode,
    charpass_id_short,
    dump_json_schema,
    encryption_level_to_int,
    encryption_level_to_label,
    manifest_to_dict,
    parse_manifest,
)

_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\s]+')


@dataclass
class PackedAsset:
    name: str
    data: bytes
    uri: str = ""
    kind: str = "reference_image"


@dataclass
class PackedCharpass:
    data: bytes
    filename: str
    checksum: str
    size: int
    mode: Literal["full", "lite"]
    encryption_level: int
    manifest: dict[str, Any]
    warning: str | None = None

    @property
    def blob(self) -> bytes:
        return self.data


@dataclass
class UnpackedCharpass:
    manifest: dict[str, Any]
    assets: dict[str, bytes]
    checksum: str
    warnings: list[str] = field(default_factory=list)
    encryption_level: int = 0

    @property
    def passport(self) -> CharpassManifest:
        return parse_manifest(self.manifest)

    @property
    def warning(self) -> str | None:
        return "; ".join(self.warnings) if self.warnings else None


def safe_character_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", (name or "character").strip()).strip("._")
    return cleaned or "character"


def suggest_filename(manifest: dict[str, Any]) -> str:
    identity = manifest.get("_identity") if isinstance(manifest.get("_identity"), dict) else {}
    meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
    name = safe_character_filename(
        str(meta.get("character_name") or identity.get("name") or meta.get("entity_id") or "character")
    )
    short_id = charpass_id_short(str(meta.get("charpass_id") or "000000"))
    return f"{name}_{short_id}{FORMAT_EXTENSION}"


def _coerce_assets(assets: Iterable[PackedAsset] | Mapping[str, bytes] | None) -> list[PackedAsset]:
    if assets is None:
        return []
    if isinstance(assets, Mapping):
        packed: list[PackedAsset] = []
        for name, data in assets.items():
            kind = "voice" if "voice" in name else "reference_image"
            packed.append(PackedAsset(name=str(name), data=data, uri=str(name), kind=kind))
        return packed
    return list(assets)


def _load_packaged_schema() -> bytes:
    path = Path(__file__).with_name("schema.json")
    if path.is_file():
        return path.read_bytes()
    return dump_json_schema().encode("utf-8")


def _dump_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            archive.writestr(name, members[name])
    return buffer.getvalue()


def _read_zip_members(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            return {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    except zipfile.BadZipFile as exc:
        raise CharpassError("不是有效的 .charpass ZIP 容器") from exc


def _asset_member_path(asset: PackedAsset) -> str:
    name = asset.name.replace("\\", "/")
    if name.startswith("assets/") or name.startswith("thumb/"):
        return name
    if asset.kind in {"voice", "voice_sample"} or "voice" in name:
        return f"assets/voice/{Path(name).name}"
    if asset.kind in {"identity", "face", "face_embedding"}:
        return f"assets/identity/{Path(name).name}"
    if asset.kind in {"style", "outfit"}:
        return f"assets/style/{Path(name).name}"
    if asset.kind in {"body", "mesh", "skeleton"}:
        return f"assets/body/{Path(name).name}"
    if asset.kind in {"expression", "pose"}:
        return f"assets/{asset.kind}/{Path(name).name}"
    if name.startswith("references/"):
        return f"assets/{name}"
    return f"assets/identity/{Path(name).name}"


class CharpassPacker:
    """打包角色護照 ZIP。不是 P12 Exporter。"""

    def pack(
        self,
        manifest: CharpassManifest | dict[str, Any],
        assets: Iterable[PackedAsset] | Mapping[str, bytes] | None = None,
        *,
        mode: PackMode = "full",
        encryption_level: EncryptionLevel | int | str = 0,
        key: str | bytes | None = None,
        include_assets: bool = True,
        include_causal_history: bool = True,
        include_voice: bool = True,
        lite_threshold_bytes: int = LITE_THRESHOLD_BYTES,
        asset_base_url: str | None = None,
    ) -> PackedCharpass:
        payload = manifest_to_dict(manifest)
        asset_list = _coerce_assets(assets)
        level = encryption_level_to_int(encryption_level)
        packed = self._pack_once(
            payload,
            asset_list,
            mode=mode,
            encryption_level=level,
            key=key,
            include_assets=include_assets,
            include_causal_history=include_causal_history,
            include_voice=include_voice,
            asset_base_url=asset_base_url,
        )
        if packed.mode == "full" and packed.size > lite_threshold_bytes:
            packed = self._pack_once(
                payload,
                asset_list,
                mode="lite",
                encryption_level=level,
                key=key,
                include_assets=False,
                include_causal_history=include_causal_history,
                include_voice=include_voice,
                asset_base_url=asset_base_url,
            )
        return packed

    def _pack_once(
        self,
        manifest: dict[str, Any],
        assets: list[PackedAsset],
        *,
        mode: PackMode,
        encryption_level: int,
        key: str | bytes | None,
        include_assets: bool,
        include_causal_history: bool,
        include_voice: bool,
        asset_base_url: str | None = None,
    ) -> PackedCharpass:
        if encryption_level not in {0, 1, 2, 3}:
            raise CharpassError(f"不支援的 encryption_level={encryption_level}")
        if encryption_level >= 2 and not key:
            raise CharpassCryptoError("L2/L3 需要金鑰")

        body = json.loads(json.dumps(manifest, ensure_ascii=False))
        meta = body.setdefault("_meta", {})
        if not include_causal_history:
            causal = body.setdefault("_causal", {})
            causal["evolution_log"] = []
        if not include_voice:
            voice = body.setdefault("_voice", {})
            voice["sample_uri"] = None
            voice["samples"] = []
            voice["enabled"] = False
            ref_audio = voice.get("ref_audio")
            if isinstance(ref_audio, dict):
                ref_audio["path"] = ""
            embedding = voice.get("voice_embedding")
            if isinstance(embedding, dict):
                embedding["path"] = ""

        embed = mode == "full" and include_assets
        pack_mode: PackMode = "full" if embed else "lite"
        members: dict[str, bytes] = {}
        members["schema.json"] = _load_packaged_schema()
        body["schema"] = body.get("schema") or "https://narratron.dev/schemas/charpass/v1.json"
        body["_mode"] = pack_mode
        if asset_base_url:
            body["_asset_base_url"] = asset_base_url
        elif pack_mode == "lite":
            body.setdefault("_asset_base_url", meta.get("asset_base_url"))

        asset_members: dict[str, bytes] = {}
        if embed:
            for asset in assets:
                path = _asset_member_path(asset)
                if not include_voice and path.startswith("assets/voice/"):
                    continue
                blob = asset.data
                if encryption_level == 2:
                    blob = crypto.encrypt_asset(path, blob, key or b"")
                asset_members[path] = blob
                self._bind_asset_ref(body, asset, path, embedded=path)
        else:
            for asset in assets:
                path = _asset_member_path(asset)
                if not include_voice and path.startswith("assets/voice/"):
                    continue
                self._bind_asset_ref(body, asset, path, embedded=None)

        causal = body.get("_causal") if isinstance(body.get("_causal"), dict) else {}
        members["causal/evolution_log.json"] = json.dumps(
            causal.get("evolution_log") or [],
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        meta["mode"] = pack_mode
        meta["encryption_level"] = encryption_level_to_label(encryption_level)
        if encryption_level >= 2:
            meta["license"] = "encrypted"
        meta["checksum"] = ""

        members["manifest.json"] = _dump_manifest_bytes(body)
        members.update(asset_members)
        checksum = compute_checksum(members)
        meta["checksum"] = checksum
        members["manifest.json"] = _dump_manifest_bytes(body)

        if encryption_level >= 1 and key:
            members["signature.sig"] = crypto.hmac_signature(checksum, key)

        zip_data = _zip_bytes(members)
        if encryption_level == 3:
            zip_data = crypto.encrypt_zip(zip_data, key or b"")

        meta["size_bytes"] = len(zip_data)
        filename = suggest_filename(body)
        return PackedCharpass(
            data=zip_data,
            filename=filename,
            checksum=checksum,
            size=len(zip_data),
            mode=pack_mode,
            encryption_level=encryption_level,
            manifest=body,
        )

    def _bind_asset_ref(
        self,
        manifest: dict[str, Any],
        asset: PackedAsset,
        path: str,
        *,
        embedded: str | None,
    ) -> None:
        ref = {
            "id": Path(asset.name).stem,
            "kind": asset.kind,
            "path": path,
            "uri": asset.uri or path,
            "embedded": embedded,
        }
        if asset.kind == "voice" or path.startswith("assets/voice/"):
            voice = manifest.setdefault("_voice", {})
            samples = list(voice.get("samples") or [])
            if not any(
                (item.get("uri") == ref["uri"] or item.get("path") == path)
                for item in samples
                if isinstance(item, dict)
            ):
                samples.append(ref)
            voice["samples"] = samples
            if not voice.get("sample_uri"):
                voice["sample_uri"] = ref["uri"]
            ref_audio = voice.setdefault("ref_audio", {})
            if isinstance(ref_audio, dict) and not ref_audio.get("path"):
                ref_audio["path"] = path
            voice["enabled"] = True
            return
        if path.startswith("assets/style/"):
            style = manifest.setdefault("_style", {})
            outfit = style.setdefault("outfit", {})
            images = list(outfit.get("ref_images") or [])
            if not any(item.get("path") == path for item in images if isinstance(item, dict)):
                images.append({"path": path, "note": ref.get("note") or ""})
            outfit["ref_images"] = images
            return
        identity = manifest.setdefault("_identity", {})
        faces = list(identity.get("ref_images") or [])
        if not any(
            (item.get("path") == path or item.get("uri") == ref["uri"])
            for item in faces
            if isinstance(item, dict)
        ):
            faces.append({"path": path, "uri": ref["uri"], "angle": "front", "weight": 1.0})
        identity["ref_images"] = faces
        style = manifest.setdefault("_style", {})
        images = list(style.get("reference_images") or [])
        if not any(item.get("uri") == ref["uri"] for item in images if isinstance(item, dict)):
            images.append(ref)
        style["reference_images"] = images


class CharpassReader:
    """讀取角色護照 ZIP。不是 Beta Importer。"""

    def read(self, data: bytes, *, key: str | bytes | None = None) -> UnpackedCharpass:
        encryption_level = 0
        blob = data
        if crypto.is_l3_blob(blob):
            if not key:
                raise CharpassCryptoError("L3 容器需要金鑰")
            blob = crypto.decrypt_zip(blob, key)
            encryption_level = 3
        members = _read_zip_members(blob)
        if "manifest.json" not in members:
            raise CharpassError("缺少 manifest.json")
        if "schema.json" not in members:
            raise CharpassError("缺少 schema.json")
        manifest = json.loads(members["manifest.json"].decode("utf-8"))
        if not isinstance(manifest, dict):
            raise CharpassError("manifest.json 必須是物件")
        parse_manifest(manifest)
        meta = manifest.get("_meta") if isinstance(manifest.get("_meta"), dict) else {}
        warnings: list[str] = []
        compat = check_version(str(meta.get("format_version") or "1.0.0"))
        if compat.warning:
            warnings.append(compat.warning)

        recorded = str(meta.get("checksum") or "")
        actual = compute_checksum(members)
        if recorded and not checksums_equal(recorded, actual):
            raise CharpassChecksumError("checksum 不符")
        if "signature.sig" in members:
            if not key:
                raise CharpassCryptoError("含 signature.sig 的 L1 容器需要金鑰")
            crypto.verify_hmac(actual, members["signature.sig"], key)
            encryption_level = max(encryption_level, 1)

        assets: dict[str, bytes] = {}
        for name, payload in members.items():
            if not name.startswith("assets/"):
                continue
            if crypto.is_l2_blob(payload):
                encryption_level = max(encryption_level, 2)
                if not key:
                    continue
                payload = crypto.decrypt_asset(name, payload, key)
            assets[name] = payload

        if encryption_level == 0:
            try:
                encryption_level = encryption_level_to_int(meta.get("encryption_level") or 0)
            except ValueError:
                encryption_level = 0
        return UnpackedCharpass(
            manifest=manifest,
            assets=assets,
            checksum=actual,
            warnings=warnings,
            encryption_level=encryption_level,
        )
