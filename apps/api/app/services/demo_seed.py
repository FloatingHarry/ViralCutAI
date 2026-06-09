from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ViralFactor, ViralVideoAnalysis
from app.services.preset_seed import seed_preset_workspace


def seed_public_demo_data(db: Session) -> dict[str, Any]:
    preset = seed_preset_workspace(db)
    viral = _seed_viral_library(db)
    return {
        "status": "ready",
        "message": "Public demo assets and viral library seed data are ready.",
        "preset_assets": preset,
        "viral_library": viral,
    }


def _seed_viral_library(db: Session) -> dict[str, Any]:
    payload = _load_seed_payload()
    cover_count = 0
    video_count = 0
    factor_count = 0

    for item in payload.get("viral_videos") or []:
        if not isinstance(item, dict):
            continue
        record = _upsert_viral_video(item, db)
        if _copy_demo_cover(item):
            cover_count += 1
        record.analysis = _analysis_with_local_cover(item, record.id)
        db.add(record)
        video_count += 1

    db.flush()

    for item in payload.get("viral_factors") or []:
        if not isinstance(item, dict):
            continue
        _upsert_viral_factor(item, db)
        factor_count += 1

    db.commit()
    return {
        "status": "ready",
        "video_count": video_count,
        "factor_count": factor_count,
        "cover_count": cover_count,
    }


def _upsert_viral_video(item: dict[str, Any], db: Session) -> ViralVideoAnalysis:
    record_id = _uuid_or_none(item.get("id"))
    record = db.get(ViralVideoAnalysis, record_id) if record_id else None
    source_url = str(item.get("source_url") or "").strip()
    if record is None and source_url:
        record = db.scalar(select(ViralVideoAnalysis).where(ViralVideoAnalysis.source_url == source_url).limit(1))
    if record is None:
        record = ViralVideoAnalysis(id=record_id) if record_id else ViralVideoAnalysis()
    record.title = str(item.get("title") or "Demo viral reference")[:220]
    record.source_url = source_url
    record.category = str(item.get("category") or "general")[:120]
    record.source_statement = str(item.get("source_statement") or "Public demo viral-library seed record.")[:2000]
    db.add(record)
    db.flush()
    return record


def _upsert_viral_factor(item: dict[str, Any], db: Session) -> ViralFactor:
    record_id = _uuid_or_none(item.get("id"))
    record = db.get(ViralFactor, record_id) if record_id else None
    source = str(item.get("source") or "external:demo")[:120]
    factor_key = str(item.get("factor_key") or "")[:120]
    if record is None and factor_key:
        record = db.scalar(
            select(ViralFactor)
            .where(ViralFactor.source == source, ViralFactor.factor_key == factor_key)
            .limit(1)
        )
    if record is None:
        record = ViralFactor(id=record_id) if record_id else ViralFactor()
    record.factor_key = factor_key or "demo-factor"
    record.name = str(item.get("name") or "Demo viral factor")[:160]
    record.category = str(item.get("category") or "hook")[:80]
    record.source = source
    record.description = str(item.get("description") or "")[:2000]
    record.metadata_payload = dict(item.get("metadata_payload") or {})
    db.add(record)
    return record


def _analysis_with_local_cover(item: dict[str, Any], record_id: UUID) -> dict[str, Any]:
    analysis = dict(item.get("analysis") or {})
    source = dict(analysis.get("source") or {})
    thumbnail_url = str(item.get("thumbnail_url") or "").strip()
    if thumbnail_url:
        analysis.setdefault("thumbnail_url", thumbnail_url)
        source.setdefault("thumbnail_url", thumbnail_url)
    cover_path = _demo_cover_destination(item)
    if cover_path and cover_path.exists():
        local_cover_url = f"/viral-videos/{record_id}/cover"
        analysis.update({"cover_path": str(cover_path), "local_cover_url": local_cover_url})
        source.update({"cover_path": str(cover_path), "local_cover_url": local_cover_url})
    analysis["source"] = source
    return analysis


def _copy_demo_cover(item: dict[str, Any]) -> bool:
    source = _demo_cover_source(item)
    destination = _demo_cover_destination(item)
    if source is None or destination is None:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return True


def _demo_cover_source(item: dict[str, Any]) -> Path | None:
    filename = _safe_filename(item.get("cover_filename"))
    if not filename:
        return None
    path = _demo_data_root() / "viral-covers" / filename
    return path if path.exists() else None


def _demo_cover_destination(item: dict[str, Any]) -> Path | None:
    filename = _safe_filename(item.get("cover_filename"))
    if not filename:
        return None
    return Path(get_settings().upload_dir).parent / "viral-covers" / filename


def _load_seed_payload() -> dict[str, Any]:
    path = _demo_data_root() / "viral-library-seed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _demo_data_root() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "demo-data"


def _safe_filename(value: Any) -> str:
    text = Path(str(value or "")).name
    if not text or text in {".", ".."}:
        return ""
    return text


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
