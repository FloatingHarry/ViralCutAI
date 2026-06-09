from __future__ import annotations

import json
import re
import time
from typing import Any, Literal, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.services.viral_library import build_factor_board


class ProviderExecutionError(RuntimeError):
    """Raised when a configured real provider fails and mock fallback is not allowed."""


EDITING_SHOT_COUNT = 3
MAX_EDITING_SHOT_COUNT = 3
SHOT_CLIP_DURATION_SECONDS = 4
MAX_TIMELINE_DURATION_SECONDS = 12
FACTOR_CATEGORIES = ("hook", "proof", "scene", "trust", "visual", "audio", "cta", "risk")
SEGMENT_BEATS = ("Hook", "Proof + Use", "CTA")


class GenerationGraphState(TypedDict, total=False):
    run_id: str
    request: dict[str, Any]
    strategy: dict[str, Any]
    script: dict[str, Any]
    storyboard: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    preview: dict[str, Any]
    export_manifest: dict[str, Any]
    compliance: dict[str, Any]
    trace: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    strategy_attempts: int
    script_attempts: int


def _clean_points(points: list[str] | None) -> list[str]:
    cleaned = [point.strip() for point in points or [] if point.strip()]
    return cleaned or ["clear product benefit", "easy daily use", "visual proof"]


def _short(text: str, fallback: str) -> str:
    value = (text or "").strip()
    return value if value else fallback


def _valid_short_sentence(value: Any, *, min_chars: int = 10, max_chars: int = 220) -> bool:
    if not isinstance(value, str):
        return False
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) < min_chars or len(text) > max_chars:
        return False
    return not re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?", text)


def _limit_text(value: Any, length: int, fallback: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or fallback)).strip()
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)].rstrip() + "..."


def _response_excerpt(content: str) -> str:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text:
        return "empty response"
    if len(text) <= 420:
        return text
    return f"{text[:210]} ... {text[-210:]}"


def _asset_summary(request: dict[str, Any]) -> str:
    assets = request.get("source_assets") or []
    retrieval = request.get("retrieval_context") or {}
    if not assets and not retrieval:
        return "No uploaded source assets; rely on product notes and provider prompts."
    names = ", ".join(asset.get("filename", "source asset") for asset in assets[:4])
    retrieval_note = retrieval.get("evidence_summary") or ""
    if names and retrieval_note:
        return f"{len(assets)} source assets: {names}. Retrieval: {retrieval_note}."
    if names:
        return f"{len(assets)} source assets: {names}."
    return f"Retrieval: {retrieval_note}."


def _shot_durations(total_seconds: int, shot_count: int = EDITING_SHOT_COUNT) -> list[int]:
    count = max(1, min(int(shot_count or EDITING_SHOT_COUNT), MAX_EDITING_SHOT_COUNT))
    total = max(count, min(int(total_seconds or 12), MAX_TIMELINE_DURATION_SECONDS))
    base = total // count
    remainder = total % count
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _text_provider_configured() -> bool:
    settings = get_settings()
    return bool(settings.volcengine_api_key and (settings.volcengine_endpoint_id or settings.volcengine_text_model))


def _image_generation_configured() -> bool:
    settings = get_settings()
    return bool(settings.volcengine_api_key and settings.volcengine_image_model)


def _video_provider_configured() -> bool:
    settings = get_settings()
    return bool(settings.seedance_api_key and (settings.seedance_endpoint_id or settings.seedance_model))


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    settings = get_settings()
    for secret in (settings.volcengine_api_key, settings.seedance_api_key):
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]", message)
    return message[:800]


def _is_tpm_rate_limit(exc: Exception) -> bool:
    message = str(exc)
    return "EndpointTPMExceeded" in message or "RateLimitExceeded" in message or "HTTP 429" in message


def _provider_retry_delay_seconds(exc: Exception, attempt: int) -> int:
    if _is_tpm_rate_limit(exc):
        return 45 if attempt == 1 else 65
    return attempt


def _text_task_temperature(task: str) -> float:
    if task in {"strategy_brief", "factor_board_packaging", "copy_draft", "storyboard_plan", "prompt_package", "segment_rewrite"}:
        return 0.1
    return 0.35


def _text_task_max_tokens(task: str) -> int:
    if task == "strategy_brief":
        return 800
    if task == "factor_board_packaging":
        return 1300
    if task == "copy_draft":
        return 900
    if task == "storyboard_plan":
        return 1100
    if task == "prompt_package":
        return 850
    if task == "script_storyboard":
        return 2200
    if task == "segment_rewrite":
        return 900
    if task == "viral_strategy":
        return 1700
    return 1800


def _join_api_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def _ark_base_url(value: str | None) -> str:
    base = (value or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    if "/api/v3" not in base:
        return f"{base}/api/v3"
    return base


def _raise_for_status(response: httpx.Response, context: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:600]
        raise RuntimeError(f"{context} failed with HTTP {response.status_code}: {detail}") from exc


def _is_retryable_seedance_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    message = str(exc)
    return "HTTP 429" in message or "HTTP 500" in message or "HTTP 502" in message or "HTTP 503" in message or "HTTP 504" in message


def _json_control_safe_text(text: str) -> str:
    cleaned: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        code = ord(char)
        if escaped:
            cleaned.append("n" if code < 32 else char)
            escaped = False
            continue
        if char == "\\" and in_string:
            cleaned.append(char)
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            cleaned.append(char)
            continue
        if code < 32:
            if in_string:
                cleaned.append(" ")
            elif char in "\r\n\t":
                cleaned.append(char)
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    text = _json_control_safe_text(text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Provider response did not contain a JSON object.") from None
        parsed = json.loads(_json_control_safe_text(match.group(0)))
    if not isinstance(parsed, dict):
        raise ValueError("Provider response JSON was not an object.")
    return parsed


def _compact_request_for_llm(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "generation_mode": request.get("generation_mode"),
        "product_name": request.get("product_name"),
        "category": request.get("category"),
        "selling_points": request.get("selling_points", [])[:5],
        "target_audience": request.get("target_audience"),
        "price_offer": request.get("price_offer"),
        "material_notes": request.get("material_notes"),
        "creative_goal": request.get("creative_goal"),
        "reference_style": request.get("reference_style"),
        "visual_style": request.get("visual_style"),
        "duration_seconds": request.get("duration_seconds"),
        "platform": request.get("platform"),
        "source_assets": [
            {
                "filename": asset.get("filename"),
                "asset_kind": asset.get("asset_kind"),
                "description": str(asset.get("description", ""))[:180],
            }
            for asset in (request.get("source_assets") or [])[:4]
        ],
        "asset_collection": request.get("asset_collection"),
        "asset_library": [
            {
                "filename": asset.get("filename"),
                "summary": str(asset.get("summary") or asset.get("description") or "")[:180],
                "tags": asset.get("tags", [])[:8],
            }
            for asset in (request.get("asset_library") or [])[:4]
        ],
        "retrieval_context": _compact_retrieval_context(request.get("retrieval_context") or {}),
        "reference_video": request.get("reference_video"),
        "creative_template": request.get("creative_template"),
        "selected_factors": [
            {
                "name": factor.get("name"),
                "category": factor.get("category"),
                "reason": str(factor.get("reason") or factor.get("description") or "")[:160],
            }
            for factor in (request.get("selected_factors") or request.get("viral_factors") or [])[:8]
        ],
    }


def _compact_retrieval_context(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_query": retrieval.get("asset_query"),
        "evidence_summary": retrieval.get("evidence_summary"),
        "selected_collection": retrieval.get("selected_collection"),
        "methodology_summary": retrieval.get("methodology_summary"),
        "reference_match_mode": retrieval.get("reference_match_mode"),
        "reference_match_reason": retrieval.get("reference_match_reason"),
        "selected_reference_video": _compact_reference_for_llm(retrieval.get("selected_reference_video")),
        "auto_asset_results": [
            {
                "filename": item.get("filename"),
                "score": item.get("score"),
                "reason": item.get("reason"),
                "usable_for": item.get("usable_for", [])[:4],
                "matched_slices": [
                    {
                        "slice_id": slice_item.get("slice_id"),
                        "summary": str(slice_item.get("summary", ""))[:140],
                        "usable_for": slice_item.get("usable_for"),
                    }
                    for slice_item in item.get("matched_slices", [])[:2]
                ],
            }
            for item in retrieval.get("auto_asset_results", [])[:4]
        ],
        "selected_slices": [
            {
                "slice_id": item.get("slice_id"),
                "filename": item.get("filename"),
                "summary": str(item.get("summary", ""))[:140],
                "usable_for": item.get("usable_for"),
            }
            for item in retrieval.get("selected_slices", [])[:4]
        ],
        "auto_factors": [
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "source": item.get("source"),
                "reason": str(item.get("description") or item.get("reason") or "")[:160],
                "source_reference_id": item.get("source_reference_id"),
                "visual_verified": item.get("visual_verified"),
                "evidence_type": item.get("evidence_type"),
            }
            for item in retrieval.get("auto_factors", [])[:8]
        ],
        "auto_templates": [
            {"name": item.get("name"), "strategy": str(item.get("strategy", ""))[:160]}
            for item in retrieval.get("auto_templates", [])[:3]
        ],
    }


def _compact_reference_for_llm(reference: Any) -> dict[str, Any] | None:
    if not isinstance(reference, dict):
        return None
    summary = reference.get("summary") if isinstance(reference.get("summary"), dict) else {}
    return {
        "id": reference.get("id"),
        "title": reference.get("title"),
        "category": reference.get("category"),
        "source_url": reference.get("source_url"),
        "source_mode": reference.get("source_mode"),
        "source_capability": reference.get("source_capability"),
        "visual_verified": reference.get("visual_verified"),
        "hook_method": summary.get("hook_method"),
        "selling_point_order": summary.get("selling_point_order", [])[:4],
        "caption_style": summary.get("caption_style"),
        "cta_pattern": summary.get("cta_pattern"),
        "risk_notes": summary.get("risk_notes", [])[:3],
        "metrics": summary.get("metrics"),
        "storyboard_structure": reference.get("storyboard_structure", [])[:6],
    }


def _compact_strategy_for_llm(strategy: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_angle": strategy.get("product_angle"),
        "hook": strategy.get("hook"),
        "audience_pain": strategy.get("audience_pain"),
        "retrieval_evidence": [
            {
                "type": item.get("type"),
                "title": item.get("title"),
                "reason": str(item.get("reason") or "")[:160],
                "usable_for": item.get("usable_for", [])[:4],
            }
            for item in (strategy.get("retrieval_evidence") or [])[:5]
        ],
        "asset_usage_plan": [
            {
                "shot_id": item.get("shot_id"),
                "asset_title": item.get("asset_title"),
                "usage": item.get("usage"),
                "reason": str(item.get("reason") or "")[:160],
            }
            for item in (strategy.get("asset_usage_plan") or [])[:5]
        ],
        "factor_selection_reason": [
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "source": item.get("source"),
                "reason": str(item.get("reason") or "")[:90],
            }
            for item in (strategy.get("factor_selection_reason") or [])[:8]
        ],
        "selling_point_order": strategy.get("selling_point_order", [])[:5],
        "content_rhythm": strategy.get("content_rhythm", [])[:5],
        "factor_board": [
            {
                "factor_key": factor.get("factor_key"),
                "name": factor.get("name"),
                "category": factor.get("category"),
                "reason": str(factor.get("reason", ""))[:90],
                "linked_shot_ids": factor.get("linked_shot_ids", []),
            }
            for factor in (strategy.get("factor_board") or strategy.get("selected_factors") or [])[:8]
        ],
        "risk_notes": strategy.get("risk_notes", [])[:4],
    }


def _provider_trace_value(provider: Any, attr: str, fallback: str) -> str:
    return str(getattr(provider, attr, None) or fallback)


def _fallback_trace(provider: Any, default: str) -> str:
    return str(getattr(provider, "last_fallback", None) or default)


def _status_trace(provider: Any) -> str:
    return "failed" if _provider_status_value(provider) == "error" else "succeeded"


def _execution_trace_value(provider: Any) -> str:
    return str(getattr(provider, "last_execution_mode", "mock_missing_config"))


def _provider_status_value(provider: Any) -> str:
    return str(getattr(provider, "last_provider_status", "missing_config"))


def _provider_message_value(provider: Any) -> str:
    return str(getattr(provider, "last_provider_message", "Provider status was not recorded."))


def _combine_execution_modes(*providers: Any) -> str:
    modes = [_execution_trace_value(provider) for provider in providers]
    if "real_failed" in modes:
        return "real_failed"
    if "mock_missing_config" in modes:
        return "mock_missing_config"
    return "real"


def _combine_provider_statuses(*providers: Any) -> str:
    statuses = [_provider_status_value(provider) for provider in providers]
    if "error" in statuses:
        return "error"
    if "missing_config" in statuses:
        return "missing_config"
    return "configured"


def _combine_substep_execution_modes(substeps: list[dict[str, Any]]) -> str:
    modes = [str(step.get("execution_mode") or "mock_missing_config") for step in substeps]
    if "real_failed" in modes:
        return "real_failed"
    if any("fallback" in mode for mode in modes):
        return "real_with_local_fallback"
    if "mock_missing_config" in modes:
        return "mock_missing_config"
    return "real"


def _combine_substep_provider_statuses(substeps: list[dict[str, Any]]) -> str:
    statuses = [str(step.get("provider_status") or "missing_config") for step in substeps]
    if "error" in statuses:
        return "error"
    if "missing_config" in statuses:
        return "missing_config"
    return "configured"


def _substep_trace(
    *,
    substep_name: str,
    provider: str,
    model: str,
    started_at: float,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    execution_mode: str,
    provider_status: str,
    provider_message: str,
    status: str = "succeeded",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "substep_name": substep_name,
        "status": status,
        "provider": provider,
        "model": model,
        "execution_mode": execution_mode,
        "provider_status": provider_status,
        "provider_message": provider_message,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "duration_ms": max(1, int((time.perf_counter() - started_at) * 1000)),
        "error": error,
    }


def _provider_substep(substep_name: str, started_at: float, input_summary: dict[str, Any], output_summary: dict[str, Any], provider: Any) -> dict[str, Any]:
    return _substep_trace(
        substep_name=substep_name,
        provider=_provider_trace_value(provider, "last_provider", getattr(provider, "provider", "provider")),
        model=_provider_trace_value(provider, "last_model", getattr(provider, "model", "model")),
        started_at=started_at,
        input_summary=input_summary,
        output_summary=output_summary,
        execution_mode=_execution_trace_value(provider),
        provider_status=_provider_status_value(provider),
        provider_message=_provider_message_value(provider),
        status=_status_trace(provider),
        error=_provider_message_value(provider) if _provider_status_value(provider) == "error" else None,
    )


def _provider_failed_substep(substep_name: str, started_at: float, input_summary: dict[str, Any], provider: Any, exc: Exception) -> dict[str, Any]:
    return _substep_trace(
        substep_name=substep_name,
        provider=_provider_trace_value(provider, "last_provider", getattr(provider, "provider", "provider")),
        model=_provider_trace_value(provider, "last_model", getattr(provider, "model", "model")),
        started_at=started_at,
        input_summary=input_summary,
        output_summary={"error": _safe_error(exc)},
        execution_mode="real_failed",
        provider_status="error",
        provider_message=_provider_message_value(provider),
        status="failed",
        error=_safe_error(exc),
    )


def _failed_agent_state(
    state: GenerationGraphState,
    *,
    agent_name: str,
    started_at: float,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    substeps: list[dict[str, Any]],
    exc: Exception,
) -> GenerationGraphState:
    message = _safe_error(exc)
    trace = _trace_step(
        agent_name=agent_name,
        provider=" + ".join(dict.fromkeys(str(step.get("provider")) for step in substeps)) or "provider",
        model=" / ".join(dict.fromkeys(str(step.get("model")) for step in substeps)) or "model",
        input_payload=input_payload,
        output_payload={**output_payload, "substeps": substeps},
        started_at=started_at,
        fallback="Configured real provider failed; no placeholder output was generated.",
        execution_mode="real_failed",
        provider_status="error",
        provider_message="; ".join(str(step.get("provider_message")) for step in substeps if step.get("provider_message")) or message,
        status="failed",
        error=message,
    )
    return {
        **state,
        **{key: value for key, value in output_payload.items() if key in {"strategy", "script", "storyboard"}},
        "trace": [*state.get("trace", []), trace],
        "errors": [
            *state.get("errors", []),
            {
                "agent_name": agent_name,
                "message": message,
                "execution_mode": "real_failed",
                "provider_status": "error",
            },
        ],
    }


def _public_provider_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "model",
        "status",
        "created_at",
        "updated_at",
        "seed",
        "resolution",
        "ratio",
        "duration",
        "framespersecond",
        "service_tier",
        "usage",
        "url",
        "revised_prompt",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _public_model_label(value: str, label: str) -> str:
    if value.startswith("ep-"):
        return f"{label}:configured-endpoint"
    if "unconfigured" in value:
        return value
    return value[:120]


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else fallback


def _factor_confidence(value: Any, fallback: int = 76) -> int:
    confidence = _to_int(value, fallback)
    if confidence <= 0 or confidence > 100:
        return fallback
    return confidence


def _factor_shot_ids(value: Any, index: int) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    normalized_shot_ids: list[str] = []
    for raw in raw_values:
        matches = re.findall(r"shot[-_\s]*(\d+)|\b([1-9])\b", str(raw or "").lower())
        for explicit, bare in matches:
            shot_index = min(_to_int(explicit or bare, EDITING_SHOT_COUNT), EDITING_SHOT_COUNT)
            shot_id = f"shot-{max(1, shot_index)}"
            if shot_id not in normalized_shot_ids:
                normalized_shot_ids.append(shot_id)
    if not normalized_shot_ids:
        normalized_shot_ids = [f"shot-{min(index, EDITING_SHOT_COUNT)}"]
    return normalized_shot_ids


def _coerce_str_list(value: Any, fallback: list[str], *, limit: int = 6) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        cleaned = [item.strip(" .") for item in re.split(r"[;\n]|,(?=\s)", value) if item.strip(" .")]
    else:
        cleaned = []
    return (cleaned or fallback)[:limit]


def _seedance_duration(value: Any) -> int:
    requested = _to_int(value, 12)
    return min(12, max(4, requested))


def _trace_step(
    *,
    agent_name: str,
    provider: str,
    model: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    started_at: float,
    fallback: str,
    execution_mode: str,
    provider_status: str,
    provider_message: str,
    status: str = "succeeded",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "agent_name": agent_name,
        "status": status,
        "provider": provider,
        "model": model,
        "execution_mode": execution_mode,
        "provider_status": provider_status,
        "provider_message": provider_message,
        "input": input_payload,
        "output": output_payload,
        "duration_ms": max(1, int((time.perf_counter() - started_at) * 1000)),
        "fallback": fallback,
        "error": error,
    }


class MockLLMProvider:
    provider = "mock_llm_provider"
    model = "mock-volcengine-structured-v1"

    def generate_structured(
        self,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if task == "viral_strategy":
            return self._viral_strategy(payload)
        if task == "strategy_brief":
            return self._strategy_brief(payload)
        if task == "factor_board_packaging":
            return self._factor_board_packaging(payload)
        if task == "script_storyboard":
            return self._script_storyboard(payload)
        if task == "copy_draft":
            return self._copy_draft(payload)
        if task == "storyboard_plan":
            return self._storyboard_plan(payload)
        if task == "prompt_package":
            return self._prompt_package(payload)
        if task == "segment_rewrite":
            return self._segment_rewrite(payload)
        return self._script_storyboard(payload)

    def _viral_strategy(self, request: dict[str, Any]) -> dict[str, Any]:
        points = _clean_points(request.get("selling_points"))
        product = _short(request.get("product_name", ""), "this product")
        audience = _short(request.get("target_audience", ""), "short-video shoppers")
        platform = _short(request.get("platform", ""), "short video")
        primary = points[0]
        secondary = points[1] if len(points) > 1 else points[0]
        asset_summary = _asset_summary(request)
        hook = f"Stop scrolling if you need {primary} without giving up {secondary}."
        factor_board = build_factor_board(request)
        if "weak factor test" in str(request.get("creative_goal", "")).lower() and int(request.get("_strategy_attempt", 1)) == 1:
            factor_board = factor_board[:3]
        factor_coverage = round(len({factor["category"] for factor in factor_board}) / 8, 2)
        return {
            "product_angle": f"Position {product} as a quick, believable upgrade for {audience}.",
            "hook": hook,
            "audience_pain": f"{audience} need proof fast before they trust a {platform} purchase.",
            "source_asset_summary": asset_summary,
            "selling_point_order": points[:4],
            "factor_coverage": factor_coverage,
            "factor_board": factor_board,
            "content_rhythm": [
                "0-4s interrupt with the strongest problem",
                "4-8s combine proof with the real-use payoff",
                "8-12s close with offer and low-friction CTA",
            ],
            "selected_factors": factor_board,
            "risk_notes": [
                "Avoid guaranteed results or unverifiable claims.",
                "Keep reference style as inspiration only; do not imply copied footage.",
            ],
        }

    def _strategy_brief(self, request: dict[str, Any]) -> dict[str, Any]:
        strategy = self._viral_strategy(request)
        return {
            "product_angle": strategy["product_angle"],
            "hook": strategy["hook"],
            "audience_pain": strategy["audience_pain"],
            "source_asset_summary": strategy["source_asset_summary"],
            "selling_point_order": strategy["selling_point_order"],
            "content_rhythm": strategy["content_rhythm"],
            "risk_notes": strategy["risk_notes"],
        }

    def _factor_board_packaging(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = payload.get("request", payload)
        strategy = self._viral_strategy(request)
        return {
            "factor_board": strategy["factor_board"],
            "selected_factors": strategy["selected_factors"],
            "factor_coverage": strategy["factor_coverage"],
        }

    def _script_storyboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = payload["request"]
        strategy = payload["strategy"]
        points = _clean_points(request.get("selling_points"))
        product = _short(request.get("product_name", ""), "the product")
        visual_style = _short(request.get("visual_style", ""), "clean product close-ups")
        duration = int(request.get("duration_seconds") or 12)
        asset_summary = _asset_summary(request)
        script_attempt = int(request.get("_script_attempt", 1))
        factor_board = strategy.get("factor_board") or strategy.get("selected_factors") or []
        shot_durations = _shot_durations(duration)
        material_note = request.get("material_notes") or request.get("reference_style")
        if script_attempt > 1:
            material_note = _claim_safe(material_note)
        proof_point = points[1] if len(points) > 1 else points[0]
        use_point = points[2] if len(points) > 2 else points[-1]
        scenes = [
            {
                "beat": "Hook",
                "point": points[0],
                "voiceover": strategy["hook"],
                "camera": "snap zoom from problem scene into product close-up",
                "bgm": "cold open hit",
            },
            {
                "beat": "Proof + Use",
                "point": f"{proof_point}; {use_point}",
                "voiceover": f"Here is the proof: {proof_point}. Then use it for {use_point}.",
                "camera": "macro proof shot into one quick real-use cutaway",
                "bgm": "proof pulse",
            },
            {
                "beat": "CTA",
                "point": request.get("price_offer") or points[-1],
                "voiceover": f"Tap through while {request.get('price_offer') or 'the offer'} is available.",
                "camera": "daily-use scene into locked product hero shot with subtle push-in",
                "bgm": "warm CTA lift",
            },
        ]
        storyboard = []
        for index, scene in enumerate(scenes, start=1):
            subtitle = scene["voiceover"][:70]
            linked_factors = [
                factor
                for factor in factor_board
                if f"shot-{index}" in factor.get("linked_shot_ids", [])
            ]
            storyboard.append(
                {
                    "shot_id": f"shot-{index}",
                    "order_index": index,
                    "duration_seconds": shot_durations[index - 1],
                    "beat": scene["beat"],
                    "visual_description": (
                        f"{visual_style}; {scene['beat'].lower()} shot for {product}, "
                        f"emphasizing {scene['point']}. Source cue: {asset_summary}"
                    ),
                    "camera_motion": scene["camera"],
                    "voiceover": scene["voiceover"],
                    "subtitle": subtitle,
                    "tts_line": scene["voiceover"],
                    "bgm_cue": scene["bgm"],
                    "linked_factor_keys": [factor["factor_key"] for factor in linked_factors],
                    "image_prompt": (
                        f"Product image mock for {product}, {visual_style}, "
                        f"show {scene['point']}, vertical commerce composition, use source assets: {asset_summary}"
                    ),
                    "video_prompt": (
                        f"Seedance-style video prompt: {product}, {scene['beat']} beat, "
                        f"{scene['camera']}, focus on {scene['point']}, vertical {request.get('platform')} ad, "
                        f"source assets: {asset_summary}"
                    ),
                }
            )
        script = {
            "title": f"{product} {duration}s commerce script",
            "narrative": " ".join(scene["voiceover"] for scene in scenes),
            "voiceover_lines": [scene["voiceover"] for scene in scenes],
            "subtitle_lines": [shot["subtitle"] for shot in storyboard],
            "tts_lines": [shot["tts_line"] for shot in storyboard],
            "bgm_plan": "Start with a crisp hook hit, keep proof shots on a tight pulse, lift into CTA.",
            "duration_seconds": sum(shot_durations),
            "visual_style": visual_style,
            "source_asset_summary": asset_summary,
        }
        return {"script": script, "storyboard": storyboard}

    def _copy_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._script_storyboard(payload)["script"]

    def _storyboard_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        script_payload = {
            "request": payload["request"],
            "strategy": payload["strategy"],
        }
        return {"storyboard": self._script_storyboard(script_payload)["storyboard"]}

    def _prompt_package(self, payload: dict[str, Any]) -> dict[str, Any]:
        storyboard = payload.get("storyboard") or self._storyboard_plan(payload)["storyboard"]
        return {
            "storyboard_prompts": [
                {
                    "shot_id": shot["shot_id"],
                    "image_prompt": shot["image_prompt"],
                    "video_prompt": shot["video_prompt"],
                    "tts_line": shot["tts_line"],
                    "bgm_cue": shot["bgm_cue"],
                    "subtitle": shot["subtitle"],
                }
                for shot in storyboard
            ],
        }

    def _segment_rewrite(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = payload.get("request", {})
        shot = dict(payload.get("shot") or {})
        product = _short(request.get("product_name", ""), "the product")
        beat = _short(str(shot.get("beat") or ""), "Proof")
        selling_points = _clean_points(request.get("selling_points"))
        proof_point = selling_points[min(max(_to_int(shot.get("order_index"), 1) - 1, 0), len(selling_points) - 1)]
        voiceover = f"Here is the sharper {beat.lower()} moment: {proof_point}."
        subtitle = voiceover[:90]
        visual_style = _short(request.get("visual_style", ""), "clean product close-ups")
        return {
            "beat": beat,
            "visual_description": f"{visual_style}; refreshed {beat.lower()} segment for {product}, centered on {proof_point}.",
            "camera_motion": str(shot.get("camera_motion") or "steady close-up with a clean push-in"),
            "voiceover": voiceover,
            "subtitle": subtitle,
            "tts_line": voiceover,
            "image_prompt": f"Refreshed product still for {product}, {beat} beat, show {proof_point}, {visual_style}.",
            "video_prompt": f"Regenerate only this {beat} segment for {product}; show {proof_point}, keep continuity with the timeline, vertical commerce pacing.",
        }


class VolcengineLLMProvider:
    provider = "volcengine_ark_chat"
    fallback_provider = MockLLMProvider()

    def __init__(self) -> None:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine")
        self.last_fallback: str | None = None
        self.last_repair_used = False
        self.last_raw_excerpt: str | None = None
        self.last_execution_mode = "mock_missing_config"
        self.last_provider_status = "missing_config"
        self.last_provider_message = "Image text plan provider has not run yet."
        self.last_execution_mode = "mock_missing_config"
        self.last_provider_status = "missing_config"
        self.last_provider_message = "Volcengine text provider has not run yet."

    @property
    def model(self) -> str:
        settings = get_settings()
        return settings.volcengine_endpoint_id or settings.volcengine_text_model or "volcengine-endpoint-unconfigured"

    def generate_structured(
        self,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine")
        self.last_fallback = None
        self.last_repair_used = False
        self.last_raw_excerpt = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = "Volcengine text provider returned structured output."
        settings = get_settings()
        if not _text_provider_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "Volcengine text provider is not connected; local placeholder text was generated."
            return self.fallback_provider.generate_structured(task, payload)
        try:
            provider_payload = self._call_chat_json(task, payload)
            if self.last_repair_used:
                self.last_provider_message = "Volcengine text provider returned malformed JSON; JSON repair succeeded."
            return self._normalize(task, payload, provider_payload)
        except Exception as exc:
            self._raise_provider_failure(exc)

    def _raise_provider_failure(self, exc: Exception) -> None:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine")
        reason = _safe_error(exc)
        raw_excerpt = f" Raw response excerpt: {self.last_raw_excerpt}" if self.last_raw_excerpt else ""
        self.last_execution_mode = "real_failed"
        self.last_provider_status = "error"
        self.last_provider_message = f"Volcengine text provider failed; no placeholder output was generated. Reason: {reason}{raw_excerpt}"
        self.last_fallback = self.last_provider_message
        raise ProviderExecutionError(self.last_provider_message) from exc

    def _call_chat_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        base_url = _ark_base_url(settings.volcengine_base_url)
        url = _join_api_url(base_url, "/chat/completions")
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are ViralCutAI's commerce video planning engine. "
                        "Return strict JSON only, in English, with no markdown fences."
                    ),
                },
                {"role": "user", "content": self._prompt(task, payload)},
            ],
            "temperature": _text_task_temperature(task),
            "max_tokens": _text_task_max_tokens(task),
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.volcengine_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=body)
                    if response.status_code == 400:
                        retry_body = {key: value for key, value in body.items() if key not in {"response_format", "thinking"}}
                        response = client.post(url, headers=headers, json=retry_body)
                    _raise_for_status(response, "Volcengine chat completion")
                break
            except Exception as exc:
                last_error = exc
                if attempt == 3:
                    raise
                time.sleep(_provider_retry_delay_seconds(exc, attempt))
        if last_error is not None and "response" not in locals():
            raise last_error
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        self.last_raw_excerpt = _response_excerpt(content)
        try:
            return _extract_json_object(content)
        except Exception as exc:
            repaired = self._repair_json_content(task, content, exc)
            self.last_repair_used = True
            return repaired

    def _repair_json_content(self, task: str, broken_content: str, parse_error: Exception) -> dict[str, Any]:
        settings = get_settings()
        base_url = _ark_base_url(settings.volcengine_base_url)
        url = _join_api_url(base_url, "/chat/completions")
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Repair malformed JSON. Return one valid JSON object only, no markdown.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Task: {task}\n"
                        f"Parse error: {_safe_error(parse_error)}\n"
                        "Fix the JSON while preserving the original fields and English content. "
                        "Do not add private data.\n\n"
                        f"BROKEN JSON/TEXT:\n{broken_content[:12000]}"
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": _text_task_max_tokens(task),
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.volcengine_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=body)
            if response.status_code == 400:
                retry_body = {key: value for key, value in body.items() if key not in {"response_format", "thinking"}}
                response = client.post(url, headers=headers, json=retry_body)
            _raise_for_status(response, "Volcengine JSON repair")
        content = response.json()["choices"][0]["message"]["content"]
        self.last_raw_excerpt = _response_excerpt(content)
        return _extract_json_object(content)

    def _prompt(self, task: str, payload: dict[str, Any]) -> str:
        if task in {"viral_strategy", "strategy_brief"}:
            compact = _compact_request_for_llm(payload)
            if task == "strategy_brief":
                return (
                    "Return exactly one minified JSON object with exactly these keys and no extra keys: "
                    "product_angle, hook, audience_pain, source_asset_summary, selling_point_order, content_rhythm, risk_notes. "
                    "Hard limits: every string <= 90 characters; arrays <= 3 items; no newlines inside strings; "
                    "no markdown; no claims not present in the request. "
                    "Use this exact shape: {\"product_angle\":\"\",\"hook\":\"\",\"audience_pain\":\"\","
                    "\"source_asset_summary\":\"\",\"selling_point_order\":[\"\"],"
                    "\"content_rhythm\":[\"0-4s hook\",\"4-8s proof + use\",\"8-12s CTA\"],"
                    "\"risk_notes\":[\"\"]}.\n\n"
                    f"REQUEST JSON:\n{json.dumps(compact, ensure_ascii=False)}"
                )
            return (
                "Create a compact viral commerce strategy. Return minified valid JSON only. "
                "No markdown, no comments, no trailing commas, no newline characters inside string values. "
                "Keep each string under 140 characters. All list fields must be JSON arrays, not paragraphs. "
                "Required shape: {\"product_angle\":\"\",\"hook\":\"\",\"audience_pain\":\"\","
                "\"source_asset_summary\":\"\",\"selling_point_order\":[\"\"],\"factor_coverage\":1,"
                "\"content_rhythm\":[\"\"],\"risk_notes\":[\"\"],\"factor_board\":[{\"factor_key\":\"\","
                "\"name\":\"\",\"category\":\"hook|proof|scene|trust|visual|audio|cta|risk\","
                "\"reason\":\"\",\"expected_effect\":\"\",\"confidence\":80,\"linked_shot_ids\":[\"shot-1\"],"
                "\"source\":\"user_input|asset|reference|template\"}]}. "
                "factor_board must contain exactly 8 items, one per category.\n\n"
                f"REQUEST JSON:\n{json.dumps(compact, ensure_ascii=False)}"
            )
        if task == "factor_board_packaging":
            compact_payload = {
                "request": _compact_request_for_llm(payload.get("request", {})),
                "brief": {
                    "product_angle": payload.get("brief", {}).get("product_angle"),
                    "hook": payload.get("brief", {}).get("hook"),
                    "audience_pain": payload.get("brief", {}).get("audience_pain"),
                },
            }
            return (
                "Return exactly one minified JSON object. No markdown. No extra keys. "
                "Object keys: factor_board, selected_factors, factor_coverage. "
                "factor_board must contain exactly 8 objects, in this exact category order: "
                "hook, proof, scene, trust, visual, audio, cta, risk. "
                "Each factor object keys exactly: factor_key, name, category, reason, expected_effect, confidence, linked_shot_ids, source. "
                "Hard limits: name <= 36 chars, reason <= 70 chars, expected_effect <= 70 chars, "
                "confidence integer 60-95, linked_shot_ids only shot-1/shot-2/shot-3. "
                "selected_factors must be an empty array because the backend derives it from factor_board. factor_coverage must be 1. "
                "Use this shape: {\"factor_board\":[{\"factor_key\":\"hook-1\",\"name\":\"\","
                "\"category\":\"hook\",\"reason\":\"\",\"expected_effect\":\"\",\"confidence\":80,"
                "\"linked_shot_ids\":[\"shot-1\"],\"source\":\"volcengine\"}],"
                "\"selected_factors\":[],\"factor_coverage\":1}.\n\n"
                f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
            )
        if task == "copy_draft":
            compact_payload = {
                "request": _compact_request_for_llm(payload.get("request", {})),
                "strategy": _compact_strategy_for_llm(payload.get("strategy", {})),
            }
            return (
                "Return exactly one minified JSON object. No markdown. No extra keys. "
                "Keys exactly: title,narrative,voiceover_lines,subtitle_lines,tts_lines,bgm_plan,duration_seconds,visual_style,source_asset_summary. "
                "Hard limits: title <= 60 chars, narrative <= 120 chars, visual_style <= 100 chars, source_asset_summary <= 90 chars, bgm_plan <= 90 chars. "
                "voiceover_lines, subtitle_lines, and tts_lines must each contain exactly 3 strings for Hook, Proof + Use, CTA. "
                "Each voiceover/TTS line <= 90 chars. Each subtitle <= 70 chars. duration_seconds must equal request duration. "
                "Use this shape exactly: {\"title\":\"\",\"narrative\":\"\",\"voiceover_lines\":[\"\",\"\",\"\"],"
                "\"subtitle_lines\":[\"\",\"\",\"\"],\"tts_lines\":[\"\",\"\",\"\"],\"bgm_plan\":\"\","
                "\"duration_seconds\":12,\"visual_style\":\"\",\"source_asset_summary\":\"\"}.\n\n"
                f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
            )
        if task == "storyboard_plan":
            compact_payload = {
                "request": _compact_request_for_llm(payload.get("request", {})),
                "strategy": _compact_strategy_for_llm(payload.get("strategy", {})),
                "script": {
                    "title": payload.get("script", {}).get("title"),
                    "voiceover_lines": payload.get("script", {}).get("voiceover_lines", [])[:EDITING_SHOT_COUNT],
                    "subtitle_lines": payload.get("script", {}).get("subtitle_lines", [])[:EDITING_SHOT_COUNT],
                    "duration_seconds": payload.get("script", {}).get("duration_seconds"),
                },
            }
            return (
                "Return exactly one minified JSON object. No markdown. No extra keys. "
                "Key exactly: storyboard. storyboard must contain exactly 3 objects. "
                "Shot identities are fixed: shot-1/order 1/beat Hook, shot-2/order 2/beat Proof + Use, shot-3/order 3/beat CTA. "
                "Each object keys exactly: shot_id,order_index,duration_seconds,beat,visual_description,camera_motion,voiceover,subtitle,linked_factor_keys. "
                "Each duration_seconds must be 4 for a 12s request. visual_description <= 120 chars, camera_motion <= 60 chars, voiceover <= 90 chars, subtitle <= 70 chars. "
                "linked_factor_keys <= 3 strings. Do not include image_prompt, video_prompt, tts_line, or bgm_cue in this step. "
                "Use this shape: {\"storyboard\":[{\"shot_id\":\"shot-1\",\"order_index\":1,\"duration_seconds\":4,"
                "\"beat\":\"Hook\",\"visual_description\":\"\",\"camera_motion\":\"\",\"voiceover\":\"\","
                "\"subtitle\":\"\",\"linked_factor_keys\":[\"\"]}]}.\n\n"
                f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
            )
        if task == "segment_rewrite":
            compact_payload = {
                "request": _compact_request_for_llm(payload.get("request", {})),
                "script": {
                    "title": payload.get("script", {}).get("title"),
                    "duration_seconds": payload.get("script", {}).get("duration_seconds"),
                },
                "shot": {
                    "shot_id": payload.get("shot", {}).get("shot_id"),
                    "order_index": payload.get("shot", {}).get("order_index"),
                    "duration_seconds": payload.get("shot", {}).get("duration_seconds"),
                    "beat": payload.get("shot", {}).get("beat"),
                    "visual_description": str(payload.get("shot", {}).get("visual_description", ""))[:260],
                    "camera_motion": payload.get("shot", {}).get("camera_motion"),
                    "voiceover": str(payload.get("shot", {}).get("voiceover", ""))[:220],
                    "subtitle": str(payload.get("shot", {}).get("subtitle", ""))[:140],
                    "video_prompt": str(payload.get("shot", {}).get("video_prompt", ""))[:320],
                },
                "neighbor_context": payload.get("neighbor_context", {}),
            }
            return (
                "Rewrite only the target timeline segment. Return valid minified JSON only. "
                "Keys: beat, visual_description, camera_motion, voiceover, subtitle, tts_line, image_prompt, video_prompt. "
                "Do not rewrite other segments. Keep continuity with neighbor_context and keep strings concise.\n\n"
                f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
            )
        if task == "prompt_package":
            request = payload.get("request", {})
            compact_payload = {
                "product_name": request.get("product_name"),
                "category": request.get("category"),
                "visual_style": payload.get("script", {}).get("visual_style") or request.get("visual_style"),
                "shots": [
                    {
                        "shot_id": shot.get("shot_id"),
                        "beat": shot.get("beat"),
                        "visual": str(shot.get("visual_description", ""))[:110],
                        "voiceover": str(shot.get("voiceover", ""))[:80],
                    }
                    for shot in payload.get("storyboard", [])[:EDITING_SHOT_COUNT]
                ],
            }
            return (
                "Return exactly one minified JSON object. No markdown. No extra keys. "
                "Key exactly: storyboard_prompts. storyboard_prompts must contain exactly 3 objects for shot-1, shot-2, shot-3. "
                "Each object keys exactly: shot_id,image_prompt,video_prompt,bgm_cue. "
                "Write compact prompt fragments, not prose. No more than 12 words per image_prompt, 16 words per video_prompt, 8 words per bgm_cue. "
                "Do not include tts_line or subtitle. Do not add script or storyboard keys. "
                "Use this shape: {\"storyboard_prompts\":[{\"shot_id\":\"shot-1\","
                "\"image_prompt\":\"\",\"video_prompt\":\"\",\"bgm_cue\":\"\"}]}.\n\n"
                f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
            )
        compact_payload = {
            "request": _compact_request_for_llm(payload.get("request", {})),
            "strategy": _compact_strategy_for_llm(payload.get("strategy", {})),
        }
        return (
            "Create a compact fixed 3-segment commerce script and storyboard for clip-level editing. Return minified valid JSON only. "
            "No markdown, no comments, no trailing commas, no newline characters inside string values. "
            "Keep each string under 150 characters. Required shape: {\"script\":{\"title\":\"\","
            "\"narrative\":\"\",\"voiceover_lines\":[\"\"],\"subtitle_lines\":[\"\"],\"tts_lines\":[\"\"],"
            "\"bgm_plan\":\"\",\"duration_seconds\":12,\"visual_style\":\"\",\"source_asset_summary\":\"\"},"
            "\"storyboard\":[{\"shot_id\":\"shot-1\",\"order_index\":1,\"duration_seconds\":4,"
            "\"beat\":\"Hook\",\"visual_description\":\"\",\"camera_motion\":\"\",\"voiceover\":\"\","
            "\"subtitle\":\"\",\"tts_line\":\"\",\"bgm_cue\":\"\",\"linked_factor_keys\":[\"\"],"
            "\"image_prompt\":\"\",\"video_prompt\":\"\"}]}. storyboard must contain exactly 3 segments. "
            "Beat labels are fixed: shot-1 Hook, shot-2 Proof + Use, shot-3 CTA. "
            "Do not use beat for audio rhythm descriptions.\n\n"
            f"PAYLOAD JSON:\n{json.dumps(compact_payload, ensure_ascii=False)}"
        )

    def _normalize(self, task: str, payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        baseline = self.fallback_provider.generate_structured(task, payload)
        if task == "strategy_brief":
            normalized = {**baseline, **{key: value for key, value in data.items() if value not in (None, "", [])}}
            for key in ("product_angle", "hook", "audience_pain", "source_asset_summary"):
                if not _valid_short_sentence(data.get(key)):
                    raise ValueError(f"Volcengine strategy_brief returned invalid {key}.")
                normalized[key] = re.sub(r"\s+", " ", str(data.get(key))).strip()
            normalized["selling_point_order"] = _coerce_str_list(
                normalized.get("selling_point_order"),
                baseline.get("selling_point_order", []),
                limit=5,
            )
            normalized["content_rhythm"] = _coerce_str_list(normalized.get("content_rhythm"), baseline.get("content_rhythm", []), limit=5)
            normalized["risk_notes"] = _coerce_str_list(normalized.get("risk_notes"), baseline.get("risk_notes", []), limit=4)
            return normalized
        if task == "factor_board_packaging":
            factors = data.get("factor_board") if isinstance(data.get("factor_board"), list) else baseline["factor_board"]
            factor_board = _complete_factor_board(factors, baseline["factor_board"])
            return {
                "factor_board": factor_board,
                "selected_factors": factor_board,
                "factor_coverage": round(len({factor["category"] for factor in factor_board}) / 8, 2),
            }
        if task == "copy_draft":
            normalized = {**baseline, **{key: value for key, value in data.items() if value not in (None, "", [])}}
            normalized["voiceover_lines"] = _coerce_str_list(normalized.get("voiceover_lines"), baseline.get("voiceover_lines", []), limit=EDITING_SHOT_COUNT)
            normalized["subtitle_lines"] = _coerce_str_list(normalized.get("subtitle_lines"), baseline.get("subtitle_lines", []), limit=EDITING_SHOT_COUNT)
            normalized["tts_lines"] = _coerce_str_list(normalized.get("tts_lines"), baseline.get("tts_lines", []), limit=EDITING_SHOT_COUNT)
            normalized["voiceover_lines"] = [_limit_text(line, 90) for line in normalized["voiceover_lines"]]
            normalized["subtitle_lines"] = [_limit_text(line, 70) for line in normalized["subtitle_lines"]]
            normalized["tts_lines"] = [_limit_text(line, 90) for line in normalized["tts_lines"]]
            normalized["title"] = _limit_text(normalized.get("title"), 60, baseline.get("title", ""))
            normalized["narrative"] = _limit_text(normalized.get("narrative"), 120, baseline.get("narrative", ""))
            normalized["bgm_plan"] = _limit_text(normalized.get("bgm_plan"), 90, baseline.get("bgm_plan", ""))
            normalized["visual_style"] = _limit_text(normalized.get("visual_style"), 100, baseline.get("visual_style", ""))
            normalized["source_asset_summary"] = _limit_text(
                normalized.get("source_asset_summary"),
                90,
                baseline.get("source_asset_summary", ""),
            )
            normalized["duration_seconds"] = _to_int(normalized.get("duration_seconds"), _to_int(baseline.get("duration_seconds"), 12))
            return normalized
        if task == "storyboard_plan":
            baseline_storyboard = baseline["storyboard"]
            storyboard = data.get("storyboard") if isinstance(data.get("storyboard"), list) else baseline_storyboard
            normalized_storyboard = [
                _normalize_shot(shot, baseline_storyboard[min(index, len(baseline_storyboard) - 1)], index + 1)
                for index, shot in enumerate(storyboard[:EDITING_SHOT_COUNT])
                if isinstance(shot, dict)
            ]
            return {"storyboard": normalized_storyboard if len(normalized_storyboard) == EDITING_SHOT_COUNT else baseline_storyboard}
        if task == "prompt_package":
            baseline_prompts = baseline["storyboard_prompts"]
            prompts = data.get("storyboard_prompts") if isinstance(data.get("storyboard_prompts"), list) else baseline_prompts
            normalized_prompts = []
            for index, item in enumerate(prompts[:EDITING_SHOT_COUNT]):
                if not isinstance(item, dict):
                    continue
                fallback = baseline_prompts[min(index, len(baseline_prompts) - 1)]
                normalized_prompts.append(
                    {
                        "shot_id": str(item.get("shot_id") or fallback["shot_id"]),
                        "image_prompt": _limit_text(item.get("image_prompt"), 150, fallback["image_prompt"]),
                        "video_prompt": _limit_text(item.get("video_prompt"), 180, fallback["video_prompt"]),
                        "tts_line": _limit_text(item.get("tts_line"), 90, fallback["tts_line"]),
                        "bgm_cue": _limit_text(item.get("bgm_cue"), 70, fallback["bgm_cue"]),
                        "subtitle": _limit_text(item.get("subtitle"), 70, fallback["subtitle"]),
                    }
                )
            return {"storyboard_prompts": normalized_prompts if len(normalized_prompts) == EDITING_SHOT_COUNT else baseline_prompts}
        if task == "segment_rewrite":
            normalized = {**baseline}
            for key in ("beat", "visual_description", "camera_motion", "voiceover", "subtitle", "tts_line", "image_prompt", "video_prompt"):
                value = data.get(key)
                if value not in (None, "", []):
                    normalized[key] = str(value)
            return normalized
        if task == "viral_strategy":
            normalized = {**baseline, **{key: value for key, value in data.items() if value not in (None, "", [])}}
            normalized["selling_point_order"] = _coerce_str_list(
                normalized.get("selling_point_order"),
                baseline.get("selling_point_order", []),
                limit=5,
            )
            normalized["content_rhythm"] = _coerce_str_list(
                normalized.get("content_rhythm"),
                baseline.get("content_rhythm", []),
                limit=5,
            )
            normalized["risk_notes"] = _coerce_str_list(normalized.get("risk_notes"), baseline.get("risk_notes", []), limit=4)
            factors = normalized.get("factor_board")
            if not isinstance(factors, list):
                factors = baseline["factor_board"]
            normalized["factor_board"] = _complete_factor_board(factors, baseline["factor_board"])
            normalized["selected_factors"] = normalized["factor_board"]
            normalized["factor_coverage"] = round(len({factor["category"] for factor in normalized["factor_board"]}) / 8, 2)
            return normalized
        script = {**baseline["script"], **data.get("script", {})} if isinstance(data.get("script"), dict) else baseline["script"]
        script["voiceover_lines"] = _coerce_str_list(script.get("voiceover_lines"), baseline["script"].get("voiceover_lines", []), limit=EDITING_SHOT_COUNT)
        script["subtitle_lines"] = _coerce_str_list(script.get("subtitle_lines"), baseline["script"].get("subtitle_lines", []), limit=EDITING_SHOT_COUNT)
        script["tts_lines"] = _coerce_str_list(script.get("tts_lines"), baseline["script"].get("tts_lines", []), limit=EDITING_SHOT_COUNT)
        storyboard = data.get("storyboard") if isinstance(data.get("storyboard"), list) else baseline["storyboard"]
        storyboard = [
            _normalize_shot(shot, baseline["storyboard"][min(index, len(baseline["storyboard"]) - 1)], index + 1)
            for index, shot in enumerate(storyboard[:EDITING_SHOT_COUNT])
            if isinstance(shot, dict)
        ]
        if len(storyboard) < EDITING_SHOT_COUNT:
            storyboard = baseline["storyboard"]
        script["duration_seconds"] = sum(int(shot.get("duration_seconds") or 0) for shot in storyboard)
        return {"script": script, "storyboard": storyboard}


def _normalize_factor(factor: dict[str, Any], index: int) -> dict[str, Any]:
    category = str(factor.get("category") or "proof").lower()
    if category not in FACTOR_CATEGORIES:
        category = "proof"
    return {
        "factor_key": str(factor.get("factor_key") or f"{category}-{index}"),
        "name": _limit_text(factor.get("name"), 48, f"{category.title()} factor"),
        "category": category,
        "reason": _limit_text(factor.get("reason"), 90, "Selected by the real provider from the product request."),
        "expected_effect": _limit_text(factor.get("expected_effect"), 90, "Improve hook clarity and buyer confidence."),
        "confidence": _factor_confidence(factor.get("confidence"), 76),
        "linked_shot_ids": _factor_shot_ids(factor.get("linked_shot_ids"), index),
        "source": _limit_text(factor.get("source"), 60, "volcengine"),
    }


def _complete_factor_board(factors: list[Any], baseline_factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for index, factor in enumerate(factors, start=1):
        if not isinstance(factor, dict):
            continue
        normalized = _normalize_factor(factor, index)
        selected.setdefault(normalized["category"], normalized)
    for index, factor in enumerate(baseline_factors, start=1):
        normalized = _normalize_factor(factor, index)
        selected.setdefault(normalized["category"], normalized)
    return [selected[category] for category in FACTOR_CATEGORIES if category in selected][:8]


def _strategy_retrieval_fields(request: dict[str, Any]) -> dict[str, Any]:
    retrieval = request.get("retrieval_context") or {}
    auto_assets = retrieval.get("auto_asset_results") or []
    selected_collection = retrieval.get("selected_collection")
    selected_slices = retrieval.get("selected_slices") or []
    auto_factors = retrieval.get("auto_factors") or []
    selected_template = retrieval.get("selected_template") or request.get("creative_template")
    selected_reference = retrieval.get("selected_reference_video") or request.get("reference_video")
    retrieval_evidence = []
    if selected_collection:
        retrieval_evidence.append(
            {
                "type": "asset_collection",
                "title": selected_collection.get("product_name"),
                "score": 1,
                "reason": selected_collection.get("summary") or "Selected private asset collection.",
                "usable_for": list((selected_collection.get("coverage") or {}).keys())[:5],
                "matched_slices": [],
            }
        )
    retrieval_evidence.extend(
        {
            "type": "asset",
            "title": item.get("filename"),
            "score": item.get("score"),
            "reason": item.get("reason"),
            "usable_for": item.get("usable_for", []),
            "matched_slices": item.get("matched_slices", [])[:2],
        }
        for item in auto_assets[:4]
    )
    retrieval_evidence.extend(
        {
            "type": "selected_slice",
            "title": item.get("filename"),
            "score": 1,
            "reason": item.get("summary"),
            "usable_for": [item.get("usable_for")] if item.get("usable_for") else [],
            "matched_slices": [item],
        }
        for item in selected_slices[:4]
    )
    factor_selection_reason = [
        {
            "factor_key": item.get("factor_key"),
            "name": item.get("name"),
            "category": item.get("category"),
            "source": item.get("source"),
            "reason": item.get("description") or item.get("reason") or "Retrieved from the viral methodology library.",
        }
        for item in auto_factors[:8]
    ]
    if selected_template:
        factor_selection_reason.append(
            {
                "factor_key": "template",
                "name": selected_template.get("name"),
                "category": "template",
                "source": "selected template",
                "reason": selected_template.get("strategy"),
            }
        )
    if selected_reference:
        factor_selection_reason.append(
            {
                "factor_key": "reference",
                "name": selected_reference.get("title"),
                "category": "reference",
                "source": "selected reference",
                "reason": "Reference analysis is used as method inspiration only, not copied footage.",
            }
        )
    return {
        "generation_mode": request.get("generation_mode", "auto_mix"),
        "retrieval_evidence": retrieval_evidence,
        "factor_selection_reason": factor_selection_reason,
        "asset_usage_plan": _asset_usage_plan(auto_assets, selected_slices),
        "private_asset_evidence": {
            "selected_collection": selected_collection,
            "auto_asset_count": len(auto_assets),
            "selected_slice_count": len(selected_slices),
        },
        "retrieval_summary": {
            "asset": retrieval.get("evidence_summary"),
            "methodology": retrieval.get("methodology_summary"),
            "asset_query": retrieval.get("asset_query"),
            "viral_query": retrieval.get("viral_query"),
        },
    }


def _asset_usage_plan(auto_assets: list[dict[str, Any]], selected_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for item in auto_assets[:4]:
        slices = item.get("matched_slices") or []
        evidence.append(
            {
                "shot_id": _shot_for_usable_for(item.get("usable_for", [])),
                "asset": item.get("filename"),
                "usage": ", ".join(item.get("usable_for", [])[:3]) or "general proof",
                "reason": item.get("reason"),
                "slice_ids": [slice_item.get("slice_id") for slice_item in slices if slice_item.get("slice_id")],
            }
        )
    for item in selected_slices[:4]:
        evidence.append(
            {
                "shot_id": _shot_for_usable_for([item.get("usable_for")]),
                "asset": item.get("filename"),
                "usage": item.get("usable_for") or "selected slice",
                "reason": item.get("summary"),
                "slice_ids": [item.get("slice_id")],
            }
        )
    return evidence


def _shot_for_usable_for(values: list[Any]) -> str:
    text = " ".join(str(item).lower() for item in values if item)
    if "hook" in text:
        return "shot-1"
    if "proof" in text or "close" in text:
        return "shot-2"
    if "cta" in text:
        return "shot-3"
    return "shot-3"


def _normalize_shot(shot: dict[str, Any], fallback: dict[str, Any], order_index: int) -> dict[str, Any]:
    normalized = {**fallback, **{key: value for key, value in shot.items() if value not in (None, "")}}
    normalized["shot_id"] = str(normalized.get("shot_id") or f"shot-{order_index}")
    normalized["order_index"] = order_index
    normalized["beat"] = SEGMENT_BEATS[min(max(order_index - 1, 0), len(SEGMENT_BEATS) - 1)]
    normalized["duration_seconds"] = _to_int(normalized.get("duration_seconds"), _to_int(fallback.get("duration_seconds"), 3))
    normalized["visual_description"] = _limit_text(normalized.get("visual_description"), 120, fallback.get("visual_description", ""))
    normalized["camera_motion"] = _limit_text(normalized.get("camera_motion"), 60, fallback.get("camera_motion", ""))
    normalized["voiceover"] = _limit_text(normalized.get("voiceover"), 90, fallback.get("voiceover", ""))
    normalized["subtitle"] = _limit_text(normalized.get("subtitle"), 70, fallback.get("subtitle", ""))
    normalized["linked_factor_keys"] = [
        _limit_text(item, 60)
        for item in (normalized.get("linked_factor_keys") if isinstance(normalized.get("linked_factor_keys"), list) else [])
        if str(item or "").strip()
    ][:3]
    return normalized


def _rebalance_storyboard_durations(storyboard: list[dict[str, Any]], total_seconds: Any) -> list[dict[str, Any]]:
    durations = _shot_durations(_to_int(total_seconds, 12), max(1, len(storyboard)))
    return [{**shot, "duration_seconds": durations[index]} for index, shot in enumerate(storyboard)]


class MockImageProvider:
    provider = "mock_image_provider"
    model = "mock-volcengine-image-description-v1"

    def generate_image_description(self, shot: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_type": "image_mock",
            "title": f"Image mock / {shot['beat']}",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "shot_id": shot["shot_id"],
                "prompt": shot["image_prompt"],
                "description": (
                    f"A vertical product frame for {request['product_name']} with {shot['visual_description']} "
                    "The mock represents the future image generation result as text."
                ),
                "source_assets": request.get("source_assets", []),
                "composition": "center product, visible hands, clean negative space for subtitles",
                "is_real_output": False,
                "mock_reason": "Image generation provider is not configured.",
            },
        }


class VolcengineImagePlanProvider:
    provider = "volcengine_text_image_plan"
    fallback_provider = MockImageProvider()

    def __init__(self) -> None:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine")
        self.last_fallback: str | None = None

    @property
    def model(self) -> str:
        settings = get_settings()
        return settings.volcengine_endpoint_id or settings.volcengine_text_model or "volcengine-endpoint-unconfigured"

    def generate_image_description(self, shot: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine")
        self.last_fallback = None
        is_configured = _text_provider_configured()
        self.last_execution_mode = "real" if is_configured else "mock_missing_config"
        self.last_provider_status = "configured" if is_configured else "missing_config"
        self.last_provider_message = (
            "Image plan uses the configured Volcengine text endpoint output."
            if is_configured
                else "Volcengine text provider is not connected; image plan uses local placeholder prompt text."
        )
        return {
            "artifact_type": "image_text_plan",
            "title": f"Image plan / {shot['beat']}",
            "provider": self.provider,
            "status": "text_prompt_ready" if is_configured else "mock_missing_config",
            "payload": {
                "shot_id": shot["shot_id"],
                "prompt": shot["image_prompt"],
                "description": (
                    f"Text-model image plan for {request['product_name']}: {shot['visual_description']} "
                    "This uses the same Volcengine text endpoint to prepare an image-ready prompt, "
                    "without calling a separate image generation API."
                ),
                "source_assets": request.get("source_assets", []),
                "composition": "vertical commerce frame, product centered, subtitle-safe negative space",
                "handoff_state": "ready_for_image_generation_model_if_added_later",
                "is_real_output": is_configured,
                "mock_reason": None if is_configured else "Volcengine text provider is not connected.",
            },
        }


class MockCoverImageProvider:
    provider = "mock_cover_image_provider"
    model = "mock-seedream-cover-description-v1"

    def generate_cover_image(self, storyboard: list[dict[str, Any]], script: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        first_shot = storyboard[0] if storyboard else {}
        prompt = first_shot.get("image_prompt") or f"Vertical commerce hero image for {request.get('product_name', 'the product')}"
        return {
            "artifact_type": "cover_image_mock",
            "title": f"Cover image not generated / {request['product_name']}",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "prompt": prompt,
                "description": (
                    f"Placeholder plan for a 9:16 cover image of {request['product_name']}. "
                    f"Use the hook: {script.get('voiceover_lines', [script.get('title', '')])[0]}"
                ),
                "aspect_ratio": "9:16",
                "source_shot_id": first_shot.get("shot_id"),
                "is_real_output": False,
                "mock_reason": "VOLCENGINE_IMAGE_MODEL is not connected.",
            },
        }


class VolcengineCoverImageProvider:
    provider = "volcengine_seedream_image"
    fallback_provider = MockCoverImageProvider()

    def __init__(self) -> None:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine-image")
        self.last_fallback: str | None = None
        self.last_execution_mode = "mock_missing_config"
        self.last_provider_status = "missing_config"
        self.last_provider_message = "Volcengine image generation provider has not run yet."

    @property
    def model(self) -> str:
        settings = get_settings()
        return settings.volcengine_image_model or "volcengine-image-model-unconfigured"

    def generate_cover_image(self, storyboard: list[dict[str, Any]], script: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "volcengine-image")
        self.last_fallback = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = "Volcengine image generation provider returned a cover image."
        if not _image_generation_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "VOLCENGINE_IMAGE_MODEL is not connected; cover image was not generated."
            fallback = self.fallback_provider.generate_cover_image(storyboard, script, request)
            fallback["status"] = "mock_missing_config"
            fallback["payload"]["mock_reason"] = self.last_provider_message
            return fallback
        try:
            result = self._generate_image(storyboard, script, request)
            return {
                "artifact_type": "cover_image_real",
                "title": f"Cover image / {request['product_name']}",
                "provider": self.provider,
                "status": "real_generated",
                "payload": {
                    "prompt": result["prompt"],
                    "image_url": result.get("image_url"),
                    "aspect_ratio": "9:16",
                    "source_shot_id": storyboard[0].get("shot_id") if storyboard else None,
                    "raw_provider_fields": result.get("raw_provider_fields", {}),
                    "is_real_output": True,
                    "mock_reason": None,
                },
            }
        except Exception as exc:
            self.last_provider = self.provider
            self.last_model = _public_model_label(self.model, "volcengine-image")
            reason = _safe_error(exc)
            self.last_execution_mode = "real_failed"
            self.last_provider_status = "error"
            self.last_provider_message = f"Volcengine image generation failed; no placeholder output was generated. Reason: {reason}"
            self.last_fallback = self.last_provider_message
            first_shot = storyboard[0] if storyboard else {}
            return {
                "artifact_type": "cover_image_failed",
                "title": f"Cover image failed / {request['product_name']}",
                "provider": self.provider,
                "status": "provider_failed",
                "payload": {
                    "prompt": self._cover_prompt(storyboard, script),
                    "aspect_ratio": "9:16",
                    "source_shot_id": first_shot.get("shot_id"),
                    "is_real_output": False,
                    "failure_reason": self.last_provider_message,
                    "retry_hint": "Check VOLCENGINE_IMAGE_MODEL, model access, quota, and request parameters before retrying.",
                    "mock_reason": None,
                },
            }

    def _generate_image(self, storyboard: list[dict[str, Any]], script: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        base_url = _ark_base_url(settings.volcengine_base_url)
        url = _join_api_url(base_url, "/images/generations")
        prompt = self._cover_prompt(storyboard, script)
        body = {
            "model": self.model,
            "prompt": prompt,
            "size": "2K",
            "response_format": "url",
            "watermark": False,
        }
        headers = {
            "Authorization": f"Bearer {settings.volcengine_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=body)
            if response.status_code == 400:
                retry_body = {key: value for key, value in body.items() if key != "watermark"}
                response = client.post(url, headers=headers, json=retry_body)
            _raise_for_status(response, "Volcengine image generation")
        data = response.json()
        image_url = _extract_image_url(data)
        if not image_url:
            raise ValueError("Volcengine image response did not include an image URL.")
        return {"prompt": prompt, "image_url": image_url, "raw_provider_fields": _public_provider_fields(data)}

    def _cover_prompt(self, storyboard: list[dict[str, Any]], script: dict[str, Any]) -> str:
        first_shot = storyboard[0] if storyboard else {}
        return (
            f"{first_shot.get('image_prompt') or script.get('title')}. "
            "Create one polished 9:16 TikTok Shop cover frame, product centered, subtitle-safe space, no watermark."
        )


def _extract_image_url(data: dict[str, Any]) -> str | None:
    candidates = data.get("data")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, dict):
            if first.get("url") or first.get("image_url"):
                return first.get("url") or first.get("image_url")
            if first.get("b64_json"):
                return f"data:image/png;base64,{first['b64_json']}"
    if isinstance(data.get("url"), str):
        return data["url"]
    if isinstance(data.get("image_url"), str):
        return data["image_url"]
    return None


class MockVideoProvider:
    provider = "mock_video_provider"
    model = "mock-seedance-video-description-v1"

    def generate_draft_video(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = _draft_video_prompt(storyboard, script, request)
        return {
            "artifact_type": "seedance_draft_video",
            "title": f"AI draft video not generated / {request['product_name']}",
            "provider": self.provider,
            "status": "mock_missing_config",
            "payload": {
                "duration_seconds": script["duration_seconds"],
                "planned_duration_seconds": script["duration_seconds"],
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": prompt,
                "style_bible": _draft_style_bible(request, script),
                "task_id": None,
                "task_status": "not_connected",
                "video_url": None,
                "last_frame_url": None,
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "mock_reason": "Seedance provider is not connected.",
                "editing_role": "continuous_ai_draft_video",
            },
        }

    def generate_replacement_clip(
        self,
        shot: dict[str, Any],
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
        draft_artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = _replacement_clip_prompt(shot, storyboard, script, request, draft_artifact)
        return {
            "artifact_type": "seedance_replacement_clip",
            "title": f"Replacement clip not generated / {shot.get('shot_id')}",
            "provider": self.provider,
            "status": "mock_missing_config",
            "payload": {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "duration_seconds": _seedance_duration(shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS),
                "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": prompt,
                "style_bible": _draft_style_bible(request, script),
                "task_id": None,
                "task_status": "not_connected",
                "video_url": None,
                "last_frame_url": None,
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "mock_reason": "Seedance provider is not connected.",
                "editing_role": "replacement_segment_clip",
            },
        }

    def generate_shot_clip(
        self,
        shot: dict[str, Any],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = str(shot.get("video_prompt") or shot.get("visual_description") or "")
        return {
            "artifact_type": "seedance_shot_clip",
            "title": f"AI shot clip not generated / {shot.get('shot_id')}",
            "provider": self.provider,
            "status": "mock_missing_config",
            "payload": {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "duration_seconds": _seedance_duration(shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS),
                "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": prompt,
                "task_id": None,
                "task_status": "not_connected",
                "video_url": None,
                "last_frame_url": None,
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "mock_reason": "Seedance provider is not connected.",
                "editing_role": "ai_draft_shot_clip",
            },
        }

    def generate_video_description(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "artifact_type": "video_mock",
            "title": f"Video mock / {request['product_name']}",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "duration_seconds": script["duration_seconds"],
                "prompt": "\n".join(shot["video_prompt"] for shot in storyboard),
                "description": (
                    f"A text-only mock video plan for {request['product_name']} with "
                    f"{len(storyboard)} shots, optimized for {request.get('platform')}."
                ),
                "planned_duration_seconds": script["duration_seconds"],
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "preview_copy": [shot["subtitle"] for shot in storyboard],
                "source_assets": request.get("source_assets", []),
                "delivery_state": "ready_for_real_seedance_provider",
                "is_real_output": False,
                "mock_reason": "Seedance provider is not connected.",
            },
        }


class SeedanceVideoProvider:
    provider = "seedance_content_generation"
    fallback_provider = MockVideoProvider()

    def __init__(self) -> None:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        self.last_fallback: str | None = None
        self.last_execution_mode = "mock_missing_config"
        self.last_provider_status = "missing_config"
        self.last_provider_message = "Seedance provider has not run yet."

    @property
    def model(self) -> str:
        settings = get_settings()
        return settings.seedance_endpoint_id or settings.seedance_model or "seedance-model-unconfigured"

    def generate_video_description(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        self.last_fallback = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = "Seedance provider returned a video generation task result."
        settings = get_settings()
        if not _video_provider_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "Seedance provider is not connected; local video plan was generated instead of a real video."
            fallback = self.fallback_provider.generate_video_description(storyboard, script, request)
            fallback["status"] = "mock_missing_config"
            fallback["payload"]["is_real_output"] = False
            fallback["payload"]["mock_reason"] = self.last_provider_message
            return fallback
        try:
            result = self._create_and_poll_video(storyboard, script, request)
            status = "real_generated" if result.get("status") == "succeeded" else "real_task_pending"
            return {
                "artifact_type": "video_real",
                "title": f"Seedance video / {request['product_name']}",
                "provider": self.provider,
                "status": status,
                "payload": {
                    "planned_duration_seconds": script["duration_seconds"],
                    "requested_provider_duration_seconds": result.get("requested_provider_duration_seconds"),
                    "duration_seconds": result.get("duration_seconds")
                    or result.get("requested_provider_duration_seconds")
                    or script["duration_seconds"],
                    "provider_duration_seconds": result.get("duration_seconds"),
                    "prompt": "\n".join(shot["video_prompt"] for shot in storyboard),
                    "task_id": result.get("task_id"),
                    "task_status": result.get("status"),
                    "video_url": result.get("video_url"),
                    "last_frame_url": result.get("last_frame_url"),
                    "query_url": result.get("query_url"),
                    "source_assets": request.get("source_assets", []),
                    "raw_provider_fields": result.get("raw_provider_fields", {}),
                    "is_real_output": True,
                    "mock_reason": None,
                },
            }
        except Exception as exc:
            return self._failed_artifact(storyboard, script, request, exc)

    def generate_draft_video(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        self.last_fallback = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = "Seedance provider returned a continuous draft video task result."
        if not _video_provider_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "Seedance provider is not connected; the continuous AI draft video was not generated."
            artifact = self.fallback_provider.generate_draft_video(storyboard, script, request)
            artifact["payload"]["mock_reason"] = self.last_provider_message
            return artifact
        try:
            draft_storyboard = [
                {
                    "shot_id": "draft-video",
                    "order_index": 1,
                    "duration_seconds": script["duration_seconds"],
                    "video_prompt": _draft_video_prompt(storyboard, script, request),
                }
            ]
            result = self._create_and_poll_video(draft_storyboard, script, request)
            status = "real_generated" if result.get("status") == "succeeded" and result.get("video_url") else "real_task_pending"
            return {
                "artifact_type": "seedance_draft_video",
                "title": f"Seedance draft video / {request['product_name']}",
                "provider": self.provider,
                "status": status,
                "payload": {
                    "planned_duration_seconds": script["duration_seconds"],
                    "requested_provider_duration_seconds": result.get("requested_provider_duration_seconds"),
                    "duration_seconds": result.get("duration_seconds")
                    or result.get("requested_provider_duration_seconds")
                    or script["duration_seconds"],
                    "provider_duration_seconds": result.get("duration_seconds"),
                    "prompt": draft_storyboard[0]["video_prompt"],
                    "style_bible": _draft_style_bible(request, script),
                    "task_id": result.get("task_id"),
                    "task_status": result.get("status"),
                    "video_url": result.get("video_url"),
                    "last_frame_url": result.get("last_frame_url"),
                    "query_url": result.get("query_url"),
                    "source_assets": request.get("source_assets", []),
                    "raw_provider_fields": result.get("raw_provider_fields", {}),
                    "is_real_output": True,
                    "mock_reason": None,
                    "editing_role": "continuous_ai_draft_video",
                },
            }
        except Exception as exc:
            return self._failed_draft_video(storyboard, script, request, exc)

    def generate_replacement_clip(
        self,
        shot: dict[str, Any],
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
        draft_artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        self.last_fallback = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = f"Seedance provider returned a replacement clip task result for {shot.get('shot_id')}."
        if not _video_provider_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "Seedance provider is not connected; this replacement clip was not generated."
            artifact = self.fallback_provider.generate_replacement_clip(shot, storyboard, script, request, draft_artifact)
            artifact["payload"]["mock_reason"] = self.last_provider_message
            return artifact
        try:
            replacement_script = {**script, "duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS}
            replacement_storyboard = [
                {
                    **shot,
                    "video_prompt": _replacement_clip_prompt(shot, storyboard, script, request, draft_artifact),
                }
            ]
            result = self._create_and_poll_video(replacement_storyboard, replacement_script, request)
            status = "real_generated" if result.get("status") == "succeeded" and result.get("video_url") else "real_task_pending"
            return {
                "artifact_type": "seedance_replacement_clip",
                "title": f"Seedance replacement clip / {shot.get('shot_id')}",
                "provider": self.provider,
                "status": status,
                "payload": {
                    "shot_id": shot.get("shot_id"),
                    "order_index": shot.get("order_index"),
                    "duration_seconds": result.get("duration_seconds")
                    or result.get("requested_provider_duration_seconds")
                    or shot.get("duration_seconds")
                    or SHOT_CLIP_DURATION_SECONDS,
                    "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                    "requested_provider_duration_seconds": result.get("requested_provider_duration_seconds"),
                    "provider_duration_seconds": result.get("duration_seconds"),
                    "prompt": replacement_storyboard[0]["video_prompt"],
                    "style_bible": _draft_style_bible(request, script),
                    "task_id": result.get("task_id"),
                    "task_status": result.get("status"),
                    "video_url": result.get("video_url"),
                    "last_frame_url": result.get("last_frame_url"),
                    "query_url": result.get("query_url"),
                    "source_assets": request.get("source_assets", []),
                    "raw_provider_fields": result.get("raw_provider_fields", {}),
                    "is_real_output": True,
                    "mock_reason": None,
                    "editing_role": "replacement_segment_clip",
                },
            }
        except Exception as exc:
            return self._failed_replacement_clip(shot, storyboard, script, request, draft_artifact, exc)

    def generate_shot_clip(
        self,
        shot: dict[str, Any],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        self.last_fallback = None
        self.last_execution_mode = "real"
        self.last_provider_status = "configured"
        self.last_provider_message = f"Seedance provider returned a task result for {shot.get('shot_id')}."
        if not _video_provider_configured():
            self.last_provider = self.fallback_provider.provider
            self.last_model = self.fallback_provider.model
            self.last_execution_mode = "mock_missing_config"
            self.last_provider_status = "missing_config"
            self.last_provider_message = "Seedance provider is not connected; this shot clip was not generated."
            artifact = self.fallback_provider.generate_shot_clip(shot, script, request)
            artifact["payload"]["mock_reason"] = self.last_provider_message
            return artifact
        try:
            shot_script = {**script, "duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS}
            result = self._create_and_poll_video([shot], shot_script, request)
            status = "real_generated" if result.get("status") == "succeeded" and result.get("video_url") else "real_task_pending"
            return {
                "artifact_type": "seedance_shot_clip",
                "title": f"Seedance shot clip / {shot.get('shot_id')}",
                "provider": self.provider,
                "status": status,
                "payload": {
                    "shot_id": shot.get("shot_id"),
                    "order_index": shot.get("order_index"),
                    "duration_seconds": result.get("duration_seconds")
                    or result.get("requested_provider_duration_seconds")
                    or shot.get("duration_seconds")
                    or SHOT_CLIP_DURATION_SECONDS,
                    "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                    "requested_provider_duration_seconds": result.get("requested_provider_duration_seconds"),
                    "provider_duration_seconds": result.get("duration_seconds"),
                    "prompt": str(shot.get("video_prompt") or ""),
                    "task_id": result.get("task_id"),
                    "task_status": result.get("status"),
                    "video_url": result.get("video_url"),
                    "last_frame_url": result.get("last_frame_url"),
                    "query_url": result.get("query_url"),
                    "source_assets": request.get("source_assets", []),
                    "raw_provider_fields": result.get("raw_provider_fields", {}),
                    "is_real_output": True,
                    "mock_reason": None,
                    "editing_role": "ai_draft_shot_clip",
                },
            }
        except Exception as exc:
            return self._failed_shot_clip(shot, script, request, exc)

    def _failed_draft_video(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        reason = _safe_error(exc)
        self.last_execution_mode = "real_failed"
        self.last_provider_status = "error"
        self.last_provider_message = f"Seedance provider failed for the continuous draft video; no placeholder video was generated. Reason: {reason}"
        self.last_fallback = self.last_provider_message
        return {
            "artifact_type": "seedance_draft_video",
            "title": f"Seedance draft video failed / {request['product_name']}",
            "provider": self.provider,
            "status": "provider_failed",
            "payload": {
                "planned_duration_seconds": script.get("duration_seconds"),
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": _draft_video_prompt(storyboard, script, request),
                "style_bible": _draft_style_bible(request, script),
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "failure_reason": self.last_provider_message,
                "retry_hint": "Check Seedance endpoint access, quota, task API shape, and provider duration support before retrying the draft.",
                "mock_reason": None,
                "editing_role": "continuous_ai_draft_video",
            },
        }

    def _failed_replacement_clip(
        self,
        shot: dict[str, Any],
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
        draft_artifact: dict[str, Any] | None,
        exc: Exception,
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        reason = _safe_error(exc)
        self.last_execution_mode = "real_failed"
        self.last_provider_status = "error"
        self.last_provider_message = f"Seedance provider failed for replacement clip {shot.get('shot_id')}; no placeholder clip was generated. Reason: {reason}"
        self.last_fallback = self.last_provider_message
        return {
            "artifact_type": "seedance_replacement_clip",
            "title": f"Seedance replacement clip failed / {shot.get('shot_id')}",
            "provider": self.provider,
            "status": "provider_failed",
            "payload": {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": _replacement_clip_prompt(shot, storyboard, script, request, draft_artifact),
                "style_bible": _draft_style_bible(request, script),
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "failure_reason": self.last_provider_message,
                "retry_hint": "Check Seedance endpoint access, quota, task API shape, and provider duration support before retrying this replacement.",
                "mock_reason": None,
                "editing_role": "replacement_segment_clip",
            },
        }

    def _failed_shot_clip(
        self,
        shot: dict[str, Any],
        script: dict[str, Any],
        request: dict[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        reason = _safe_error(exc)
        self.last_execution_mode = "real_failed"
        self.last_provider_status = "error"
        self.last_provider_message = f"Seedance provider failed for {shot.get('shot_id')}; no placeholder clip was generated. Reason: {reason}"
        self.last_fallback = self.last_provider_message
        return {
            "artifact_type": "seedance_shot_clip",
            "title": f"Seedance shot clip failed / {shot.get('shot_id')}",
            "provider": self.provider,
            "status": "provider_failed",
            "payload": {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "planned_duration_seconds": shot.get("duration_seconds") or SHOT_CLIP_DURATION_SECONDS,
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": str(shot.get("video_prompt") or ""),
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "failure_reason": self.last_provider_message,
                "retry_hint": "Check Seedance endpoint access, quota, task API shape, and provider duration support before retrying this shot.",
                "mock_reason": None,
                "editing_role": "ai_draft_shot_clip",
            },
        }

    def _failed_artifact(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
        exc: Exception,
    ) -> dict[str, Any]:
        self.last_provider = self.provider
        self.last_model = _public_model_label(self.model, "seedance")
        reason = _safe_error(exc)
        self.last_execution_mode = "real_failed"
        self.last_provider_status = "error"
        self.last_provider_message = f"Seedance provider failed; no placeholder output was generated. Reason: {reason}"
        self.last_fallback = self.last_provider_message
        return {
            "artifact_type": "video_failed",
            "title": f"Seedance video failed / {request['product_name']}",
            "provider": self.provider,
            "status": "provider_failed",
            "payload": {
                "planned_duration_seconds": script.get("duration_seconds"),
                "requested_provider_duration_seconds": None,
                "provider_duration_seconds": None,
                "prompt": "\n".join(shot["video_prompt"] for shot in storyboard),
                "source_assets": request.get("source_assets", []),
                "is_real_output": False,
                "failure_reason": self.last_provider_message,
                "retry_hint": "Check Seedance endpoint access, quota, task API shape, and provider duration support before retrying.",
                "mock_reason": None,
            },
        }

    def _create_and_poll_video(
        self,
        storyboard: list[dict[str, Any]],
        script: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        settings = get_settings()
        base_url = _ark_base_url(settings.seedance_base_url)
        create_url = _join_api_url(base_url, "/contents/generations/tasks")
        prompt = "\n".join(shot["video_prompt"] for shot in storyboard)
        requested_duration = _to_int(script.get("duration_seconds") or request.get("duration_seconds"), 12)
        duration = _seedance_duration(requested_duration)
        body = {
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "generate_audio": True,
            "ratio": "9:16",
            "duration": duration,
            "planned_duration": requested_duration,
            "watermark": False,
        }
        headers = {
            "Authorization": f"Bearer {settings.seedance_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
            last_create_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    create_response = client.post(create_url, headers=headers, json=body)
                    _raise_for_status(create_response, "Seedance create task")
                    break
                except Exception as exc:
                    last_create_error = exc
                    if attempt == 3 or not _is_retryable_seedance_error(exc):
                        raise
                    time.sleep(_provider_retry_delay_seconds(exc, attempt))
            if last_create_error is not None and "create_response" not in locals():
                raise last_create_error
            create_data = create_response.json()
            task_id = create_data.get("id") or create_data.get("task_id")
            if not task_id:
                raise ValueError("Seedance response did not include a task id.")
            query_url = _join_api_url(base_url, f"/contents/generations/tasks/{task_id}")
            deadline = time.monotonic() + max(0, settings.seedance_poll_seconds)
            last_data = create_data
            query_error_count = 0
            while time.monotonic() <= deadline:
                try:
                    query_response = client.get(query_url, headers=headers)
                    _raise_for_status(query_response, "Seedance query task")
                    query_error_count = 0
                except Exception as exc:
                    query_error_count += 1
                    if query_error_count >= 3 or not _is_retryable_seedance_error(exc):
                        raise
                    time.sleep(_provider_retry_delay_seconds(exc, query_error_count))
                    continue
                last_data = query_response.json()
                status = str(last_data.get("status") or "").lower()
                if status in {"succeeded", "failed", "cancelled", "canceled"}:
                    break
                time.sleep(max(1, settings.seedance_poll_interval_seconds))
        content = last_data.get("content") if isinstance(last_data.get("content"), dict) else {}
        return {
            "task_id": task_id,
            "status": str(last_data.get("status") or create_data.get("status") or "submitted"),
            "planned_duration_seconds": requested_duration,
            "requested_provider_duration_seconds": duration,
            "duration_seconds": content.get("duration") or last_data.get("duration") or create_data.get("duration"),
            "video_url": content.get("video_url"),
            "last_frame_url": content.get("last_frame_url"),
            "query_url": query_url,
            "raw_provider_fields": _public_provider_fields(last_data),
        }


class MockTTSProvider:
    provider = "mock_tts_provider"
    model = "mock-volcengine-tts-plan-v1"

    def generate_voice_track(self, script: dict[str, Any], storyboard: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "artifact_type": "voice_track_plan",
            "title": "Voice track plan",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "voice": "warm commerce narrator",
                "language": "en",
                "lines": [
                    {
                        "shot_id": shot["shot_id"],
                        "text": shot["tts_line"],
                        "duration_seconds": shot["duration_seconds"],
                    }
                    for shot in storyboard
                ],
                "handoff_state": "ready_for_volcengine_tts_provider",
                "script_title": script.get("title"),
                "is_real_output": False,
                "mock_reason": "TTS provider is not connected yet.",
            },
        }


class MockSubtitleProvider:
    provider = "mock_subtitle_provider"
    model = "mock-subtitle-track-v1"

    def generate_subtitle_track(self, storyboard: list[dict[str, Any]]) -> dict[str, Any]:
        cursor = 0
        cues = []
        for shot in storyboard:
            start = cursor
            cursor += shot["duration_seconds"]
            cues.append(
                {
                    "shot_id": shot["shot_id"],
                    "start_seconds": start,
                    "end_seconds": cursor,
                    "text": shot["subtitle"],
                }
            )
        return {
            "artifact_type": "subtitle_track_plan",
            "title": "Subtitle track plan",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "format": "srt_plan",
                "cues": cues,
                "is_real_output": False,
                "mock_reason": "Subtitle rendering provider is not connected yet.",
            },
        }


class MockBGMProvider:
    provider = "mock_bgm_provider"
    model = "mock-bgm-plan-v1"

    def generate_bgm_plan(self, script: dict[str, Any], storyboard: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "artifact_type": "bgm_plan",
            "title": "BGM plan",
            "provider": self.provider,
            "status": "mock_generated",
            "payload": {
                "mood": "clean native commerce pulse",
                "tempo": "104 BPM",
                "mix_notes": "duck music under voiceover, lift at CTA, no copyrighted track is selected yet",
                "cue_map": [{"shot_id": shot["shot_id"], "cue": shot["bgm_cue"]} for shot in storyboard],
                "script_title": script.get("title"),
                "is_real_output": False,
                "mock_reason": "BGM provider is not connected yet.",
            },
        }


llm_provider = VolcengineLLMProvider()
image_provider = VolcengineImagePlanProvider()
cover_image_provider = VolcengineCoverImageProvider()
video_provider = SeedanceVideoProvider()
tts_provider = MockTTSProvider()
subtitle_provider = MockSubtitleProvider()
bgm_provider = MockBGMProvider()


def _merge_prompt_package(storyboard: list[dict[str, Any]], prompt_package: dict[str, Any]) -> list[dict[str, Any]]:
    prompts_by_shot = {
        str(item.get("shot_id")): item
        for item in prompt_package.get("storyboard_prompts", [])
        if isinstance(item, dict) and item.get("shot_id")
    }
    merged = []
    for shot in storyboard:
        prompt = prompts_by_shot.get(str(shot.get("shot_id")), {})
        merged.append(
            {
                **shot,
                "image_prompt": str(prompt.get("image_prompt") or shot.get("image_prompt") or f"Product image for {shot.get('beat')}"),
                "video_prompt": str(prompt.get("video_prompt") or shot.get("video_prompt") or f"Product video shot for {shot.get('beat')}"),
                "tts_line": str(prompt.get("tts_line") or shot.get("tts_line") or shot.get("voiceover") or ""),
                "bgm_cue": str(prompt.get("bgm_cue") or shot.get("bgm_cue") or "clean commerce pulse"),
                "subtitle": str(prompt.get("subtitle") or shot.get("subtitle") or shot.get("voiceover") or "")[:120],
            }
        )
    return merged


def _timeline_clips_from_artifacts(storyboard: list[dict[str, Any]], video_artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts_by_shot = {
        str(artifact.get("payload", {}).get("shot_id")): artifact
        for artifact in video_artifacts
        if artifact.get("payload", {}).get("shot_id")
    }
    cursor = 0
    clips: list[dict[str, Any]] = []
    for shot in storyboard:
        duration = _to_int(shot.get("duration_seconds"), SHOT_CLIP_DURATION_SECONDS)
        artifact = artifacts_by_shot.get(str(shot.get("shot_id")), {})
        payload = artifact.get("payload", {}) if isinstance(artifact.get("payload"), dict) else {}
        start = cursor
        cursor += duration
        clips.append(
            {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "beat": shot.get("beat"),
                "subtitle": shot.get("subtitle"),
                "voiceover": shot.get("voiceover"),
                "duration_seconds": duration,
                "time_range": f"{start}-{cursor}s",
                "artifact_id": artifact.get("id"),
                "artifact_type": artifact.get("artifact_type"),
                "artifact_status": artifact.get("status"),
                "task_id": payload.get("task_id"),
                "task_status": payload.get("task_status"),
                "video_url": payload.get("video_url"),
                "last_frame_url": payload.get("last_frame_url"),
                "prompt": payload.get("prompt") or shot.get("video_prompt"),
                "failure_reason": payload.get("failure_reason"),
                "mock_reason": payload.get("mock_reason"),
            }
        )
    return clips


def _draft_style_bible(request: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": request.get("product_name"),
        "category": request.get("category"),
        "platform": request.get("platform"),
        "visual_style": request.get("visual_style"),
        "reference_style": request.get("reference_style"),
        "script_title": script.get("title"),
        "continuity_rules": [
            "Keep the same product identity, color, material, and proportions across the whole video.",
            "Keep one coherent lighting setup and visual language across all beats.",
            "Do not swap to a different product, package, person, logo, or unrelated scene between shots.",
            "Use smooth short-video transitions so the full requested timeline feels like one continuous draft.",
        ],
    }


def _draft_video_prompt(storyboard: list[dict[str, Any]], script: dict[str, Any], request: dict[str, Any]) -> str:
    style = _draft_style_bible(request, script)
    beats = []
    cursor = 0
    for shot in sorted(storyboard, key=lambda item: int(item.get("order_index") or 0)):
        duration = _to_int(shot.get("duration_seconds"), SHOT_CLIP_DURATION_SECONDS)
        start = cursor
        cursor += duration
        beats.append(
            (
                f"{start}-{cursor}s / {shot.get('beat')}: "
                f"{shot.get('visual_description')} "
                f"Camera: {shot.get('camera_motion')}. "
                f"Subtitle-safe caption: {shot.get('subtitle')}."
            )
        )
    total_duration = cursor or _to_int(script.get("duration_seconds") or request.get("duration_seconds"), 12)
    segment_count = len(beats) or EDITING_SHOT_COUNT
    return (
        f"Create one continuous {total_duration}-second vertical 9:16 TikTok Shop product video for {style['product_name']}.\n"
        f"Product category: {style['category']}. Platform: {style['platform']}.\n"
        f"Unified visual style: {style['visual_style']}. Reference style: {style['reference_style']}.\n"
        f"Script title: {style['script_title']}.\n"
        f"Continuity constraints: keep the same hero product, finish, proportions, lighting, and product world across all {segment_count} timeline beats. "
        f"Do not introduce unrelated products, people, packaging, logos, or locations. Make the video feel like one coherent draft with {segment_count} editable segments.\n"
        "Timeline beats:\n"
        + "\n".join(beats)
    )


def _replacement_clip_prompt(
    shot: dict[str, Any],
    storyboard: list[dict[str, Any]],
    script: dict[str, Any],
    request: dict[str, Any],
    draft_artifact: dict[str, Any] | None = None,
) -> str:
    style = _draft_style_bible(request, script)
    sorted_storyboard = sorted(storyboard, key=lambda item: int(item.get("order_index") or 0))
    index = next((idx for idx, item in enumerate(sorted_storyboard) if item.get("shot_id") == shot.get("shot_id")), 0)
    previous_shot = sorted_storyboard[index - 1] if index > 0 else None
    next_shot = sorted_storyboard[index + 1] if index + 1 < len(sorted_storyboard) else None
    cursor = 0
    target_start = 0
    target_end = _to_int(shot.get("duration_seconds"), SHOT_CLIP_DURATION_SECONDS)
    for item in sorted_storyboard:
        duration = _to_int(item.get("duration_seconds"), SHOT_CLIP_DURATION_SECONDS)
        start = cursor
        cursor += duration
        if item.get("shot_id") == shot.get("shot_id"):
            target_start = start
            target_end = cursor
            break
    draft_payload = (draft_artifact or {}).get("payload", {}) if isinstance(draft_artifact, dict) else {}
    retrieval = request.get("retrieval_context") or {}
    selected_reference = retrieval.get("selected_reference_video") or request.get("reference_video") or {}
    reference_title = selected_reference.get("title") if isinstance(selected_reference, dict) else ""
    reference_mode = selected_reference.get("source_mode") if isinstance(selected_reference, dict) else ""
    factor_names = [
        str(item.get("name") or item.get("factor_key") or "")
        for item in (retrieval.get("auto_factors") or request.get("selected_library_factors") or [])[:4]
        if isinstance(item, dict)
    ]
    asset_anchors = [
        f"{asset.get('filename') or asset.get('title') or 'asset'}: {str(asset.get('description') or asset.get('summary') or '')[:160]}"
        for asset in (request.get("source_assets") or request.get("asset_library") or request.get("selected_asset_slices") or [])[:4]
        if isinstance(asset, dict)
    ]
    source_asset_warning = (
        "No uploaded visual source asset is available; maintain consistency from the original draft and text style bible only."
        if not request.get("source_assets") and not (request.get("selected_asset_slices") or request.get("asset_slice_ids"))
        else "Use the attached product assets or selected slices as visual anchors."
    )
    return (
        f"Regenerate only one {shot.get('duration_seconds') or SHOT_CLIP_DURATION_SECONDS}-second replacement segment for {style['product_name']}.\n"
        f"This replacement will be inserted into the original {target_start}-{target_end}s timeline slot. The original draft audio/timing may remain underneath it, so match the pacing and visual rhythm of that slot.\n"
        f"Keep strict continuity with the existing AI draft timeline: same hero product, same color/material/proportions, same lighting, same background world, same camera language, and same ad quality.\n"
        f"Global style: {style['visual_style']}. Reference style: {style['reference_style']}.\n"
        f"Best viral reference: {reference_title or 'none'} ({reference_mode or 'auto'}). Factor anchors: {', '.join(factor_names) or 'use the current strategy board'}.\n"
        f"Asset continuity note: {source_asset_warning}\n"
        f"Visual asset anchors: {' | '.join(asset_anchors) if asset_anchors else 'none'}.\n"
        f"Draft task context: {draft_payload.get('task_id') or 'draft task not available'}.\n"
        f"Previous beat context: {(previous_shot or {}).get('beat') or 'none'} / {(previous_shot or {}).get('visual_description') or ''} / {(previous_shot or {}).get('subtitle') or ''}\n"
        f"Target beat: {shot.get('beat')} / {shot.get('visual_description')}\n"
        f"Target voiceover: {shot.get('voiceover')}\n"
        f"Target subtitle-safe caption: {shot.get('subtitle')}\n"
        f"Camera: {shot.get('camera_motion')}. Updated video prompt: {shot.get('video_prompt')}\n"
        f"Next beat context: {(next_shot or {}).get('beat') or 'none'} / {(next_shot or {}).get('visual_description') or ''} / {(next_shot or {}).get('subtitle') or ''}\n"
        "Do not make a standalone new ad. Do not change the hero product, packaging, model, logo, room, palette, or visual universe. "
        "The first frame must plausibly follow the previous beat, and the last frame must plausibly lead into the next beat."
    )


def _timeline_segments_from_artifacts(
    storyboard: list[dict[str, Any]],
    draft_artifact: dict[str, Any] | None,
    replacement_artifacts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    draft_payload = (draft_artifact or {}).get("payload", {}) if isinstance(draft_artifact, dict) else {}
    replacements_by_shot = {
        str(artifact.get("payload", {}).get("shot_id")): artifact
        for artifact in replacement_artifacts or []
        if artifact.get("payload", {}).get("shot_id")
    }
    cursor = 0
    segments: list[dict[str, Any]] = []
    for shot in sorted(storyboard, key=lambda item: int(item.get("order_index") or 0)):
        duration = _to_int(shot.get("duration_seconds"), SHOT_CLIP_DURATION_SECONDS)
        start = cursor
        cursor += duration
        replacement = replacements_by_shot.get(str(shot.get("shot_id")))
        replacement_payload = replacement.get("payload", {}) if isinstance(replacement, dict) else {}
        replacement_ready = bool(replacement and replacement.get("status") == "real_generated" and replacement_payload.get("video_url"))
        source_artifact = replacement if replacement_ready else draft_artifact
        source_payload = replacement_payload if replacement_ready else draft_payload
        source = "replacement_clip" if replacement_ready else "draft_video"
        segments.append(
            {
                "shot_id": shot.get("shot_id"),
                "order_index": shot.get("order_index"),
                "beat": shot.get("beat"),
                "subtitle": shot.get("subtitle"),
                "voiceover": shot.get("voiceover"),
                "duration_seconds": duration,
                "start_seconds": start,
                "end_seconds": cursor,
                "time_range": f"{start}-{cursor}s",
                "source": source,
                "source_label": "Replacement clip" if replacement_ready else "Draft slice",
                "artifact_id": source_artifact.get("id") if isinstance(source_artifact, dict) else None,
                "artifact_type": source_artifact.get("artifact_type") if isinstance(source_artifact, dict) else None,
                "artifact_status": source_artifact.get("status") if isinstance(source_artifact, dict) else "waiting",
                "draft_video_url": draft_payload.get("video_url"),
                "replacement_video_url": replacement_payload.get("video_url"),
                "video_url": source_payload.get("video_url"),
                "task_id": source_payload.get("task_id"),
                "task_status": source_payload.get("task_status"),
                "last_frame_url": source_payload.get("last_frame_url"),
                "prompt": replacement_payload.get("prompt") if replacement_ready else shot.get("video_prompt"),
                "draft_prompt": draft_payload.get("prompt"),
                "failure_reason": replacement_payload.get("failure_reason") or draft_payload.get("failure_reason"),
                "mock_reason": source_payload.get("mock_reason"),
            }
        )
    return segments


def _active_segment_sources(segments: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(segment.get("shot_id")): str(segment.get("source") or "draft_video")
        for segment in segments
        if segment.get("shot_id")
    }


def _aggregate_clip_status(video_artifacts: list[dict[str, Any]]) -> str:
    if not video_artifacts:
        return "not_started"
    statuses = [str(artifact.get("status") or "").lower() for artifact in video_artifacts]
    task_statuses = [str(artifact.get("payload", {}).get("task_status") or "").lower() for artifact in video_artifacts]
    if any(status in {"provider_failed", "real_failed"} or task in {"failed", "cancelled", "canceled"} for status, task in zip(statuses, task_statuses, strict=False)):
        return "failed"
    if statuses and all(status == "real_generated" for status in statuses):
        return "succeeded"
    if any(status == "real_task_pending" or task in {"submitted", "running", "pending", "processing", "queued"} for status, task in zip(statuses, task_statuses, strict=False)):
        return "processing"
    if all(status == "mock_missing_config" for status in statuses):
        return "not_connected"
    return "pending"


def viral_strategy_agent(state: GenerationGraphState) -> GenerationGraphState:
    started_at = time.perf_counter()
    attempt = state.get("strategy_attempts", 0) + 1
    request = {**state["request"], "_strategy_attempt": attempt}
    substeps: list[dict[str, Any]] = []

    retrieval_started = time.perf_counter()
    retrieval_context = request.get("retrieval_context") or {}
    substeps.append(
        _substep_trace(
            substep_name="retrieval_context",
            provider="local_retrieval_context",
            model="asset-and-methodology-retrieval-v1",
            started_at=retrieval_started,
            input_summary={
                "asset_query": retrieval_context.get("asset_query"),
                "viral_query": retrieval_context.get("viral_query"),
            },
            output_summary={
                "asset_results": len(retrieval_context.get("auto_asset_results") or []),
                "selected_slices": len(retrieval_context.get("selected_slices") or []),
                "auto_factors": len(retrieval_context.get("auto_factors") or []),
                "auto_templates": len(retrieval_context.get("auto_templates") or []),
                "auto_references": len(retrieval_context.get("auto_references") or []),
                "reference_match_mode": retrieval_context.get("reference_match_mode"),
            },
            execution_mode="real",
            provider_status="configured",
            provider_message="Asset and viral methodology retrieval context was prepared before strategy planning.",
        )
    )

    sub_started = time.perf_counter()
    try:
        brief = llm_provider.generate_structured("strategy_brief", request)
    except Exception as exc:
        substeps.append(
            _provider_failed_substep(
                "strategy_brief",
                sub_started,
                {"product_name": request.get("product_name"), "selling_points": request.get("selling_points")},
                llm_provider,
                exc,
            )
        )
        failed = _failed_agent_state(
            state,
            agent_name="Viral Strategy Agent",
            started_at=started_at,
            input_payload={"request": request},
            output_payload={},
            substeps=substeps,
            exc=exc,
        )
        return {**failed, "strategy_attempts": attempt}
    substeps.append(
        _provider_substep(
            "strategy_brief",
            sub_started,
            {"product_name": request.get("product_name"), "selling_points": request.get("selling_points")},
            {"hook": brief.get("hook"), "angle": brief.get("product_angle")},
            llm_provider,
        )
    )

    sub_started = time.perf_counter()
    try:
        factor_result = llm_provider.generate_structured("factor_board_packaging", {"request": request, "brief": brief})
    except Exception as exc:
        substeps.append(
            _provider_failed_substep(
                "factor_board_packaging",
                sub_started,
                input_summary={"hook": brief.get("hook"), "category_count": 8},
                provider=llm_provider,
                exc=exc,
            )
        )
        failed = _failed_agent_state(
            state,
            agent_name="Viral Strategy Agent",
            started_at=started_at,
            input_payload={"request": request},
            output_payload={"strategy": brief},
            substeps=substeps,
            exc=exc,
        )
        return {**failed, "strategy_attempts": attempt}
    substeps.append(
        _provider_substep(
            "factor_board_packaging",
            sub_started,
            {"hook": brief.get("hook"), "category_count": 8},
            {
                "factor_count": len(factor_result.get("factor_board", [])),
                "factor_coverage": factor_result.get("factor_coverage"),
            },
            llm_provider,
        )
    )

    strategy = {**brief, **factor_result, **_strategy_retrieval_fields(request)}
    strategy["selected_factors"] = strategy.get("factor_board", [])
    trace = _trace_step(
        agent_name="Viral Strategy Agent",
        provider=" + ".join(dict.fromkeys(str(step.get("provider")) for step in substeps)),
        model=" / ".join(dict.fromkeys(str(step.get("model")) for step in substeps)),
        input_payload={"request": request},
        output_payload={**strategy, "substeps": substeps},
        started_at=started_at,
        fallback=_fallback_trace(
            llm_provider,
            "Volcengine Ark generates factor board from assets, reference, template, and user fields.",
        ),
        execution_mode=_combine_substep_execution_modes(substeps),
        provider_status=_combine_substep_provider_statuses(substeps),
        provider_message="; ".join(str(step.get("provider_message")) for step in substeps if step.get("provider_message")),
        status=_status_trace(llm_provider),
    )
    return {**state, "strategy": strategy, "strategy_attempts": attempt, "trace": [*state.get("trace", []), trace]}


def script_storyboard_agent(state: GenerationGraphState) -> GenerationGraphState:
    started_at = time.perf_counter()
    attempt = state.get("script_attempts", 0) + 1
    payload = {"request": {**state["request"], "_script_attempt": attempt}, "strategy": state["strategy"]}
    substeps: list[dict[str, Any]] = []

    sub_started = time.perf_counter()
    try:
        script = llm_provider.generate_structured("copy_draft", payload)
    except Exception as exc:
        substeps.append(
            _provider_failed_substep(
                "copy_draft",
                sub_started,
                {"hook": state["strategy"].get("hook"), "duration_seconds": payload["request"].get("duration_seconds")},
                llm_provider,
                exc,
            )
        )
        failed = _failed_agent_state(
            state,
            agent_name="Script & Storyboard Agent",
            started_at=started_at,
            input_payload=payload,
            output_payload={},
            substeps=substeps,
            exc=exc,
        )
        return {**failed, "script_attempts": attempt}
    substeps.append(
        _provider_substep(
            "copy_draft",
            sub_started,
            {"hook": state["strategy"].get("hook"), "duration_seconds": payload["request"].get("duration_seconds")},
            {
                "title": script.get("title"),
                "line_count": len(script.get("voiceover_lines", [])),
                "duration_seconds": script.get("duration_seconds"),
            },
            llm_provider,
        )
    )

    sub_started = time.perf_counter()
    try:
        storyboard_result = llm_provider.generate_structured(
            "storyboard_plan",
            {"request": payload["request"], "strategy": state["strategy"], "script": script},
        )
    except Exception as exc:
        substeps.append(
            _provider_failed_substep(
                "storyboard_plan",
                sub_started,
                {"script_title": script.get("title"), "line_count": len(script.get("voiceover_lines", []))},
                llm_provider,
                exc,
            )
        )
        failed = _failed_agent_state(
            state,
            agent_name="Script & Storyboard Agent",
            started_at=started_at,
            input_payload=payload,
            output_payload={"script": script},
            substeps=substeps,
            exc=exc,
        )
        return {**failed, "script_attempts": attempt}
    storyboard = _rebalance_storyboard_durations(storyboard_result["storyboard"], payload["request"].get("duration_seconds"))
    substeps.append(
        _provider_substep(
            "storyboard_plan",
            sub_started,
            {"script_title": script.get("title"), "line_count": len(script.get("voiceover_lines", []))},
            {
                "shot_count": len(storyboard),
                "duration_seconds": sum(_to_int(shot.get("duration_seconds"), 0) for shot in storyboard),
                "beats": [shot.get("beat") for shot in storyboard],
            },
            llm_provider,
        )
    )

    sub_started = time.perf_counter()
    try:
        prompt_package = llm_provider.generate_structured(
            "prompt_package",
            {"request": payload["request"], "strategy": state["strategy"], "script": script, "storyboard": storyboard},
        )
    except Exception as exc:
        substeps.append(
            _provider_failed_substep(
                "prompt_package",
                sub_started,
                {"shot_count": len(storyboard), "visual_style": script.get("visual_style")},
                llm_provider,
                exc,
            )
        )
        failed = _failed_agent_state(
            state,
            agent_name="Script & Storyboard Agent",
            started_at=started_at,
            input_payload=payload,
            output_payload={"script": script, "storyboard": storyboard},
            substeps=substeps,
            exc=exc,
        )
        return {**failed, "script_attempts": attempt}
    storyboard = _merge_prompt_package(storyboard, prompt_package)
    script["subtitle_lines"] = [shot["subtitle"] for shot in storyboard]
    script["tts_lines"] = [shot["tts_line"] for shot in storyboard]
    script["duration_seconds"] = sum(_to_int(shot.get("duration_seconds"), 0) for shot in storyboard)
    substeps.append(
        _provider_substep(
            "prompt_package",
            sub_started,
            {"shot_count": len(storyboard), "visual_style": script.get("visual_style")},
            {"prompt_count": len(prompt_package.get("storyboard_prompts", []))},
            llm_provider,
        )
    )

    trace = _trace_step(
        agent_name="Script & Storyboard Agent",
        provider=" + ".join(dict.fromkeys(str(step.get("provider")) for step in substeps)),
        model=" / ".join(dict.fromkeys(str(step.get("model")) for step in substeps)),
        input_payload=payload,
        output_payload={
            "script_title": script["title"],
            "shot_count": len(storyboard),
            "duration_seconds": script["duration_seconds"],
            "substeps": substeps,
        },
        started_at=started_at,
        fallback=_fallback_trace(
            llm_provider,
            "Volcengine Ark generates copy, fixed storyboard, and prompts as three small structured calls.",
        ),
        execution_mode=_combine_substep_execution_modes(substeps),
        provider_status=_combine_substep_provider_statuses(substeps),
        provider_message="; ".join(str(step.get("provider_message")) for step in substeps if step.get("provider_message")),
        status="failed" if any(str(step.get("status")) == "failed" for step in substeps) else "succeeded",
    )
    return {
        **state,
        "script": script,
        "storyboard": storyboard,
        "script_attempts": attempt,
        "trace": [*state.get("trace", []), trace],
    }


def render_review_agent(state: GenerationGraphState) -> GenerationGraphState:
    started_at = time.perf_counter()
    request = state["request"]
    storyboard = state["storyboard"]
    script = state["script"]
    substeps: list[dict[str, Any]] = []

    sub_started = time.perf_counter()
    cover_artifact = cover_image_provider.generate_cover_image(storyboard, script, request)
    substeps.append(
        _provider_substep(
            "cover_image_generation",
            sub_started,
            {"script_title": script.get("title"), "first_shot": storyboard[0].get("shot_id") if storyboard else None},
            {
                "artifact_type": cover_artifact.get("artifact_type"),
                "status": cover_artifact.get("status"),
                "has_image_url": bool(cover_artifact.get("payload", {}).get("image_url")),
            },
            cover_image_provider,
        )
    )

    sub_started = time.perf_counter()
    image_artifacts = [image_provider.generate_image_description(shot, request) for shot in storyboard]
    substeps.append(
        _provider_substep(
            "shot_image_prompt_plan",
            sub_started,
            {"shot_count": len(storyboard)},
            {"artifact_count": len(image_artifacts)},
            image_provider,
        )
    )

    sub_started = time.perf_counter()
    draft_video_artifact = video_provider.generate_draft_video(storyboard, script, request)
    substeps.append(
        _provider_substep(
            "seedance_draft_video",
            sub_started,
            {
                "shot_count": len(storyboard),
                "planned_duration_seconds": script.get("duration_seconds"),
                "prompt": str(draft_video_artifact.get("payload", {}).get("prompt") or "")[:220],
            },
            {
                "artifact_type": draft_video_artifact.get("artifact_type"),
                "status": draft_video_artifact.get("status"),
                "task_status": draft_video_artifact.get("payload", {}).get("task_status"),
                "has_video_url": bool(draft_video_artifact.get("payload", {}).get("video_url")),
            },
            video_provider,
        )
    )

    sub_started = time.perf_counter()
    voice_artifact = tts_provider.generate_voice_track(script, storyboard)
    subtitle_artifact = subtitle_provider.generate_subtitle_track(storyboard)
    bgm_artifact = bgm_provider.generate_bgm_plan(script, storyboard)
    substeps.append(
        _substep_trace(
            substep_name="voice_subtitle_bgm_plan",
            provider="local_track_plan_provider",
            model="local-tts-subtitle-bgm-plan",
            started_at=sub_started,
            input_summary={"shot_count": len(storyboard), "script_title": script.get("title")},
            output_summary={"voice_lines": len(voice_artifact["payload"].get("lines", [])), "subtitle_cues": len(subtitle_artifact["payload"].get("cues", []))},
            execution_mode="mock_missing_config",
            provider_status="missing_config",
            provider_message="TTS, subtitle rendering, and BGM providers are not connected yet.",
        )
    )
    timeline_segments = _timeline_segments_from_artifacts(storyboard, draft_video_artifact, [])
    primary_video_payload = draft_video_artifact.get("payload", {})
    ready_video_payloads = [primary_video_payload] if primary_video_payload.get("video_url") else []
    aggregate_video_status = _aggregate_clip_status([draft_video_artifact])
    cover_payload = cover_artifact.get("payload", {})
    preview_duration = sum(_to_int(segment.get("duration_seconds"), 0) for segment in timeline_segments) or script["duration_seconds"]
    preview_mode = "ai_draft_timeline" if primary_video_payload.get("video_url") else "provider_preview_package"
    preview = {
        "mode": preview_mode,
        "aspect_ratio": "9:16",
        "total_duration_seconds": preview_duration,
        "planned_duration_seconds": script["duration_seconds"],
        "requested_provider_duration_seconds": primary_video_payload.get("requested_provider_duration_seconds"),
        "provider_duration_seconds": primary_video_payload.get("provider_duration_seconds") or (preview_duration if ready_video_payloads else None),
        "source_asset_count": len(request.get("source_assets") or []),
        "cover_text": storyboard[0]["subtitle"] if storyboard else script.get("title", ""),
        "cover_image_url": cover_payload.get("image_url"),
        "cover_image_status": cover_artifact.get("status"),
        "video_url": primary_video_payload.get("video_url"),
        "video_task_id": primary_video_payload.get("task_id"),
        "video_task_status": aggregate_video_status,
        "draft_video_url": primary_video_payload.get("video_url"),
        "draft_video_status": draft_video_artifact.get("status"),
        "timeline_segments": timeline_segments,
        "active_segment_sources": _active_segment_sources(timeline_segments),
        "voice_track": voice_artifact["payload"],
        "subtitle_track": subtitle_artifact["payload"],
        "bgm_plan": bgm_artifact["payload"],
        "timeline": [
            {
                "shot_id": shot["shot_id"],
                "time_range": f"{sum(item['duration_seconds'] for item in storyboard[:index])}-{sum(item['duration_seconds'] for item in storyboard[: index + 1])}s",
                "beat": shot["beat"],
                "caption": shot["subtitle"],
                "visual": shot["visual_description"],
            }
            for index, shot in enumerate(storyboard)
        ],
    }
    export_manifest = {
        "format": "provider_preview_package",
        "version": "1.0",
        "run_mode": "auto_provider_selection",
        "platform": request.get("platform"),
        "aspect_ratios": ["9:16", "1:1", "16:9"],
        "source_assets": request.get("source_assets", []),
        "script_title": script.get("title"),
        "shot_count": len(storyboard),
        "planned_duration_seconds": script.get("duration_seconds"),
        "requested_provider_duration_seconds": primary_video_payload.get("requested_provider_duration_seconds"),
        "provider_duration_seconds": preview.get("provider_duration_seconds"),
        "artifact_types": [
            "script",
            "storyboard",
            "cover_image",
            "image_prompt_plan",
            "seedance_draft_video",
            "seedance_replacement_clips",
            "voice_track_plan",
            "subtitle_track_plan",
            "bgm_plan",
            "edit_decision_list",
            "compliance",
        ],
        "handoff_note": "Provider outputs include real URLs when connected; not-connected capabilities are recorded separately.",
        "is_real_output": bool(ready_video_payloads or cover_payload.get("image_url")),
        "mock_reason": None if ready_video_payloads or cover_payload.get("image_url") else primary_video_payload.get("mock_reason") or cover_payload.get("mock_reason"),
    }
    banned_terms = ["guaranteed cure", "permanent result", "medical cure"]
    claim_safe = not any(term in script.get("narrative", "").lower() for term in banned_terms)
    compliance = {
        "passed": claim_safe,
        "checks": [
            {
                "name": "claim safety",
                "status": "passed" if claim_safe else "failed",
                "note": "No guaranteed effect, medical, or unverifiable superlative claim generated."
                if claim_safe
                else "Claim-risk wording detected; LangGraph should route back to script rewrite.",
            },
            {
                "name": "reference safety",
                "status": "passed",
                "note": "Reference style is treated as directional language only.",
            },
            {
                "name": "source asset handling",
                "status": "passed",
                "note": "Uploaded assets are stored locally and referenced as metadata in the Agent run.",
            },
            {
                "name": "artifact mode",
                "status": "passed",
                "note": "Not-connected providers are separated from configured provider failures.",
            },
        ],
        "final_delivery": "Use the generated provider artifacts and export manifest as the delivery package.",
    }
    final_artifact = {
        "artifact_type": "delivery_plan",
        "title": "Final delivery plan",
        "provider": "render_review_agent",
        "status": "ready",
        "payload": {
            "summary": compliance["final_delivery"],
            "image_artifact_count": len(image_artifacts) + 1,
            "video_artifact_count": 1,
            "export_format": export_manifest["format"],
            "compliance_passed": compliance["passed"],
            "is_real_output": bool(ready_video_payloads or cover_payload.get("image_url")),
            "mock_reason": None if ready_video_payloads or cover_payload.get("image_url") else primary_video_payload.get("mock_reason") or cover_payload.get("mock_reason"),
        },
    }
    sub_started = time.perf_counter()
    export_artifact = {
        "artifact_type": "export_manifest",
        "title": "Provider preview export manifest",
        "provider": "render_review_agent",
        "status": "ready",
        "payload": export_manifest,
    }
    edit_decision_artifact = {
            "artifact_type": "edit_decision_list",
            "title": "Edit decision list",
        "provider": "render_review_agent",
        "status": "provider_pending",
        "payload": {
            "cuts": [
                {
                    "shot_id": shot["shot_id"],
                    "duration_seconds": shot["duration_seconds"],
                    "source": "fixed segment assembly is handled by the local Timeline Editor",
                }
                for shot in storyboard
            ],
            "disabled_capabilities": ["freeform trim handles", "multi-track smart edit decisions", "real TTS rendering"],
            "is_real_output": False,
            "mock_reason": "Shot-level smart editing provider is not connected yet.",
        },
    }
    substeps.append(
        _substep_trace(
            substep_name="edit_decision_plan",
            provider="render_review_agent",
            model="deterministic-edit-decision-plan",
            started_at=sub_started,
            input_summary={"shot_count": len(storyboard)},
            output_summary={"cut_count": len(edit_decision_artifact["payload"].get("cuts", [])), "provider_pending": True},
            execution_mode="mock_missing_config",
            provider_status="missing_config",
            provider_message="Smart editing provider is reserved for the future Editing & Assembly Agent.",
        )
    )
    artifacts = [
        cover_artifact,
        *image_artifacts,
        draft_video_artifact,
        voice_artifact,
        subtitle_artifact,
        bgm_artifact,
        edit_decision_artifact,
        export_artifact,
        final_artifact,
    ]
    media_errors = [
        {
            "agent_name": "Render & Review Agent",
            "message": str(step.get("provider_message") or step.get("error") or "Provider failed."),
            "execution_mode": "real_failed",
            "provider_status": "error",
            "substep_name": step.get("substep_name"),
        }
        for step in substeps
        if step.get("provider_status") == "error"
    ]
    trace = _trace_step(
        agent_name="Render & Review Agent",
        provider=(
            f"{_provider_trace_value(cover_image_provider, 'last_provider', cover_image_provider.provider)} + "
            f"{_provider_trace_value(image_provider, 'last_provider', image_provider.provider)} + "
            f"{_provider_trace_value(video_provider, 'last_provider', video_provider.provider)}"
        ),
        model=(
            f"{_provider_trace_value(cover_image_provider, 'last_model', cover_image_provider.model)} / "
            f"{_provider_trace_value(image_provider, 'last_model', image_provider.model)} / "
            f"{_provider_trace_value(video_provider, 'last_model', video_provider.model)}"
        ),
        input_payload={"script": script, "storyboard": storyboard},
        output_payload={
            "artifact_count": len(artifacts),
            "compliance_passed": compliance["passed"],
            "preview_mode": preview["mode"],
            "cover_image_status": cover_artifact["status"],
            "video_status": aggregate_video_status,
            "segment_count": len(timeline_segments),
            "substeps": substeps,
        },
        started_at=started_at,
        fallback="; ".join(
            item
            for item in [
                _provider_message_value(image_provider),
                _provider_message_value(cover_image_provider),
                _fallback_trace(video_provider, ""),
                "Image Prompt Plan uses the Volcengine text endpoint. TTS, subtitles, and BGM remain local planning outputs until those providers are connected.",
            ]
            if item
        ),
        execution_mode=_combine_substep_execution_modes(substeps),
        provider_status=_combine_substep_provider_statuses(substeps),
        provider_message="; ".join(
            [_provider_message_value(cover_image_provider), _provider_message_value(image_provider), _provider_message_value(video_provider)]
        ),
        status="failed" if media_errors else "succeeded",
        error="; ".join(error["message"] for error in media_errors) if media_errors else None,
    )
    return {
        **state,
        "artifacts": artifacts,
        "preview": preview,
        "export_manifest": export_manifest,
        "compliance": compliance,
        "trace": [*state.get("trace", []), trace],
        "errors": [*state.get("errors", []), *media_errors],
    }


def _route_after_strategy(state: GenerationGraphState) -> str:
    if state.get("errors"):
        return "done"
    if state.get("strategy", {}).get("factor_coverage", 1) < 0.7 and state.get("strategy_attempts", 0) < 2:
        return "retry_strategy"
    return "continue"


def _route_after_script(state: GenerationGraphState) -> str:
    return "done" if state.get("errors") else "continue"


def _route_after_render(state: GenerationGraphState) -> str:
    if state.get("errors"):
        return "done"
    if not state.get("compliance", {}).get("passed", True) and state.get("script_attempts", 0) < 2:
        return "rewrite_script"
    return "done"


def _build_generation_graph():
    graph = StateGraph(GenerationGraphState)
    graph.add_node("viral_strategy", viral_strategy_agent)
    graph.add_node("script_storyboard", script_storyboard_agent)
    graph.add_node("render_review", render_review_agent)
    graph.set_entry_point("viral_strategy")
    graph.add_conditional_edges(
        "viral_strategy",
        _route_after_strategy,
        {
            "retry_strategy": "viral_strategy",
            "continue": "script_storyboard",
            "done": END,
        },
    )
    graph.add_conditional_edges(
        "script_storyboard",
        _route_after_script,
        {
            "continue": "render_review",
            "done": END,
        },
    )
    graph.add_conditional_edges(
        "render_review",
        _route_after_render,
        {
            "rewrite_script": "script_storyboard",
            "done": END,
        },
    )
    return graph.compile()


GENERATION_GRAPH = _build_generation_graph()


def _initial_generation_state(run_id: str, request: dict[str, Any]) -> GenerationGraphState:
    return {
        "run_id": run_id,
        "request": request,
        "trace": [],
        "artifacts": [],
        "preview": {},
        "export_manifest": {},
        "errors": [],
        "strategy_attempts": 0,
        "script_attempts": 0,
    }


def run_generation_graph(run_id: str, request: dict[str, Any]) -> GenerationGraphState:
    return GENERATION_GRAPH.invoke(_initial_generation_state(run_id, request))


def stream_generation_graph(run_id: str, request: dict[str, Any]):
    state: GenerationGraphState = _initial_generation_state(run_id, request)
    for chunk in GENERATION_GRAPH.stream(state):
        if not isinstance(chunk, dict):
            continue
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            state = {**state, **update}
            yield state


def _claim_safe(text: str) -> str:
    value = text or "daily use moment"
    replacements = {
        "guaranteed cure": "visible daily support",
        "permanent result": "clear short-term use cue",
        "medical cure": "non-medical product benefit",
    }
    for risky, safe in replacements.items():
        value = value.replace(risky, safe).replace(risky.title(), safe)
    return value
