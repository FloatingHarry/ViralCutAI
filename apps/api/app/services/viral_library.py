from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CreativeTemplate, ViralFactor, ViralVideoAnalysis
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
                "beats": ["interrupt", "proof", "usage payoff", "offer close"],
                "shot_count": 4,
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
    return videos


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
        "reference_video": _video_payload(reference) if reference else None,
        "creative_template": _template_payload(template) if template else None,
        "selected_library_factors": [_factor_payload(factor) for factor in factors],
    }


def viral_retrieval_for_generation(request: dict[str, Any], db: Session) -> dict[str, Any]:
    query = " ".join(
        [
            str(request.get("product_name") or ""),
            str(request.get("category") or ""),
            " ".join(str(point) for point in request.get("selling_points", [])),
            str(request.get("creative_goal") or ""),
            str(request.get("reference_style") or ""),
        ]
    ).strip()
    category = str(request.get("category") or "")
    auto_factors = _rank_viral_factors(db, query=query, product_category=category)
    auto_templates = _rank_templates(db, query=query, product_category=category)
    auto_references = _rank_references(db, query=query, product_category=category)
    return {
        "viral_query": query,
        "auto_factors": [_factor_payload(factor) for factor in auto_factors[:8]],
        "auto_templates": [_template_payload(template) for template in auto_templates[:3]],
        "auto_references": [_video_payload(video) for video in auto_references[:3]],
        "methodology_summary": _viral_evidence_summary(auto_factors, auto_templates, auto_references),
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


def _rank_references(db: Session, *, query: str, product_category: str) -> list[ViralVideoAnalysis]:
    tokens = _tokens(" ".join([query, product_category]))
    rows = list(db.scalars(select(ViralVideoAnalysis).order_by(ViralVideoAnalysis.created_at.desc())).all())
    scored = []
    for video in rows:
        text = " ".join([video.title, video.category, video.source_statement, json.dumps(video.analysis or {}, ensure_ascii=False)])
        score = _keyword_score(tokens, text)
        if product_category and product_category.lower() in video.category.lower():
            score += 0.35
        if score > 0:
            scored.append((score, video))
    return [video for _, video in sorted(scored, key=lambda item: item[0], reverse=True)[:3]]


def _tokens(text: str) -> list[str]:
    return [item for item in re.split(r"[^A-Za-z0-9]+", text.lower()) if len(item) > 2]


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
            return beats[:5]
    return [
        {"shot_id": "shot-1", "beat": "Hook", "duration": 3, "purpose": "pattern interrupt"},
        {"shot_id": "shot-2", "beat": "Proof", "duration": 3, "purpose": "visible product proof"},
        {"shot_id": "shot-3", "beat": "Transfer", "duration": 3, "purpose": "daily use case"},
        {"shot_id": "shot-4", "beat": "CTA", "duration": 3, "purpose": "offer-backed action"},
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
        _factor(category, "visual", "High-contrast product silhouette", "Make the product readable on a small phone screen.", notes, ["shot-1", "shot-4"], source_context=source_context),
        _factor(category, "audio", "Rhythm-matched voiceover", "Let subtitle cadence and music support the visual proof beat.", notes, ["shot-1", "shot-2"], source_context=source_context),
        _factor(category, "cta", "Offer-backed close", "Tie the final action to the current offer or use moment.", notes, ["shot-4"], source_context=source_context),
        _factor(category, "risk", "Claim-safe wording", "Avoid absolute claims and keep reference analysis transformative.", notes, ["shot-1", "shot-4"], source_context=source_context),
    ]
    return {
        "source": source_context,
        "hook_method": hook,
        "hook_methods": [hook, "show proof before brand talk", "convert the pain into a scene"],
        "selling_point_order": ["problem", "visible proof", "daily payoff", "offer"],
        "selling_point_map": ["problem", "visible proof", "daily payoff", "offer"],
        "storyboard_structure": [
            {"shot_id": "shot-1", "beat": "Hook", "duration": 3, "purpose": "stop the scroll with a category tension"},
            {"shot_id": "shot-2", "beat": "Proof", "duration": 3, "purpose": "turn the main claim into a visible proof moment"},
            {"shot_id": "shot-3", "beat": "Daily payoff", "duration": 3, "purpose": "show the product fitting a real buyer routine"},
            {"shot_id": "shot-4", "beat": "CTA", "duration": 3, "purpose": "close with a low-friction action"},
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
        _factor(category, "visual", "Clean mobile silhouette", "Keep the product readable in a vertical feed.", product, ["shot-1", "shot-4"], source="template"),
        _factor(category, "audio", "Voiceover beat match", "Use short lines that match shot duration and caption rhythm.", product, ["shot-1", "shot-2", "shot-3"], source="template"),
        _factor(category, "cta", "Offer-backed CTA", "Connect the action to the price or shipping offer.", product, ["shot-4"], source="user input"),
        _factor(category, "risk", "Reference-safe remix", "Use reference ideas as analysis, not copied footage.", product, ["shot-4"], source="reference"),
    ]
    for item in library_factors[:3]:
        board.append(
            {
                "factor_key": item.get("factor_key", f"library-{len(board)}"),
                "name": item.get("name", "Library factor"),
                "category": item.get("category", "template"),
                "reason": item.get("description") or item.get("reason", "Selected from the viral factor library."),
                "expected_effect": item.get("metadata_payload", {}).get("expected_effect", "Improves creative fit for the selected reference."),
                "confidence": item.get("metadata_payload", {}).get("confidence", 76),
                "linked_shot_ids": item.get("metadata_payload", {}).get("linked_shot_ids", ["shot-2"]),
                "source": "factor library",
            }
        )
    return board


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
