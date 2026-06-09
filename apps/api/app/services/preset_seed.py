from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import Asset, AssetCollection, AssetEmbedding, AssetSlice, AssetTag


PRESET_COLLECTION_NAME = "Aurora Glow Bottle"
PRESET_CATEGORY = "beauty & personal care"
PRESET_PROVIDER_MESSAGE = "Preset product asset with owner-provided image and structured notes."


def seed_preset_workspace(db: Session) -> dict[str, Any]:
    collection = _ensure_preset_collection(db)
    collection_id = collection.id
    created_or_updated: list[str] = []
    for spec in _preset_asset_specs():
        asset, changed = _ensure_preset_asset(collection_id, spec, db)
        if changed:
            created_or_updated.append(asset.filename)
    _refresh_preset_collection(collection_id, db)
    collection = _load_collection(collection_id, db)
    return {
        "status": "ready",
        "message": "Aurora Glow Bottle preset asset collection is ready.",
        "collection_id": str(collection.id),
        "product_name": collection.product_name,
        "category": collection.category,
        "asset_count": len(collection.assets),
        "slice_count": sum(len(asset.slices) for asset in collection.assets),
        "created_or_updated": created_or_updated,
    }


def _ensure_preset_collection(db: Session) -> AssetCollection:
    collection = db.scalar(select(AssetCollection).where(AssetCollection.product_name == PRESET_COLLECTION_NAME))
    description = (
        "Aurora Glow Bottle is a 100ml iridescent beauty bottle with a glass-like pastel body, "
        "polished cap, gold label, and soft radiant studio lighting."
    )
    usage_notes = (
        "Use this preset as the product evidence for Studio runs. Focus on glow finish, premium packaging, "
        "giftable shelf appeal, reflective color shift, and close-up beauty product proof. Source video is not attached yet."
    )
    if collection is None:
        collection = AssetCollection(
            product_name=PRESET_COLLECTION_NAME,
            category=PRESET_CATEGORY,
            description=description,
            usage_notes=usage_notes,
            status="analyzed",
            summary="Preset product assets ready for Studio generation.",
            coverage={},
            tags=[],
        )
    else:
        collection.category = PRESET_CATEGORY
        collection.description = description
        collection.usage_notes = usage_notes
        collection.status = "analyzed"
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def _ensure_preset_asset(collection_id: Any, spec: dict[str, Any], db: Session) -> tuple[Asset, bool]:
    asset = db.scalar(select(Asset).where(Asset.collection_id == collection_id, Asset.filename == spec["filename"]))
    path = _preset_root() / spec["filename"]
    _copy_preset_image(path, spec["source_candidates"])
    content_size = path.stat().st_size
    changed = False
    if asset is None:
        asset = Asset(
            collection_id=collection_id,
            filename=spec["filename"],
            content_type="image/png",
            asset_kind="image",
            category=PRESET_CATEGORY,
            size_bytes=content_size,
            storage_path=str(path),
            description=spec["description"],
            analysis={},
            analysis_status="pending",
            provider_status="preset",
            provider_message=PRESET_PROVIDER_MESSAGE,
        )
        db.add(asset)
        db.flush()
        changed = True
    else:
        asset.content_type = "image/png"
        asset.asset_kind = "image"
        asset.category = PRESET_CATEGORY
        asset.size_bytes = content_size
        asset.storage_path = str(path)
        asset.description = spec["description"]
        changed = True
        _clear_asset_children(asset.id, db)

    asset.analysis = spec["analysis"]
    asset.analysis_status = "analyzed"
    asset.provider_status = "preset"
    asset.provider_message = PRESET_PROVIDER_MESSAGE
    _write_asset_children(asset.id, asset.filename, asset.description, asset.analysis, spec, db)
    db.commit()
    db.refresh(asset)
    return asset, changed


def _copy_preset_image(destination: Path, source_candidates: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for value in source_candidates:
        source = Path(value)
        if source.exists() and source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
            return
    if destination.exists() and destination.stat().st_size > 0:
        return
    raise FileNotFoundError(f"Preset source image is missing for {destination.name}.")


def _write_asset_children(asset_id: Any, filename: str, description: str, analysis: dict[str, Any], spec: dict[str, Any], db: Session) -> None:
    for index, tag in enumerate(spec["tags"], start=1):
        db.add(
            AssetTag(
                asset_id=asset_id,
                name=str(tag).strip().lower()[:120],
                tag_type="preset_signal" if index <= 5 else "keyword",
                confidence=max(72, 98 - index * 2),
                source="preset",
            )
        )
    for index, item in enumerate(spec["slices"], start=1):
        db.add(
            AssetSlice(
                asset_id=asset_id,
                order_index=index,
                slice_type="image_region",
                start_seconds=0,
                end_seconds=0,
                summary=item["summary"],
                features=item.get("features") or {},
                usable_for=item["usable_for"],
                source_frame_path="",
                is_pinned=bool(item.get("is_pinned", False)),
            )
        )
    db.add(
        AssetEmbedding(
            asset_id=asset_id,
            model="preset-pseudo-embedding-v1",
            vector=_pseudo_embedding(filename, description, str(analysis)),
        )
    )


def _clear_asset_children(asset_id: Any, db: Session) -> None:
    db.query(AssetSlice).filter(AssetSlice.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetTag).filter(AssetTag.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetEmbedding).filter(AssetEmbedding.asset_id == asset_id).delete(synchronize_session=False)
    db.flush()


def _refresh_preset_collection(collection_id: Any, db: Session) -> None:
    db.expire_all()
    collection = _load_collection(collection_id, db)
    tag_names = sorted({tag.name for asset in collection.assets for tag in asset.tags})[:18]
    collection.status = "analyzed"
    collection.summary = (
        f"{len(collection.assets)} preset image assets analyzed with hero, angle, label, cap, glow, and CTA slices. "
        "Source video is not attached yet."
    )
    collection.coverage = {
        "appearance": True,
        "detail": True,
        "packaging": True,
        "premium_finish": True,
        "video_slices": False,
    }
    collection.tags = tag_names
    db.add(collection)
    db.commit()


def _load_collection(collection_id: Any, db: Session) -> AssetCollection:
    collection = db.scalar(
        select(AssetCollection)
        .where(AssetCollection.id == collection_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(AssetCollection.assets).selectinload(Asset.slices),
            selectinload(AssetCollection.assets).selectinload(Asset.tags),
            selectinload(AssetCollection.assets).selectinload(Asset.embedding),
        )
    )
    if collection is None:
        raise LookupError("Preset asset collection was not found after seeding.")
    return collection


def _preset_root() -> Path:
    return Path(get_settings().upload_dir).parent / "preset-assets"


def _pseudo_embedding(*values: str) -> list[float]:
    digest = hashlib.sha256("|".join(values).encode("utf-8")).digest()
    return [round((byte / 255) * 2 - 1, 4) for byte in digest[:12]]


def _preset_asset_specs() -> list[dict[str, Any]]:
    return [
        {
            "filename": "aurora-glow-bottle-front.png",
            "source_candidates": [
                "D:/Desktop/61da9cb3-bb9f-4028-8e31-bb6831f32fb3.png",
                str(_preset_root() / "aurora-glow-bottle-front.png"),
            ],
            "description": "Front hero product image for Aurora Glow Bottle with centered label, iridescent pastel body, polished cap, and clean reflective surface.",
            "analysis": _analysis(
                "Front-facing hero image of Aurora Glow Bottle, a premium 100ml iridescent beauty bottle with readable label and radiant pastel reflection.",
                "centered front hero bottle, readable Aurora Glow label, pastel glass-like body, metallic cap, soft studio reflection",
            ),
            "tags": ["beauty", "personal care", "fragrance", "aurora glow", "iridescent", "pastel", "premium packaging", "hero shot", "100ml"],
            "slices": [
                _slice("Hero shot: centered full bottle, readable label, premium pastel glow, ideal for opening frame.", "hook", "front hero", True),
                _slice("Proof/detail shot: cap, gold neck ring, and glass-like shoulder communicate premium packaging.", "proof", "cap and neck detail", True),
                _slice("CTA shot: clean centered product with empty soft background for price, offer, or shop-now overlay.", "cta", "clean offer composition"),
            ],
        },
        {
            "filename": "aurora-glow-bottle-angle.png",
            "source_candidates": [
                "D:/Desktop/d4aa0656-5752-4237-8c8f-99eadca4bd22.png",
                str(_preset_root() / "aurora-glow-bottle-angle.png"),
            ],
            "description": "Angled product image for Aurora Glow Bottle showing dimensional bottle shape, iridescent color shift, cap shine, and reflective shelf appeal.",
            "analysis": _analysis(
                "Angled product image showing Aurora Glow Bottle depth, color-shift finish, cap shine, and premium beauty shelf appeal.",
                "angled bottle pose, dimensional glass body, color-shift reflection, luminous background, premium beauty product mood",
            ),
            "tags": ["beauty", "fragrance", "angle shot", "color shift", "glow finish", "premium", "giftable", "shelf appeal", "radiance"],
            "slices": [
                _slice("Scene shot: angled bottle creates motion and depth for a premium beauty reveal.", "scene", "angled reveal", True),
                _slice("Visual shot: cyan, lavender, and pink reflections support the aurora/glow creative direction.", "visual", "color shift"),
                _slice("Trust shot: clear 100ml labeling and polished cap make the product feel finished and retail-ready.", "trust", "label and finish"),
            ],
        },
    ]


def _analysis(summary: str, retrieval_text: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "product_subject": "Aurora Glow Bottle",
        "category": PRESET_CATEGORY,
        "colors": ["cyan", "lavender", "pink", "pearl white", "gold"],
        "materials": ["glass-like bottle", "metallic cap", "reflective label"],
        "visible_details": ["Aurora Glow label", "100ml marking", "iridescent body", "polished cap", "radiant reflection"],
        "scale_cues": ["100ml beauty bottle", "single premium shelf product"],
        "usage_scenes": ["beauty shelf", "gift set", "vanity table", "premium product reveal"],
        "risk_tags": ["do not claim medical effect", "avoid unsupported skin-care or fragrance-performance claims"],
        "recommended_usage": ["hook", "proof", "scene", "visual", "cta"],
        "owner_script_notes": (
            "Open with the color-shift bottle reveal, then call out the luminous finish, premium 100ml packaging, "
            "giftable beauty-shelf look, and a soft CTA to try Aurora Glow today."
        ),
        "retrieval_text": f"Aurora Glow Bottle beauty personal care iridescent premium packaging {retrieval_text}",
    }


def _slice(summary: str, usable_for: str, detail: str, pinned: bool = False) -> dict[str, Any]:
    return {
        "summary": summary,
        "usable_for": usable_for,
        "is_pinned": pinned,
        "features": {
            "subject": "Aurora Glow Bottle",
            "category": PRESET_CATEGORY,
            "detail": detail,
            "colors": ["cyan", "lavender", "pink", "pearl white"],
            "materials": ["glass-like body", "metallic cap"],
            "usage_scenes": ["beauty shelf", "gift", "vanity table"],
            "usable_for": usable_for,
        },
    }
