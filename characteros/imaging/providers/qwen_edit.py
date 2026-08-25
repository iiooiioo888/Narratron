"""Qwen-Image-Edit-2511 + 懶載入 LoRA（HTTP 客戶端）。

對接上游 Gradio Server / Narratron 相容編輯端點，不內嵌 CUDA／diffusers 重型棧。
上游：https://github.com/PRITHIVSAKTHIUR/Qwen-Image-Edit-2511-LoRAs-Fast-Lazy-Load
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from urllib.parse import urlparse

from characteros.imaging.base import GeneratedImage, ImageGenProvider, ImageGenRequest, ImageGenResult
from characteros.imaging.qwen_edit_adapters import (
    DEFAULT_GUIDANCE,
    DEFAULT_LORA,
    DEFAULT_STEPS,
    QWEN_EDIT_MAX_REF_IMAGES,
    build_edit_prompt,
    normalize_lora,
    pick_lora_for_request,
)
from characteros.imaging.settings import settings

DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_MODEL = "Qwen-Image-Edit-2511"
DEFAULT_NEGATIVE = (
    "worst quality, low quality, bad anatomy, bad hands, text, error, missing fingers, "
    "extra digit, fewer digits, cropped, jpeg artifacts, signature, watermark, username, blurry"
)


def resolve_qwen_edit_base(base_url: str | None = None) -> str:
    raw = (base_url or settings.get_base_url() or DEFAULT_BASE_URL).strip()
    if not raw:
        raw = DEFAULT_BASE_URL
    return raw.rstrip("/")


def _strip_data_uri(payload: str) -> str:
    text = str(payload or "").strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def _ensure_data_uri(payload: str, *, mime: str = "image/png") -> str:
    text = str(payload or "").strip()
    if not text:
        return ""
    if text.startswith("data:"):
        return text
    # 純 base64
    return f"data:{mime};base64,{text}"


def uris_to_b64_json(ref_image_uris: list[str], *, limit: int = QWEN_EDIT_MAX_REF_IMAGES) -> str:
    """把 http(s) / data URI 轉成上游 infer() 要的 images_b64_json 字串。"""
    images: list[str] = []
    for uri in ref_image_uris:
        cleaned = str(uri or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered.startswith("data:"):
            images.append(cleaned)
        elif lowered.startswith(("http://", "https://")):
            images.append(_download_as_data_uri(cleaned))
        else:
            continue
        if len(images) >= limit:
            break
    if not images:
        raise RuntimeError(
            "Qwen Edit 需要至少一張參考圖（data URI 或 http(s)）。"
            "請先用 wan／openai 生成身份圖，或上傳 ref_images。"
        )
    return json.dumps(images)


def _download_as_data_uri(url: str, *, timeout_s: float = 60.0) -> str:
    import httpx

    response = httpx.get(url, timeout=timeout_s, follow_redirects=True)
    response.raise_for_status()
    content_type = str(response.headers.get("content-type") or "image/png").split(";")[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/png"
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _decode_result_image(payload: Any) -> tuple[bytes | None, str | None]:
    if payload is None:
        return None, None
    if isinstance(payload, dict):
        for key in ("image", "url", "b64", "b64_json", "data"):
            if key in payload:
                return _decode_result_image(payload[key])
        return None, None
    text = str(payload).strip()
    if not text:
        return None, None
    if text.startswith(("http://", "https://")):
        return None, text
    raw_b64 = _strip_data_uri(text)
    try:
        return base64.b64decode(raw_b64), None
    except Exception as exc:
        raise RuntimeError(f"無法解碼 Qwen Edit 回傳圖片：{exc}") from exc


def _extract_edit_payload(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RuntimeError("Qwen Edit 回應不是 JSON 物件")

    # Narratron 契約
    if "image" in body or "seed" in body:
        return body

    # Gradio predict 常見包裝：{"data":[{...}]} 或 {"data":["data:image..."]}
    data = body.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, str):
            return {"image": first, "seed": body.get("seed")}
        if isinstance(first, list) and first:
            return {"image": first[0], "seed": body.get("seed")}

    # HF / 其他：output
    output = body.get("output")
    if isinstance(output, dict):
        return output
    if isinstance(output, list) and output:
        item = output[0]
        return item if isinstance(item, dict) else {"image": item}

    raise RuntimeError(f"無法解析 Qwen Edit 回應鍵：{sorted(body.keys())}")


class QwenEditImageProvider(ImageGenProvider):
    """圖生圖編輯：多角度／風格 LoRA／超分。

    支援兩種 HTTP 契約（自動探測）：

    1. Narratron 簡化契約 ``POST {base}/edit``
    2. 上游 Gradio Server ``POST {base}/gradio_api/call/edit_image``
    """

    name = "qwen_edit"
    display_name = "Qwen Image Edit（2511 + LoRA）"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self.api_key = (
            api_key
            or settings.get_api_key()
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self.base_url = resolve_qwen_edit_base(base_url)
        self.default_model = model or settings.get_model() or DEFAULT_MODEL
        self.timeout_s = timeout_s

    def generate(self, request: ImageGenRequest) -> ImageGenResult:
        extra = request.extra if isinstance(request.extra, dict) else {}
        angle = str(extra.get("angle") or "").strip() or None
        multi_angle = bool(extra.get("multi_angle"))
        style_hints = str(extra.get("style_hints") or "")
        lora = pick_lora_for_request(
            purpose=request.purpose,
            angle=angle,
            explicit_lora=str(extra.get("lora") or extra.get("lora_adapter") or ""),
            style_hints=style_hints,
            multi_angle=multi_angle or bool(angle),
        )
        prompt = build_edit_prompt(
            prompt=request.prompt,
            angle=angle,
            lora=lora,
            multi_angle=multi_angle or bool(angle),
        )
        if request.negative_prompt:
            # 上游固定 negative；附加到 prompt 尾端作為避免條款
            avoid = str(request.negative_prompt).strip()
            if avoid and avoid not in prompt:
                prompt = f"{prompt}\nAvoid: {avoid[:240]}"

        seed = int(extra.get("seed") or 0)
        randomize_seed = bool(extra.get("randomize_seed", seed == 0))
        guidance = float(extra.get("guidance_scale") or extra.get("true_cfg_scale") or DEFAULT_GUIDANCE)
        steps = int(extra.get("steps") or DEFAULT_STEPS)

        images_b64_json = uris_to_b64_json(list(request.ref_image_uris))
        body = self._call_edit(
            images_b64_json=images_b64_json,
            prompt=prompt,
            lora_adapter=lora,
            seed=seed,
            randomize_seed=randomize_seed,
            guidance_scale=guidance,
            steps=steps,
        )
        parsed = _extract_edit_payload(body)
        data, url = _decode_result_image(parsed.get("image"))
        if data is None and not url:
            raise RuntimeError("Qwen Edit 回應沒有圖片")

        prefix = str(extra.get("filename_prefix") or request.purpose)
        used_seed = parsed.get("seed", seed)
        image = GeneratedImage(
            filename=f"{prefix}_001.png",
            mime_type="image/png",
            data=data,
            url=url,
            metadata={
                "lora": lora,
                "seed": used_seed,
                "angle": angle,
                "steps": steps,
                "guidance_scale": guidance,
                "edit_prompt": prompt,
            },
        )
        return ImageGenResult(
            provider=self.name,
            model=request.model or self.default_model,
            images=[image],
            raw={
                "lora": lora,
                "seed": used_seed,
                "steps": steps,
                "guidance_scale": guidance,
                "response": body if isinstance(body, dict) else {"body": body},
            },
        )

    def edit(
        self,
        *,
        ref_image_uris: list[str],
        prompt: str,
        lora: str | None = None,
        seed: int = 0,
        randomize_seed: bool = True,
        guidance_scale: float = DEFAULT_GUIDANCE,
        steps: int = DEFAULT_STEPS,
        filename_prefix: str = "qwen_edit",
    ) -> ImageGenResult:
        """直接編輯 API（不經 assemble_request）。"""
        request = ImageGenRequest(
            purpose="edit",
            prompt=prompt,
            negative_prompt=DEFAULT_NEGATIVE,
            size="1024x1024",
            n=1,
            model=self.default_model,
            ref_image_uris=list(ref_image_uris),
            extra={
                "lora": normalize_lora(lora or DEFAULT_LORA),
                "seed": seed,
                "randomize_seed": randomize_seed,
                "guidance_scale": guidance_scale,
                "steps": steps,
                "filename_prefix": filename_prefix,
                "multi_angle": False,
            },
        )
        return self.generate(request)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _call_edit(
        self,
        *,
        images_b64_json: str,
        prompt: str,
        lora_adapter: str,
        seed: int,
        randomize_seed: bool,
        guidance_scale: float,
        steps: int,
    ) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("Qwen Edit provider 需要 httpx：pip install httpx") from exc

        narratron_payload = {
            "images_b64_json": images_b64_json,
            "images": json.loads(images_b64_json),
            "prompt": prompt,
            "lora": lora_adapter,
            "lora_adapter": lora_adapter,
            "seed": seed,
            "randomize_seed": randomize_seed,
            "guidance_scale": guidance_scale,
            "steps": steps,
        }
        gradio_payload = {
            "data": [
                images_b64_json,
                prompt,
                lora_adapter,
                seed,
                randomize_seed,
                guidance_scale,
                steps,
            ]
        }

        errors: list[str] = []
        with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
            # 1) Narratron 簡化端點
            for path in ("/edit", "/api/edit", "/api/v1/edit"):
                url = f"{self.base_url}{path}"
                try:
                    response = client.post(url, headers=self._headers(), json=narratron_payload)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    body = response.json()
                    if isinstance(body, dict):
                        return body
                except Exception as exc:
                    errors.append(f"{path}: {exc}")

            # 2) Gradio Server 同步／非同步 API
            for path in (
                "/gradio_api/call/edit_image",
                "/api/edit_image",
                "/call/edit_image",
            ):
                url = f"{self.base_url}{path}"
                try:
                    response = client.post(url, headers=self._headers(), json=gradio_payload)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        continue
                    # 非同步：{"event_id": "..."}
                    event_id = body.get("event_id") or body.get("eventId")
                    if event_id:
                        return self._poll_gradio_event(client, path, str(event_id))
                    return body
                except Exception as exc:
                    errors.append(f"{path}: {exc}")

        host = urlparse(self.base_url).netloc or self.base_url
        detail = "; ".join(errors[-3:]) if errors else "無可用端點"
        raise RuntimeError(
            f"Qwen Edit 連線失敗（{host}）。"
            f"請確認已啟動上游服務（uv run app.py）或相容 /edit 端點。細節：{detail}"
        )

    def _poll_gradio_event(
        self,
        client: Any,
        call_path: str,
        event_id: str,
        *,
        max_wait_s: float | None = None,
    ) -> dict[str, Any]:
        """輪詢 Gradio SSE／結果端點。"""
        deadline = time.time() + (max_wait_s or self.timeout_s)
        # Gradio 6: GET /gradio_api/call/edit_image/{event_id}
        result_url = f"{self.base_url}{call_path.rstrip('/')}/{event_id}"
        last_error = ""
        while time.time() < deadline:
            try:
                response = client.get(result_url, headers=self._headers())
                if response.status_code == 404:
                    time.sleep(0.5)
                    continue
                response.raise_for_status()
                content_type = str(response.headers.get("content-type") or "")
                text = response.text or ""
                if "text/event-stream" in content_type or text.lstrip().startswith("event:"):
                    parsed = _parse_gradio_sse(text)
                    if parsed is not None:
                        return parsed
                    time.sleep(0.4)
                    continue
                body = response.json()
                if isinstance(body, dict):
                    if body.get("status") in {"pending", "processing", "QUEUED", "PENDING"}:
                        time.sleep(0.5)
                        continue
                    return body
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)
        raise RuntimeError(f"Qwen Edit Gradio 輪詢逾時：{last_error or event_id}")


def _parse_gradio_sse(text: str) -> dict[str, Any] | None:
    """從 Gradio SSE 文字抽出最終 data。"""
    current_event = ""
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
            continue
        if line == "" and data_lines:
            payload = "\n".join(data_lines)
            data_lines = []
            if current_event in {"complete", "result", "estimation"} or current_event == "":
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    current_event = ""
                    continue
                if current_event == "complete" or (
                    isinstance(parsed, (list, dict)) and current_event in {"", "result"}
                ):
                    if isinstance(parsed, list):
                        return {"data": parsed}
                    if isinstance(parsed, dict):
                        return parsed
            current_event = ""
    # 檔尾無空行
    if data_lines:
        payload = "\n".join(data_lines)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return {"data": parsed}
        if isinstance(parsed, dict):
            return parsed
    return None
