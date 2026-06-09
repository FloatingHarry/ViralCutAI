from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, ViralFactor, ViralVideoAnalysis
from app.schemas import AssetCreate, FastMossVideoImportCreate
from app.services.asset_library import create_asset


FASTMOSS_SOURCE_STATEMENT = "FastMoss structured TikTok video data; source footage is not copied."
STRUCTURED_SOURCE_MODE = "fastmoss_structured_only"
VERIFIED_SOURCE_MODE = "owner_viral_verified"
UPLOADED_UNVERIFIED_SOURCE_MODE = "owner_viral_uploaded_unverified"
OWNER_REFERENCE_ASSET_KIND = "owner_viral_reference"
FACTOR_CATEGORIES = ["hook", "proof", "scene", "trust", "visual", "audio", "cta", "risk"]
FASTMOSS_ORDER_FIELDS = {
    "play_count",
    "digg_count",
    "share_count",
    "comment_count",
    "units_sold",
    "gmv",
    "interact_rate",
    "publish_time",
    "follower_count",
}

_TOKEN_CACHE: dict[str, Any] = {
    "access_token": "",
    "refresh_token": "",
    "expires_at": 0.0,
    "refresh_expires_at": 0.0,
}


class FastMossProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider_status: str = "error",
        code: int | str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status = provider_status
        self.code = code
        self.request_id = request_id


def import_fastmoss_videos(payload: FastMossVideoImportCreate, db: Session) -> dict[str, Any]:
    request_payload = _safe_request_payload(payload)
    if not _fastmoss_configured():
        return _import_result(
            status="failed",
            provider_status="missing_config",
            provider_message="FastMoss not connected. Set FASTMOSS_API_KEY or FASTMOSS_CLIENT_ID/FASTMOSS_CLIENT_SECRET in .env.local.",
            request_payload=request_payload,
        )
    if not _text_provider_configured():
        return _import_result(
            status="failed",
            provider_status="llm_missing_config",
            provider_message="Volcengine text provider is not connected; FastMoss quota was not consumed.",
            request_payload=request_payload,
        )

    try:
        token = _get_fastmoss_access_token()
        order_field, order = _parse_order_by(payload.order_by)
        response_body = _fastmoss_post(
            "/video/v1/search",
            {
                "keywords": payload.keywords,
                "filter": _fastmoss_filter(payload),
                "orderby": [{"field": order_field, "order": order}],
                "page": payload.page,
                "pagesize": payload.pagesize,
            },
            token,
        )
    except FastMossProviderError as exc:
        return _import_result(
            status="failed",
            provider_status=exc.provider_status,
            provider_message=_provider_error_message(exc),
            request_payload=request_payload,
        )
    except Exception as exc:
        return _import_result(
            status="failed",
            provider_status="error",
            provider_message=f"FastMoss import request failed. Reason: {_safe_error(exc)}",
            request_payload=request_payload,
        )

    videos, raw_total = _extract_video_items(response_body)
    items: list[dict[str, Any]] = []
    for video in videos:
        item = _import_one_video(video, payload, db)
        items.append(item)

    imported_count = sum(1 for item in items if item["status"] == "imported")
    skipped_count = sum(1 for item in items if item["status"] == "skipped_duplicate")
    failed_count = sum(1 for item in items if item["status"].startswith("failed"))
    factor_count = sum(int(item.get("factor_count") or 0) for item in items)
    status = "succeeded"
    if failed_count and imported_count:
        status = "partial_failure"
    elif failed_count and not imported_count and not skipped_count:
        status = "failed"
    summary = f"Imported {imported_count} videos, skipped {skipped_count} duplicates, failed {failed_count}; generated {factor_count} factors."
    return _import_result(
        status=status,
        provider_status="configured",
        provider_message="FastMoss Video Search returned structured-only data; Volcengine extracted non-visual-verified factors.",
        request_payload=request_payload,
        imported_count=imported_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        factor_count=factor_count,
        items=items,
        raw_total=raw_total,
        summary=summary,
    )


def attach_source_video_to_reference(
    reference_id: UUID,
    *,
    filename: str,
    content_type: str,
    content: bytes,
    db: Session,
) -> ViralVideoAnalysis:
    reference = db.get(ViralVideoAnalysis, reference_id)
    if reference is None:
        raise LookupError("Viral reference not found")
    normalized_content_type = _video_content_type(filename, content_type)
    if not normalized_content_type.startswith("video/"):
        raise ValueError("Only video files can be attached for visual verification.")
    if not content:
        raise ValueError("Attached source video is empty.")

    asset = create_asset(
        AssetCreate(
            filename=filename,
            content_type=normalized_content_type,
            asset_kind=OWNER_REFERENCE_ASSET_KIND,
            category=reference.category,
            description=(
                f"Owner-uploaded MP4 for internal visual verification of viral reference '{reference.title}'. "
                f"Original source URL: {reference.source_url}. Do not copy or redistribute source footage."
            ),
        ),
        db,
        content=content,
    )

    reference = db.get(ViralVideoAnalysis, reference_id)
    if reference is None:
        raise LookupError("Viral reference not found")
    existing_analysis = dict(reference.analysis or {})
    fastmoss_metadata = _fastmoss_metadata_from_analysis(existing_analysis)
    video_id = _reference_video_id(reference, fastmoss_metadata)
    factor_source = _factor_source(video_id, reference.id)
    visual_verified = _asset_visual_verified(asset)

    if visual_verified and _text_provider_configured():
        try:
            llm_analysis = _extract_verified_fastmoss_analysis_with_llm(reference, asset, fastmoss_metadata)
            factor_board = _normalize_factor_board(
                llm_analysis.get("factor_board"),
                video_id=video_id,
                reference_id=str(reference.id),
                source_url=reference.source_url,
                category=reference.category,
                fastmoss_metadata=fastmoss_metadata,
                source_mode=VERIFIED_SOURCE_MODE,
                visual_verified=True,
                verified_asset_id=str(asset.id),
                factor_source=factor_source,
            )
            reference.analysis = _normalize_verified_analysis(
                existing_analysis,
                llm_analysis,
                reference=reference,
                asset=asset,
                factor_board=factor_board,
                fastmoss_metadata=fastmoss_metadata,
            )
            _replace_reference_factors(factor_source, factor_board, db)
        except Exception as exc:
            reference.analysis = _mark_reference_video_attached(
                existing_analysis,
                reference=reference,
                asset=asset,
                message=f"Source MP4 keyframes were analyzed, but verified factor regeneration failed: {_safe_error(exc)}",
            )
    else:
        reference.analysis = _mark_reference_video_attached(existing_analysis, reference=reference, asset=asset)

    db.add(reference)
    db.commit()
    db.refresh(reference)
    return reference


def _import_one_video(video: dict[str, Any], payload: FastMossVideoImportCreate, db: Session) -> dict[str, Any]:
    video_id = str(video.get("video_id") or video.get("id") or "").strip()
    title = _video_title(video)
    source_url = str(video.get("video_url") or "").strip()
    metrics = _video_metrics(video)
    if not video_id:
        return {
            "status": "failed_invalid_video",
            "video_id": "",
            "title": title,
            "source_url": source_url,
            "message": "FastMoss video item did not include video_id.",
            "metrics": metrics,
        }
    if _is_duplicate_video(video_id, source_url, db):
        return {
            "status": "skipped_duplicate",
            "video_id": video_id,
            "title": title,
            "source_url": source_url,
            "message": "Video already exists in Viral Library.",
            "metrics": metrics,
        }

    try:
        analysis = _extract_fastmoss_analysis_with_llm(video, payload)
    except Exception as exc:
        return {
            "status": "failed_llm",
            "video_id": video_id,
            "title": title,
            "source_url": source_url,
            "message": f"Volcengine factor extraction failed; no factors were created. Reason: {_safe_error(exc)}",
            "metrics": metrics,
        }

    fastmoss_metadata = _fastmoss_metadata(video)
    category = _video_category(video, payload)
    record = ViralVideoAnalysis(
        title=title[:220],
        source_url=source_url,
        category=category,
        source_statement=FASTMOSS_SOURCE_STATEMENT,
        analysis={},
    )
    try:
        db.add(record)
        db.flush()
        factor_board = _normalize_factor_board(
            analysis.get("factor_board"),
            video_id=video_id,
            reference_id=str(record.id),
            source_url=source_url,
            category=category,
            fastmoss_metadata=fastmoss_metadata,
        )
        record.analysis = _normalize_analysis(
            analysis,
            video=video,
            payload=payload,
            reference_id=str(record.id),
            factor_board=factor_board,
            fastmoss_metadata=fastmoss_metadata,
        )
        for factor in factor_board:
            db.add(
                ViralFactor(
                    factor_key=factor["factor_key"],
                    name=str(factor.get("name") or title)[:160],
                    category=str(factor.get("category") or "hook")[:80],
                    source=f"external:fastmoss:{video_id}",
                    description=str(factor.get("reason") or "")[:2000],
                    metadata_payload=factor,
                )
            )
        db.commit()
        db.refresh(record)
    except Exception as exc:
        db.rollback()
        return {
            "status": "failed_db",
            "video_id": video_id,
            "title": title,
            "source_url": source_url,
            "message": f"Database write failed; no partial record was kept. Reason: {_safe_error(exc)}",
            "metrics": metrics,
        }
    return {
        "status": "imported",
        "video_id": video_id,
        "title": title,
        "source_url": source_url,
        "reference_id": record.id,
        "factor_count": len(factor_board),
        "message": "Imported into Viral Library.",
        "metrics": metrics,
    }


def _fastmoss_configured() -> bool:
    settings = get_settings()
    return bool(settings.fastmoss_api_key or (settings.fastmoss_client_id and settings.fastmoss_client_secret))


def _text_provider_configured() -> bool:
    settings = get_settings()
    return bool(settings.volcengine_api_key and (settings.volcengine_endpoint_id or settings.volcengine_text_model))


def _get_fastmoss_access_token() -> str:
    settings = get_settings()
    if settings.fastmoss_api_key:
        return settings.fastmoss_api_key
    now = time.time()
    if _TOKEN_CACHE["access_token"] and float(_TOKEN_CACHE["expires_at"]) - 60 > now:
        return str(_TOKEN_CACHE["access_token"])
    if _TOKEN_CACHE["refresh_token"] and float(_TOKEN_CACHE["refresh_expires_at"]) - 60 > now:
        try:
            return _refresh_fastmoss_token()
        except Exception:
            _TOKEN_CACHE["access_token"] = ""
    try:
        return _request_fastmoss_token()
    except FastMossProviderError as exc:
        fallback_key = str(settings.fastmoss_client_secret or "").strip()
        error_text = str(exc).lower()
        if fallback_key and ("client_id" in error_text or "client_secret" in error_text or exc.code == 1002):
            return fallback_key
        raise


def _request_fastmoss_token() -> str:
    settings = get_settings()
    data = _fastmoss_auth_post(
        "/v1/token",
        {
            "client_id": settings.fastmoss_client_id,
            "client_secret": settings.fastmoss_client_secret,
        },
    )
    return _store_token_payload(data)


def _refresh_fastmoss_token() -> str:
    settings = get_settings()
    data = _fastmoss_auth_post(
        "/v1/refreshToken",
        {
            "client_id": settings.fastmoss_client_id,
            "refresh_token": _TOKEN_CACHE["refresh_token"],
        },
    )
    return _store_token_payload(data)


def _store_token_payload(data: dict[str, Any]) -> str:
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise FastMossProviderError("FastMoss token response did not include access_token.", provider_status="auth_error")
    now = time.time()
    expires_in = _to_int(data.get("expires_in"), 3600)
    refresh_expires_in = _to_int(data.get("refresh_expires_in"), 0)
    _TOKEN_CACHE["access_token"] = token
    _TOKEN_CACHE["refresh_token"] = str(data.get("refresh_token") or _TOKEN_CACHE.get("refresh_token") or "")
    _TOKEN_CACHE["expires_at"] = now + max(60, expires_in)
    _TOKEN_CACHE["refresh_expires_at"] = now + max(0, refresh_expires_in)
    return token


def _fastmoss_auth_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    response_json = _fastmoss_request(path, body, token="")
    data = response_json.get("data") or {}
    if not isinstance(data, dict):
        raise FastMossProviderError("FastMoss auth response data was not an object.", provider_status="auth_error")
    return data


def _fastmoss_post(path: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    return _fastmoss_request(path, body, token=token)


def _fastmoss_request(path: str, body: dict[str, Any], *, token: str) -> dict[str, Any]:
    settings = get_settings()
    url = _join_url(settings.fastmoss_base_url, path)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=body)
    except Exception as exc:
        raise FastMossProviderError(f"FastMoss request failed: {_safe_error(exc)}") from exc
    if response.status_code != 200:
        raise FastMossProviderError(
            f"FastMoss HTTP {response.status_code}: {_safe_response_text(response)}",
            provider_status="http_error",
            request_id=response.headers.get("x-request-id"),
        )
    try:
        response_json = response.json()
    except ValueError as exc:
        raise FastMossProviderError("FastMoss response was not valid JSON.") from exc
    code = response_json.get("code")
    if str(code) != "0":
        message = str(response_json.get("msg") or response_json.get("message") or "FastMoss business error")
        raise FastMossProviderError(
            message,
            provider_status="business_error",
            code=code,
            request_id=str(response_json.get("request_id") or response.headers.get("x-request-id") or ""),
        )
    return response_json


def _extract_fastmoss_analysis_with_llm(video: dict[str, Any], payload: FastMossVideoImportCreate) -> dict[str, Any]:
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model
    if not settings.volcengine_api_key or not model:
        raise RuntimeError("Volcengine text provider is not connected.")
    base_url = _ark_base_url(settings.volcengine_base_url)
    url = _join_url(base_url, "/chat/completions")
    compact_video = _compact_video_for_llm(video)
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are ViralCutAI's commerce video factor extraction engine. "
                    "Return strict JSON only, in English, with no markdown. "
                    "Use source data as market intelligence; never suggest copying footage or creator identity. "
                    "No source video frames are available in this request."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this FastMoss TikTok ecommerce video record and extract exactly one structured-only factor "
                    "for each category: hook, proof, scene, trust, visual, audio, cta, risk.\n"
                    "You have FastMoss text, product, creator, and metrics only. Do not claim observed camera angles, "
                    "first-person footage, exact scenes, on-screen actions, sounds, music, voiceover, or editing rhythm. "
                    "For visual and audio categories, describe reusable hypotheses inferred from text/metrics and label "
                    "them as unverified direction, not confirmed footage.\n"
                    "Return JSON with keys: hook_method, selling_point_order, storyboard_structure, "
                    "visual_style, caption_style, audio_style, cta_pattern, risk_notes, template_strategy, "
                    "factor_board, compliance_statement.\n"
                    "factor_board items must have: factor_key, name, category, reason, expected_effect, "
                    "confidence integer 0-100, linked_shot_ids array, evidence_type, evidence_text. "
                    "No private data, no invented metrics.\n\n"
                    f"IMPORT REQUEST:\n{json.dumps(_safe_request_payload(payload), ensure_ascii=False)}\n\n"
                    f"FASTMOSS VIDEO JSON:\n{json.dumps(compact_video, ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.35,
        "max_tokens": 2200,
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
            if response.status_code >= 400:
                raise RuntimeError(f"Volcengine chat completion failed with HTTP {response.status_code}: {_safe_response_text(response)}")
            break
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(_provider_retry_delay_seconds(exc, attempt))
    if last_error is not None and "response" not in locals():
        raise last_error
    content = response.json()["choices"][0]["message"]["content"]
    try:
        return _extract_json_object(content)
    except Exception as exc:
        return _repair_json_content(content, exc)


def _extract_verified_fastmoss_analysis_with_llm(
    reference: ViralVideoAnalysis,
    asset: Asset,
    fastmoss_metadata: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model
    if not settings.volcengine_api_key or not model:
        raise RuntimeError("Volcengine text provider is not connected.")
    base_url = _ark_base_url(settings.volcengine_base_url)
    url = _join_url(base_url, "/chat/completions")
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are ViralCutAI's verified commerce video factor extraction engine. "
                    "Return strict JSON only, in English, with no markdown. "
                    "Use the source MP4 only as internal evidence; never suggest copying footage, creator identity, or exact shots."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this owner-uploaded viral reference MP4 using the verified keyframe analysis and FastMoss market data. "
                    "Extract exactly one factor for each category: hook, proof, scene, trust, visual, audio, cta, risk.\n"
                    "You may cite visual evidence only when it is supported by the keyframe summaries. Audio is not directly analyzed; "
                    "if no transcript/audio evidence is present, treat audio_style as a recommendation inferred from captions or market context.\n"
                    "Return JSON with keys: hook_method, selling_point_order, storyboard_structure, visual_style, caption_style, "
                    "audio_style, cta_pattern, risk_notes, template_strategy, factor_board, compliance_statement.\n"
                    "factor_board items must have: factor_key, name, category, reason, expected_effect, confidence integer 0-100, "
                    "linked_shot_ids array, evidence_type, evidence_text. No invented metrics.\n\n"
                    f"VIRAL REFERENCE:\n{json.dumps(_compact_reference_for_llm(reference), ensure_ascii=False)}\n\n"
                    f"FASTMOSS MARKET DATA:\n{json.dumps(fastmoss_metadata, ensure_ascii=False)}\n\n"
                    f"VERIFIED VIDEO ASSET:\n{json.dumps(_compact_asset_for_llm(asset), ensure_ascii=False)}"
                ),
            },
        ],
        "temperature": 0.28,
        "max_tokens": 2400,
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
    if response.status_code >= 400:
        raise RuntimeError(f"Volcengine verified factor extraction failed with HTTP {response.status_code}: {_safe_response_text(response)}")
    content = response.json()["choices"][0]["message"]["content"]
    try:
        return _extract_json_object(content)
    except Exception as exc:
        return _repair_json_content(content, exc)


def _repair_json_content(broken_content: str, parse_error: Exception) -> dict[str, Any]:
    settings = get_settings()
    model = settings.volcengine_endpoint_id or settings.volcengine_text_model
    base_url = _ark_base_url(settings.volcengine_base_url)
    url = _join_url(base_url, "/chat/completions")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Repair malformed JSON. Return one valid JSON object only, no markdown."},
            {
                "role": "user",
                "content": (
                    f"Parse error: {_safe_error(parse_error)}\n"
                    "Fix this FastMoss factor extraction JSON. Keep the same meaning. "
                    "Do not invent metrics, API keys, or private data.\n\n"
                    f"BROKEN JSON/TEXT:\n{broken_content[:10000]}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 2200,
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
    if response.status_code >= 400:
        raise RuntimeError(f"Volcengine JSON repair failed with HTTP {response.status_code}: {_safe_response_text(response)}")
    return _extract_json_object(response.json()["choices"][0]["message"]["content"])


def _normalize_analysis(
    analysis: dict[str, Any],
    *,
    video: dict[str, Any],
    payload: FastMossVideoImportCreate,
    reference_id: str,
    factor_board: list[dict[str, Any]],
    fastmoss_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": {
            "reference_id": reference_id,
            "source_mode": STRUCTURED_SOURCE_MODE,
            "visual_verified": False,
            "platform": "TikTok",
            "source_url": str(video.get("video_url") or ""),
            "category": _video_category(video, payload),
            "product_type": _product_type(video),
            "country": str(video.get("region") or payload.region),
            "language": "",
            "metrics": _video_metrics(video),
            "published_at": str(video.get("publish_time") or ""),
            "thumbnail_url": str(video.get("cover") or ""),
            "source_statement": FASTMOSS_SOURCE_STATEMENT,
            "fastmoss": fastmoss_metadata,
        },
        "source_mode": STRUCTURED_SOURCE_MODE,
        "visual_verified": False,
        "verified_asset_id": None,
        "frame_count": 0,
        "video_metadata": {},
        "hook_method": str(analysis.get("hook_method") or ""),
        "selling_point_order": _string_list(analysis.get("selling_point_order"))[:8],
        "storyboard_structure": _normalize_storyboard(analysis.get("storyboard_structure")),
        "visual_style": str(analysis.get("visual_style") or ""),
        "style": str(analysis.get("visual_style") or ""),
        "caption_style": str(analysis.get("caption_style") or ""),
        "audio_style": str(analysis.get("audio_style") or ""),
        "cta_pattern": str(analysis.get("cta_pattern") or ""),
        "risk_notes": _string_list(analysis.get("risk_notes"))[:8],
        "template_strategy": str(analysis.get("template_strategy") or ""),
        "factor_board": factor_board,
        "compliance_statement": str(analysis.get("compliance_statement") or FASTMOSS_SOURCE_STATEMENT),
    }


def _normalize_factor_board(
    raw_board: Any,
    *,
    video_id: str,
    reference_id: str,
    source_url: str,
    category: str,
    fastmoss_metadata: dict[str, Any],
    source_mode: str = STRUCTURED_SOURCE_MODE,
    visual_verified: bool = False,
    verified_asset_id: str | None = None,
    factor_source: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw_board, list):
        raise ValueError("LLM response did not include factor_board array.")
    by_category: dict[str, dict[str, Any]] = {}
    for raw in raw_board:
        if not isinstance(raw, dict):
            continue
        factor_category = str(raw.get("category") or "").strip().lower()
        if factor_category not in FACTOR_CATEGORIES or factor_category in by_category:
            continue
        by_category[factor_category] = raw
    missing = [item for item in FACTOR_CATEGORIES if item not in by_category]
    if missing:
        raise ValueError(f"LLM response missed required factor categories: {', '.join(missing)}.")
    normalized = []
    for factor_category in FACTOR_CATEGORIES:
        raw = by_category[factor_category]
        key_seed = f"fastmoss|{video_id}|{factor_category}|{raw.get('name') or raw.get('reason') or ''}"
        source = factor_source or f"external:fastmoss:{video_id}"
        factor_visual_verified = visual_verified and factor_category != "audio"
        factor_audio_verified = False
        source_capability = "keyframe_verified" if factor_visual_verified else "structured_only"
        if visual_verified and factor_category == "audio":
            source_capability = "caption_metric_inference"
        normalized.append(
            {
                "factor_key": f"fastmoss-{factor_category}-{hashlib.sha1(key_seed.encode('utf-8')).hexdigest()[:8]}",
                "name": _clip(str(raw.get("name") or f"{factor_category.title()} factor"), 160),
                "category": factor_category,
                "reason": _clip(str(raw.get("reason") or ""), 2000),
                "expected_effect": _clip(str(raw.get("expected_effect") or "Improves TikTok commerce creative fit using FastMoss signals."), 500),
                "confidence": _clamp_int(raw.get("confidence"), 0, 100, 72),
                "linked_shot_ids": _linked_shot_ids(raw.get("linked_shot_ids")),
                "source": source,
                "source_reference_id": reference_id,
                "source_url": source_url,
                "platform": "TikTok",
                "source_mode": source_mode,
                "source_capability": source_capability,
                "reference_visual_verified": visual_verified,
                "visual_verified": factor_visual_verified,
                "audio_verified": factor_audio_verified,
                "verified_asset_id": verified_asset_id,
                "evidence_type": _factor_evidence_type(factor_category, raw, visual_verified),
                "evidence_text": _clip(str(raw.get("evidence_text") or raw.get("reason") or ""), 1000),
                "product_type": _product_type_from_metadata(fastmoss_metadata),
                "country": str(fastmoss_metadata.get("region") or ""),
                "category_context": category,
                "fastmoss": fastmoss_metadata,
                "source_safety_note": (
                    "Owner-uploaded source MP4 was used for internal keyframe verification; source footage is not copied."
                    if visual_verified
                    else "Structured analysis only; source footage is not available or copied."
                ),
            }
        )
    return normalized


def _normalize_verified_analysis(
    existing_analysis: dict[str, Any],
    llm_analysis: dict[str, Any],
    *,
    reference: ViralVideoAnalysis,
    asset: Asset,
    factor_board: list[dict[str, Any]],
    fastmoss_metadata: dict[str, Any],
) -> dict[str, Any]:
    source = dict(existing_analysis.get("source") or {})
    verified_at = _iso_datetime(asset.updated_at)
    uploaded_at = _iso_datetime(asset.created_at)
    cover_path = _ensure_reference_cover(reference, asset, fastmoss_metadata)
    source.update(
        {
            "reference_id": str(reference.id),
            "source_mode": VERIFIED_SOURCE_MODE,
            "source_capability": "keyframe_verified",
            "visual_verified": True,
            "verified_at": verified_at,
            "verified_asset_id": str(asset.id),
            "verified_asset_filename": asset.filename,
            "verified_asset_kind": asset.asset_kind,
            "verified_asset_provider_status": asset.provider_status,
            "verified_asset_created_at": uploaded_at,
            "verified_asset_updated_at": verified_at,
            "cover_path": cover_path,
            "local_cover_url": f"/viral-videos/{reference.id}/cover" if cover_path else source.get("local_cover_url"),
            "fastmoss": fastmoss_metadata,
        }
    )
    frame_count = len(asset.analysis.get("frame_analyses") or asset.slices or [])
    return {
        **existing_analysis,
        "source": source,
        "source_mode": VERIFIED_SOURCE_MODE,
        "source_capability": "keyframe_verified",
        "visual_verified": True,
        "verified_at": verified_at,
        "verified_asset_id": str(asset.id),
        "verified_asset_kind": asset.asset_kind,
        "verified_asset_filename": asset.filename,
        "verified_asset_created_at": uploaded_at,
        "verified_asset_updated_at": verified_at,
        "cover_path": cover_path or existing_analysis.get("cover_path"),
        "local_cover_url": f"/viral-videos/{reference.id}/cover" if cover_path else existing_analysis.get("local_cover_url"),
        "frame_count": frame_count,
        "video_metadata": asset.analysis.get("video_metadata") or {},
        "verified_frame_evidence": _compact_asset_frames(asset),
        "hook_method": str(llm_analysis.get("hook_method") or existing_analysis.get("hook_method") or ""),
        "selling_point_order": _string_list(llm_analysis.get("selling_point_order") or existing_analysis.get("selling_point_order"))[:8],
        "storyboard_structure": _normalize_storyboard(llm_analysis.get("storyboard_structure") or existing_analysis.get("storyboard_structure")),
        "visual_style": str(llm_analysis.get("visual_style") or existing_analysis.get("visual_style") or ""),
        "style": str(llm_analysis.get("visual_style") or existing_analysis.get("style") or ""),
        "caption_style": str(llm_analysis.get("caption_style") or existing_analysis.get("caption_style") or ""),
        "audio_style": str(llm_analysis.get("audio_style") or existing_analysis.get("audio_style") or ""),
        "cta_pattern": str(llm_analysis.get("cta_pattern") or existing_analysis.get("cta_pattern") or ""),
        "risk_notes": _string_list(llm_analysis.get("risk_notes") or existing_analysis.get("risk_notes"))[:8],
        "template_strategy": str(llm_analysis.get("template_strategy") or existing_analysis.get("template_strategy") or ""),
        "factor_board": factor_board,
        "compliance_statement": str(
            llm_analysis.get("compliance_statement")
            or "Owner-uploaded source MP4 was used for internal keyframe verification; source footage is not copied."
        ),
    }


def _mark_reference_video_attached(
    existing_analysis: dict[str, Any],
    *,
    reference: ViralVideoAnalysis,
    asset: Asset,
    message: str | None = None,
) -> dict[str, Any]:
    source = dict(existing_analysis.get("source") or {})
    frame_count = len(asset.analysis.get("frame_analyses") or asset.slices or [])
    visual_verified = _asset_visual_verified(asset)
    source_mode = VERIFIED_SOURCE_MODE if visual_verified else UPLOADED_UNVERIFIED_SOURCE_MODE
    verified_at = _iso_datetime(asset.updated_at) if visual_verified else ""
    uploaded_at = _iso_datetime(asset.created_at)
    analyzed_at = _iso_datetime(asset.updated_at)
    cover_path = _ensure_reference_cover(reference, asset, _fastmoss_metadata_from_analysis(existing_analysis))
    source.update(
        {
            "reference_id": str(reference.id),
            "source_mode": source_mode,
            "source_capability": "keyframe_verified" if visual_verified else "mp4_uploaded_unverified",
            "visual_verified": visual_verified,
            "verified_at": verified_at,
            "verified_asset_id": str(asset.id),
            "verified_asset_filename": asset.filename,
            "verified_asset_kind": asset.asset_kind,
            "verified_asset_provider_status": asset.provider_status,
            "verified_asset_created_at": uploaded_at,
            "verified_asset_updated_at": analyzed_at,
            "cover_path": cover_path,
            "local_cover_url": f"/viral-videos/{reference.id}/cover" if cover_path else source.get("local_cover_url"),
        }
    )
    return {
        **existing_analysis,
        "source": source,
        "source_mode": source_mode,
        "source_capability": "keyframe_verified" if visual_verified else "mp4_uploaded_unverified",
        "visual_verified": visual_verified,
        "verified_at": verified_at,
        "verified_asset_id": str(asset.id),
        "verified_asset_kind": asset.asset_kind,
        "verified_asset_filename": asset.filename,
        "verified_asset_created_at": uploaded_at,
        "verified_asset_updated_at": analyzed_at,
        "cover_path": cover_path or existing_analysis.get("cover_path"),
        "local_cover_url": f"/viral-videos/{reference.id}/cover" if cover_path else existing_analysis.get("local_cover_url"),
        "frame_count": frame_count,
        "video_metadata": asset.analysis.get("video_metadata") or {},
        "verified_frame_evidence": _compact_asset_frames(asset),
        "verification_message": (
            message
            or
            "Source MP4 was attached, but verified factor regeneration did not run. "
            f"Asset provider status: {asset.provider_status}. {asset.provider_message}"
        ),
    }


def _ensure_reference_cover(reference: ViralVideoAnalysis, asset: Asset, fastmoss_metadata: dict[str, Any]) -> str:
    source_path = _first_asset_frame_path(asset)
    if source_path is None:
        return ""
    video_id = _reference_video_id(reference, fastmoss_metadata) or str(reference.id)
    safe_video_id = re.sub(r"[^A-Za-z0-9_-]+", "-", video_id).strip("-") or str(reference.id)
    cover_dir = Path(get_settings().upload_dir).parent / "viral-covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    target = cover_dir / f"{safe_video_id}.jpg"
    try:
        shutil.copyfile(source_path, target)
    except OSError:
        return str(source_path)
    return str(target)


def _first_asset_frame_path(asset: Asset) -> Path | None:
    for item in asset.analysis.get("frame_analyses") or []:
        if isinstance(item, dict):
            path = _existing_file_path(item.get("frame_path"))
            if path:
                return path
    for item in asset.slices or []:
        path = _existing_file_path(item.source_frame_path)
        if path:
            return path
    return None


def _existing_file_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.exists() and path.is_file():
        return path
    return None


def _replace_reference_factors(source: str, factor_board: list[dict[str, Any]], db: Session) -> None:
    db.execute(delete(ViralFactor).where(ViralFactor.source == source))
    for factor in factor_board:
        db.add(
            ViralFactor(
                factor_key=factor["factor_key"],
                name=str(factor.get("name") or "Verified viral factor")[:160],
                category=str(factor.get("category") or "hook")[:80],
                source=source,
                description=str(factor.get("reason") or "")[:2000],
                metadata_payload=factor,
            )
        )


def _normalize_storyboard(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for index, item in enumerate(value[:6], start=1):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "shot_id": str(item.get("shot_id") or f"shot-{index}"),
                "beat": str(item.get("beat") or f"Shot {index}"),
                "duration": _clamp_int(item.get("duration"), 1, 12, 3),
                "purpose": str(item.get("purpose") or ""),
            }
        )
    return normalized


def _extract_video_items(response_body: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    data = response_body.get("data") or {}
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)], None
    if not isinstance(data, dict):
        return [], None
    raw_items = data.get("list") or data.get("items") or data.get("records") or []
    raw_total = data.get("total") or data.get("total_count")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    return items, _to_int(raw_total, None) if raw_total is not None else None


def _fastmoss_filter(payload: FastMossVideoImportCreate) -> dict[str, Any]:
    filter_payload: dict[str, Any] = {
        "region": payload.region,
        "is_ecommerce": 1,
    }
    if payload.product_category_id is not None:
        filter_payload["product_category_id"] = payload.product_category_id
    if payload.creator_category_id is not None:
        filter_payload["creator_category_id"] = payload.creator_category_id
    return filter_payload


def _parse_order_by(value: str) -> tuple[str, str]:
    normalized = re.sub(r"[:_]+", " ", value.strip().lower())
    parts = [part for part in normalized.split() if part]
    field = parts[0] if parts else "play_count"
    order = parts[1] if len(parts) > 1 else "desc"
    if field not in FASTMOSS_ORDER_FIELDS:
        field = "play_count"
    if order not in {"asc", "desc"}:
        order = "desc"
    return field, order


def _safe_request_payload(payload: FastMossVideoImportCreate) -> dict[str, Any]:
    return {
        "keywords": payload.keywords,
        "region": payload.region,
        "product_category_id": payload.product_category_id,
        "creator_category_id": payload.creator_category_id,
        "order_by": payload.order_by,
        "pagesize": payload.pagesize,
        "page": payload.page,
    }


def _is_duplicate_video(video_id: str, source_url: str, db: Session) -> bool:
    if source_url:
        existing_url = db.scalar(select(ViralVideoAnalysis.id).where(ViralVideoAnalysis.source_url == source_url).limit(1))
        if existing_url:
            return True
    existing_factor = db.scalar(select(ViralFactor.id).where(ViralFactor.source == f"external:fastmoss:{video_id}").limit(1))
    return bool(existing_factor)


def _fastmoss_metadata(video: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": str(video.get("video_id") or video.get("id") or ""),
        "video_url": str(video.get("video_url") or ""),
        "desc": str(video.get("desc") or ""),
        "region": str(video.get("region") or ""),
        "play_count": _to_int(video.get("play_count"), 0),
        "digg_count": _to_int(video.get("digg_count"), 0),
        "share_count": _to_int(video.get("share_count"), 0),
        "comment_count": _to_int(video.get("comment_count"), 0),
        "units_sold": _to_int(video.get("units_sold"), 0),
        "gmv": video.get("gmv"),
        "creator": video.get("creator") if isinstance(video.get("creator"), dict) else {},
        "product_info": video.get("product_info") if isinstance(video.get("product_info"), list) else [],
        "cover": str(video.get("cover") or ""),
        "publish_time": video.get("publish_time"),
    }


def _compact_video_for_llm(video: dict[str, Any]) -> dict[str, Any]:
    product_info = video.get("product_info") if isinstance(video.get("product_info"), list) else []
    return {
        "video_id": str(video.get("video_id") or video.get("id") or ""),
        "description": str(video.get("desc") or "")[:1800],
        "region": video.get("region"),
        "duration": video.get("duration"),
        "publish_time": video.get("publish_time"),
        "is_ad": video.get("is_ad"),
        "is_ecommerce": video.get("is_ecommerce"),
        "metrics": _video_metrics(video),
        "creator": _compact_creator(video.get("creator")),
        "product_info": [_compact_product(item) for item in product_info[:3] if isinstance(item, dict)],
        "cover": video.get("cover"),
        "video_url": video.get("video_url"),
        "source_statement": FASTMOSS_SOURCE_STATEMENT,
    }


def _compact_creator(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "uid",
        "unique_id",
        "nickname",
        "follower_count",
        "following_count",
        "heart_count",
        "video_count",
        "region",
        "category",
    }
    return {key: value.get(key) for key in allowed if key in value}


def _compact_product(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "product_id",
        "title",
        "product_title",
        "name",
        "category",
        "category_name",
        "price",
        "sales",
        "units_sold",
        "gmv",
        "currency",
        "shop_name",
    }
    return {key: value.get(key) for key in allowed if key in value}


def _video_metrics(video: dict[str, Any]) -> dict[str, Any]:
    return {
        "views": _to_int(video.get("play_count"), 0),
        "likes": _to_int(video.get("digg_count"), 0),
        "comments": _to_int(video.get("comment_count"), 0),
        "shares": _to_int(video.get("share_count"), 0),
        "units_sold": _to_int(video.get("units_sold"), 0),
        "gmv": video.get("gmv"),
    }


def _video_title(video: dict[str, Any]) -> str:
    desc = str(video.get("desc") or "").strip()
    if desc:
        return _clip(re.sub(r"\s+", " ", desc), 120)
    product_type = _product_type(video)
    if product_type:
        return _clip(f"FastMoss {product_type} video", 120)
    video_id = str(video.get("video_id") or video.get("id") or "").strip()
    return f"FastMoss video {video_id[:12] or 'reference'}"


def _video_category(video: dict[str, Any], payload: FastMossVideoImportCreate) -> str:
    product_info = video.get("product_info") if isinstance(video.get("product_info"), list) else []
    for product in product_info:
        if not isinstance(product, dict):
            continue
        for key in ("category_name", "category", "product_category_name"):
            value = str(product.get(key) or "").strip()
            if value:
                return _clip(value.lower(), 120)
    if payload.product_category_id:
        return f"fastmoss-category-{payload.product_category_id}"
    return "tiktok-shop"


def _product_type(video: dict[str, Any]) -> str:
    product_info = video.get("product_info") if isinstance(video.get("product_info"), list) else []
    for product in product_info:
        if not isinstance(product, dict):
            continue
        for key in ("title", "product_title", "name"):
            value = str(product.get(key) or "").strip()
            if value:
                return _clip(value, 160)
    return ""


def _product_type_from_metadata(metadata: dict[str, Any]) -> str:
    for product in metadata.get("product_info") or []:
        if not isinstance(product, dict):
            continue
        for key in ("title", "product_title", "name"):
            value = str(product.get(key) or "").strip()
            if value:
                return _clip(value, 160)
    return ""


def _video_content_type(filename: str, content_type: str) -> str:
    value = str(content_type or "").strip().lower()
    if value.startswith("video/"):
        return value
    lowered_name = filename.lower()
    if lowered_name.endswith(".mp4"):
        return "video/mp4"
    if lowered_name.endswith(".mov"):
        return "video/quicktime"
    if lowered_name.endswith(".webm"):
        return "video/webm"
    return value or "application/octet-stream"


def _asset_visual_verified(asset: Asset) -> bool:
    frame_count = len(asset.analysis.get("frame_analyses") or asset.slices or [])
    return asset.content_type.startswith("video/") and asset.analysis_status == "analyzed" and asset.provider_status == "configured" and frame_count > 0


def _fastmoss_metadata_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    source = analysis.get("source") if isinstance(analysis.get("source"), dict) else {}
    fastmoss = source.get("fastmoss") or analysis.get("fastmoss") or {}
    return dict(fastmoss) if isinstance(fastmoss, dict) else {}


def _reference_video_id(reference: ViralVideoAnalysis, fastmoss_metadata: dict[str, Any]) -> str:
    video_id = str(fastmoss_metadata.get("video_id") or "").strip()
    if video_id:
        return video_id
    match = re.search(r"/video/(\d+)", reference.source_url or "")
    if match:
        return match.group(1)
    return str(reference.id)


def _factor_source(video_id: str, reference_id: UUID) -> str:
    if re.fullmatch(r"\d{6,}", video_id):
        return f"external:fastmoss:{video_id}"
    return f"external:verified_reference:{reference_id}"


def _iso_datetime(value: Any) -> str:
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _factor_evidence_type(category: str, raw: dict[str, Any], visual_verified: bool) -> str:
    explicit = str(raw.get("evidence_type") or "").strip()
    if explicit:
        return _clip(explicit, 120)
    if visual_verified and category in {"hook", "proof", "scene", "trust", "visual", "cta", "risk"}:
        return "verified_keyframe_evidence"
    if category in {"proof", "trust"}:
        return "fastmoss_metric"
    if category in {"visual", "audio"}:
        return "llm_inference_from_structured_data"
    return "fastmoss_text"


def _compact_reference_for_llm(reference: ViralVideoAnalysis) -> dict[str, Any]:
    analysis = reference.analysis or {}
    return {
        "reference_id": str(reference.id),
        "title": reference.title,
        "source_url": reference.source_url,
        "category": reference.category,
        "source_statement": reference.source_statement,
        "source": analysis.get("source") if isinstance(analysis.get("source"), dict) else {},
        "source_mode": analysis.get("source_mode"),
        "existing_factor_summary": [
            {
                "category": item.get("category"),
                "name": item.get("name"),
                "reason": item.get("reason"),
            }
            for item in (analysis.get("factor_board") or [])
            if isinstance(item, dict)
        ][:8],
    }


def _compact_asset_for_llm(asset: Asset) -> dict[str, Any]:
    return {
        "asset_id": str(asset.id),
        "filename": asset.filename,
        "asset_kind": asset.asset_kind,
        "content_type": asset.content_type,
        "analysis_status": asset.analysis_status,
        "provider_status": asset.provider_status,
        "provider_message": asset.provider_message,
        "summary": asset.analysis.get("summary"),
        "retrieval_text": asset.analysis.get("retrieval_text"),
        "video_metadata": asset.analysis.get("video_metadata") or {},
        "frames": _compact_asset_frames(asset),
    }


def _compact_asset_frames(asset: Asset) -> list[dict[str, Any]]:
    frames = []
    raw_frames = asset.analysis.get("frame_analyses") or []
    if isinstance(raw_frames, list):
        for item in raw_frames[:8]:
            if not isinstance(item, dict):
                continue
            analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
            frames.append(
                {
                    "frame_index": item.get("frame_index"),
                    "frame_path": item.get("frame_path"),
                    "summary": analysis.get("summary"),
                    "product_subject": analysis.get("product_subject"),
                    "visible_details": analysis.get("visible_details"),
                    "usage_scenes": analysis.get("usage_scenes"),
                    "risk_tags": analysis.get("risk_tags"),
                }
            )
    if frames:
        return frames
    return [
        {
            "slice_id": str(item.id),
            "order_index": item.order_index,
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "summary": item.summary,
            "usable_for": item.usable_for,
            "source_frame_path": item.source_frame_path,
        }
        for item in list(asset.slices or [])[:8]
    ]


def _import_result(
    *,
    status: str,
    provider_status: str,
    provider_message: str,
    request_payload: dict[str, Any],
    imported_count: int = 0,
    skipped_count: int = 0,
    failed_count: int = 0,
    factor_count: int = 0,
    items: list[dict[str, Any]] | None = None,
    raw_total: int | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary or provider_message,
        "provider_status": provider_status,
        "provider_message": provider_message,
        "request": request_payload,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "factor_count": factor_count,
        "items": items or [],
        "raw_total": raw_total,
    }


def _provider_error_message(exc: FastMossProviderError) -> str:
    parts = [str(exc)]
    if exc.code is not None:
        parts.append(f"code={exc.code}")
    if exc.request_id:
        parts.append(f"request_id={exc.request_id}")
    return "; ".join(parts)


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def _ark_base_url(value: str | None) -> str:
    base = (value or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    if "/api/v3" not in base:
        return f"{base}/api/v3"
    return base


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    settings = get_settings()
    for secret in (
        settings.volcengine_api_key,
        settings.seedance_api_key,
        settings.fastmoss_api_key,
        settings.fastmoss_client_id,
        settings.fastmoss_client_secret,
        _TOKEN_CACHE.get("access_token"),
        _TOKEN_CACHE.get("refresh_token"),
    ):
        if secret:
            message = message.replace(str(secret), "[redacted]")
    message = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]", message)
    return message[:800]


def _safe_response_text(response: httpx.Response) -> str:
    return _safe_error(RuntimeError(response.text[:600]))


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Provider response did not contain a JSON object.") from None
        parsed = json.loads(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", match.group(0)))
    if not isinstance(parsed, dict):
        raise ValueError("Provider response JSON was not an object.")
    return parsed


def _provider_retry_delay_seconds(exc: Exception, attempt: int) -> int:
    message = str(exc)
    if "EndpointTPMExceeded" in message or "RateLimitExceeded" in message or "HTTP 429" in message:
        return 45 if attempt == 1 else 65
    return attempt


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _linked_shot_ids(value: Any) -> list[str]:
    shot_ids = _string_list(value)
    return shot_ids[:6] if shot_ids else ["shot-1"]


def _to_int(value: Any, fallback: int | None = 0) -> int | None:
    try:
        if value is None or value == "":
            return fallback
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return fallback


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    parsed = _to_int(value, fallback)
    if parsed is None:
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "..."
