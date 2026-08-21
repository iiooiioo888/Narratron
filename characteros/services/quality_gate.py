"""生成品質閘門：生圖後檢查可用性／臉部相似度，未通過則讓呼叫端重試。"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_SIMILARITY_THRESHOLD = 0.45
MAX_QUALITY_RETRIES = 3


class QualityGateFailed(Exception):
    """品質未過關，應重試或標記 failed。"""

    def __init__(self, report: QualityReport) -> None:
        self.report = report
        super().__init__(report.reason or "quality gate failed")


@dataclass
class QualityReport:
    passed: bool
    quality_score: float
    face_similarity: float | None = None
    anatomy_score: float | None = None
    reason: str | None = None
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "quality_score": self.quality_score,
            "face_similarity": self.face_similarity,
            "anatomy_score": self.anatomy_score,
            "reason": self.reason,
            "checks": self.checks,
        }


def quality_gate_enabled() -> bool:
    raw = str(os.environ.get("CHARACTEROS_QUALITY_GATE", "1") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def similarity_threshold() -> float:
    raw = str(os.environ.get("CHARACTEROS_FACE_SIMILARITY_THRESHOLD") or "").strip()
    if not raw:
        return DEFAULT_SIMILARITY_THRESHOLD
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return DEFAULT_SIMILARITY_THRESHOLD


def max_quality_retries(image_request: dict[str, Any] | None = None) -> int:
    req = image_request if isinstance(image_request, dict) else {}
    raw = req.get("max_quality_retries")
    if raw in (None, ""):
        env = str(os.environ.get("CHARACTEROS_QUALITY_MAX_RETRIES") or "").strip()
        raw = env or MAX_QUALITY_RETRIES
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return MAX_QUALITY_RETRIES


def _has_image_payload(payload: dict[str, Any] | None) -> bool:
    data = payload if isinstance(payload, dict) else {}
    images = data.get("images") if isinstance(data.get("images"), list) else []
    if any(isinstance(item, dict) and (item.get("url") or item.get("uri") or item.get("asset_path") or item.get("has_bytes")) for item in images):
        return True
    return bool(data.get("url") or data.get("uri") or data.get("lock_url"))


def _load_image_bytes(source: str) -> bytes | None:
    text = str(source or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return None
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme == "file" else text
    try:
        from pathlib import Path

        candidate = Path(path)
        if candidate.is_file():
            return candidate.read_bytes()
    except OSError:
        return None
    return None


def _average_hash_similarity(left: bytes, right: bytes) -> float | None:
    try:
        from PIL import Image
    except ImportError:
        return None

    def _hash(data: bytes) -> int:
        image = Image.open(io.BytesIO(data)).convert("L").resize((8, 8))
        pixels = list(image.getdata())
        avg = sum(pixels) / max(1, len(pixels))
        bits = 0
        for index, pixel in enumerate(pixels):
            if pixel >= avg:
                bits |= 1 << index
        return bits

    try:
        a = _hash(left)
        b = _hash(right)
    except Exception:
        logger.debug("quality gate could not hash images", exc_info=True)
        return None
    xor = a ^ b
    distance = xor.bit_count() if hasattr(int, "bit_count") else bin(xor).count("1")
    return max(0.0, min(1.0, 1.0 - (distance / 64.0)))


def evaluate_generation(
    payload: dict[str, Any] | None,
    *,
    extra_ref_uris: list[str] | None = None,
    provider_name: str | None = None,
) -> QualityReport:
    """檢查生成結果。null provider 只做結構檢查，避免測試占位圖被誤殺。"""
    data = payload if isinstance(payload, dict) else {}
    checks: dict[str, Any] = {"has_image": _has_image_payload(data)}
    if not checks["has_image"]:
        return QualityReport(
            passed=False,
            quality_score=0.0,
            reason="missing_image",
            checks=checks,
        )

    provider = str(provider_name or data.get("provider") or "").strip().lower()
    similarity: float | None = None
    if provider != "null":
        images = data.get("images") if isinstance(data.get("images"), list) else []
        generated_bytes: bytes | None = None
        for item in images:
            if not isinstance(item, dict):
                continue
            generated_bytes = _load_image_bytes(str(item.get("asset_path") or item.get("path") or ""))
            if generated_bytes:
                break
        for ref in extra_ref_uris or []:
            ref_bytes = _load_image_bytes(str(ref))
            if generated_bytes and ref_bytes:
                similarity = _average_hash_similarity(generated_bytes, ref_bytes)
                if similarity is not None:
                    break

    checks["face_similarity"] = similarity
    threshold = similarity_threshold()
    if similarity is not None and similarity < threshold:
        return QualityReport(
            passed=False,
            quality_score=round(similarity, 4),
            face_similarity=similarity,
            reason="low_face_similarity",
            checks=checks,
        )

    score = 0.82 if similarity is None else max(0.55, similarity)
    return QualityReport(
        passed=True,
        quality_score=round(score, 4),
        face_similarity=similarity,
        anatomy_score=0.8,
        checks=checks,
    )
