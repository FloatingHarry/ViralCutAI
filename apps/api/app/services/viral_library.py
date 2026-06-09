from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Asset, CreativeTemplate, ViralFactor, ViralVideoAnalysis
from app.schemas import CreativeTemplateBuildCreate, ViralVideoAnalyzeCreate


FACTOR_CATEGORIES = [
    "hook",
    "proof",
    "scene",
    "trust",
    "visual",
    "audio",
    "cta",
    "risk",
]
GENERIC_RETRIEVAL_TOKENS = {
    "tiktok",
    "shop",
    "video",
    "viral",
    "fyp",
    "foryou",
    "product",
    "products",
    "generate",
    "conversion",
    "oriented",
    "native",
    "short",
    "demo",
    "proof",
    "reference",
    "style",
}


def analyze_reference_video(payload: ViralVideoAnalyzeCreate, db: Session) -> ViralVideoAnalysis:
    analysis = _mock_video_analysis(payload)
    record = ViralVideoAnalysis(
        title=payload.title,
        source_url=payload.source_url,
        category=payload.category,
        source_statement=payload.source_statement,
        analysis=analysis,
    )
    db.add(record)
    db.flush()
    analysis = {
        **analysis,
        "source": {
            **analysis["source"],
            "reference_id": str(record.id),
        },
        "factor_board": [
            {
                **factor,
                "source_reference_id": str(record.id),
            }
            for factor in analysis["factor_board"]
        ],
    }
    record.analysis = analysis

    for factor in analysis["factor_board"]:
        db.add(
            ViralFactor(
                factor_key=factor["factor_key"],
                name=factor["name"],
                category=factor["category"],
                source=f"reference:{record.title}",
                description=factor["reason"],
                metadata_payload=factor,
            )
        )
    db.add(
        CreativeTemplate(
            name=f"{payload.category.title()} proof loop",
            category=payload.category,
            strategy=analysis["template_strategy"],
            factor_keys=[factor["factor_key"] for factor in analysis["factor_board"]],
            structure={
                "beats": ["interrupt", "proof + usage payoff", "offer close"],
                "shot_count": 3,
                "duration_seconds": 12,
                "source_video_id": str(record.id),
            },
        )
    )
    db.commit()
    db.refresh(record)
    return record


def build_creative_template(payload: CreativeTemplateBuildCreate, db: Session) -> CreativeTemplate:
    references = [video for reference_id in payload.reference_ids if (video := db.get(ViralVideoAnalysis, reference_id))]
    if len(references) < 2:
        raise ValueError("Select at least two existing external references to build a template.")
    if len(references) > 5:
        raise ValueError("A template can use at most five references.")

    category = payload.category or _most_common([video.category for video in references]) or "general"
    factor_board = _merged_reference_factors(references)
    beats = _merged_beats(references)
    factor_keys = [factor["factor_key"] for factor in factor_board[:8]]
    name = payload.name or f"{category.title()} viral playbook"
    strategy = _template_strategy(category, references, factor_board, payload.notes)
    template = CreativeTemplate(
        name=name,
        category=category,
        strategy=strategy,
        factor_keys=factor_keys,
        structure={
            "source_reference_ids": [str(video.id) for video in references],
            "source_titles": [video.title for video in references],
            "beat_structure": beats,
            "factor_keys": factor_keys,
            "constraints": [
                "Use external references as method inspiration only.",
                "Do not copy source footage or creator identity.",
                "Rewrite claims around the user's product evidence and compliance notes.",
            ],
            "best_fit_categories": sorted({video.category for video in references}),
            "notes": payload.notes,
            "template_type": "n_to_1_cluster",
        },
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def list_viral_videos(
    db: Session,
    *,
    query: str = "",
    category: str = "",
    factor_category: str = "",
) -> list[ViralVideoAnalysis]:
    statement = select(ViralVideoAnalysis).order_by(ViralVideoAnalysis.created_at.desc())
    if category:
        statement = statement.where(ViralVideoAnalysis.category.ilike(f"%{category.lower()}%"))
    if query:
        like = f"%{query.lower()}%"
        statement = statement.where(
            or_(
                ViralVideoAnalysis.title.ilike(like),
                ViralVideoAnalysis.source_statement.ilike(like),
                ViralVideoAnalysis.category.ilike(like),
            )
        )
    videos = list(db.scalars(statement).all())
    if factor_category:
        videos = [
            video
            for video in videos
            if any(factor.get("category") == factor_category for factor in video.analysis.get("factor_board", []))
        ]
    return [_with_verification_asset_metadata(video, db) for video in videos]


def list_viral_factors(db: Session, *, query: str = "", category: str = "") -> list[ViralFactor]:
    statement = select(ViralFactor).where(_external_factor_source_filter()).order_by(ViralFactor.created_at.desc())
    if category:
        statement = statement.where(ViralFactor.category == category)
    if query:
        like = f"%{query.lower()}%"
        statement = statement.where(
            or_(
                ViralFactor.name.ilike(like),
                ViralFactor.description.ilike(like),
                ViralFactor.source.ilike(like),
                ViralFactor.category.ilike(like),
            )
        )
    return list(db.scalars(statement).all())


def _with_verification_asset_metadata(video: ViralVideoAnalysis, db: Session) -> ViralVideoAnalysis:
    analysis = dict(video.analysis or {})
    source = dict(analysis.get("source") or {})
    cover_path = _reference_cover_path_from_analysis(analysis)
    if cover_path:
        source.update(
            {
                "cover_path": str(cover_path),
                "local_cover_url": f"/viral-videos/{video.id}/cover",
            }
        )
        analysis.update(
            {
                "cover_path": str(cover_path),
                "local_cover_url": f"/viral-videos/{video.id}/cover",
            }
        )
    asset_id = str(analysis.get("verified_asset_id") or source.get("verified_asset_id") or "").strip()
    if not asset_id:
        video.analysis = analysis
        return video
    try:
        asset = db.get(Asset, UUID(asset_id))
    except ValueError:
        return video
    if asset is None:
        video.analysis = analysis
        return video
    asset_cover_path = _cover_path_from_asset(asset)
    if asset_cover_path:
        source.update(
            {
                "cover_path": str(asset_cover_path),
                "local_cover_url": f"/viral-videos/{video.id}/cover",
            }
        )
        analysis.update(
            {
                "cover_path": str(asset_cover_path),
                "local_cover_url": f"/viral-videos/{video.id}/cover",
            }
        )
    uploaded_at = asset.created_at.isoformat() if asset.created_at else ""
    analyzed_at = asset.updated_at.isoformat() if asset.updated_at else ""
    frame_count = analysis.get("frame_count") or len(asset.analysis.get("frame_analyses") or [])
    source.update(
        {
            "verified_asset_id": str(asset.id),
            "verified_asset_filename": source.get("verified_asset_filename") or asset.filename,
            "verified_asset_kind": source.get("verified_asset_kind") or asset.asset_kind,
            "verified_asset_provider_status": source.get("verified_asset_provider_status") or asset.provider_status,
            "verified_asset_created_at": source.get("verified_asset_created_at") or uploaded_at,
            "verified_asset_updated_at": source.get("verified_asset_updated_at") or analyzed_at,
            "verified_at": source.get("verified_at") or (analyzed_at if analysis.get("visual_verified") or source.get("visual_verified") else ""),
        }
    )
    analysis.update(
        {
            "source": source,
            "verified_asset_filename": analysis.get("verified_asset_filename") or asset.filename,
            "verified_asset_kind": analysis.get("verified_asset_kind") or asset.asset_kind,
            "verified_asset_created_at": analysis.get("verified_asset_created_at") or uploaded_at,
            "verified_asset_updated_at": analysis.get("verified_asset_updated_at") or analyzed_at,
            "verified_at": analysis.get("verified_at") or (analyzed_at if analysis.get("visual_verified") or source.get("visual_verified") else ""),
            "frame_count": frame_count,
            "video_metadata": analysis.get("video_metadata") or asset.analysis.get("video_metadata") or {},
        }
    )
    video.analysis = analysis
    return video


def viral_reference_cover_path(reference_id: UUID, db: Session) -> Path | None:
    video = db.get(ViralVideoAnalysis, reference_id)
    if video is None:
        raise LookupError("Viral reference not found")
    analysis = dict(video.analysis or {})
    existing_path = _reference_cover_path_from_analysis(analysis)
    if existing_path:
        return existing_path
    source = analysis.get("source") if isinstance(analysis.get("source"), dict) else {}
    asset_id = str(analysis.get("verified_asset_id") or source.get("verified_asset_id") or "").strip()
    if not asset_id:
        return None
    try:
        asset = db.get(Asset, UUID(asset_id))
    except ValueError:
        return None
    if asset is None:
        return None
    return _cover_path_from_asset(asset)


def _reference_cover_path_from_analysis(analysis: dict[str, Any]) -> Path | None:
    source = analysis.get("source") if isinstance(analysis.get("source"), dict) else {}
    for value in (
        analysis.get("cover_path"),
        source.get("cover_path"),
        analysis.get("local_cover_path"),
        source.get("local_cover_path"),
    ):
        path = _existing_file_path(value)
        if path:
            return path
    for item in analysis.get("verified_frame_evidence") or []:
        if not isinstance(item, dict):
            continue
        path = _existing_file_path(item.get("frame_path") or item.get("source_frame_path"))
        if path:
            return path
    return None


def _cover_path_from_asset(asset: Asset) -> Path | None:
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


def list_templates(db: Session, *, query: str = "", category: str = "") -> list[CreativeTemplate]:
    statement = select(CreativeTemplate).order_by(CreativeTemplate.created_at.desc())
    if category:
        statement = statement.where(CreativeTemplate.category.ilike(f"%{category.lower()}%"))
    if query:
        like = f"%{query.lower()}%"
        statement = statement.where(
            or_(
                CreativeTemplate.name.ilike(like),
                CreativeTemplate.strategy.ilike(like),
                CreativeTemplate.category.ilike(like),
            )
        )
    return list(db.scalars(statement).all())


def viral_context_for_generation(
    *,
    reference_video_id: UUID | None,
    template_id: UUID | None,
    factor_ids: list[UUID],
    db: Session,
) -> dict[str, Any]:
    reference = db.get(ViralVideoAnalysis, reference_video_id) if reference_video_id else None
    template = db.get(CreativeTemplate, template_id) if template_id else None
    factors = [factor for factor_id in factor_ids if (factor := db.get(ViralFactor, factor_id))]
    return {
        "reference_video": _reference_payload_for_generation(reference, match_mode="manual") if reference else None,
        "creative_template": _template_payload(template) if template else None,
        "selected_library_factors": [_factor_payload(factor) for factor in factors],
    }


def viral_retrieval_for_generation(request: dict[str, Any], db: Session) -> dict[str, Any]:
    query = " ".join(
        [
            str(request.get("product_name") or ""),
            str(request.get("category") or ""),
            " ".join(str(point) for point in request.get("selling_points", [])),
        ]
    ).strip()
    category = str(request.get("category") or "")
    product_name = str(request.get("product_name") or "")
    manual_reference = request.get("reference_video") if isinstance(request.get("reference_video"), dict) else None
    auto_references = (
        []
        if manual_reference
        else _rank_references(db, query=query, product_category=category, product_id=_request_product_id(request), product_name=product_name)
    )
    selected_reference = manual_reference or (_reference_payload_for_generation(auto_references[0], match_mode="auto_best") if auto_references else None)
    auto_factors = _reference_factor_summaries(selected_reference)
    return {
        "viral_query": query,
        "auto_factors": auto_factors,
        "auto_templates": [],
        "auto_references": [selected_reference] if selected_reference else [],
        "selected_reference_video": selected_reference,
        "reference_match_mode": "manual" if manual_reference else ("auto_best" if selected_reference else "none"),
        "reference_match_reason": _reference_match_reason(selected_reference, category),
        "methodology_summary": _viral_evidence_summary_from_reference(selected_reference, auto_factors),
    }


def _rank_viral_factors(db: Session, *, query: str, product_category: str) -> list[ViralFactor]:
    tokens = _tokens(" ".join([query, product_category]))
    rows = list(db.scalars(select(ViralFactor).where(_external_factor_source_filter()).order_by(ViralFactor.created_at.desc())).all())
    scored = []
    for factor in rows:
        metadata = json.dumps(factor.metadata_payload or {}, ensure_ascii=False)
        text = " ".join([factor.name, factor.description, factor.source, factor.category, metadata])
        score = _keyword_score(tokens, text)
        if product_category and product_category.lower() in text.lower():
            score += 0.25
        if score > 0:
            scored.append((score, factor))
    if not scored:
        return rows[:8]
    scored.sort(key=lambda item: item[0], reverse=True)
    diversified: list[ViralFactor] = []
    seen_categories: set[str] = set()
    for _, factor in scored:
        if factor.category in seen_categories:
            continue
        diversified.append(factor)
        seen_categories.add(factor.category)
        if len(diversified) >= 8:
            return diversified
    for _, factor in scored:
        if factor in diversified:
            continue
        diversified.append(factor)
        if len(diversified) >= 8:
            break
    return diversified


def _rank_templates(db: Session, *, query: str, product_category: str) -> list[CreativeTemplate]:
    tokens = _tokens(" ".join([query, product_category]))
    rows = list(db.scalars(select(CreativeTemplate).order_by(CreativeTemplate.created_at.desc())).all())
    scored = []
    for template in rows:
        text = " ".join([template.name, template.category, template.strategy, json.dumps(template.structure or {}, ensure_ascii=False)])
        score = _keyword_score(tokens, text)
        if product_category and product_category.lower() in template.category.lower():
            score += 0.35
        if score > 0:
            scored.append((score, template))
    return [template for _, template in sorted(scored, key=lambda item: item[0], reverse=True)[:3]]


def _rank_references(db: Session, *, query: str, product_category: str, product_id: str = "", product_name: str = "") -> list[ViralVideoAnalysis]:
    tokens = _tokens(" ".join([query, product_category]))
    rows = list(db.scalars(select(ViralVideoAnalysis).order_by(ViralVideoAnalysis.created_at.desc())).all())
    scored = []
    for video in rows:
        text = " ".join([video.title, video.category, video.source_statement, json.dumps(video.analysis or {}, ensure_ascii=False)])
        score = _reference_match_score(video, text, tokens, product_category, product_id, product_name)
        if score > 0:
            scored.append((score, video))
    return [video for _, video in sorted(scored, key=lambda item: item[0], reverse=True)[:1]]


def _request_product_id(request: dict[str, Any]) -> str:
    for key in ("product_id", "pid", "shop_product_id"):
        value = str(request.get(key) or "").strip()
        if value:
            return value
    return ""


def _reference_match_score(video: ViralVideoAnalysis, text: str, tokens: list[str], product_category: str, product_id: str, product_name: str = "") -> float:
    lowered = text.lower()
    analysis = video.analysis or {}
    fastmoss = analysis.get("fastmoss") if isinstance(analysis.get("fastmoss"), dict) else {}
    source = analysis.get("source") if isinstance(analysis.get("source"), dict) else {}
    category_tokens = _tokens(product_category)
    category_token_set = set(category_tokens)
    product_tokens = [token for token in tokens if token not in category_token_set]
    core_product_tokens = _tokens(product_name)
    token_hits = [token for token in tokens if token in lowered]
    product_token_hits = [token for token in product_tokens if token in lowered]
    core_product_hits = [token for token in core_product_tokens if token in lowered]
    score = len(token_hits) / max(1, min(len(tokens), 12))
    has_meaningful_match = score > 0
    strong_match = False
    if product_id and product_id in text:
        score += 3.0
        has_meaningful_match = True
        strong_match = True
    category_candidates = [
        str(video.category or ""),
        str(analysis.get("category") or ""),
        str(source.get("category_context") or ""),
        str(fastmoss.get("category_name") or ""),
        str(fastmoss.get("product_type") or ""),
    ]
    if product_category:
        if any(product_category.lower() in item.lower() for item in category_candidates):
            score += 1.0
            has_meaningful_match = True
        elif category_tokens and any(token in " ".join(category_candidates).lower() for token in category_tokens):
            score += 0.45
            has_meaningful_match = True
    if not has_meaningful_match:
        return 0

    # Category matches alone are too broad: beauty cologne should not become the
    # best reference for an iridescent bottle unless the product terms also land.
    if len(core_product_tokens) >= 2 and len(core_product_hits) < 2:
        return 0
    if len(core_product_tokens) == 1 and not core_product_hits:
        return 0
    if core_product_hits:
        score += min(1.2, len(core_product_hits) * 0.6)
    if product_token_hits:
        score += min(1.5, len(product_token_hits) * 0.45)
    if len(core_product_hits) >= 2 or len(product_token_hits) >= 3:
        strong_match = True
    elif len(product_token_hits) == 1 and len(token_hits) >= 4:
        strong_match = True
    if not strong_match:
        return 0
    if analysis.get("visual_verified") or source.get("visual_verified"):
        score += 0.25
    metrics = fastmoss if fastmoss else (source.get("fastmoss") if isinstance(source.get("fastmoss"), dict) else {})
    play_count = _to_int(metrics.get("play_count"), 0) if isinstance(metrics, dict) else 0
    units_sold = _to_int(metrics.get("units_sold"), 0) if isinstance(metrics, dict) else 0
    if play_count > 1000000:
        score += 0.2
    if units_sold > 0:
        score += 0.15
    if tokens and any(token in lowered for token in tokens):
        score += 0.05
    return score


def _tokens(text: str) -> list[str]:
    return [
        item
        for item in re.split(r"[^A-Za-z0-9]+", text.lower())
        if len(item) > 2 and item not in GENERIC_RETRIEVAL_TOKENS
    ]


def _keyword_score(tokens: list[str], text: str) -> float:
    if not tokens:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for token in tokens if token in lowered)
    return hits / max(1, min(len(tokens), 12))


def _external_factor_source_filter():
    return or_(
        ViralFactor.source.ilike("reference:%"),
        ViralFactor.source.ilike("external:%"),
        ViralFactor.source.ilike("manual_external:%"),
    )


def _most_common(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def _merged_reference_factors(references: list[ViralVideoAnalysis]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    all_factors = [
        {**factor, "reference_title": video.title, "reference_id": str(video.id)}
        for video in references
        for factor in (video.analysis or {}).get("factor_board", [])
    ]
    for factor in all_factors:
        category = str(factor.get("category") or "")
        if category in seen_categories:
            continue
        selected.append(factor)
        seen_categories.add(category)
        if len(selected) >= 8:
            return selected
    for factor in all_factors:
        if factor in selected:
            continue
        selected.append(factor)
        if len(selected) >= 8:
            break
    return selected


def _merged_beats(references: list[ViralVideoAnalysis]) -> list[dict[str, Any]]:
    for video in references:
        beats = (video.analysis or {}).get("storyboard_structure")
        if isinstance(beats, list) and beats:
            return _compact_storyboard(beats)
    return [
        {"shot_id": "shot-1", "beat": "Hook", "duration": 4, "purpose": "pattern interrupt"},
        {"shot_id": "shot-2", "beat": "Proof + Use", "duration": 4, "purpose": "visible product proof and daily use case"},
        {"shot_id": "shot-3", "beat": "CTA", "duration": 4, "purpose": "offer-backed action"},
    ]


def _template_strategy(category: str, references: list[ViralVideoAnalysis], factors: list[dict[str, Any]], notes: str) -> str:
    names = ", ".join(video.title for video in references[:3])
    factor_names = ", ".join(str(factor.get("name")) for factor in factors[:4])
    note_suffix = f" Notes: {notes}" if notes else ""
    return (
        f"{category.title()} n:1 playbook distilled from {len(references)} external references"
        f" ({names}). Reuse the beat logic and factors ({factor_names}) while rewriting all claims"
        f" around the merchant's own product evidence.{note_suffix}"
    )


def _mock_video_analysis(payload: ViralVideoAnalyzeCreate) -> dict[str, Any]:
    notes = payload.notes or payload.title
    category = payload.category
    product_type = payload.product_type or category
    platform = payload.platform or "TikTok"
    hook = f"Open with a {platform}-native tension: why {product_type} shoppers stop scrolling."
    source_context = {
        "platform": payload.platform,
        "source_url": payload.source_url,
        "category": payload.category,
        "product_type": payload.product_type,
        "country": payload.country,
        "language": payload.language,
        "metrics": payload.metrics,
        "published_at": payload.published_at,
        "thumbnail_url": payload.thumbnail_url,
        "source_statement": payload.source_statement,
        "notes": payload.notes,
    }
    factor_board = [
        _factor(category, "hook", "Pattern interrupt hook", hook, notes, ["shot-1"], source_context=source_context),
        _factor(category, "proof", "Visible proof close-up", "Turn the strongest claim into a tactile visual test.", notes, ["shot-2"], source_context=source_context),
        _factor(category, "scene", "Use-case transfer", "Show the product in a scene that matches the buyer's daily rhythm.", notes, ["shot-3"], source_context=source_context),
        _factor(category, "trust", "Low-friction credibility", "Add a plain-language constraint or use condition instead of hype.", notes, ["shot-2", "shot-3"], source_context=source_context),
        _factor(category, "visual", "High-contrast product silhouette", "Make the product readable on a small phone screen.", notes, ["shot-1", "shot-3"], source_context=source_context),
        _factor(category, "audio", "Rhythm-matched voiceover", "Let subtitle cadence and music support the visual proof beat.", notes, ["shot-1", "shot-2"], source_context=source_context),
        _factor(category, "cta", "Offer-backed close", "Tie the final action to the current offer or use moment.", notes, ["shot-3"], source_context=source_context),
        _factor(category, "risk", "Claim-safe wording", "Avoid absolute claims and keep reference analysis transformative.", notes, ["shot-1", "shot-3"], source_context=source_context),
    ]
    return {
        "source": source_context,
        "hook_method": hook,
        "hook_methods": [hook, "show proof before brand talk", "convert the pain into a scene"],
        "selling_point_order": ["problem", "visible proof + daily payoff", "offer"],
        "selling_point_map": ["problem", "visible proof + daily payoff", "offer"],
        "storyboard_structure": [
            {"shot_id": "shot-1", "beat": "Hook", "duration": 4, "purpose": "stop the scroll with a category tension"},
            {"shot_id": "shot-2", "beat": "Proof + Use", "duration": 4, "purpose": "turn the main claim into visible proof and daily payoff"},
            {"shot_id": "shot-3", "beat": "CTA", "duration": 4, "purpose": "close with a low-friction action"},
        ],
        "visual_style": f"{platform}-native commerce, clean proof shots, fast but readable captions",
        "style": f"{platform}-native commerce, clean proof shots, fast but readable captions",
        "caption_style": "short sentence captions, one benefit per shot, subtitle-safe visual spacing",
        "audio_style": "voiceover cadence follows shot rhythm; BGM supports proof without overpowering speech",
        "cta_pattern": "offer-backed close tied to a current shopper action",
        "risk_notes": [
            "Use the source as structural inspiration only.",
            "Avoid copying creator identity, original footage, or unverifiable claims.",
        ],
        "template_strategy": f"{category} proof loop: interrupt, prove, transfer, close.",
        "factor_board": factor_board,
        "compliance_statement": payload.source_statement,
    }


def build_factor_board(request: dict[str, Any]) -> list[dict[str, Any]]:
    category = str(request.get("category") or "general")
    product = str(request.get("product_name") or "product")
    selling_points = request.get("selling_points") or ["clear benefit"]
    primary = selling_points[0] if selling_points else "clear benefit"
    retrieval = request.get("retrieval_context") or {}
    library_factors = request.get("selected_library_factors") or []
    library_factors = [*library_factors, *(retrieval.get("auto_factors") or [])]
    board = [
        _factor(category, "hook", "Problem-first hook", f"Frame the need for {primary} before showing {product}.", product, ["shot-1"], source="user input"),
        _factor(category, "proof", "Macro proof shot", f"Make {primary} visible with a close tactile demonstration using retrieved asset evidence.", product, ["shot-2"], source="asset retrieval"),
        _factor(category, "scene", "Daily-use transfer", "Move from product proof into a practical use case suggested by retrieved slices.", product, ["shot-3"], source="asset retrieval"),
        _factor(category, "trust", "Specificity over hype", "Use concrete language and avoid unverifiable promises.", product, ["shot-2", "shot-3"], source="compliance"),
        _factor(category, "visual", "Clean mobile silhouette", "Keep the product readable in a vertical feed.", product, ["shot-1", "shot-3"], source="template"),
        _factor(category, "audio", "Voiceover beat match", "Use short lines that match shot duration and caption rhythm.", product, ["shot-1", "shot-2", "shot-3"], source="template"),
        _factor(category, "cta", "Offer-backed CTA", "Connect the action to the price or shipping offer.", product, ["shot-3"], source="user input"),
        _factor(category, "risk", "Reference-safe remix", "Use reference ideas as analysis, not copied footage.", product, ["shot-3"], source="reference"),
    ]
    by_category = {factor["category"]: factor for factor in board}
    for item in library_factors:
        metadata = item.get("metadata_payload") if isinstance(item.get("metadata_payload"), dict) else {}
        factor_category = str(item.get("category") or metadata.get("category") or "").lower()
        if factor_category not in FACTOR_CATEGORIES:
            continue
        by_category[factor_category] = {
            "factor_key": str(item.get("factor_key") or metadata.get("factor_key") or f"library-{factor_category}"),
            "name": str(item.get("name") or metadata.get("name") or "Library factor"),
            "category": factor_category,
            "reason": str(item.get("description") or item.get("reason") or metadata.get("reason") or "Selected from the viral factor library."),
            "expected_effect": str(metadata.get("expected_effect") or item.get("expected_effect") or "Improves creative fit for the selected reference."),
            "confidence": _factor_confidence(metadata.get("confidence", item.get("confidence", 76))),
            "linked_shot_ids": _normalize_linked_shot_ids(metadata.get("linked_shot_ids", item.get("linked_shot_ids")), fallback=["shot-2"]),
            "source": "factor library",
        }
    return [by_category[category] for category in FACTOR_CATEGORIES]


def _factor(
    category: str,
    factor_category: str,
    name: str,
    reason: str,
    seed: str,
    shot_ids: list[str],
    *,
    source: str = "dynamic reference analysis",
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key_seed = f"{category}|{factor_category}|{name}|{seed}"
    confidence = 68 + hashlib.sha1(key_seed.encode("utf-8")).digest()[0] % 25
    lift = 4 + hashlib.sha1((key_seed + "lift").encode("utf-8")).digest()[0] % 14
    context = source_context or {}
    return {
        "factor_key": f"{factor_category}-{hashlib.sha1(key_seed.encode('utf-8')).hexdigest()[:8]}",
        "name": name,
        "category": factor_category,
        "reason": reason,
        "expected_effect": f"Estimated +{lift}% lift potential on {factor_category} for {category} viewers.",
        "confidence": confidence,
        "linked_shot_ids": shot_ids,
        "source": source,
        "source_reference_id": context.get("reference_id"),
        "source_url": context.get("source_url"),
        "platform": context.get("platform"),
        "product_type": context.get("product_type"),
        "country": context.get("country"),
        "language": context.get("language"),
        "source_safety_note": "Structured analysis only; source footage is not copied.",
    }


def _video_payload(video: ViralVideoAnalysis | None) -> dict[str, Any] | None:
    if video is None:
        return None
    return {
        "id": str(video.id),
        "title": video.title,
        "source_url": video.source_url,
        "category": video.category,
        "analysis": video.analysis,
    }


def _reference_payload_for_generation(video: ViralVideoAnalysis | None, *, match_mode: str) -> dict[str, Any] | None:
    if video is None:
        return None
    analysis = video.analysis or {}
    source = analysis.get("source") if isinstance(analysis.get("source"), dict) else {}
    fastmoss = analysis.get("fastmoss") if isinstance(analysis.get("fastmoss"), dict) else {}
    if not fastmoss and isinstance(source.get("fastmoss"), dict):
        fastmoss = source.get("fastmoss") or {}
    visual_verified = bool(analysis.get("visual_verified") or source.get("visual_verified"))
    source_mode = str(analysis.get("source_mode") or source.get("source_mode") or ("owner_viral_verified" if visual_verified else "fastmoss_structured_only"))
    factor_board = _compact_reference_factor_board(analysis.get("factor_board"), video)
    return {
        "id": str(video.id),
        "title": _limit(video.title, 180),
        "source_url": video.source_url,
        "category": video.category,
        "match_mode": match_mode,
        "source_mode": source_mode,
        "source_capability": str(analysis.get("source_capability") or source.get("source_capability") or ("visual_verified" if visual_verified else "structured_only")),
        "visual_verified": visual_verified,
        "verified_asset_id": str(analysis.get("verified_asset_id") or source.get("verified_asset_id") or "") or None,
        "summary": {
            "hook_method": _limit(str(analysis.get("hook_method") or ""), 180),
            "selling_point_order": _string_list(analysis.get("selling_point_order"), limit=4, item_limit=100),
            "caption_style": _limit(str(analysis.get("caption_style") or ""), 160),
            "cta_pattern": _limit(str(analysis.get("cta_pattern") or ""), 160),
            "risk_notes": _string_list(analysis.get("risk_notes"), limit=3, item_limit=120),
            "metrics": _reference_metrics(fastmoss),
        },
        "storyboard_structure": _compact_storyboard(analysis.get("storyboard_structure")),
        "factor_board": factor_board,
    }


def _reference_factor_summaries(reference: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not reference:
        return []
    factors = reference.get("factor_board") if isinstance(reference.get("factor_board"), list) else []
    return [_compact_factor_for_generation(factor, reference) for factor in factors[:8] if isinstance(factor, dict)]


def _compact_reference_factor_board(value: Any, video: ViralVideoAnalysis) -> list[dict[str, Any]]:
    factors = value if isinstance(value, list) else []
    compact = []
    for index, factor in enumerate(factors[:8], start=1):
        if not isinstance(factor, dict):
            continue
        compact.append(
            {
                "factor_key": str(factor.get("factor_key") or f"reference-{index}"),
                "name": _limit(str(factor.get("name") or "Reference factor"), 120),
                "category": _limit(str(factor.get("category") or "proof"), 40),
                "reason": _limit(str(factor.get("reason") or factor.get("description") or ""), 220),
                "expected_effect": _limit(str(factor.get("expected_effect") or ""), 180),
                "confidence": _factor_confidence(factor.get("confidence"), 76),
                "linked_shot_ids": _normalize_linked_shot_ids(factor.get("linked_shot_ids"), fallback=["shot-2"]),
                "source": str(factor.get("source") or f"reference:{video.id}"),
                "evidence_type": _limit(str(factor.get("evidence_type") or ""), 60),
                "visual_verified": bool(factor.get("visual_verified") or factor.get("reference_visual_verified")),
            }
        )
    return compact


def _compact_factor_for_generation(factor: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    visual_verified = bool(factor.get("visual_verified") or reference.get("visual_verified"))
    return {
        "factor_key": str(factor.get("factor_key") or ""),
        "name": _limit(str(factor.get("name") or "Reference factor"), 120),
        "category": _limit(str(factor.get("category") or "proof"), 40),
        "source": str(factor.get("source") or f"reference:{reference.get('id')}"),
        "description": _limit(str(factor.get("reason") or factor.get("description") or ""), 220),
        "reason": _limit(str(factor.get("reason") or factor.get("description") or ""), 220),
        "expected_effect": _limit(str(factor.get("expected_effect") or ""), 180),
        "confidence": _factor_confidence(factor.get("confidence"), 76),
        "linked_shot_ids": _normalize_linked_shot_ids(factor.get("linked_shot_ids"), fallback=["shot-2"]),
        "source_reference_id": reference.get("id"),
        "reference_title": reference.get("title"),
        "source_mode": reference.get("source_mode"),
        "source_capability": reference.get("source_capability"),
        "visual_verified": visual_verified,
        "audio_verified": False,
        "evidence_type": _limit(str(factor.get("evidence_type") or "reference_structure"), 60),
        "evidence_text": _limit(str(factor.get("evidence_text") or factor.get("reason") or ""), 180),
    }


def _compact_storyboard(value: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    compact = []
    for index, item in enumerate(items[:3], start=1):
        if not isinstance(item, dict):
            continue
        shot_index = max(1, min(_to_int(item.get("shot_id") or index, index), 3))
        compact.append(
            {
                "shot_id": f"shot-{shot_index}",
                "beat": _limit(str(item.get("beat") or item.get("name") or ""), 80),
                "duration": _limit(str(item.get("duration") or item.get("duration_seconds") or ""), 40),
                "purpose": _limit(str(item.get("purpose") or item.get("description") or item.get("reason") or ""), 180),
            }
        )
    return compact


def _reference_metrics(fastmoss: dict[str, Any]) -> dict[str, Any]:
    return {
        key: fastmoss.get(key)
        for key in ("video_id", "play_count", "digg_count", "comment_count", "share_count", "units_sold", "gmv", "region")
        if fastmoss.get(key) not in (None, "")
    }


def _reference_match_reason(reference: dict[str, Any] | None, category: str) -> str:
    if not reference:
        return "No strong viral reference match found; use default commerce structure."
    if reference.get("match_mode") == "manual":
        return "Manual reference selected by the user."
    label = f"Best local viral reference for category/query match"
    if category:
        label += f" against {category}."
    else:
        label += "."
    return label


def _viral_evidence_summary_from_reference(reference: dict[str, Any] | None, factors: list[dict[str, Any]]) -> str:
    if not reference:
        return "No matching viral reference found; use default commerce factors."
    status = "video-verified" if reference.get("visual_verified") else "structured-only"
    return f"1 best viral reference selected ({status}); {len(factors)} same-reference factors summarized."


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if isinstance(value, list):
        return [_limit(str(item), item_limit) for item in value[:limit] if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [_limit(value, item_limit)]
    return []


def _normalize_linked_shot_ids(value: Any, *, fallback: list[str]) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for raw in raw_values:
        for explicit, bare in re.findall(r"shot[-_\s]*(\d+)|\b([1-9])\b", str(raw or "").lower()):
            shot_index = max(1, min(_to_int(explicit or bare, 2), 3))
            shot_id = f"shot-{shot_index}"
            if shot_id not in normalized:
                normalized.append(shot_id)
    return normalized or fallback


def _factor_confidence(value: Any, fallback: int = 76) -> int:
    confidence = _to_int(value, fallback)
    if confidence <= 0 or confidence > 100:
        return fallback
    return confidence


def _limit(value: str, length: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:length]


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        if value in (None, ""):
            return fallback
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return fallback


def _template_payload(template: CreativeTemplate | None) -> dict[str, Any] | None:
    if template is None:
        return None
    return {
        "id": str(template.id),
        "name": template.name,
        "category": template.category,
        "strategy": template.strategy,
        "factor_keys": template.factor_keys,
        "structure": template.structure,
    }


def _factor_payload(factor: ViralFactor) -> dict[str, Any]:
    return {
        "id": str(factor.id),
        "factor_key": factor.factor_key,
        "name": factor.name,
        "category": factor.category,
        "source": factor.source,
        "description": factor.description,
        "metadata_payload": factor.metadata_payload,
    }


def _viral_evidence_summary(factors: list[ViralFactor], templates: list[CreativeTemplate], references: list[ViralVideoAnalysis]) -> str:
    parts = []
    if factors:
        parts.append(f"{min(len(factors), 8)} retrieved factors")
    if templates:
        parts.append(f"{min(len(templates), 3)} templates")
    if references:
        parts.append(f"{min(len(references), 3)} reference analyses")
    return ", ".join(parts) if parts else "No matching methodology records yet; use default commerce factors."
