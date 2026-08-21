"""年齡軸生圖：character_variants 的一個特殊案例（request_params.age）。

預設按需生成：使用者請求 `?age=80` 只產生該歲的面部／T 型，不強制跑 1→80。
若明確 `fill_span=true`（或 age_end > age_start），才以區間逐步銜接。

參考圖採「軟鎖定」：有上一歲快取就用；沒有就退回護照種子圖，不為了連貫而補生成中間歲數。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from characteros.utils.hash import canonical_evolution_params

AGE_SPAN_START = 1
AGE_SPAN_END = 80
AGE_SPAN_PIPELINE = "age_span"
AGE_SPAN_PURPOSES = {"age_span", "identity", "face_detail", "tpose"}
WAITING_STATUS = "waiting"
RUNNING_STATUS = "running"
STALE_RUNNING_SECONDS = 20 * 60
PHASE_LABELS = {
    "face_detail": "面部",
    "tpose": "T 型",
    "identity": "身份",
    "outfit": "服裝",
    "expression": "表情",
    "thumb": "縮圖",
    "age_span": "年齡軸",
}


class AgeSpanDependencyPending(Exception):
    """年齡軸前置步驟尚未完成，任務應保持 pending 而非標記 failed。"""


def _parse_task_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def recover_stale_running_tasks(
    tasks: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_s: int = STALE_RUNNING_SECONDS,
) -> list[dict[str, Any]]:
    """卡住的 running（行程中斷）收斂回 pending，避免生圖迴圈永久停住。"""
    current = now or datetime.now(timezone.utc)
    recovered: list[dict[str, Any]] = []
    limit = timedelta(seconds=max(1, int(max_age_s)))
    for task in tasks:
        if str(task.get("status") or "").strip().lower() != RUNNING_STATUS:
            continue
        started = _parse_task_datetime(task.get("started_at") or task.get("updated_at"))
        if started is not None and current - started < limit:
            continue
        task["status"] = "pending"
        recovered.append(task)
    return recovered


def has_in_flight_generation(tasks: list[dict[str, Any]]) -> bool:
    recover_stale_running_tasks(tasks)
    return any(str(item.get("status") or "").strip().lower() == RUNNING_STATUS for item in tasks)

FACE_PHASE = "face_detail"
TPOSE_PHASE = "tpose"


def resolve_age_span_ages(
    *,
    age: int | None = None,
    age_start: int | None = None,
    age_end: int | None = None,
    fill_span: bool = False,
) -> tuple[list[int], bool]:
    """回傳要生成的歲數列表，以及是否為區間補齊模式。

    預設按需：只回傳目標歲數。`fill_span=True` 才展開區間，且必須同時給 age_start／age_end。
    """
    start_raw = age_start
    end_raw = age_end
    if fill_span:
        if start_raw is None or end_raw is None:
            raise ValueError("fill_span requires both age_start and age_end")
        start = max(AGE_SPAN_START, int(start_raw))
        end = min(AGE_SPAN_END, int(end_raw))
        if end < start:
            raise ValueError("age_end must be greater than or equal to age_start")
        return list(range(start, end + 1)), True
    if age is not None:
        target = int(age)
    elif start_raw is not None:
        target = int(start_raw)
    elif end_raw is not None:
        target = int(end_raw)
    else:
        raise ValueError("on-demand age_span requires a target age")
    target = max(AGE_SPAN_START, min(AGE_SPAN_END, target))
    return [target], False


def age_span_steps(
    *,
    age: int | None = None,
    age_start: int | None = None,
    age_end: int | None = None,
    fill_span: bool = False,
) -> list[dict[str, Any]]:
    ages, span_mode = resolve_age_span_ages(
        age=age,
        age_start=age_start,
        age_end=age_end,
        fill_span=fill_span,
    )
    start = ages[0]
    end = ages[-1]
    total = len(ages) * 2
    last_face_age = ages[-1]
    steps: list[dict[str, Any]] = []
    for offset, current_age in enumerate(ages):
        steps.append(
            {
                "phase": FACE_PHASE,
                "purpose": FACE_PHASE,
                "age": current_age,
                "age_start": start,
                "age_end": end,
                "fill_span": span_mode,
                "step_index": offset,
                "total_steps": total,
                "angle": "face_detail",
                "depends_on": None if offset == 0 else {"phase": FACE_PHASE, "age": current_age - 1},
            }
        )
    for offset, current_age in enumerate(ages):
        steps.append(
            {
                "phase": TPOSE_PHASE,
                "purpose": TPOSE_PHASE,
                "age": current_age,
                "age_start": start,
                "age_end": end,
                "fill_span": span_mode,
                "step_index": len(ages) + offset,
                "total_steps": total,
                "angle": "tpose",
                "depends_on": {"phase": FACE_PHASE, "age": last_face_age}
                if offset == 0
                else {"phase": TPOSE_PHASE, "age": current_age - 1},
            }
        )
    return steps


def character_needs_age_span(manifest: dict[str, Any] | None) -> bool:
    data = manifest if isinstance(manifest, dict) else {}
    identity = data.get("_identity") if isinstance(data.get("_identity"), dict) else {}
    refs = identity.get("ref_images") if isinstance(identity.get("ref_images"), list) else []
    if any(isinstance(item, dict) and (item.get("path") or item.get("uri")) for item in refs):
        return False
    extensions = data.get("_extensions") if isinstance(data.get("_extensions"), dict) else {}
    image_gen = extensions.get("image_gen") if isinstance(extensions.get("image_gen"), dict) else {}
    if image_gen.get("last_asset_paths") or image_gen.get("age_span"):
        return False
    return True


def should_queue_age_span(purpose: str, manifest: dict[str, Any] | None) -> bool:
    """只有明確選擇 age_span 才走年齡變體管線；不再因「新人物無參考圖」而強制 1→80。"""
    _ = manifest
    return str(purpose or "").strip() == AGE_SPAN_PIPELINE


def is_span_fill(image_request: dict[str, Any] | None) -> bool:
    req = image_request if isinstance(image_request, dict) else {}
    if bool(req.get("fill_span")):
        return True
    try:
        start = int(req.get("age_start") or 0)
        end = int(req.get("age_end") or 0)
    except (TypeError, ValueError):
        return False
    return end > start


def _age_token(age: int) -> str:
    return f"{int(age):03d}"


def age_span_prompt_extra(
    *,
    phase: str,
    age: int,
    user_extra: str = "",
    emotion: str | None = None,
    scene: str | None = None,
    weather: str | None = None,
    injury: float | None = None,
) -> str:
    parts = [
        f"exactly {age} years old, age {age}",
        "same named person as the reference images",
        "biologically plausible aging only, no redesign, no different person",
    ]
    if phase == FACE_PHASE:
        parts.append(
            "extreme facial close-up, highly detailed face, one face only, "
            "identity lock to the reference face"
        )
    else:
        parts.append(
            "full-body T-pose, match the matching-age face reference, "
            "same body identity across consecutive ages"
        )
    emotion_text = str(emotion or "").strip()
    if emotion_text:
        parts.append(f"expression: {emotion_text}")
    scene_text = str(scene or "").strip()
    if scene_text:
        parts.append(f"scene: {scene_text}")
    weather_text = str(weather or "").strip()
    if weather_text:
        parts.append(f"weather: {weather_text}")
    if injury is not None:
        try:
            level = float(injury)
        except (TypeError, ValueError):
            level = 0.0
        if level > 0:
            parts.append(f"visible injury level {level:.2f}")
    cleaned_user = str(user_extra or "").strip()
    if cleaned_user:
        parts.append(cleaned_user)
    return ", ".join(parts)


def step_priority(base_priority: int, step: dict[str, Any]) -> int:
    total = int(step.get("total_steps") or 0)
    index = int(step.get("step_index") or 0)
    return int(base_priority) + (total - index)


def initial_queue_status(step: dict[str, Any]) -> str:
    """只有沒有前置依賴的第一步是 pending，其餘先 waiting，避免一次全跑。"""
    return "pending" if not step.get("depends_on") else WAITING_STATUS


def build_age_span_evolution_params(
    step: dict[str, Any],
    *,
    pipeline_id: str,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    extra: str = "",
    persist: bool = True,
    entity_id: str | None = None,
    emotion: str | None = None,
    scene: str | None = None,
    weather: str | None = None,
    injury: float | None = None,
) -> dict[str, Any]:
    # api_key 仍接受以相容舊呼叫端，但絕不寫入佇列 JSON。
    _ = api_key
    age = int(step["age"])
    purpose = str(step["purpose"])
    token = _age_token(age)
    age_start = int(step.get("age_start") or age)
    age_end = int(step.get("age_end") or age)
    fill_span = bool(step.get("fill_span"))
    user_extra = str(extra or "").strip()
    emotion_text = str(emotion or "").strip() or None
    scene_text = str(scene or "").strip() or None
    weather_text = str(weather or "").strip() or None
    injury_value: float | None = None
    if injury is not None:
        try:
            injury_value = max(0.0, min(1.0, float(injury)))
        except (TypeError, ValueError):
            injury_value = None
    image_request: dict[str, Any] = {
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "extra": age_span_prompt_extra(
            phase=str(step["phase"]),
            age=age,
            user_extra=user_extra,
            emotion=emotion_text,
            scene=scene_text,
            weather=weather_text,
            injury=injury_value,
        ),
        "user_extra": user_extra,
        "n": 1,
        "multi_angle": False,
        "persist": persist,
        "entity_id": entity_id,
        "pipeline": AGE_SPAN_PIPELINE,
        "pipeline_id": pipeline_id,
        "phase": step["phase"],
        "age": age,
        "age_start": age_start,
        "age_end": age_end,
        "fill_span": fill_span,
        "step_index": step["step_index"],
        "total_steps": step["total_steps"],
        "depends_on": step.get("depends_on") if fill_span else None,
        "angle": step.get("angle"),
        "asset_dir": f"assets/{purpose}/age_{token}",
        "filename_prefix": f"ref_{purpose}_age_{token}",
        "emotion": emotion_text,
        "scene": scene_text,
        "weather": weather_text,
        "injury": injury_value,
    }
    params: dict[str, Any] = {
        "age_override": age,
        "purpose": purpose,
        "_image_request": image_request,
    }
    if emotion_text:
        params["emotion_state"] = emotion_text
    if scene_text:
        params["scene_context"] = scene_text
    if weather_text:
        params["weather"] = weather_text
    if injury_value:
        params["injury_level"] = injury_value
    return params


def phase_label(phase: str | None) -> str:
    key = str(phase or "").strip()
    return PHASE_LABELS.get(key, key or "生圖")


def step_phrase(image_request: dict[str, Any] | None) -> str:
    req = image_request if isinstance(image_request, dict) else {}
    label = phase_label(str(req.get("phase") or req.get("purpose") or ""))
    age = req.get("age")
    try:
        age_int = int(age)
    except (TypeError, ValueError):
        return label
    return f"{label} {age_int} 歲"


def _task_image_request(task: dict[str, Any]) -> dict[str, Any]:
    params = task.get("evolution_params") if isinstance(task.get("evolution_params"), dict) else {}
    image_request = params.get("_image_request")
    return dict(image_request) if isinstance(image_request, dict) else {}


def _task_review_status(task: dict[str, Any]) -> str:
    result_metadata = task.get("result_metadata") if isinstance(task.get("result_metadata"), dict) else {}
    image_generation = (
        result_metadata.get("image_generation")
        if isinstance(result_metadata.get("image_generation"), dict)
        else {}
    )
    review = image_generation.get("review") if isinstance(image_generation.get("review"), dict) else {}
    return str(
        review.get("status")
        or result_metadata.get("review_status")
        or image_generation.get("review_status")
        or ""
    ).strip().lower()


def _task_is_ready(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "").strip().lower() == "ready"


def _task_is_accepted(task: dict[str, Any]) -> bool:
    if not _task_is_ready(task):
        return False
    review = _task_review_status(task)
    if review == "accepted":
        return True
    if review == "rejected":
        return False
    # 生圖完成即自動入庫；ready 且已有結果即可銜接下一步
    return bool(_collect_image_uris(task))


def _condition_key(image_request: dict[str, Any] | None, evolution_params: dict[str, Any] | None = None) -> tuple:
    """外觀條件指紋：相同年齡但不同情緒／場景／天氣必須分開。"""
    params = dict(evolution_params or {})
    if image_request and "_image_request" not in params:
        params["_image_request"] = image_request
    canonical = canonical_evolution_params(params)
    injury = canonical.get("injury_level")
    injury_token: float | None = None
    if injury not in (None, ""):
        try:
            injury_token = round(float(injury), 2)
        except (TypeError, ValueError):
            injury_token = None
    return (
        str(canonical.get("emotion_state") or "").strip().lower(),
        str(canonical.get("scene_context") or "").strip().lower(),
        str(canonical.get("weather") or "").strip().lower(),
        injury_token,
    )


def find_pipeline_task(
    tasks: list[dict[str, Any]],
    *,
    pipeline_id: str,
    phase: str,
    age: int,
) -> dict[str, Any] | None:
    return find_age_phase_task(tasks, phase=phase, age=age, pipeline_id=pipeline_id)


def find_age_phase_task(
    tasks: list[dict[str, Any]],
    *,
    phase: str,
    age: int,
    pipeline_id: str | None = None,
    match_request: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """找指定歲數／用途的任務。優先相同演化條件，再同 pipeline，最後跨快取軟鎖定身份。"""
    matches: list[dict[str, Any]] = []
    for task in tasks:
        image_request = _task_image_request(task)
        task_phase = str(image_request.get("phase") or image_request.get("purpose") or "")
        if task_phase != phase:
            continue
        try:
            task_age = int(image_request.get("age") or 0)
        except (TypeError, ValueError):
            continue
        if task_age != int(age):
            continue
        matches.append(task)
    if not matches:
        return None
    want = _condition_key(match_request)

    def _score(task: dict[str, Any]) -> tuple:
        req = _task_image_request(task)
        same_cond = 0 if _condition_key(req, task.get("evolution_params")) == want else 1
        same_pipe = 0 if pipeline_id and str(req.get("pipeline_id") or "") == pipeline_id else 1
        accepted = 0 if _task_is_accepted(task) else 1
        ready = 0 if _task_is_ready(task) else 1
        return (same_cond, same_pipe, accepted, ready, -int(task.get("id") or 0))

    matches.sort(key=_score)
    return matches[0]


def extract_public_image_url(payload: dict[str, Any] | None) -> str | None:
    """從生圖 payload／任務 metadata 取出 WAN 可用的公開參考網址。"""
    data = payload if isinstance(payload, dict) else {}
    candidates: list[Any] = [data.get("lock_url")]
    image_generation = data.get("image_generation") if isinstance(data.get("image_generation"), dict) else data
    if isinstance(image_generation, dict):
        candidates.append(image_generation.get("lock_url"))
        for image in image_generation.get("images") or []:
            if isinstance(image, dict):
                candidates.extend((image.get("url"), image.get("uri")))
        candidates.extend(
            (
                image_generation.get("url"),
                image_generation.get("uri"),
            )
        )
    for image in data.get("images") or []:
        if isinstance(image, dict):
            candidates.extend((image.get("url"), image.get("uri")))
    for value in candidates:
        text = str(value or "").strip()
        if text.lower().startswith(("http://", "https://")):
            return text
    return None


def stamp_lock_url(result_metadata: dict[str, Any], payload: dict[str, Any] | None = None) -> str | None:
    """把本步產出的公開 URL 標成 lock_url，供下一步身份鎖定。"""
    url = extract_public_image_url(payload) or extract_public_image_url(result_metadata)
    if not url:
        return None
    result_metadata["lock_url"] = url
    image_generation = result_metadata.get("image_generation")
    if isinstance(image_generation, dict):
        image_generation["lock_url"] = url
    return url


def _collect_image_uris(task: dict[str, Any]) -> list[str]:
    result_metadata = task.get("result_metadata") if isinstance(task.get("result_metadata"), dict) else {}
    image_generation = (
        result_metadata.get("image_generation")
        if isinstance(result_metadata.get("image_generation"), dict)
        else {}
    )
    uris: list[str] = []
    seen: set[str] = set()

    def _push(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        uris.append(text)

    _push(result_metadata.get("lock_url"))
    _push(image_generation.get("lock_url"))
    for image in image_generation.get("images") or []:
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "").strip()
        uri = str(image.get("uri") or "").strip()
        if url:
            _push(url)
        elif uri:
            _push(uri)
        else:
            _push(image.get("asset_path"))
    if not uris:
        for key in ("face_detail_asset_path", "thumbnail_asset_path"):
            _push(image_generation.get(key))
    return uris


def _prefer_http_uris(values: list[str]) -> list[str]:
    https: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        lowered = cleaned.lower()
        if lowered.startswith("file:"):
            continue
        seen.add(cleaned)
        if lowered.startswith(("http://", "https://")):
            https.append(cleaned)
        else:
            rest.append(cleaned)
    return https + rest


def _https_only(values: list[str]) -> list[str]:
    return [
        item
        for item in _prefer_http_uris(values)
        if str(item).lower().startswith(("http://", "https://"))
    ]


def _lock_uris_from_task(task: dict[str, Any] | None) -> list[str]:
    if not task:
        return []
    collected = _collect_image_uris(task)
    return _https_only(collected) or _prefer_http_uris(collected)[:2]


def _lock_uris_from_manifest(manifest: dict[str, Any] | None, *, phase: str, age: int) -> list[str]:
    data = manifest if isinstance(manifest, dict) else {}
    extensions = data.get("_extensions") if isinstance(data.get("_extensions"), dict) else {}
    image_gen = extensions.get("image_gen") if isinstance(extensions.get("image_gen"), dict) else {}
    age_span = image_gen.get("age_span") if isinstance(image_gen.get("age_span"), dict) else {}
    bucket_name = "faces" if phase == FACE_PHASE else "tposes" if phase == TPOSE_PHASE else ""
    bucket = age_span.get(bucket_name) if isinstance(age_span.get(bucket_name), dict) else {}
    refs = bucket.get(str(age)) or bucket.get(age) or []
    uris: list[str] = []
    if isinstance(refs, dict):
        refs = [refs]
    for item in refs if isinstance(refs, list) else []:
        if not isinstance(item, dict):
            continue
        uris.extend((item.get("uri"), item.get("url"), item.get("path")))
    https = _https_only(uris)
    return https or _prefer_http_uris(uris)[:2]


def collect_age_span_ref_uris(
    tasks: list[dict[str, Any]],
    image_request: dict[str, Any],
    *,
    seed_uris: list[str] | None = None,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    pipeline_id = str(image_request.get("pipeline_id") or "").strip()
    phase = str(image_request.get("phase") or image_request.get("purpose") or "").strip()
    age = int(image_request.get("age") or 0)
    if age < 1:
        return []
    seed = _https_only(list(seed_uris or [])) or _prefer_http_uris(list(seed_uris or []))

    def _face_lock(target_age: int) -> list[str]:
        task = find_age_phase_task(
            tasks,
            phase=FACE_PHASE,
            age=target_age,
            pipeline_id=pipeline_id or None,
            match_request=image_request,
        )
        return _lock_uris_from_task(task) or _lock_uris_from_manifest(
            manifest, phase=FACE_PHASE, age=target_age
        )

    def _tpose_lock(target_age: int) -> list[str]:
        task = find_age_phase_task(
            tasks,
            phase=TPOSE_PHASE,
            age=target_age,
            pipeline_id=pipeline_id or None,
            match_request=image_request,
        )
        return _lock_uris_from_task(task) or _lock_uris_from_manifest(
            manifest, phase=TPOSE_PHASE, age=target_age
        )

    def _nearest_younger(lock_fn, target_age: int) -> list[str]:
        for previous in range(int(target_age) - 1, 0, -1):
            uris = lock_fn(previous)
            if uris:
                return uris
        return []

    if phase == FACE_PHASE:
        previous = _nearest_younger(_face_lock, age)
        return (previous or seed)[:2]

    uris = list(_face_lock(age)[:1] or _nearest_younger(_face_lock, age)[:1] or seed[:1])
    previous_tpose = _tpose_lock(age - 1) if age > 1 else []
    if not previous_tpose and age > 1:
        previous_tpose = _nearest_younger(_tpose_lock, age)
    for uri in previous_tpose:
        if uri not in uris:
            uris.append(uri)
        if len(uris) >= 2:
            break
    return uris[:2]


def ensure_age_span_dependencies(
    tasks: list[dict[str, Any]],
    image_request: dict[str, Any],
) -> None:
    if str(image_request.get("pipeline") or "") != AGE_SPAN_PIPELINE:
        return
    pipeline_id = str(image_request.get("pipeline_id") or "").strip()
    current_phase = str(image_request.get("phase") or image_request.get("purpose") or "").strip()
    current_age = int(image_request.get("age") or 0)
    if not is_span_fill(image_request):
        if current_phase == TPOSE_PHASE and current_age >= 1:
            matching_face = find_age_phase_task(
                tasks,
                phase=FACE_PHASE,
                age=current_age,
                pipeline_id=pipeline_id or None,
            )
            if matching_face and not _task_is_accepted(matching_face):
                raise AgeSpanDependencyPending(
                    f"年齡軸 T 型體需先完成 face_detail {current_age} 歲"
                )
        return
    depends_on = image_request.get("depends_on")
    if not isinstance(depends_on, dict):
        return
    phase = str(depends_on.get("phase") or "").strip()
    age = int(depends_on.get("age") or 0)
    previous = find_age_phase_task(tasks, phase=phase, age=age, pipeline_id=pipeline_id or None)
    if not previous or not _task_is_accepted(previous):
        raise AgeSpanDependencyPending(
            f"年齡軸任務需先完成 {phase} {age} 歲，以維持連貫外觀"
        )
    if current_phase == TPOSE_PHASE and current_age >= 1:
        matching_face = find_age_phase_task(
            tasks,
            phase=FACE_PHASE,
            age=current_age,
            pipeline_id=pipeline_id or None,
        )
        if not matching_face or not _task_is_accepted(matching_face):
            raise AgeSpanDependencyPending(
                f"年齡軸 T 型體需先完成 face_detail {current_age} 歲"
            )


def prepare_queued_image_generation(
    evolved_manifest: dict[str, Any],
    image_request: dict[str, Any],
    *,
    sibling_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """補齊年齡軸參考圖與檔名；非年齡軸任務則原樣返回。"""

    extra = str(image_request.get("extra") or "")
    extra_fields = {
        key: value
        for key, value in {
            "asset_dir": image_request.get("asset_dir"),
            "filename_prefix": image_request.get("filename_prefix"),
            "angle": image_request.get("angle"),
            "age": image_request.get("age"),
            "pipeline": image_request.get("pipeline"),
            "pipeline_id": image_request.get("pipeline_id"),
        }.items()
        if value not in (None, "")
    }
    extra_ref_uris: list[str] = []
    if str(image_request.get("pipeline") or "") == AGE_SPAN_PIPELINE:
        ensure_age_span_dependencies(sibling_tasks or [], image_request)
        from narratron.charpass.style_prompt import collect_ref_image_uris

        extra_ref_uris = collect_age_span_ref_uris(
            sibling_tasks or [],
            image_request,
            seed_uris=collect_ref_image_uris(evolved_manifest),
            manifest=evolved_manifest,
        )
        # 參考圖只交給本次 API 請求，不可覆寫護照 identity.ref_images
    return {
        "extra": extra,
        "extra_fields": extra_fields,
        "extra_ref_uris": extra_ref_uris,
        "multi_angle": bool(image_request.get("multi_angle", True)),
    }


def following_step(image_request: dict[str, Any]) -> dict[str, Any] | None:
    """目前步驟完成後，下一筆應生成的步驟。按需模式只銜接同歲 T 型；區間模式才往下一歲走。"""
    fill_span = is_span_fill(image_request)
    start = int(image_request.get("age_start") or image_request.get("age") or AGE_SPAN_START)
    end = int(image_request.get("age_end") or image_request.get("age") or start)
    steps = age_span_steps(age_start=start, age_end=end, fill_span=fill_span)
    index = int(image_request.get("step_index") or 0)
    if index < 0 or index + 1 >= len(steps):
        return None
    return steps[index + 1]


def evolution_params_from_previous(
    next_step: dict[str, Any],
    previous_request: dict[str, Any],
) -> dict[str, Any]:
    return build_age_span_evolution_params(
        next_step,
        pipeline_id=str(previous_request.get("pipeline_id") or ""),
        provider=previous_request.get("provider"),
        model=previous_request.get("model"),
        base_url=previous_request.get("base_url"),
        api_key=previous_request.get("api_key"),
        extra=str(previous_request.get("user_extra") or ""),
        persist=bool(previous_request.get("persist", True)),
        entity_id=previous_request.get("entity_id"),
        emotion=previous_request.get("emotion") or previous_request.get("emotion_state"),
        scene=previous_request.get("scene") or previous_request.get("scene_context"),
        weather=previous_request.get("weather"),
        injury=previous_request.get("injury") or previous_request.get("injury_level"),
    )


def missing_next_step(
    tasks: list[dict[str, Any]],
    pipeline_id: str,
) -> dict[str, Any] | None:
    """若 pipeline 未結束且下一步尚未入列，回傳該步驟定義。"""
    group = tasks_for_pipeline(tasks, pipeline_id)
    if not group:
        return None
    for task in group:
        status = str(task.get("status") or "").strip().lower()
        if status in {"pending", "failed", WAITING_STATUS}:
            return None
    accepted = [task for task in group if _task_is_accepted(task)]
    if not accepted:
        return None
    last = max(
        accepted,
        key=lambda item: int(_task_image_request(item).get("step_index") or 0),
    )
    nxt = following_step(_task_image_request(last))
    if nxt is None:
        return None
    existing = find_pipeline_task(
        tasks,
        pipeline_id=pipeline_id,
        phase=str(nxt["phase"]),
        age=int(nxt["age"]),
    )
    if existing:
        return None
    return nxt


def next_enqueue_payload(
    tasks: list[dict[str, Any]],
    pipeline_id: str,
) -> dict[str, Any] | None:
    """組出下一步入列所需的 evolution_params；無需入列則回傳 None。"""
    nxt = missing_next_step(tasks, pipeline_id)
    if nxt is None:
        return None
    group = tasks_for_pipeline(tasks, pipeline_id)
    template = max(
        group,
        key=lambda item: int(_task_image_request(item).get("step_index") or 0),
    )
    previous_request = _task_image_request(template)
    return {
        "core_id": int(template.get("core_id") or 0),
        "character_name": template.get("character_name"),
        "evolution_params": evolution_params_from_previous(nxt, previous_request),
        "priority": step_priority(0, nxt),
        "step": nxt,
    }


def find_open_age_span_pipeline_id(tasks: list[dict[str, Any]]) -> str | None:
    for pipeline_id, group in _pipeline_groups(tasks).items():
        if not pipeline_id:
            continue
        for task in group:
            status = str(task.get("status") or "").strip().lower()
            if status in {"pending", WAITING_STATUS, "failed", RUNNING_STATUS}:
                return pipeline_id
        if missing_next_step(tasks, pipeline_id):
            return pipeline_id
    return None


def pipeline_groups(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """依 pipeline_id 分組年齡軸任務。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        image_request = _task_image_request(task)
        if str(image_request.get("pipeline") or "") != AGE_SPAN_PIPELINE:
            continue
        pipeline_id = str(image_request.get("pipeline_id") or "")
        grouped.setdefault(pipeline_id, []).append(task)
    return grouped


# 向後相容舊 import
_pipeline_groups = pipeline_groups


def activate_next_waiting_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """每個 pipeline 最多一筆 pending／running；前置步驟入庫後，才把下一步從 waiting 轉成 pending。"""
    recover_stale_running_tasks(tasks)
    activated: dict[str, Any] | None = None
    for pipeline_tasks in _pipeline_groups(tasks).values():
        if any(
            str(item.get("status") or "").strip().lower() in {"pending", RUNNING_STATUS}
            for item in pipeline_tasks
        ):
            continue
        waiting = sorted(
            [
                item
                for item in pipeline_tasks
                if str(item.get("status") or "").strip().lower() == WAITING_STATUS
            ],
            key=lambda item: (
                int(_task_image_request(item).get("step_index") or 0),
                int(item.get("id") or 0),
            ),
        )
        for task in waiting:
            try:
                ensure_age_span_dependencies(tasks, _task_image_request(task))
            except AgeSpanDependencyPending:
                continue
            task["status"] = "pending"
            if activated is None:
                activated = task
            break
    return activated


def normalize_age_span_queue(tasks: list[dict[str, Any]]) -> None:
    """把多筆同時 pending 的年齡軸步驟收斂成一次只開放下一步。"""
    recover_stale_running_tasks(tasks)
    for pipeline_tasks in _pipeline_groups(tasks).values():
        if any(str(item.get("status") or "").strip().lower() == RUNNING_STATUS for item in pipeline_tasks):
            for item in pipeline_tasks:
                status = str(item.get("status") or "").strip().lower()
                if status == "pending":
                    item["status"] = WAITING_STATUS
            continue
        candidates = sorted(
            [
                item
                for item in pipeline_tasks
                if str(item.get("status") or "").strip().lower() in {"pending", WAITING_STATUS}
            ],
            key=lambda item: (
                int(_task_image_request(item).get("step_index") or 0),
                int(item.get("id") or 0),
            ),
        )
        found_runnable = False
        for task in candidates:
            try:
                ensure_age_span_dependencies(tasks, _task_image_request(task))
            except AgeSpanDependencyPending:
                task["status"] = WAITING_STATUS
                continue
            if found_runnable:
                task["status"] = WAITING_STATUS
                continue
            task["status"] = "pending"
            found_runnable = True


def tasks_for_pipeline(tasks: list[dict[str, Any]], pipeline_id: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for task in tasks:
        image_request = _task_image_request(task)
        if str(image_request.get("pipeline_id") or "") == pipeline_id:
            matched.append(task)
    return matched


def new_pipeline_id() -> str:
    return f"age-span-{uuid4()}"


def _age_span_tasks(
    tasks: list[dict[str, Any]],
    *,
    core_id: int | None = None,
    pipeline_id: str | None = None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for task in tasks:
        image_request = _task_image_request(task)
        if str(image_request.get("pipeline") or "") != AGE_SPAN_PIPELINE:
            continue
        if core_id is not None and int(task.get("core_id", 0)) != int(core_id):
            continue
        if pipeline_id is not None and str(image_request.get("pipeline_id") or "") != pipeline_id:
            continue
        matched.append(task)
    matched.sort(
        key=lambda item: (
            int(_task_image_request(item).get("step_index") or 0),
            int(item.get("id") or 0),
        )
    )
    return matched


def find_age_span_blocking_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """年齡軸已改為自動入庫，不再因待審核而阻擋。"""
    return None


def _step_effective_status(task: dict[str, Any] | None) -> str:
    if task is None:
        return "missing"
    if _task_is_accepted(task):
        return "accepted"
    status = str(task.get("status") or "").strip().lower()
    if status == "failed":
        return "failed"
    if status == "pending":
        return "pending"
    if status == RUNNING_STATUS:
        return RUNNING_STATUS
    if status == WAITING_STATUS:
        return WAITING_STATUS
    if status == "ready":
        review = _task_review_status(task)
        if review == "rejected":
            return "rejected"
        if review == "accepted" or _collect_image_uris(task):
            return "accepted"
        return "ready"
    return status or "unknown"


def _build_pipeline_steps(pipeline_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not pipeline_tasks:
        return []
    first_request = _task_image_request(pipeline_tasks[0])
    fill_span = is_span_fill(first_request)
    start = int(first_request.get("age_start") or first_request.get("age") or AGE_SPAN_START)
    end = int(first_request.get("age_end") or first_request.get("age") or start)
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for task in pipeline_tasks:
        image_request = _task_image_request(task)
        key = (
            str(image_request.get("phase") or image_request.get("purpose") or ""),
            int(image_request.get("age") or 0),
        )
        by_key[key] = task
    steps: list[dict[str, Any]] = []
    for planned in age_span_steps(age_start=start, age_end=end, fill_span=fill_span):
        task = by_key.get((str(planned["phase"]), int(planned["age"])))
        if task is None:
            steps.append(
                {
                    "task_id": None,
                    "step_index": int(planned["step_index"]),
                    "phase": str(planned["phase"]),
                    "age": int(planned["age"]),
                    "status": "missing",
                    "error_message": None,
                }
            )
            continue
        image_request = _task_image_request(task)
        steps.append(
            {
                "task_id": int(task.get("id") or 0) or None,
                "step_index": int(image_request.get("step_index") or planned["step_index"]),
                "phase": str(image_request.get("phase") or image_request.get("purpose") or planned["phase"]),
                "age": int(image_request.get("age") or planned["age"]) or None,
                "status": _step_effective_status(task),
                "error_message": task.get("error_message"),
            }
        )
    return steps


def summarize_age_span_pipeline(
    tasks: list[dict[str, Any]],
    *,
    core_id: int | None = None,
    pipeline_id: str | None = None,
) -> dict[str, Any] | None:
    """彙整年齡軸 pipeline 進度與下一個可執行／阻擋步驟。"""
    pipeline_tasks = _age_span_tasks(tasks, core_id=core_id, pipeline_id=pipeline_id)
    if not pipeline_tasks:
        return None

    resolved_pipeline_id = pipeline_id or str(
        _task_image_request(pipeline_tasks[0]).get("pipeline_id") or ""
    ).strip()
    accepted = [task for task in pipeline_tasks if _task_is_accepted(task)]
    ready_pending = [
        task
        for task in pipeline_tasks
        if _task_is_ready(task) and _task_review_status(task) in {"", "pending"}
    ]
    pending = [
        task
        for task in pipeline_tasks
        if str(task.get("status") or "").strip().lower() == "pending"
    ]
    running = [
        task
        for task in pipeline_tasks
        if str(task.get("status") or "").strip().lower() == RUNNING_STATUS
    ]
    waiting = [
        task
        for task in pipeline_tasks
        if str(task.get("status") or "").strip().lower() == WAITING_STATUS
    ]
    failed = [
        task
        for task in pipeline_tasks
        if str(task.get("status") or "").strip().lower() == "failed"
    ]
    blocking = None
    preview = [dict(task) for task in tasks]
    if running:
        runnable = running[0]
        runnable_image_request = _task_image_request(runnable)
    else:
        activate_next_waiting_task(preview)
        runnable = find_next_runnable_task(preview)
        runnable_image_request = _task_image_request(runnable) if runnable else {}
        if runnable and str(runnable_image_request.get("pipeline") or "") != AGE_SPAN_PIPELINE:
            runnable = None
            runnable_image_request = {}

    blocking_reason: str | None = None
    if failed:
        first_failed = failed[0]
        image_request = _task_image_request(first_failed)
        blocking_reason = (
            f"任務 #{first_failed.get('id')} 失敗：{first_failed.get('error_message') or '未知錯誤'}。"
            "請按「重設失敗並繼續」後再試。"
        )

    total_steps = int(_task_image_request(pipeline_tasks[0]).get("total_steps") or len(pipeline_tasks))
    planned_steps = _build_pipeline_steps(pipeline_tasks)
    missing_count = sum(1 for item in planned_steps if item.get("status") == "missing")
    has_open = bool(
        pending or waiting or failed or running or missing_next_step(pipeline_tasks, resolved_pipeline_id)
    )
    name = pipeline_tasks[0].get("character_name") or f"角色 #{pipeline_tasks[0].get('core_id')}"
    done = f"{len(accepted)}/{total_steps}"
    if blocking_reason:
        headline = blocking_reason
    elif running:
        headline = f"正在生成 {name} · {step_phrase(runnable_image_request)}（{done}）"
    elif runnable:
        headline = f"排隊中 {name} · 下一步 {step_phrase(runnable_image_request)}（{done}）"
    elif has_open:
        headline = f"{name} 年齡軸進行中（{done}）"
    else:
        headline = f"{name} 年齡軸已完成（{done}）"
    return {
        "pipeline_id": resolved_pipeline_id or None,
        "core_id": int(pipeline_tasks[0].get("core_id") or 0) or None,
        "character_name": pipeline_tasks[0].get("character_name"),
        "total_steps": total_steps,
        "accepted_count": len(accepted),
        "ready_pending_review_count": len(ready_pending),
        "pending_count": len(pending),
        "waiting_count": len(waiting) + missing_count,
        "running_count": len(running),
        "failed_count": len(failed),
        "blocking_task_id": int(blocking["id"]) if blocking else None,
        "blocking_reason": blocking_reason,
        "next_runnable_task_id": int(runnable["id"]) if runnable else None,
        "next_phase": runnable_image_request.get("phase") if runnable else None,
        "next_age": runnable_image_request.get("age") if runnable else None,
        "has_open_pipeline": has_open,
        "headline": headline,
        "steps": planned_steps,
    }


def find_next_runnable_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """找出下一筆可執行的 pending 任務（全系統同時只允許一張 in-flight）。"""
    recover_stale_running_tasks(tasks)
    if has_in_flight_generation(tasks):
        return None
    pending = [task for task in tasks if str(task.get("status") or "").strip().lower() == "pending"]

    def _sort_key(task: dict[str, Any]) -> tuple:
        image_request = _task_image_request(task)
        if str(image_request.get("pipeline") or "") == AGE_SPAN_PIPELINE:
            return (
                0,
                int(image_request.get("step_index") or 0),
                int(task.get("id") or 0),
            )
        return (
            1,
            -int(task.get("priority") or 0),
            str(task.get("created_at") or ""),
            int(task.get("id") or 0),
        )

    pending.sort(key=_sort_key)
    for task in pending:
        image_request = _task_image_request(task)
        if str(image_request.get("pipeline") or "") != AGE_SPAN_PIPELINE:
            return task
        try:
            ensure_age_span_dependencies(tasks, image_request)
            return task
        except AgeSpanDependencyPending:
            continue
    return None
