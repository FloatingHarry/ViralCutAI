from __future__ import annotations

import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Asset, AssetSlice, GenerationRun, MediaArtifact, RunEvent


FPS = 30
DEFAULT_TARGET_DURATION_SECONDS = 12
MAX_TARGET_DURATION_SECONDS = 12


@dataclass(frozen=True)
class ExportProfile:
    aspect_ratio: str
    width: int
    height: int

    @property
    def slug(self) -> str:
        return self.aspect_ratio.replace(":", "x")


class AssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssemblyMaterial:
    material_id: str
    label: str
    kind: str
    path: Path
    usable_for: str = ""
    summary: str = ""
    slice_id: str | None = None
    asset_id: str | None = None
    start_seconds: int = 0
    end_seconds: int = 0


def assemble_generation_preview(
    run_id: UUID,
    db: Session,
    *,
    aspect_ratio: str = "9:16",
    include_bgm: bool = True,
    record_queued_event: bool = True,
) -> GenerationRun:
    run = _load_run(run_id, db)
    profile = _export_profile(aspect_ratio)
    work_dir = _render_root() / str(run.id) / profile.slug
    clip_dir = work_dir / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)

    run.preview = {
        **(run.preview or {}),
        "assembly_status": "running",
        "active_export_profile": profile.aspect_ratio,
    }
    if record_queued_event:
        queued_duration_seconds = _assembly_duration_seconds(run)
        _add_event(
            db,
            run,
            "assembly_queued",
            "queued",
            f"Local FFmpeg assembly queued for {profile.aspect_ratio}.",
            {"profile": _ffmpeg_profile(profile, include_bgm=include_bgm, has_audio=False, duration_seconds=queued_duration_seconds)},
        )
    db.add(run)
    db.commit()

    try:
        editor_clips = _editor_timeline_clips(run)
        if editor_clips:
            timeline_items = _resolve_editor_timeline_clips(run, db, editor_clips)
            target_duration_seconds = _timeline_items_total_duration(timeline_items)
            materials = [item["_material"] for item in timeline_items]
            timeline_mode = "editor_timeline"
        else:
            storyboard = _normalize_storyboard(run.storyboard)
            timeline_items = _resolve_storyboard_timeline_items(run, db, storyboard)
            target_duration_seconds = _timeline_items_total_duration(timeline_items)
            materials = [item["_material"] for item in timeline_items]
            timeline_mode = "storyboard"
        uploaded_audio_material = _resolve_audio_material(run, db) if include_bgm else None
        audio_material = uploaded_audio_material
        audio_source = "uploaded_audio" if uploaded_audio_material else None
        if not materials:
            raise AssemblyError("No usable image or video assets are attached. Upload or select at least one product asset before assembling video.")

        _add_event(
            db,
            run,
            "material_resolved",
            "completed",
            f"{len(materials)} usable source materials resolved for local assembly.",
            {"materials": [_material_payload(item) for item in materials]},
        )

        clip_paths: list[Path] = []
        source_shots: list[dict[str, Any]] = []
        for index, item in enumerate(timeline_items, start=1):
            material = item["_material"]
            duration = int(item.get("duration_seconds") or 3)
            clip_path = clip_dir / f"clip-{index:02d}.mp4"
            _render_clip(material, duration, clip_path, profile)
            clip_paths.append(clip_path)
            source_shots.append(
                {
                    "clip_id": item.get("clip_id"),
                    "shot_id": item.get("shot_id"),
                    "order_index": index,
                    "duration_seconds": duration,
                    "subtitle": item.get("subtitle"),
                    "voiceover": item.get("voiceover"),
                    "source_type": item.get("source_type") or item.get("source_mode"),
                    "selected_material": _material_payload(material),
                }
            )

        _add_event(
            db,
            run,
            "clips_rendered",
            "completed",
            f"{len(clip_paths)} local video clips rendered.",
            {"clip_count": len(clip_paths), "duration_seconds": sum(item["duration_seconds"] for item in source_shots)},
        )

        concat_path = work_dir / "concat.txt"
        stitched_path = work_dir / "stitched.mp4"
        subtitle_path = work_dir / "subtitles.ass"
        video_no_audio_path = work_dir / f"ffmpeg-preview-{profile.slug}-silent.mp4"
        output_path = work_dir / f"ffmpeg-preview-{profile.slug}.mp4"
        _write_concat_file(concat_path, clip_paths)
        _run_tool(
            [
                _tool_path("ffmpeg"),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                str(stitched_path),
            ]
        )
        _write_subtitles(subtitle_path, timeline_items, profile)
        _run_tool(
            [
                _tool_path("ffmpeg"),
                "-y",
                "-i",
                str(stitched_path.resolve()),
                "-vf",
                "subtitles=subtitles.ass",
                "-t",
                str(target_duration_seconds),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(video_no_audio_path.resolve()),
            ],
            cwd=work_dir,
        )
        if include_bgm and audio_material is None and timeline_mode == "editor_timeline":
            audio_material = _render_editor_timeline_audio(timeline_items, work_dir / "audio", target_duration_seconds)
            audio_source = "editor_timeline_audio" if audio_material else None
        if include_bgm and audio_material is None and timeline_mode != "editor_timeline":
            audio_material = _resolve_draft_audio_material(run)
            audio_source = "draft_audio" if audio_material else None
        if audio_material:
            _mix_audio(
                video_no_audio_path,
                audio_material,
                output_path,
                target_duration_seconds,
                volume=0.22 if audio_source == "uploaded_audio" else 1.0,
            )
            audio_message = (
                "Uploaded BGM/audio was mixed into the local preview. TTS voiceover remains a placeholder."
                if audio_source == "uploaded_audio"
                else "Editor timeline audio was cut and stitched to match the assembled clips."
                if audio_source == "editor_timeline_audio"
                else "The original continuous draft audio track was preserved under the assembled timeline."
            )
            _add_event(
                db,
                run,
                "audio_mixed" if audio_source == "uploaded_audio" else "editor_timeline_audio_synced" if audio_source == "editor_timeline_audio" else "draft_audio_preserved",
                "completed",
                audio_message,
                {"audio_source": audio_source, "audio": _material_payload(audio_material), "tts_status": "placeholder"},
            )
        else:
            output_path.write_bytes(video_no_audio_path.read_bytes())
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise AssemblyError("FFmpeg did not produce a playable preview file.")

        _add_event(
            db,
            run,
            "subtitles_burned",
            "completed",
            "Storyboard subtitles were burned into the local preview.",
            {"subtitle_file": str(subtitle_path)},
        )

        payload = {
            "file_path": str(output_path),
            "download_url": f"/generation-runs/{run.id}/assembled-video?aspect_ratio={profile.aspect_ratio}",
            "source_shots": source_shots,
            "timeline_mode": timeline_mode,
            "source_asset_slices": [item for item in [_material_payload(material) for material in materials] if item.get("slice_id")],
            "source_ai_segments": [
                item
                for item in [_material_payload(material) for material in materials]
                if str(item.get("material_id", "")).startswith(("draft:", "replacement:", "seedance:", "editor-draft:", "editor-replacement:"))
            ],
            "ffmpeg_profile": _ffmpeg_profile(
                profile,
                include_bgm=include_bgm,
                has_audio=bool(audio_material),
                audio_source=audio_source,
                duration_seconds=target_duration_seconds,
            ),
            "has_audio": bool(audio_material),
            "audio_source": audio_source,
            "audio_material": _material_payload(audio_material) if audio_material else None,
            "bgm_status": "mixed_from_uploaded_audio" if audio_source == "uploaded_audio" else "synced_from_editor_timeline" if audio_source == "editor_timeline_audio" else "preserved_from_draft_audio" if audio_source == "draft_audio" else "not_provided",
            "tts_status": "placeholder",
            "voiceover_audio_status": "tts_placeholder",
            "is_real_output": True,
            "duration_seconds": target_duration_seconds,
            "resolution": f"{profile.width}x{profile.height}",
            "aspect_ratio": profile.aspect_ratio,
            "command_summary": "FFmpeg scaled/cropped source assets, concatenated clips, burned ASS subtitles, optionally mixed uploaded audio, and exported H.264 MP4.",
        }
        _upsert_artifact(
            db,
            run,
            profile=profile,
            status="local_generated",
            payload=payload,
        )
        assembled_exports = {
            **((run.preview or {}).get("assembled_exports") if isinstance((run.preview or {}).get("assembled_exports"), dict) else {}),
            profile.aspect_ratio: payload["download_url"],
        }
        run.storyboard = _clear_storyboard_dirty(run.storyboard)
        preview_with_clean_timeline = _clear_preview_timeline_dirty(run.preview or {})
        run.preview = {
            **preview_with_clean_timeline,
            "mode": "local_ffmpeg_preview",
            "assembled_video_url": payload["download_url"],
            "assembled_duration_seconds": target_duration_seconds,
            "assembled_resolution": payload["resolution"],
            "assembled_aspect_ratio": payload["aspect_ratio"],
            "assembled_has_audio": bool(audio_material),
            "assembled_audio_source": audio_source,
            "assembled_bgm_status": payload["bgm_status"],
            "assembled_tts_status": payload["tts_status"],
            "assembled_exports": assembled_exports,
            "assembly_status": "succeeded",
            "assembled_stale": False,
            "editor_timeline_stale": False,
            "assembly_stale_reason": None,
            "active_regeneration_shot_id": None,
            "active_export_profile": profile.aspect_ratio,
        }
        local_exports = {
            **((run.export_manifest or {}).get("local_ffmpeg_exports") if isinstance((run.export_manifest or {}).get("local_ffmpeg_exports"), dict) else {}),
            profile.aspect_ratio: payload,
        }
        run.export_manifest = {
            **(run.export_manifest or {}),
            "local_ffmpeg_preview": payload,
            "local_ffmpeg_exports": local_exports,
        }
        _add_event(
            db,
            run,
            "video_assembled",
            "completed",
            f"Local FFmpeg {profile.aspect_ratio} preview is ready for playback and download.",
            {"download_url": payload["download_url"], "duration_seconds": target_duration_seconds, "has_audio": bool(audio_material)},
        )
        db.add(run)
        db.commit()
        return _load_run(run.id, db)
    except Exception as exc:
        message = _short_error(exc)
        _upsert_artifact(
            db,
            run,
            profile=profile,
            status="provider_failed",
            payload={
                "failure_reason": message,
                "ffmpeg_profile": _ffmpeg_profile(
                    profile,
                    include_bgm=include_bgm,
                    has_audio=False,
                    duration_seconds=_assembly_duration_seconds(run),
                ),
                "has_audio": False,
                "is_real_output": False,
                "aspect_ratio": profile.aspect_ratio,
                "tts_status": "placeholder",
            },
        )
        run.preview = {
            **(run.preview or {}),
            "assembly_status": "failed",
            "assembly_failure_reason": message,
            "active_export_profile": profile.aspect_ratio,
        }
        _add_event(db, run, "assembly_failed", "failed", message, {"error": message})
        db.add(run)
        db.commit()
        raise AssemblyError(message) from exc


def queue_assembly_preview(
    run_id: UUID,
    db: Session,
    *,
    aspect_ratio: str = "9:16",
    include_bgm: bool = True,
) -> GenerationRun:
    run = _load_run(run_id, db)
    profile = _export_profile(aspect_ratio)
    run.preview = {
        **(run.preview or {}),
        "assembly_status": "queued",
        "active_export_profile": profile.aspect_ratio,
    }
    _add_event(
        db,
        run,
        "assembly_queued",
        "queued",
        f"Local FFmpeg assembly queued for {profile.aspect_ratio}.",
        {"profile": _ffmpeg_profile(profile, include_bgm=include_bgm, has_audio=False, duration_seconds=_assembly_duration_seconds(run))},
    )
    db.add(run)
    db.commit()
    return _load_run(run.id, db)


def execute_assembly_preview_task(run_id: UUID, aspect_ratio: str = "9:16", include_bgm: bool = True) -> None:
    db = SessionLocal()
    try:
        assemble_generation_preview(
            run_id,
            db,
            aspect_ratio=aspect_ratio,
            include_bgm=include_bgm,
            record_queued_event=False,
        )
    except Exception:
        # assemble_generation_preview writes the failure artifact/event before raising.
        pass
    finally:
        db.close()


def assembled_video_path(run_id: UUID, db: Session, *, aspect_ratio: str | None = None) -> Path:
    run = _load_run(run_id, db)
    profile = _export_profile(aspect_ratio or str((run.preview or {}).get("assembled_aspect_ratio") or "9:16"))
    artifact = next(
        (
            item
            for item in reversed(run.artifacts)
            if item.artifact_type.startswith("ffmpeg_assembled_video")
            and (not aspect_ratio or (item.payload or {}).get("aspect_ratio") == profile.aspect_ratio)
        ),
        None,
    )
    path_value = (artifact.payload or {}).get("file_path") if artifact else None
    if not path_value:
        path_value = (run.preview or {}).get("assembled_video_path")
    if not path_value:
        path_value = _render_root() / str(run.id) / profile.slug / f"ffmpeg-preview-{profile.slug}.mp4"
    path = Path(str(path_value))
    if not path.exists() or path.stat().st_size <= 0:
        raise LookupError("Assembled video file not found")
    return path


def editor_clip_video_path(
    run_id: UUID,
    db: Session,
    *,
    clip_id: str = "",
    shot_id: str = "",
    source_type: str = "draft_segment",
) -> Path:
    run = _load_run(run_id, db)
    clip = _editor_clip_for_preview(run, clip_id=clip_id, shot_id=shot_id, source_type=source_type)
    material = _material_for_editor_clip(run, db, clip)
    duration = max(1, int(clip.get("duration_seconds") or material.end_seconds - material.start_seconds or 1))
    output_dir = _render_root() / str(run.id) / "editor-preview-clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    key = _safe_filename(
        "-".join(
            [
                str(clip.get("clip_id") or shot_id or "clip"),
                str(clip.get("source_type") or source_type),
                str(clip.get("source_start_seconds") or 0),
                str(clip.get("source_end_seconds") or duration),
            ]
        )
    )
    output = output_dir / f"{key}.mp4"
    if output.exists() and output.stat().st_size > 0:
        return output
    _render_clip(material, duration, output, _export_profile("9:16"))
    return output


def _load_run(run_id: UUID, db: Session) -> GenerationRun:
    run = db.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run_id)
        .options(
            selectinload(GenerationRun.assets),
            selectinload(GenerationRun.events),
            selectinload(GenerationRun.artifacts),
        )
    )
    if run is None:
        raise LookupError("Generation run not found")
    return run


def _editor_timeline_clips(run: GenerationRun) -> list[dict[str, Any]]:
    timeline = (run.preview or {}).get("editor_timeline")
    if not isinstance(timeline, dict):
        return []
    clips = timeline.get("clips")
    if not isinstance(clips, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(clips, start=1):
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            continue
        source_type = str(raw.get("source_type") or "")
        if source_type not in {"draft_segment", "replacement_clip", "asset_slice"}:
            continue
        duration = max(1, int(raw.get("duration_seconds") or 1))
        source_start = max(0, int(raw.get("source_start_seconds") or 0))
        source_end = max(source_start + 1, int(raw.get("source_end_seconds") or source_start + duration))
        normalized.append(
            {
                **raw,
                "clip_id": str(raw.get("clip_id") or f"clip-{index}"),
                "order_index": index,
                "source_type": source_type,
                "duration_seconds": min(duration, source_end - source_start),
                "source_start_seconds": source_start,
                "source_end_seconds": source_end,
            }
        )
    return normalized


def _editor_clip_for_preview(run: GenerationRun, *, clip_id: str, shot_id: str, source_type: str) -> dict[str, Any]:
    timeline_clips = _editor_timeline_clips(run)
    for clip in timeline_clips:
        if clip_id and str(clip.get("clip_id") or "") == clip_id:
            return clip
    if shot_id:
        preferred_source = "replacement_clip" if source_type == "replacement_clip" else "draft_segment"
        for clip in timeline_clips:
            if str(clip.get("shot_id") or "") == shot_id and str(clip.get("source_type") or "") == preferred_source:
                return clip
    segments = [
        item
        for item in (run.preview or {}).get("timeline_segments") or []
        if isinstance(item, dict) and (not shot_id or str(item.get("shot_id") or "") == shot_id)
    ]
    if not segments:
        raise AssemblyError("Editor clip preview source was not found.")
    segment = segments[0]
    return {
        "clip_id": clip_id or f"preview-{segment.get('shot_id')}",
        "source_type": "replacement_clip" if source_type == "replacement_clip" else "draft_segment",
        "shot_id": segment.get("shot_id"),
        "asset_slice_id": None,
        "label": segment.get("beat") or segment.get("shot_id") or "Segment",
        "subtitle": segment.get("subtitle") or "",
        "voiceover": segment.get("voiceover") or "",
        "source_start_seconds": 0 if source_type == "replacement_clip" else int(segment.get("start_seconds") or 0),
        "source_end_seconds": (
            int(segment.get("duration_seconds") or 4)
            if source_type == "replacement_clip"
            else int(segment.get("end_seconds") or int(segment.get("start_seconds") or 0) + int(segment.get("duration_seconds") or 4))
        ),
        "duration_seconds": int(segment.get("duration_seconds") or 4),
        "enabled": True,
        "source_label": _editor_source_label("replacement_clip" if source_type == "replacement_clip" else "draft_segment"),
    }


def _resolve_editor_timeline_clips(run: GenerationRun, db: Session, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for index, clip in enumerate(clips, start=1):
        material = _material_for_editor_clip(run, db, clip)
        audio_material = _audio_material_for_editor_clip(run, material, clip)
        duration = max(1, int(clip.get("duration_seconds") or material.end_seconds - material.start_seconds or 1))
        resolved.append(
            {
                "clip_id": clip.get("clip_id") or f"clip-{index}",
                "shot_id": clip.get("shot_id"),
                "order_index": index,
                "duration_seconds": duration,
                "subtitle": clip.get("subtitle") or clip.get("label") or "",
                "voiceover": clip.get("voiceover") or "",
                "source_type": clip.get("source_type"),
                "_material": material,
                "_audio_material": audio_material,
            }
        )
    if not resolved:
        raise AssemblyError("Editor timeline has no enabled clips.")
    return resolved


def _audio_material_for_editor_clip(run: GenerationRun, material: AssemblyMaterial, clip: dict[str, Any]) -> AssemblyMaterial | None:
    source_type = str(clip.get("source_type") or "")
    if source_type == "replacement_clip":
        shot_range = _shot_time_range(run, str(clip.get("shot_id") or ""))
        draft = _draft_video_artifact(run)
        if draft is not None and draft.status == "real_generated" and (draft.payload or {}).get("video_url"):
            try:
                draft_path = _cached_draft_path(run, draft)
            except AssemblyError:
                draft_path = None
            if draft_path and _has_audio_stream(draft_path):
                start = shot_range[0] + max(0, int(clip.get("source_start_seconds") or 0))
                return AssemblyMaterial(
                    material_id=f"editor-audio-draft:{clip.get('clip_id')}",
                    label=f"Draft audio for replacement / {clip.get('shot_id')}",
                    kind="audio",
                    path=draft_path,
                    usable_for=str(clip.get("shot_id") or ""),
                    summary="Original draft audio aligned under a replacement visual clip.",
                    start_seconds=start,
                    end_seconds=start + max(1, int(clip.get("duration_seconds") or 1)),
                )
        return None
    if material.kind == "video" and _has_audio_stream(material.path):
        return AssemblyMaterial(
            material_id=f"editor-audio:{clip.get('clip_id')}",
            label=f"Timeline audio / {clip.get('label') or clip.get('clip_id')}",
            kind="audio",
            path=material.path,
            usable_for=material.usable_for,
            summary="Audio cut from the same source segment as the editor clip.",
            slice_id=material.slice_id,
            asset_id=material.asset_id,
            start_seconds=material.start_seconds,
            end_seconds=material.end_seconds,
        )
    return None


def _shot_time_range(run: GenerationRun, shot_id: str) -> tuple[int, int]:
    cursor = 0
    for shot in sorted(run.storyboard, key=lambda item: int(item.get("order_index") or 0)):
        duration = max(1, int(shot.get("duration_seconds") or 1))
        start = cursor
        cursor += duration
        if str(shot.get("shot_id") or "") == shot_id:
            return start, cursor
    return 0, max(1, int(run.request_payload.get("duration_seconds") or DEFAULT_TARGET_DURATION_SECONDS))


def _resolve_storyboard_timeline_items(run: GenerationRun, db: Session, storyboard: list[dict[str, Any]]) -> list[dict[str, Any]]:
    materials = _resolve_materials(run, db)
    if not materials:
        raise AssemblyError("No usable image or video assets are attached. Upload or select at least one product asset before assembling video.")
    timeline_items: list[dict[str, Any]] = []
    for index, shot in enumerate(storyboard, start=1):
        material = _material_for_shot(shot, materials, index)
        timeline_items.append(
            {
                **shot,
                "clip_id": f"storyboard-{shot.get('shot_id') or index}",
                "source_type": shot.get("source_mode") or "storyboard",
                "_material": material,
            }
        )
    return timeline_items


def _material_for_editor_clip(run: GenerationRun, db: Session, clip: dict[str, Any]) -> AssemblyMaterial:
    source_type = str(clip.get("source_type") or "")
    if source_type == "asset_slice":
        slice_id = _uuid_or_none(clip.get("asset_slice_id") or clip.get("selected_asset_slice_id"))
        if slice_id is None:
            raise AssemblyError(f"{clip.get('clip_id')} is missing asset_slice_id.")
        item = db.scalar(select(AssetSlice).where(AssetSlice.id == slice_id).options(selectinload(AssetSlice.asset)))
        if item is None:
            raise AssemblyError(f"Asset slice {slice_id} was not found.")
        materials = _materials_from_asset_slice(item)
        if not materials:
            raise AssemblyError(f"Asset slice {slice_id} has no usable video or image file.")
        return _material_with_editor_range(materials[0], clip, material_id=f"editor-asset:{clip.get('clip_id')}")

    shot_id = str(clip.get("shot_id") or "")
    if not shot_id:
        raise AssemblyError(f"{clip.get('clip_id')} is missing shot_id.")
    if source_type == "replacement_clip":
        replacement = _replacement_clip_artifacts(run).get(shot_id)
        payload = replacement.payload if replacement else {}
        if replacement is None or replacement.status != "real_generated" or not payload.get("video_url"):
            raise AssemblyError(f"{shot_id} replacement clip is not ready.")
        cache_dir = _render_root() / str(run.id) / "editor-sources"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"replacement-{_safe_filename(shot_id)}.mp4"
        if not path.exists() or path.stat().st_size <= 0:
            _download_clip(str(payload.get("video_url") or ""), path)
        return AssemblyMaterial(
            material_id=f"editor-replacement:{clip.get('clip_id')}",
            label=f"Replacement clip / {shot_id}",
            kind="video",
            path=path,
            usable_for=shot_id,
            summary=str(clip.get("label") or f"Replacement clip for {shot_id}."),
            start_seconds=max(0, int(clip.get("source_start_seconds") or 0)),
            end_seconds=max(1, int(clip.get("source_end_seconds") or clip.get("duration_seconds") or 1)),
        )

    draft = _draft_video_artifact(run)
    if draft is None or draft.status != "real_generated" or not (draft.payload or {}).get("video_url"):
        raise AssemblyError("Continuous draft video is not ready for editor timeline assembly.")
    return AssemblyMaterial(
        material_id=f"editor-draft:{clip.get('clip_id')}",
        label=f"Draft video slice / {shot_id}",
        kind="video",
        path=_cached_draft_path(run, draft),
        usable_for=shot_id,
        summary=str(clip.get("label") or f"Draft slice for {shot_id}."),
        start_seconds=max(0, int(clip.get("source_start_seconds") or 0)),
        end_seconds=max(1, int(clip.get("source_end_seconds") or clip.get("duration_seconds") or 1)),
    )


def _material_with_editor_range(material: AssemblyMaterial, clip: dict[str, Any], *, material_id: str) -> AssemblyMaterial:
    source_start = max(0, int(clip.get("source_start_seconds") or material.start_seconds or 0))
    duration = max(1, int(clip.get("duration_seconds") or material.end_seconds - material.start_seconds or 1))
    source_end = max(source_start + 1, int(clip.get("source_end_seconds") or source_start + duration))
    return AssemblyMaterial(
        material_id=material_id,
        label=str(clip.get("label") or material.label),
        kind=material.kind,
        path=material.path,
        usable_for=material.usable_for,
        summary=str(clip.get("voiceover") or clip.get("subtitle") or material.summary),
        slice_id=material.slice_id,
        asset_id=material.asset_id,
        start_seconds=source_start,
        end_seconds=source_end,
    )


def _timeline_items_total_duration(items: list[dict[str, Any]]) -> int:
    return sum(max(1, int(item.get("duration_seconds") or 1)) for item in items)


def _assembly_duration_seconds(run: GenerationRun) -> int:
    editor = _editor_timeline_clips(run)
    if editor:
        return _timeline_items_total_duration(editor)
    if run.storyboard:
        try:
            return _storyboard_total_duration(_normalize_storyboard(run.storyboard))
        except AssemblyError:
            return DEFAULT_TARGET_DURATION_SECONDS
    return DEFAULT_TARGET_DURATION_SECONDS


def _resolve_materials(run: GenerationRun, db: Session) -> list[AssemblyMaterial]:
    materials: list[AssemblyMaterial] = []
    seen: set[str] = set()

    def add(material: AssemblyMaterial) -> None:
        key = f"{material.kind}:{material.path}:{material.slice_id or material.material_id}:{material.start_seconds}:{material.end_seconds}"
        if key in seen or not material.path.exists() or material.kind not in {"image", "video"}:
            return
        seen.add(key)
        materials.append(material)

    draft_artifact = _draft_video_artifact(run)
    if draft_artifact is not None:
        missing = _missing_ready_draft_segments(run, draft_artifact)
        if missing:
            raise AssemblyError(f"AI draft timeline is not ready for assembly: {', '.join(missing)}.")
        for material in _materials_from_draft_timeline(run, draft_artifact):
            add(material)
        for material in _selected_slice_materials(run, db):
            add(material)
        return materials

    ai_clip_artifacts = [artifact for artifact in run.artifacts if artifact.artifact_type == "seedance_shot_clip"]
    if ai_clip_artifacts:
        missing = _missing_ready_ai_clip_shots(run, ai_clip_artifacts)
        if missing:
            raise AssemblyError(f"AI shot clips are not ready for assembly: {', '.join(missing)}.")
        for material in _materials_from_seedance_shot_clips(run, ai_clip_artifacts):
            add(material)
        return materials

    slice_ids = _slice_ids_from_run(run)
    if slice_ids:
        slices = db.scalars(
            select(AssetSlice)
            .where(AssetSlice.id.in_(slice_ids))
            .options(selectinload(AssetSlice.asset))
        ).all()
        for item in slices:
            for material in _materials_from_asset_slice(item):
                add(material)

    asset_ids = _uuid_list(run.request_payload.get("asset_ids", []))
    collection_id = _uuid_or_none(run.request_payload.get("asset_collection_id"))
    statement = select(Asset).options(selectinload(Asset.slices))
    filters = []
    if asset_ids:
        filters.append(Asset.id.in_(asset_ids))
    if collection_id:
        filters.append(Asset.collection_id == collection_id)
    for asset_filter in filters:
        for asset in db.scalars(statement.where(asset_filter)).all():
            for material in _materials_from_asset(asset):
                add(material)

    for asset in run.assets:
        for material in _materials_from_source_asset(asset):
            add(material)

    return materials


def _selected_slice_materials(run: GenerationRun, db: Session) -> list[AssemblyMaterial]:
    slice_ids = _slice_ids_from_run(run)
    if not slice_ids:
        return []
    materials: list[AssemblyMaterial] = []
    slices = db.scalars(
        select(AssetSlice)
        .where(AssetSlice.id.in_(slice_ids))
        .options(selectinload(AssetSlice.asset))
    ).all()
    for item in slices:
        materials.extend(_materials_from_asset_slice(item))
    return materials


def _resolve_audio_material(run: GenerationRun, db: Session) -> AssemblyMaterial | None:
    candidates: list[AssemblyMaterial] = []

    def add(material: AssemblyMaterial) -> None:
        if material.kind == "audio" and material.path.exists():
            candidates.append(material)

    for asset in run.assets:
        for material in _materials_from_source_asset(asset):
            add(material)

    asset_ids = _uuid_list(run.request_payload.get("asset_ids", []))
    collection_id = _uuid_or_none(run.request_payload.get("asset_collection_id"))
    statement = select(Asset).options(selectinload(Asset.slices))
    filters = []
    if asset_ids:
        filters.append(Asset.id.in_(asset_ids))
    if collection_id:
        filters.append(Asset.collection_id == collection_id)
    for asset_filter in filters:
        for asset in db.scalars(statement.where(asset_filter)).all():
            for material in _materials_from_asset(asset):
                add(material)

    return candidates[0] if candidates else None


def _resolve_draft_audio_material(run: GenerationRun) -> AssemblyMaterial | None:
    draft_artifact = _draft_video_artifact(run)
    if draft_artifact is None:
        return None
    payload = draft_artifact.payload or {}
    if draft_artifact.status != "real_generated" or not payload.get("video_url"):
        return None
    try:
        draft_path = _cached_draft_path(run, draft_artifact)
    except AssemblyError:
        return None
    if not _has_audio_stream(draft_path):
        return None
    return AssemblyMaterial(
        material_id="draft_audio",
        label="Continuous draft audio",
        kind="audio",
        path=draft_path,
        summary="Original Seedance continuous draft audio preserved for timeline assembly.",
    )


def _draft_video_artifact(run: GenerationRun) -> MediaArtifact | None:
    return next(
        (
            artifact
            for artifact in reversed(run.artifacts)
            if artifact.artifact_type in {"seedance_draft_video", "video_real"}
        ),
        None,
    )


def _replacement_clip_artifacts(run: GenerationRun) -> dict[str, MediaArtifact]:
    return {
        str((artifact.payload or {}).get("shot_id")): artifact
        for artifact in run.artifacts
        if artifact.artifact_type == "seedance_replacement_clip" and (artifact.payload or {}).get("shot_id")
    }


def _missing_ready_draft_segments(run: GenerationRun, draft_artifact: MediaArtifact) -> list[str]:
    payload = draft_artifact.payload or {}
    if draft_artifact.status != "real_generated" or not payload.get("video_url"):
        return ["continuous draft video"]
    missing: list[str] = []
    for shot_id, artifact in _replacement_clip_artifacts(run).items():
        replacement_payload = artifact.payload or {}
        status = str(artifact.status or "").lower()
        if status == "real_generated" and replacement_payload.get("video_url"):
            continue
        if status == "real_task_pending":
            missing.append(f"{shot_id} replacement clip")
    return missing


def _materials_from_draft_timeline(run: GenerationRun, draft_artifact: MediaArtifact) -> list[AssemblyMaterial]:
    cache_dir = _render_root() / str(run.id) / "ai-draft"
    draft_path = _cached_draft_path(run, draft_artifact)

    replacement_artifacts = _replacement_clip_artifacts(run)
    materials: list[AssemblyMaterial] = []
    cursor = 0
    for shot in sorted(run.storyboard, key=lambda item: int(item.get("order_index") or 0)):
        shot_id = str(shot.get("shot_id") or f"shot-{shot.get('order_index')}")
        duration = int(shot.get("duration_seconds") or DEFAULT_TARGET_DURATION_SECONDS)
        start = cursor
        cursor += duration
        replacement = replacement_artifacts.get(shot_id)
        replacement_payload = replacement.payload if replacement else {}
        if replacement and replacement.status == "real_generated" and replacement_payload.get("video_url"):
            replacement_path = cache_dir / f"replacement-{_safe_filename(shot_id)}.mp4"
            if not replacement_path.exists() or replacement_path.stat().st_size <= 0:
                _download_clip(str(replacement_payload.get("video_url") or ""), replacement_path)
            materials.append(
                AssemblyMaterial(
                    material_id=f"replacement:{shot_id}",
                    label=f"Replacement clip / {shot_id}",
                    kind="video",
                    path=replacement_path,
                    usable_for=shot_id,
                    summary=f"Seedance replacement clip for {shot.get('beat')}.",
                    start_seconds=0,
                    end_seconds=int(replacement_payload.get("duration_seconds") or duration),
                )
            )
            continue
        materials.append(
            AssemblyMaterial(
                material_id=f"draft:{shot_id}",
                label=f"Draft slice / {shot_id}",
                kind="video",
                path=draft_path,
                usable_for=shot_id,
                summary=f"Continuous Seedance draft slice {start}-{cursor}s for {shot.get('beat')}.",
                start_seconds=start,
                end_seconds=cursor,
            )
        )
    return materials


def _cached_draft_path(run: GenerationRun, draft_artifact: MediaArtifact) -> Path:
    draft_payload = draft_artifact.payload or {}
    draft_url = str(draft_payload.get("video_url") or "")
    cache_dir = _render_root() / str(run.id) / "ai-draft"
    cache_dir.mkdir(parents=True, exist_ok=True)
    draft_path = cache_dir / "continuous-draft.mp4"
    if not draft_path.exists() or draft_path.stat().st_size <= 0:
        _download_clip(draft_url, draft_path)
    return draft_path


def _missing_ready_ai_clip_shots(run: GenerationRun, artifacts: list[MediaArtifact]) -> list[str]:
    by_shot = {
        str((artifact.payload or {}).get("shot_id") or ""): artifact
        for artifact in artifacts
        if (artifact.payload or {}).get("shot_id")
    }
    missing: list[str] = []
    for shot in run.storyboard:
        shot_id = str(shot.get("shot_id") or "")
        artifact = by_shot.get(shot_id)
        payload = artifact.payload if artifact else {}
        if artifact is None or artifact.status != "real_generated" or not payload.get("video_url"):
            missing.append(shot_id or f"shot-{shot.get('order_index')}")
    return missing


def _materials_from_seedance_shot_clips(run: GenerationRun, artifacts: list[MediaArtifact]) -> list[AssemblyMaterial]:
    by_shot = {
        str((artifact.payload or {}).get("shot_id") or ""): artifact
        for artifact in artifacts
        if (artifact.payload or {}).get("shot_id")
    }
    materials: list[AssemblyMaterial] = []
    cache_dir = _render_root() / str(run.id) / "ai-clips"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for shot in sorted(run.storyboard, key=lambda item: int(item.get("order_index") or 0)):
        shot_id = str(shot.get("shot_id") or f"shot-{shot.get('order_index')}")
        artifact = by_shot[shot_id]
        payload = artifact.payload or {}
        video_url = str(payload.get("video_url") or "")
        clip_path = cache_dir / f"{_safe_filename(shot_id)}.mp4"
        if not clip_path.exists() or clip_path.stat().st_size <= 0:
            _download_clip(video_url, clip_path)
        materials.append(
            AssemblyMaterial(
                material_id=f"seedance:{shot_id}",
                label=f"AI draft clip / {shot_id}",
                kind="video",
                path=clip_path,
                usable_for=shot_id,
                summary=f"Seedance AI draft clip for {shot.get('beat')}.",
                start_seconds=0,
                end_seconds=int(payload.get("duration_seconds") or shot.get("duration_seconds") or DEFAULT_TARGET_DURATION_SECONDS),
            )
        )
    return materials


def _download_clip(url: str, output: Path) -> None:
    if not url:
        raise AssemblyError("Seedance clip URL is missing.")
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            output.write_bytes(response.content)
    except Exception as exc:
        raise AssemblyError(f"Failed to download Seedance clip for assembly: {_short_error(exc)}") from exc


def _materials_from_asset(asset: Asset) -> list[AssemblyMaterial]:
    path = Path(asset.storage_path or "")
    kind = _material_kind(asset.content_type, path)
    if kind not in {"image", "video", "audio"}:
        return []
    if kind == "audio":
        return [
            AssemblyMaterial(
                material_id=str(asset.id),
                label=asset.filename,
                kind=kind,
                path=path,
                asset_id=str(asset.id),
                summary=asset.description,
            )
        ]
    if asset.slices:
        materials = []
        for item in asset.slices:
            materials.extend(_materials_from_asset_slice(item))
        return materials
    return [
        AssemblyMaterial(
            material_id=str(asset.id),
            label=asset.filename,
            kind=kind,
            path=path,
            asset_id=str(asset.id),
            summary=asset.description,
        )
    ]


def _materials_from_asset_slice(item: AssetSlice) -> list[AssemblyMaterial]:
    asset = item.asset
    if asset is None:
        return []
    path = Path(asset.storage_path or "")
    kind = _material_kind(asset.content_type, path)
    if kind not in {"image", "video"}:
        return []
    return [
        AssemblyMaterial(
            material_id=str(item.id),
            label=f"{asset.filename} / slice {item.order_index}",
            kind=kind,
            path=path,
            usable_for=item.usable_for,
            summary=item.summary,
            slice_id=str(item.id),
            asset_id=str(asset.id),
            start_seconds=int(item.start_seconds or 0),
            end_seconds=int(item.end_seconds or 0),
        )
    ]


def _materials_from_source_asset(asset: Any) -> list[AssemblyMaterial]:
    path = Path(asset.storage_path or "")
    kind = _material_kind(asset.content_type, path)
    if kind not in {"image", "video", "audio"}:
        return []
    return [
        AssemblyMaterial(
            material_id=str(asset.id),
            label=asset.filename,
            kind=kind,
            path=path,
            asset_id=str(asset.id),
            summary=asset.description,
        )
    ]


def _material_for_shot(shot: dict[str, Any], materials: list[AssemblyMaterial], index: int) -> AssemblyMaterial:
    shot_id = str(shot.get("shot_id") or "")
    if shot_id:
        match = next(
            (
                item
                for item in materials
                if item.material_id in {f"replacement:{shot_id}", f"seedance:{shot_id}"}
            ),
            None,
        )
        if match:
            return match
    selected_slice = str(shot.get("selected_asset_slice_id") or "")
    if selected_slice:
        match = next((item for item in materials if item.slice_id == selected_slice), None)
        if match:
            return match
    if shot_id:
        match = next(
            (
                item
                for item in materials
                if item.material_id == f"draft:{shot_id}" or item.usable_for == shot_id
            ),
            None,
        )
        if match:
            return match
    shot_text = " ".join(
        str(value).lower()
        for value in [shot.get("beat"), shot.get("visual_description"), shot.get("subtitle"), shot.get("voiceover")]
        if value
    )
    if "hook" in shot_text:
        preferred = ["hook"]
    elif "proof" in shot_text or "detail" in shot_text or "close" in shot_text:
        preferred = ["proof", "detail"]
    elif "cta" in shot_text or "offer" in shot_text:
        preferred = ["cta"]
    else:
        preferred = ["usage", "scene"]
    match = next(
        (
            item
            for item in materials
            if any(value in item.usable_for.lower() or value in item.summary.lower() for value in preferred)
        ),
        None,
    )
    return match or materials[(index - 1) % len(materials)]


def _render_clip(material: AssemblyMaterial, duration: int, output: Path, profile: ExportProfile) -> None:
    duration = max(1, int(duration))
    if material.kind == "image":
        _run_tool(
            [
                _tool_path("ffmpeg"),
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(material.path),
                "-t",
                str(duration),
                "-vf",
                f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,crop={profile.width}:{profile.height},setsar=1,fps={FPS},format=yuv420p",
                "-an",
                "-r",
                str(FPS),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ]
        )
        return

    start = max(0, int(material.start_seconds or 0))
    _run_tool(
        [
            _tool_path("ffmpeg"),
            "-y",
            "-stream_loop",
            "-1",
            "-ss",
            str(start),
            "-i",
            str(material.path),
            "-t",
            str(duration),
            "-vf",
            f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,crop={profile.width}:{profile.height},setsar=1,fps={FPS},format=yuv420p",
            "-an",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    )


def _mix_audio(video_path: Path, audio_material: AssemblyMaterial, output_path: Path, duration_seconds: int, *, volume: float) -> None:
    _run_tool(
        [
            _tool_path("ffmpeg"),
            "-y",
            "-i",
            str(video_path.resolve()),
            "-stream_loop",
            "-1",
            "-i",
            str(audio_material.path.resolve()),
            "-t",
            str(max(1, int(duration_seconds or DEFAULT_TARGET_DURATION_SECONDS))),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-filter:a",
            f"volume={volume:.2f}",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path.resolve()),
        ]
    )


def _render_editor_timeline_audio(timeline_items: list[dict[str, Any]], audio_dir: Path, duration_seconds: int) -> AssemblyMaterial | None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []
    for index, item in enumerate(timeline_items, start=1):
        duration = max(1, int(item.get("duration_seconds") or 1))
        segment_path = audio_dir / f"audio-{index:02d}.m4a"
        audio_material = item.get("_audio_material")
        if isinstance(audio_material, AssemblyMaterial):
            _render_audio_segment(audio_material, duration, segment_path)
        else:
            _render_silence_segment(duration, segment_path)
        segment_paths.append(segment_path)
    if not segment_paths:
        return None
    concat_path = audio_dir / "audio-concat.txt"
    output_path = audio_dir / "editor-timeline-audio.m4a"
    _write_concat_file(concat_path, segment_paths)
    _run_tool(
        [
            _tool_path("ffmpeg"),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-t",
            str(max(1, int(duration_seconds or DEFAULT_TARGET_DURATION_SECONDS))),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
    )
    if not output_path.exists() or output_path.stat().st_size <= 0 or not _has_audio_stream(output_path):
        return None
    return AssemblyMaterial(
        material_id="editor_timeline_audio",
        label="Editor timeline synced audio",
        kind="audio",
        path=output_path,
        summary="Audio stitched from the same source ranges as the editor timeline clips.",
        start_seconds=0,
        end_seconds=max(1, int(duration_seconds or DEFAULT_TARGET_DURATION_SECONDS)),
    )


def _render_audio_segment(material: AssemblyMaterial, duration: int, output: Path) -> None:
    _run_tool(
        [
            _tool_path("ffmpeg"),
            "-y",
            "-ss",
            str(max(0, int(material.start_seconds or 0))),
            "-i",
            str(material.path.resolve()),
            "-t",
            str(max(1, int(duration or 1))),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output.resolve()),
        ]
    )


def _render_silence_segment(duration: int, output: Path) -> None:
    _run_tool(
        [
            _tool_path("ffmpeg"),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(max(1, int(duration or 1))),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output.resolve()),
        ]
    )


def _has_audio_stream(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        output = _run_tool(
            [
                _tool_path("ffprobe"),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )
    except AssemblyError:
        return False
    return bool(output.strip())


def _clear_storyboard_dirty(storyboard: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**shot, "dirty": False} if isinstance(shot, dict) else shot for shot in storyboard]


def _clear_preview_timeline_dirty(preview: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(preview)
    for key in ("timeline_segments", "timeline_clips"):
        value = cleaned.get(key)
        if isinstance(value, list):
            cleaned[key] = [{**item, "dirty": False} if isinstance(item, dict) else item for item in value]
    timeline = cleaned.get("editor_timeline")
    if isinstance(timeline, dict) and isinstance(timeline.get("clips"), list):
        cleaned["editor_timeline"] = {
            **timeline,
            "clips": [{**item, "dirty": False} if isinstance(item, dict) else item for item in timeline.get("clips") or []],
        }
    cleaned["editor_timeline_stale"] = False
    return cleaned


def _normalize_storyboard(storyboard: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [dict(item) for item in storyboard if isinstance(item, dict)]
    if not items:
        raise AssemblyError("Storyboard is empty. Run the agents before assembling video.")
    durations = [max(1, int(item.get("duration_seconds") or 1)) for item in items]
    total = sum(durations)
    if total < 4 or total > MAX_TARGET_DURATION_SECONDS:
        durations = _rebalance_durations(durations, max(4, min(total or DEFAULT_TARGET_DURATION_SECONDS, MAX_TARGET_DURATION_SECONDS)))
    for item, duration in zip(items, durations, strict=False):
        item["duration_seconds"] = duration
    return items


def _rebalance_durations(durations: list[int], total_seconds: int) -> list[int]:
    if not durations:
        return []
    count = len(durations)
    if count > total_seconds:
        return [1 for _ in range(count)]
    normalized = [max(1, int(value)) for value in durations]
    while sum(normalized) > total_seconds:
        index = max(range(len(normalized)), key=lambda i: normalized[i])
        if normalized[index] <= 1:
            break
        normalized[index] -= 1
    index = len(normalized) - 1
    while sum(normalized) < total_seconds:
        normalized[index] += 1
        index = (index - 1) % len(normalized)
    return normalized


def _write_concat_file(path: Path, clip_paths: list[Path]) -> None:
    lines = [f"file '{clip.resolve().as_posix()}'" for clip in clip_paths]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_subtitles(path: Path, storyboard: list[dict[str, Any]], profile: ExportProfile) -> None:
    font_size = 54 if profile.aspect_ratio == "9:16" else 42 if profile.aspect_ratio == "16:9" else 46
    margin_v = 112 if profile.aspect_ratio == "9:16" else 56
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {profile.width}",
        f"PlayResY: {profile.height}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&HAA000000,&H99000000,1,0,0,0,100,100,0,0,1,4,1,2,48,48,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cursor = 0
    for shot in storyboard:
        duration = max(1, int(shot.get("duration_seconds") or 1))
        start = cursor
        end = cursor + duration
        text = _ass_text(str(shot.get("subtitle") or shot.get("voiceover") or ""))
        if text:
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
        cursor = end
    path.write_text("\n".join(lines), encoding="utf-8")


def _ass_time(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}.00"


def _ass_text(value: str) -> str:
    cleaned = value.replace("\n", " ").replace("\r", " ").replace("{", "(").replace("}", ")").strip()
    return cleaned[:120]


def _slice_ids_from_run(run: GenerationRun) -> list[UUID]:
    values: list[Any] = []
    values.extend(run.request_payload.get("asset_slice_ids") or [])
    values.extend(item.get("slice_id") for item in run.request_payload.get("selected_asset_slices") or [] if isinstance(item, dict))
    for shot in run.storyboard:
        if isinstance(shot, dict) and shot.get("selected_asset_slice_id"):
            values.append(shot.get("selected_asset_slice_id"))
    for placement in (run.strategy or {}).get("asset_usage_plan") or []:
        if isinstance(placement, dict):
            values.extend(placement.get("slice_ids") or [])
    return _uuid_list(values)


def _uuid_list(values: list[Any]) -> list[UUID]:
    items: list[UUID] = []
    for value in values:
        item = _uuid_or_none(value)
        if item and item not in items:
            items.append(item)
    return items


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _material_kind(content_type: str, path: Path) -> str:
    lowered_type = str(content_type or "").lower()
    suffix = path.suffix.lower()
    if lowered_type.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if lowered_type.startswith("video/") or suffix in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        return "video"
    if lowered_type.startswith("audio/") or suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
        return "audio"
    return "other"


def _upsert_artifact(db: Session, run: GenerationRun, *, profile: ExportProfile, status: str, payload: dict[str, Any]) -> None:
    artifact_type = f"ffmpeg_assembled_video_{profile.slug}"
    artifact = next((item for item in run.artifacts if item.artifact_type == artifact_type), None)
    if artifact is None:
        artifact = MediaArtifact(
            run_id=run.id,
            order_index=len(run.artifacts) + 1,
            artifact_type=artifact_type,
            title=f"Local FFmpeg assembled video / {profile.aspect_ratio}",
            provider="local_ffmpeg_assembly",
            status=status,
            payload=payload,
        )
        db.add(artifact)
        run.artifacts.append(artifact)
        return
    artifact.status = status
    artifact.payload = payload
    db.add(artifact)


def _add_event(db: Session, run: GenerationRun, event_type: str, status: str, message: str, payload: dict[str, Any]) -> None:
    event = RunEvent(
        order_index=len(run.events) + 1,
        event_type=event_type,
        status=status,
        message=message,
        payload=payload,
    )
    db.add(event)
    run.events.append(event)


def _material_payload(material: AssemblyMaterial) -> dict[str, Any]:
    return {
        "material_id": material.material_id,
        "label": material.label,
        "kind": material.kind,
        "slice_id": material.slice_id,
        "asset_id": material.asset_id,
        "usable_for": material.usable_for,
        "summary": material.summary,
        "start_seconds": material.start_seconds,
        "end_seconds": material.end_seconds,
    }


def _export_profile(value: str) -> ExportProfile:
    if value == "16:9":
        return ExportProfile(aspect_ratio="16:9", width=1280, height=720)
    if value == "1:1":
        return ExportProfile(aspect_ratio="1:1", width=1080, height=1080)
    return ExportProfile(aspect_ratio="9:16", width=720, height=1280)


def _storyboard_total_duration(storyboard: list[dict[str, Any]]) -> int:
    return sum(max(1, int(shot.get("duration_seconds") or 1)) for shot in storyboard)


def _ffmpeg_profile(
    profile: ExportProfile,
    *,
    include_bgm: bool,
    has_audio: bool,
    audio_source: str | None = None,
    duration_seconds: int = DEFAULT_TARGET_DURATION_SECONDS,
) -> dict[str, Any]:
    audio_label = (
        "uploaded_bgm_mixed"
        if audio_source == "uploaded_audio"
        else "draft_audio_preserved"
        if audio_source == "draft_audio"
        else "silent_tts_placeholder"
    )
    return {
        "renderer": "ffmpeg",
        "width": profile.width,
        "height": profile.height,
        "resolution": f"{profile.width}x{profile.height}",
        "aspect_ratio": profile.aspect_ratio,
        "fps": FPS,
        "duration_seconds": max(1, int(duration_seconds or DEFAULT_TARGET_DURATION_SECONDS)),
        "codec": "libx264",
        "include_bgm": include_bgm,
        "audio": audio_label if has_audio else "silent_tts_placeholder",
        "audio_source": audio_source,
    }


def _render_root() -> Path:
    return Path(get_settings().upload_dir).parent / "renders"


def _tool_path(name: str) -> str:
    candidate = Path("D:/tools/ffmpeg/bin") / f"{name}.exe"
    return str(candidate) if candidate.exists() else name


def _run_tool(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(args, check=True, capture_output=True, text=True, timeout=180, cwd=str(cwd) if cwd else None)
        return completed.stdout
    except FileNotFoundError as exc:
        raise AssemblyError(f"{Path(args[0]).name} was not found. Install FFmpeg or add D:\\tools\\ffmpeg\\bin to PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AssemblyError(f"{Path(args[0]).name} timed out while assembling the preview.") from exc
    except subprocess.CalledProcessError as exc:
        raw_message = exc.stderr or exc.stdout or str(exc)
        message = raw_message[-1200:]
        raise AssemblyError(f"{Path(args[0]).name} failed: {message}") from exc


def _short_error(exc: Exception) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ")[:1000]


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return cleaned or "clip"
