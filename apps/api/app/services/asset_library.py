from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Asset, AssetCollection, AssetEmbedding, AssetSlice, AssetTag
from app.schemas import AssetCollectionCreate, AssetCollectionUpdate, AssetCreate


USAGE_BUCKETS = ["hook", "proof", "detail", "usage", "cta"]


class AssetProviderError(RuntimeError):
    pass


def create_collection(payload: AssetCollectionCreate, db: Session) -> AssetCollection:
    collection = AssetCollection(
        product_name=payload.product_name,
        category=payload.category,
        description=payload.description,
        usage_notes=payload.usage_notes,
        status="pending",
        summary="No assets have been analyzed yet.",
        coverage={},
        tags=[],
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return get_collection(collection.id, db)


def list_collections(db: Session) -> list[AssetCollection]:
    return list(
        db.scalars(
            select(AssetCollection)
            .options(
                selectinload(AssetCollection.assets).selectinload(Asset.slices),
                selectinload(AssetCollection.assets).selectinload(Asset.tags),
                selectinload(AssetCollection.assets).selectinload(Asset.embedding),
            )
            .order_by(AssetCollection.created_at.desc())
        ).all()
    )


def get_collection(collection_id: UUID, db: Session) -> AssetCollection:
    collection = db.scalar(
        select(AssetCollection)
        .where(AssetCollection.id == collection_id)
        .options(
            selectinload(AssetCollection.assets).selectinload(Asset.slices),
            selectinload(AssetCollection.assets).selectinload(Asset.tags),
            selectinload(AssetCollection.assets).selectinload(Asset.embedding),
        )
    )
    if collection is None:
        raise LookupError("Asset collection not found")
    return collection


def update_collection(collection_id: UUID, payload: AssetCollectionUpdate, db: Session) -> AssetCollection:
    collection = get_collection(collection_id, db)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            setattr(collection, key, value)
    db.add(collection)
    db.commit()
    _refresh_collection_summary(collection.id, db)
    return get_collection(collection.id, db)


def create_asset(
    payload: AssetCreate,
    db: Session,
    *,
    content: bytes | None = None,
) -> Asset:
    return _create_asset(payload, db, content=content)


def add_asset_to_collection(
    collection_id: UUID,
    payload: AssetCreate,
    db: Session,
    *,
    content: bytes | None = None,
) -> Asset:
    get_collection(collection_id, db)
    payload = payload.model_copy(update={"collection_id": collection_id})
    return _create_asset(payload, db, content=content)


def _create_asset(
    payload: AssetCreate,
    db: Session,
    *,
    content: bytes | None = None,
) -> Asset:
    filename = _safe_filename(payload.filename)
    storage_path = ""
    size_bytes = len(content or b"")
    if content:
        root = _asset_root()
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{hashlib.sha1(content).hexdigest()[:10]}-{filename}"
        path.write_bytes(content)
        storage_path = str(path)

    asset = Asset(
        collection_id=payload.collection_id,
        filename=filename,
        content_type=payload.content_type,
        asset_kind=payload.asset_kind or _asset_kind(payload.content_type),
        category=payload.category,
        size_bytes=size_bytes,
        storage_path=storage_path,
        description=payload.description,
        analysis={},
        analysis_status="pending",
        provider_status="missing_config",
        provider_message="Asset analysis has not run yet.",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    analyzed = analyze_asset(asset.id, db)
    if analyzed.collection_id:
        _refresh_collection_summary(analyzed.collection_id, db)
    return analyzed


def list_assets(db: Session) -> list[Asset]:
    return list(
        db.scalars(
            select(Asset)
            .options(selectinload(Asset.slices), selectinload(Asset.tags), selectinload(Asset.embedding))
            .order_by(Asset.created_at.desc())
        ).all()
    )


def get_asset(asset_id: UUID, db: Session) -> Asset:
    asset = db.scalar(
        select(Asset)
        .where(Asset.id == asset_id)
        .options(selectinload(Asset.slices), selectinload(Asset.tags), selectinload(Asset.embedding))
    )
    if asset is None:
        raise LookupError("Asset not found")
    return asset


def update_asset(asset_id: UUID, updates: dict[str, Any], db: Session) -> Asset:
    asset = get_asset(asset_id, db)
    for key in ["category", "description", "analysis_status"]:
        if key in updates and updates[key] is not None:
            setattr(asset, key, updates[key])
    db.add(asset)
    db.commit()
    if asset.collection_id:
        _refresh_collection_summary(asset.collection_id, db)
    return get_asset(asset.id, db)


def update_asset_slice(slice_id: UUID, updates: dict[str, Any], db: Session) -> AssetSlice:
    item = db.get(AssetSlice, slice_id)
    if item is None:
        raise LookupError("Asset slice not found")
    for key in ["summary", "usable_for", "is_pinned"]:
        if key in updates and updates[key] is not None:
            setattr(item, key, updates[key])
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def analyze_asset(asset_id: UUID, db: Session) -> Asset:
    asset = get_asset(asset_id, db)
    _clear_analysis_children(asset, db)
    asset.analysis_status = "analyzing"
    db.add(asset)
    db.commit()

    try:
        profile = _analyze_asset_profile(asset)
    except Exception as exc:
        asset.analysis_status = "failed"
        asset.provider_status = "error"
        asset.provider_message = _safe_error(exc)
        asset.analysis = {
            "summary": f"Provider failed while analyzing {asset.filename}.",
            "failure_reason": asset.provider_message,
            "retrieval_text": "",
        }
        db.add(asset)
        db.commit()
        if asset.collection_id:
            _refresh_collection_summary(asset.collection_id, db)
        return get_asset(asset.id, db)

    asset.analysis = profile
    asset.analysis_status = "analyzed"
    asset.provider_status = str(profile.get("provider_status") or "missing_config")
    asset.provider_message = str(profile.get("provider_message") or "")
    _write_analysis_children(asset, profile, db)
    db.add(asset)
    db.commit()
    if asset.collection_id:
        _refresh_collection_summary(asset.collection_id, db)
    db.expire_all()
    return get_asset(asset.id, db)


def search_assets(
    db: Session,
    query: str = "",
    tag: str = "",
    category: str = "",
    asset_kind: str = "",
    mode: str = "hybrid",
    limit: int = 12,
    include_slices: bool = True,
    collection_id: UUID | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(Asset)
        .options(selectinload(Asset.slices), selectinload(Asset.tags), selectinload(Asset.embedding), selectinload(Asset.collection))
        .order_by(Asset.created_at.desc())
    )
    if collection_id:
        statement = statement.where(Asset.collection_id == collection_id)
    if category:
        statement = statement.where(Asset.category.ilike(f"%{category.lower()}%"))
    if asset_kind:
        statement = statement.where(Asset.asset_kind == asset_kind)
    assets = list(db.scalars(statement).all())
    results = [
        _asset_search_result(asset, query=query, tag=tag, mode=mode, include_slices=include_slices)
        for asset in assets
        if asset.analysis_status == "analyzed"
    ]
    filtered = [
        result
        for result in results
        if result["score"] > 0 or not query.strip() and not tag.strip()
    ]
    return sorted(filtered, key=lambda item: item["score"], reverse=True)[: max(1, min(limit, 50))]


def asset_collection_context_for_generation(collection_id: UUID | None, db: Session) -> dict[str, Any] | None:
    if not collection_id:
        return None
    try:
        collection = get_collection(collection_id, db)
    except LookupError:
        return None
    return _collection_context(collection)


def asset_context_for_generation(asset_ids: list[UUID], db: Session) -> list[dict[str, Any]]:
    context = []
    for asset_id in asset_ids:
        try:
            asset = get_asset(asset_id, db)
        except LookupError:
            continue
        context.append(_asset_context(asset))
    return context


def asset_slice_context_for_generation(asset_slice_ids: list[UUID], db: Session) -> list[dict[str, Any]]:
    if not asset_slice_ids:
        return []
    rows = db.scalars(
        select(AssetSlice)
        .where(AssetSlice.id.in_(asset_slice_ids))
        .options(selectinload(AssetSlice.asset))
        .order_by(AssetSlice.order_index)
    ).all()
    context = []
    for item in rows:
        context.append(
            {
                "slice_id": str(item.id),
                "asset_id": str(item.asset_id),
                "collection_id": str(item.asset.collection_id) if item.asset and item.asset.collection_id else None,
                "filename": item.asset.filename if item.asset else "asset",
                "asset_kind": item.asset.asset_kind if item.asset else "reference",
                "summary": item.summary,
                "features": item.features,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "usable_for": item.usable_for or (item.features.get("usable_for") if isinstance(item.features, dict) else None),
                "is_pinned": item.is_pinned,
                "source_frame_path": item.source_frame_path,
            }
        )
    return context


def asset_retrieval_for_generation(request: dict[str, Any], db: Session) -> dict[str, Any]:
    query = " ".join(
        [
            str(request.get("product_name") or ""),
            str(request.get("category") or ""),
            " ".join(str(point) for point in request.get("selling_points", [])),
            str(request.get("material_notes") or ""),
            str(request.get("visual_style") or ""),
        ]
    ).strip()
    collection_id = _uuid_or_none(request.get("asset_collection_id"))
    selected_collection = asset_collection_context_for_generation(collection_id, db)
    selected_assets = asset_context_for_generation([UUID(str(item)) for item in request.get("asset_ids", [])], db)
    selected_slices = asset_slice_context_for_generation([UUID(str(item)) for item in request.get("asset_slice_ids", [])], db)
    auto_results = (
        search_assets(
            db,
            query=query,
            category=str(request.get("category") or ""),
            mode="hybrid",
            limit=6,
            include_slices=True,
            collection_id=collection_id,
        )
        if request.get("auto_retrieve_assets", True)
        else []
    )
    auto_assets = [_asset_context_from_result(result) for result in auto_results]
    return {
        "asset_query": query,
        "selected_collection": selected_collection,
        "selected_assets": selected_assets,
        "selected_slices": selected_slices,
        "auto_asset_results": [_public_search_result(result) for result in auto_results],
        "auto_assets": auto_assets,
        "evidence_summary": _asset_evidence_summary(selected_collection, selected_assets, selected_slices, auto_results),
    }


def _analyze_asset_profile(asset: Asset) -> dict[str, Any]:
    if not _vision_provider_configured():
        profile = _mock_asset_profile(asset)
        return {
            **profile,
            "execution_mode": "mock_missing_config",
            "provider_status": "missing_config",
            "provider_message": "Volcengine multimodal understanding is not connected; placeholder asset analysis was generated.",
            "provider": "mock_asset_understanding_provider",
            "model": "mock-multimodal-understanding-v1",
        }
    if asset.content_type.startswith("image/"):
        return _analyze_image_asset(asset)
    if asset.content_type.startswith("video/"):
        return _analyze_video_asset(asset)
    return _analyze_reference_asset(asset)


def _analyze_image_asset(asset: Asset) -> dict[str, Any]:
    if not asset.storage_path or not Path(asset.storage_path).exists():
        raise AssetProviderError("Image file is missing from storage.")
    content = Path(asset.storage_path).read_bytes()
    prompt = _asset_understanding_prompt(asset)
    provider_result = _call_vision_json(prompt, asset.content_type, content)
    profile = _normalize_profile(provider_result, asset)
    return {
        **profile,
        "slices": _image_region_slices(profile),
        "execution_mode": "real",
        "provider_status": "configured",
        "provider_message": "Volcengine multimodal endpoint analyzed the uploaded image.",
        "provider": "volcengine_multimodal_understanding",
        "model": _vision_model(),
    }


def _analyze_video_asset(asset: Asset) -> dict[str, Any]:
    if not asset.storage_path or not Path(asset.storage_path).exists():
        raise AssetProviderError("Video file is missing from storage.")
    metadata = _probe_video(Path(asset.storage_path))
    frame_paths = _extract_video_frames(Path(asset.storage_path), asset.id, metadata.get("duration_seconds", 12))
    frame_profiles = []
    for index, frame_path in enumerate(frame_paths, start=1):
        content = frame_path.read_bytes()
        prompt = _video_frame_prompt(asset, index, len(frame_paths), metadata)
        frame_profiles.append(
            {
                "frame_index": index,
                "frame_path": str(frame_path),
                "analysis": _normalize_profile(_call_vision_json(prompt, "image/jpeg", content), asset),
            }
        )
    summary = _summarize_video_frames(asset, metadata, frame_profiles)
    return {
        **summary,
        "video_metadata": metadata,
        "frame_analyses": frame_profiles,
        "slices": _video_slices(metadata, frame_profiles),
        "execution_mode": "real",
        "provider_status": "configured",
        "provider_message": "FFmpeg extracted keyframes and Volcengine multimodal endpoint analyzed each frame.",
        "provider": "ffmpeg_keyframes + volcengine_multimodal_understanding",
        "model": _vision_model(),
    }


def _analyze_reference_asset(asset: Asset) -> dict[str, Any]:
    text = " ".join([asset.filename, asset.category, asset.description])
    provider_result = _call_text_json(
        "Analyze this text-only reference material for an ecommerce AIGC video asset. "
        "Return compact JSON with product_subject, category, colors, materials, visible_details, "
        "scale_cues, usage_scenes, risk_tags, recommended_usage, retrieval_text, summary.\n"
        f"Reference: {text}"
    )
    profile = _normalize_profile(provider_result, asset)
    return {
        **profile,
        "slices": _image_region_slices(profile),
        "execution_mode": "real",
        "provider_status": "configured",
        "provider_message": "Volcengine text endpoint analyzed the reference material.",
        "provider": "volcengine_text_asset_understanding",
        "model": _vision_model(),
    }


def _write_analysis_children(asset: Asset, profile: dict[str, Any], db: Session) -> None:
    tags = _profile_tags(profile)
    for index, tag in enumerate(tags, start=1):
        db.add(
            AssetTag(
                asset_id=asset.id,
                name=tag,
                tag_type="product_signal" if index <= 5 else "keyword",
                confidence=max(62, 96 - index * 3),
                source="provider" if profile.get("provider_status") == "configured" else "system",
            )
        )
    for index, item in enumerate(profile.get("slices", []), start=1):
        usable_for = str(item.get("usable_for") or item.get("features", {}).get("usable_for") or USAGE_BUCKETS[(index - 1) % len(USAGE_BUCKETS)])
        db.add(
            AssetSlice(
                asset_id=asset.id,
                order_index=index,
                slice_type=str(item.get("slice_type") or ("video_slice" if asset.content_type.startswith("video/") else "image_region")),
                start_seconds=int(item.get("start_seconds") or 0),
                end_seconds=int(item.get("end_seconds") or 0),
                summary=str(item.get("summary") or ""),
                features=dict(item.get("features") or {}),
                usable_for=usable_for,
                source_frame_path=str(item.get("source_frame_path") or ""),
                is_pinned=bool(item.get("is_pinned") or False),
            )
        )
    retrieval_text = str(profile.get("retrieval_text") or profile.get("summary") or asset.description)
    db.add(
        AssetEmbedding(
            asset_id=asset.id,
            model="pseudo-text-embedding-from-multimodal-profile-v1",
            vector=_pseudo_embedding(asset.filename, asset.description, asset.category, retrieval_text),
        )
    )


def _clear_analysis_children(asset: Asset, db: Session) -> None:
    for child in [*asset.slices, *asset.tags]:
        db.delete(child)
    if asset.embedding:
        db.delete(asset.embedding)
    db.flush()


def _refresh_collection_summary(collection_id: UUID, db: Session) -> None:
    collection = get_collection(collection_id, db)
    assets = list(collection.assets)
    analyzed = [asset for asset in assets if asset.analysis_status == "analyzed"]
    failed = [asset for asset in assets if asset.analysis_status == "failed"]
    pending = [asset for asset in assets if asset.analysis_status in {"pending", "analyzing"}]
    tags = sorted({tag.name for asset in assets for tag in asset.tags})[:18]
    coverage = _collection_coverage(analyzed)
    if not assets:
        status = "pending"
        summary = "No private assets have been uploaded yet."
    elif failed and not analyzed:
        status = "failed"
        summary = f"{len(failed)} assets failed analysis. Uploads are preserved for retry."
    elif pending:
        status = "analyzing"
        summary = f"{len(analyzed)} of {len(assets)} assets analyzed for private product evidence."
    elif failed:
        status = "failed"
        summary = f"{len(analyzed)} assets analyzed, {len(failed)} failed. Usable evidence remains available."
    else:
        status = "analyzed"
        summary = _collection_summary_text(collection, analyzed)
    collection.status = status
    collection.summary = summary
    collection.coverage = coverage
    collection.tags = tags
    db.add(collection)
    db.commit()


def _collection_coverage(assets: list[Asset]) -> dict[str, Any]:
    text = " ".join(_asset_text(asset) for asset in assets)
    return {
        "appearance": bool(re.search(r"color|finish|appearance|shape|subject|product", text)),
        "detail": bool(re.search(r"detail|close|texture|material|feature", text)),
        "scale": bool(re.search(r"scale|hand|desk|bag|size", text)),
        "usage": bool(re.search(r"usage|scene|daily|commute|office|kitchen|travel", text)),
        "risk": bool(re.search(r"risk|claim|brand|safety|conflict", text)),
        "asset_count": len(assets),
        "slice_count": sum(len(asset.slices) for asset in assets),
    }


def _collection_summary_text(collection: AssetCollection, assets: list[Asset]) -> str:
    subjects = [str(asset.analysis.get("product_subject") or "") for asset in assets if isinstance(asset.analysis, dict)]
    scenes = [
        str(scene)
        for asset in assets
        if isinstance(asset.analysis, dict)
        for scene in asset.analysis.get("usage_scenes", [])[:2]
    ]
    subject = next((item for item in subjects if item), collection.product_name)
    scene_text = ", ".join(dict.fromkeys(scenes).keys()) or "core product scenes"
    return f"{collection.product_name} private evidence covers {subject}, {scene_text}, and {sum(len(asset.slices) for asset in assets)} callable slices."


def _asset_search_result(asset: Asset, *, query: str, tag: str, mode: str, include_slices: bool) -> dict[str, Any]:
    mode = mode if mode in {"keyword", "tag", "vector", "hybrid"} else "hybrid"
    query_tokens = _tokens(query)
    tag_lower = tag.lower().strip()
    asset_tags = [item.name for item in asset.tags]
    text = _asset_text(asset)
    keyword_score = _keyword_score(query_tokens, text)
    tag_score = 1.0 if tag_lower and any(item.lower() == tag_lower for item in asset_tags) else 0.0
    if not tag_lower and mode == "tag":
        tag_score = 0.2 if asset_tags else 0.0
    vector_score = _cosine_similarity(_pseudo_embedding(query or asset.category, tag or asset.category), asset.embedding.vector if asset.embedding else [])
    if mode == "keyword":
        score = keyword_score
    elif mode == "tag":
        score = tag_score
    elif mode == "vector":
        score = vector_score
    else:
        score = keyword_score * 0.45 + tag_score * 0.25 + vector_score * 0.3
    matched_tags = [
        name
        for name in asset_tags
        if (tag_lower and name.lower() == tag_lower) or any(token in name.lower() for token in query_tokens)
    ][:8]
    matched_slices = _matched_slices(asset, query_tokens, include_slices=include_slices)
    usable_for = sorted({item.get("usable_for") for item in matched_slices if item.get("usable_for")} or {item.usable_for for item in asset.slices if item.usable_for})
    reason_bits = []
    if keyword_score:
        reason_bits.append("keyword match")
    if tag_score:
        reason_bits.append("tag match")
    if vector_score > 0.2:
        reason_bits.append("vector-style similarity")
    return {
        "collection": _collection_summary(asset.collection) if asset.collection else None,
        "asset": asset,
        "score": round(max(0, min(score, 1.0)), 4),
        "retrieval_mode": mode,
        "matched_tags": matched_tags,
        "matched_slices": matched_slices,
        "usable_for": [item for item in usable_for if item and item != "None"][:6],
        "reason": ", ".join(reason_bits) or "recent analyzed asset available for selection",
    }


def _matched_slices(asset: Asset, query_tokens: list[str], *, include_slices: bool) -> list[dict[str, Any]]:
    if not include_slices:
        return []
    scored = []
    for item in asset.slices:
        text = " ".join([item.summary, item.usable_for, " ".join(str(value) for value in item.features.values()) if isinstance(item.features, dict) else ""])
        score = _keyword_score(query_tokens, text) if query_tokens else (0.45 if item.is_pinned else 0.25)
        if score <= 0 and query_tokens:
            continue
        scored.append(
            {
                "slice_id": str(item.id),
                "asset_id": str(item.asset_id),
                "collection_id": str(asset.collection_id) if asset.collection_id else None,
                "order_index": item.order_index,
                "slice_type": item.slice_type,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "summary": item.summary,
                "features": item.features,
                "usable_for": item.usable_for,
                "source_frame_path": item.source_frame_path,
                "is_pinned": item.is_pinned,
                "score": round(score, 4),
                "reason": "slice text matched query" if query_tokens else "representative slice",
            }
        )
    return sorted(scored, key=lambda entry: entry["score"], reverse=True)[:4]


def _asset_context_from_result(result: dict[str, Any]) -> dict[str, Any]:
    asset = result["asset"]
    return {
        **_asset_context(asset),
        "matched_slices": result.get("matched_slices", []),
        "retrieval_score": result.get("score"),
        "retrieval_reason": result.get("reason"),
    }


def _asset_context(asset: Asset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "collection_id": str(asset.collection_id) if asset.collection_id else None,
        "filename": asset.filename,
        "content_type": asset.content_type,
        "asset_kind": asset.asset_kind,
        "category": asset.category,
        "description": asset.description,
        "summary": asset.analysis.get("summary") if isinstance(asset.analysis, dict) else "",
        "retrieval_text": asset.analysis.get("retrieval_text") if isinstance(asset.analysis, dict) else "",
        "provider_status": asset.provider_status,
        "tags": [tag.name for tag in asset.tags],
        "slices": [
            {
                "slice_id": str(item.id),
                "summary": item.summary,
                "features": item.features,
                "usable_for": item.usable_for,
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "is_pinned": item.is_pinned,
            }
            for item in asset.slices
        ],
    }


def _collection_context(collection: AssetCollection) -> dict[str, Any]:
    return {
        **_collection_summary(collection),
        "description": collection.description,
        "usage_notes": collection.usage_notes,
        "summary": collection.summary,
        "coverage": collection.coverage,
        "tags": collection.tags,
        "assets": [_asset_context(asset) for asset in collection.assets if asset.analysis_status == "analyzed"][:8],
    }


def _collection_summary(collection: AssetCollection) -> dict[str, Any]:
    return {
        "collection_id": str(collection.id),
        "product_name": collection.product_name,
        "category": collection.category,
        "status": collection.status,
        "asset_count": len(collection.assets),
    }


def _public_search_result(result: dict[str, Any]) -> dict[str, Any]:
    asset = result["asset"]
    return {
        "collection": result.get("collection"),
        "collection_id": str(asset.collection_id) if asset.collection_id else None,
        "asset_id": str(asset.id),
        "filename": asset.filename,
        "category": asset.category,
        "asset_kind": asset.asset_kind,
        "score": result["score"],
        "matched_tags": result["matched_tags"],
        "matched_slices": result["matched_slices"],
        "usable_for": result["usable_for"],
        "reason": result["reason"],
    }


def _asset_evidence_summary(
    selected_collection: dict[str, Any] | None,
    selected_assets: list[dict[str, Any]],
    selected_slices: list[dict[str, Any]],
    auto_results: list[dict[str, Any]],
) -> str:
    parts = []
    if selected_collection:
        parts.append(f"collection {selected_collection.get('product_name')} selected")
    if selected_assets:
        parts.append(f"{len(selected_assets)} selected assets")
    if selected_slices:
        parts.append(f"{len(selected_slices)} pinned slices")
    if auto_results:
        parts.append(f"{len(auto_results)} auto-retrieved assets")
    return ", ".join(parts) if parts else "No saved asset evidence selected; rely on request notes and uploaded files."


def _asset_text(asset: Asset) -> str:
    values = [
        asset.filename,
        asset.description,
        asset.category,
        asset.asset_kind,
        str(asset.analysis.get("summary", "")) if isinstance(asset.analysis, dict) else "",
        str(asset.analysis.get("retrieval_text", "")) if isinstance(asset.analysis, dict) else "",
        " ".join(tag.name for tag in asset.tags),
        " ".join(slice_item.summary for slice_item in asset.slices),
    ]
    return " ".join(values).lower()


def _vision_provider_configured() -> bool:
    settings = get_settings()
    return bool(settings.volcengine_api_key and (settings.volcengine_endpoint_id or settings.volcengine_text_model))


def _vision_model() -> str:
    settings = get_settings()
    return str(settings.volcengine_text_model or settings.volcengine_endpoint_id or "volcengine-multimodal-endpoint")


def _call_vision_json(prompt: str, content_type: str, content: bytes) -> dict[str, Any]:
    data_url = f"data:{content_type or 'image/jpeg'};base64,{base64.b64encode(content).decode('ascii')}"
    payload = {
        "model": _vision_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 900,
    }
    return _call_ark_json(payload, "Volcengine multimodal asset understanding")


def _call_text_json(prompt: str) -> dict[str, Any]:
    payload = {
        "model": _vision_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 700,
    }
    return _call_ark_json(payload, "Volcengine asset text understanding")


def _call_ark_json(payload: dict[str, Any], context: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.volcengine_api_key:
        raise AssetProviderError("Volcengine API key is missing.")
    headers = {"Authorization": f"Bearer {settings.volcengine_api_key}", "Content-Type": "application/json"}
    base_url = _ark_base_url(settings.volcengine_base_url)
    try:
        with httpx.Client(timeout=settings.provider_request_timeout_seconds) as client:
            response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        _raise_for_status(response, context)
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _extract_json_object(content)
    except Exception as exc:
        raise AssetProviderError(_safe_error(exc)) from exc


def _asset_understanding_prompt(asset: Asset) -> str:
    return (
        "You are analyzing private ecommerce product material for an AIGC short-video generation system. "
        "Return only compact JSON with keys: summary, product_subject, category, colors, materials, "
        "visible_details, scale_cues, usage_scenes, risk_tags, recommended_usage, retrieval_text. "
        "recommended_usage must contain 2-5 of hook, proof, detail, usage, cta. "
        f"Asset metadata: filename={asset.filename}, category={asset.category}, description={asset.description}."
    )


def _video_frame_prompt(asset: Asset, index: int, total: int, metadata: dict[str, Any]) -> str:
    return (
        "Analyze this keyframe from a private ecommerce product video. Return only compact JSON with keys: "
        "summary, product_subject, category, colors, materials, visible_details, scale_cues, usage_scenes, "
        "risk_tags, recommended_usage, retrieval_text. "
        f"Frame {index}/{total}. Video metadata: {json.dumps(metadata, ensure_ascii=False)}. "
        f"Asset metadata: filename={asset.filename}, category={asset.category}, description={asset.description}."
    )


def _summarize_video_frames(asset: Asset, metadata: dict[str, Any], frame_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    frame_summaries = [
        {
            "frame_index": frame["frame_index"],
            "summary": frame["analysis"].get("summary"),
            "recommended_usage": frame["analysis"].get("recommended_usage", []),
            "retrieval_text": frame["analysis"].get("retrieval_text"),
        }
        for frame in frame_profiles
    ]
    prompt = (
        "Summarize these private ecommerce video keyframe analyses into one asset profile. "
        "Return only compact JSON with keys: summary, product_subject, category, colors, materials, "
        "visible_details, scale_cues, usage_scenes, risk_tags, recommended_usage, retrieval_text, rhythm. "
        f"Asset: {asset.filename}, category={asset.category}. Metadata: {json.dumps(metadata, ensure_ascii=False)}. "
        f"Frames: {json.dumps(frame_summaries, ensure_ascii=False)}"
    )
    provider_result = _call_text_json(prompt)
    profile = _normalize_profile(provider_result, asset)
    profile["rhythm"] = provider_result.get("rhythm") or "keyframe-based product proof rhythm"
    return profile


def _normalize_profile(data: dict[str, Any], asset: Asset) -> dict[str, Any]:
    tokens = _tokens(" ".join([asset.filename, asset.category, asset.description, json.dumps(data, ensure_ascii=False)]))
    category = str(data.get("category") or asset.category or _infer_category(tokens, asset.content_type))
    subject = str(data.get("product_subject") or _subject(tokens, category))
    colors = _string_list(data.get("colors")) or _palette(asset.filename)
    materials = _string_list(data.get("materials")) or [_material(tokens)]
    visible_details = _string_list(data.get("visible_details")) or ["product shape", "surface finish", "usage detail"]
    scale_cues = _string_list(data.get("scale_cues")) or ["desk scale", "handheld scale"]
    usage_scenes = _string_list(data.get("usage_scenes")) or [_scene(tokens), "daily use"]
    risk_tags = _string_list(data.get("risk_tags")) or ["needs claim-safe copy"]
    recommended_usage = [item for item in _string_list(data.get("recommended_usage")) if item in USAGE_BUCKETS] or ["proof", "detail"]
    summary = str(data.get("summary") or f"{asset.filename} shows {subject} for {', '.join(usage_scenes[:2])}.")
    retrieval_text = str(
        data.get("retrieval_text")
        or " ".join([summary, subject, category, " ".join(colors), " ".join(materials), " ".join(visible_details), " ".join(usage_scenes)])
    )
    return {
        "summary": summary,
        "product_subject": subject,
        "category": category,
        "colors": colors[:6],
        "materials": materials[:6],
        "visible_details": visible_details[:8],
        "scale_cues": scale_cues[:6],
        "usage_scenes": usage_scenes[:8],
        "risk_tags": risk_tags[:6],
        "recommended_usage": recommended_usage[:5],
        "retrieval_text": retrieval_text,
        "tags": list(dict.fromkeys([category, subject, *colors, *materials, *usage_scenes, *recommended_usage]))[:16],
    }


def _image_region_slices(profile: dict[str, Any]) -> list[dict[str, Any]]:
    details = profile.get("visible_details", []) or ["product detail", "material finish", "usage cue"]
    usages = profile.get("recommended_usage", []) or ["proof", "detail", "usage"]
    slices = []
    for index, detail in enumerate(details[:4], start=1):
        usage = usages[(index - 1) % len(usages)]
        slices.append(
            {
                "slice_type": "image_region",
                "start_seconds": 0,
                "end_seconds": 0,
                "summary": f"{profile.get('product_subject', 'product')} region {index}: {detail}.",
                "usable_for": usage,
                "features": {
                    "subject": profile.get("product_subject"),
                    "category": profile.get("category"),
                    "detail": detail,
                    "colors": profile.get("colors", []),
                    "materials": profile.get("materials", []),
                    "usable_for": usage,
                },
            }
        )
    return slices or _mock_asset_profile_for_profile(profile, "image_region")


def _video_slices(metadata: dict[str, Any], frame_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    duration = max(4, int(round(float(metadata.get("duration_seconds") or 12))))
    count = max(1, len(frame_profiles))
    span = max(1, math.ceil(duration / count))
    slices = []
    for index, frame in enumerate(frame_profiles, start=1):
        analysis = frame["analysis"]
        start = min(duration - 1, (index - 1) * span)
        end = min(duration, start + span)
        usage = (analysis.get("recommended_usage") or USAGE_BUCKETS)[(index - 1) % len(analysis.get("recommended_usage") or USAGE_BUCKETS)]
        slices.append(
            {
                "slice_type": "video_slice",
                "start_seconds": start,
                "end_seconds": end,
                "summary": str(analysis.get("summary") or f"Video proof slice {index}."),
                "usable_for": usage,
                "source_frame_path": frame.get("frame_path", ""),
                "features": {
                    "subject": analysis.get("product_subject"),
                    "category": analysis.get("category"),
                    "colors": analysis.get("colors", []),
                    "materials": analysis.get("materials", []),
                    "usage_scenes": analysis.get("usage_scenes", []),
                    "usable_for": usage,
                    "frame_index": index,
                },
            }
        )
    return slices


def _probe_video(path: Path) -> dict[str, Any]:
    result = _run_tool(
        [
            _tool_path("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,codec_name",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(result or "{}")
    stream = (data.get("streams") or [{}])[0]
    duration = float((data.get("format") or {}).get("duration") or 12)
    return {
        "duration_seconds": round(duration, 2),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "codec": stream.get("codec_name"),
    }


def _extract_video_frames(path: Path, asset_id: UUID, duration: float | int) -> list[Path]:
    duration_float = max(1.0, float(duration or 12))
    count = 4 if duration_float <= 12 else 6
    frame_root = _asset_root() / "frames" / str(asset_id)
    frame_root.mkdir(parents=True, exist_ok=True)
    timestamps = [min(duration_float - 0.2, max(0.1, (index + 0.5) * duration_float / count)) for index in range(count)]
    frames = []
    for index, timestamp in enumerate(timestamps, start=1):
        output = frame_root / f"frame-{index:02d}.jpg"
        _run_tool(
            [
                _tool_path("ffmpeg"),
                "-y",
                "-ss",
                f"{timestamp:.2f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-1",
                str(output),
            ]
        )
        if output.exists() and output.stat().st_size > 0:
            frames.append(output)
    if not frames:
        raise AssetProviderError("FFmpeg did not extract any keyframes from the uploaded video.")
    return frames


def _run_tool(args: list[str]) -> str:
    try:
        completed = subprocess.run(args, check=True, capture_output=True, text=True, timeout=60)
        return completed.stdout
    except FileNotFoundError as exc:
        raise AssetProviderError(f"{Path(args[0]).name} was not found. Install FFmpeg or add D:\\tools\\ffmpeg\\bin to PATH.") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc))[:600]
        raise AssetProviderError(f"{Path(args[0]).name} failed: {message}") from exc


def _tool_path(name: str) -> str:
    candidate = Path("D:/tools/ffmpeg/bin") / f"{name}.exe"
    return str(candidate) if candidate.exists() else name


def _asset_root() -> Path:
    return Path(get_settings().upload_dir).parent / "asset-library"


def _mock_asset_profile(asset: Asset) -> dict[str, Any]:
    tokens = _tokens(" ".join([asset.filename, asset.category, asset.description]))
    category = asset.category if asset.category != "general" else _infer_category(tokens, asset.content_type)
    palette = _palette(asset.filename)
    material = _material(tokens)
    subject = _subject(tokens, category)
    scene = _scene(tokens)
    slice_count = 4 if asset.content_type.startswith("video/") else 3
    slices = []
    for index in range(slice_count):
        usage = USAGE_BUCKETS[index % len(USAGE_BUCKETS)]
        start = index * 3
        slices.append(
            {
                "slice_type": "video_slice" if asset.content_type.startswith("video/") else "image_region",
                "start_seconds": start if asset.content_type.startswith("video/") else 0,
                "end_seconds": start + 3 if asset.content_type.startswith("video/") else 0,
                "summary": f"{subject} placeholder proof moment {index + 1}: {scene}, {material}, {palette[index % len(palette)]} accent.",
                "usable_for": usage,
                "features": {
                    "subject": subject,
                    "category": category,
                    "scene": scene,
                    "material": material,
                    "color": palette[index % len(palette)],
                    "usable_for": usage,
                },
            }
        )
    tags = list(dict.fromkeys([category, subject, scene, material, *palette, *tokens[:5]]))
    return {
        "summary": f"{asset.filename} is a {category} placeholder source asset focused on {subject}, {scene}, and {material}.",
        "product_subject": subject,
        "category": category,
        "colors": palette,
        "materials": [material],
        "visible_details": ["product appearance", "material finish", "usage cue"],
        "scale_cues": ["desk scale", "handheld scale"],
        "usage_scenes": [scene, "desk setup", "commute", "quick demo"],
        "risk_tags": ["no visible brand conflict", "needs claim-safe copy"],
        "recommended_usage": ["hook", "proof", "detail"],
        "retrieval_text": f"{subject} {category} {scene} {material} {' '.join(palette)}",
        "tags": tags[:12],
        "slices": slices,
    }


def _mock_asset_profile_for_profile(profile: dict[str, Any], slice_type: str) -> list[dict[str, Any]]:
    return [
        {
            "slice_type": slice_type,
            "start_seconds": 0,
            "end_seconds": 0,
            "summary": str(profile.get("summary") or "Product evidence region."),
            "usable_for": "proof",
            "features": {"usable_for": "proof"},
        }
    ]


def _profile_tags(profile: dict[str, Any]) -> list[str]:
    values = profile.get("tags") or [
        profile.get("category"),
        profile.get("product_subject"),
        *profile.get("colors", []),
        *profile.get("materials", []),
        *profile.get("usage_scenes", []),
        *profile.get("recommended_usage", []),
    ]
    return [item for item in list(dict.fromkeys(str(value).strip().lower() for value in values if str(value).strip())) if item][:16]


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip(".-")
    return cleaned or "asset"


def _asset_kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    return "reference"


def _uuid_or_none(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _tokens(text: str) -> list[str]:
    return [item for item in re.split(r"[^A-Za-z0-9]+", text.lower()) if len(item) > 2]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;\n]+", value) if item.strip()]
    return []


def _infer_category(tokens: list[str], content_type: str) -> str:
    if any(item in tokens for item in ["bottle", "cup", "mug", "drinkware"]):
        return "drinkware"
    if any(item in tokens for item in ["serum", "cream", "beauty", "makeup"]):
        return "beauty"
    if any(item in tokens for item in ["bag", "desk", "lamp", "home"]):
        return "home"
    return "video_reference" if content_type.startswith("video/") else "commerce_asset"


def _subject(tokens: list[str], category: str) -> str:
    for candidate in ["bottle", "serum", "lamp", "bag", "cream", "mug", "organizer"]:
        if candidate in tokens:
            return candidate
    return category.replace("_", " ")


def _scene(tokens: list[str]) -> str:
    for candidate in ["desk", "commute", "gym", "kitchen", "travel", "study", "office"]:
        if candidate in tokens:
            return candidate
    return "daily use"


def _material(tokens: list[str]) -> str:
    for candidate in ["steel", "glass", "cotton", "leather", "ceramic", "matte", "soft"]:
        if candidate in tokens:
            return candidate
    return "tactile finish"


def _palette(seed: str) -> list[str]:
    colors = ["white", "graphite", "silver", "teal", "coral", "sage", "blue", "rose"]
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    return [colors[digest[index] % len(colors)] for index in range(3)]


def _pseudo_embedding(*values: str) -> list[float]:
    digest = hashlib.sha256("|".join(values).encode("utf-8")).digest()
    return [round((byte / 255) * 2 - 1, 4) for byte in digest[:12]]


def _keyword_score(tokens: list[str], text: str) -> float:
    if not tokens:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for token in tokens if token in lowered)
    return min(1.0, hits / max(1, len(tokens)))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(left[index] ** 2 for index in range(size)))
    right_norm = math.sqrt(sum(right[index] ** 2 for index in range(size)))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return (dot / (left_norm * right_norm) + 1) / 2


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


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    settings = get_settings()
    for secret in (settings.volcengine_api_key, settings.seedance_api_key):
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]", message)
    return message[:800]
