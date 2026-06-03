from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import AgentStep, GenerationRun, MediaArtifact, RunEvent, SourceAsset
from app.schemas import GenerationRunCreate
from app.services.asset_library import (
    asset_collection_context_for_generation,
    asset_context_for_generation,
    asset_retrieval_for_generation,
    asset_slice_context_for_generation,
)
from app.services.agent_workflows import _public_provider_fields, _raise_for_status, stream_generation_graph, video_provider
from app.services.viral_library import viral_context_for_generation, viral_retrieval_for_generation


def create_generation_run(
    payload: GenerationRunCreate,
    db: Session,
    *,
    asset_inputs: list[dict[str, Any]] | None = None,
) -> GenerationRun:
    request_payload = payload.model_dump(mode="json")
    selected_collection_context = asset_collection_context_for_generation(payload.asset_collection_id, db)
    selected_asset_context = asset_context_for_generation(payload.asset_ids, db)
    selected_slice_context = asset_slice_context_for_generation(payload.asset_slice_ids, db)
    viral_context = viral_context_for_generation(
        reference_video_id=payload.reference_video_id,
        template_id=payload.template_id,
        factor_ids=payload.factor_ids,
        db=db,
    )
    request_payload["asset_collection"] = selected_collection_context
    request_payload["asset_library"] = selected_asset_context
    request_payload["selected_asset_slices"] = selected_slice_context
    request_payload.update(viral_context)
    asset_retrieval = asset_retrieval_for_generation(request_payload, db)
    viral_retrieval = viral_retrieval_for_generation(request_payload, db) if payload.auto_retrieve_factors else {
        "viral_query": "",
        "auto_factors": [],
        "auto_templates": [],
        "auto_references": [],
        "methodology_summary": "Automatic factor retrieval is disabled for this run.",
    }
    selected_library_factors = [
        *request_payload.get("selected_library_factors", []),
        *viral_retrieval.get("auto_factors", []),
    ]
    request_payload["selected_library_factors"] = _dedupe_factors(selected_library_factors)
    request_payload["retrieval_context"] = {
        **asset_retrieval,
        **viral_retrieval,
        "selected_reference_video": request_payload.get("reference_video"),
        "selected_template": request_payload.get("creative_template"),
        "selected_factor_count": len(payload.factor_ids),
    }
    run = GenerationRun(
        status="queued",
        request_payload=request_payload,
        strategy={},
        viral_factors=[],
        script={},
        storyboard=[],
        preview={"generation_status": "queued"},
        export_manifest={},
        compliance={},
        summary=f"{request_payload['product_name']} is queued for LangGraph generation.",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    assets = _persist_source_assets(run_id, asset_inputs or payload.source_assets, db)
    request_payload["source_assets"] = [
        *assets,
        *request_payload.get("asset_library", []),
        *asset_retrieval.get("auto_assets", []),
    ]
    run.request_payload = request_payload
    _add_event(
        db,
        run_id,
        1,
        "queued",
        "queued",
        "GenerationRun request accepted.",
        {"product_name": request_payload["product_name"]},
    )
    _add_event(
        db,
        run_id,
        2,
        "assets_ingested",
        "completed",
        f"{len(request_payload['source_assets'])} source assets attached to the run.",
        {
            "asset_count": len(request_payload["source_assets"]),
            "selected_slice_count": len(selected_slice_context),
            "asset_collection_id": str(payload.asset_collection_id) if payload.asset_collection_id else None,
            "auto_retrieved_asset_count": len(asset_retrieval.get("auto_asset_results", [])),
            "auto_retrieved_factor_count": len(viral_retrieval.get("auto_factors", [])),
            "assets": request_payload["source_assets"],
            "retrieval_context": request_payload["retrieval_context"],
        },
    )
    db.commit()

    return get_generation_run(run_id, db)


def execute_generation_run(run_id: UUID, db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    if run.status == "succeeded":
        return run
    request_payload = run.request_payload
    run.status = "running"
    run.preview = {
        **(run.preview or {}),
        "generation_status": "running",
    }
    db.add(run)
    db.commit()

    try:
        state: dict[str, Any] = {}
        persisted_trace_count = len(run.agents)
        persisted_artifact_count = len(run.artifacts)
        next_event_index = len(run.events) + 1

        for streamed_state in stream_generation_graph(str(run.id), request_payload):
            state = streamed_state
            _update_run_from_generation_state(run, request_payload, state, final=False)
            next_event_index, persisted_trace_count = _persist_trace_delta(
                db,
                run,
                state.get("trace", []),
                persisted_trace_count,
                next_event_index,
            )
            persisted_artifact_count = _persist_artifact_delta(
                db,
                run,
                state.get("artifacts", []),
                persisted_artifact_count,
            )
            db.add(run)
            db.commit()
            run = get_generation_run(run_id, db)

        _update_run_from_generation_state(run, request_payload, state, final=True)
        next_event_index, persisted_trace_count = _persist_trace_delta(
            db,
            run,
            state.get("trace", []),
            persisted_trace_count,
            next_event_index,
        )
        _persist_artifact_delta(db, run, state.get("artifacts", []), persisted_artifact_count)

        event_index = next_event_index
        _add_event(
            db,
            run.id,
            event_index,
            "preview_ready",
            "failed" if run.status == "failed" else "completed",
            "Provider preview package is incomplete because a configured provider failed."
            if run.status == "failed"
            else "Storyboard preview and provider media artifacts are ready.",
            {"preview": run.preview},
        )
        _add_event(
            db,
            run.id,
            event_index + 1,
            "export_ready",
            "failed" if run.status == "failed" else "completed",
            "Failure trace package can be exported as JSON for debugging."
            if run.status == "failed"
            else "Provider preview package can be exported as JSON.",
            {"export_manifest": run.export_manifest},
        )
        _add_event(
            db,
            run.id,
            event_index + 2,
            "run_failed" if run.status == "failed" else "run_completed",
            run.status,
            run.summary,
            {"status": run.status},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(GenerationRun, run_id)
        if failed_run is None:
            raise
        failed_run.status = "failed"
        failed_run.error_message = str(exc)
        failed_run.summary = f"Generation failed for {request_payload['product_name']}."
        failed_run.preview = {
            **(failed_run.preview or {}),
            "generation_status": "failed",
        }
        db.add(failed_run)
        _add_event(
            db,
            run_id,
            len(failed_run.events) + 1,
            "run_failed",
            "failed",
            str(exc),
            {"error": str(exc)},
        )
        db.commit()

    return get_generation_run(run_id, db)


def _update_run_from_generation_state(
    run: GenerationRun,
    request_payload: dict[str, Any],
    state: dict[str, Any],
    *,
    final: bool,
) -> None:
    if state.get("strategy"):
        run.strategy = state.get("strategy", {})
        run.viral_factors = state.get("strategy", {}).get("factor_board", [])
    if state.get("script"):
        run.script = state.get("script", {})
    if state.get("storyboard"):
        run.storyboard = state.get("storyboard", [])
    if state.get("preview"):
        run.preview = {**(run.preview or {}), **state.get("preview", {})}
    if state.get("export_manifest"):
        run.export_manifest = state.get("export_manifest", {})
    if state.get("compliance"):
        run.compliance = state.get("compliance", {})

    errors = state.get("errors", [])
    if final:
        run.status = "succeeded" if not errors else "failed"
        run.summary = _summarize_run(request_payload, state)
        run.error_message = _summarize_errors(errors)
    elif errors:
        run.status = "failed"
        run.summary = f"Generation failed for {request_payload['product_name']}."
        run.error_message = _summarize_errors(errors)
    else:
        run.status = "running"
        last_agent = (state.get("trace") or [{}])[-1].get("agent_name", "LangGraph")
        run.summary = f"{request_payload['product_name']} is running. Last completed node: {last_agent}."

    run.preview = {
        **(run.preview or {}),
        "generation_status": run.status,
    }


def _persist_trace_delta(
    db: Session,
    run: GenerationRun,
    trace: list[dict[str, Any]],
    start_index: int,
    next_event_index: int,
) -> tuple[int, int]:
    for index, step in enumerate(trace[start_index:], start=start_index + 1):
        db.add(
            AgentStep(
                run_id=run.id,
                order_index=index,
                agent_name=step["agent_name"],
                status=step["status"],
                provider=_limit_text(step["provider"], 120),
                model=_limit_text(step["model"], 120),
                execution_mode=step.get("execution_mode", "mock_missing_config"),
                provider_status=step.get("provider_status", "missing_config"),
                provider_message=step.get("provider_message", ""),
                input_payload=step["input"],
                output_payload=step["output"],
                duration_ms=step["duration_ms"],
                fallback=step["fallback"],
                error_message=step.get("error"),
            )
        )
        _add_event(
            db,
            run.id,
            next_event_index,
            _event_type_for_agent(step["agent_name"]),
            step["status"],
            f"{step['agent_name']} {'failed in' if step['status'] == 'failed' else 'completed through'} {step['provider']}.",
            {
                "agent_name": step["agent_name"],
                "duration_ms": step["duration_ms"],
                "fallback": step["fallback"],
                "execution_mode": step.get("execution_mode"),
                "provider_status": step.get("provider_status"),
                "provider_message": step.get("provider_message"),
            },
            agent_name=step["agent_name"],
        )
        next_event_index += 1
    return next_event_index, len(trace)


def _persist_artifact_delta(
    db: Session,
    run: GenerationRun,
    artifacts: list[dict[str, Any]],
    start_index: int,
) -> int:
    for index, artifact in enumerate(artifacts[start_index:], start=start_index + 1):
        db.add(
            MediaArtifact(
                run_id=run.id,
                order_index=index,
                artifact_type=artifact["artifact_type"],
                title=artifact["title"],
                provider=artifact["provider"],
                status=artifact["status"],
                payload=artifact["payload"],
            )
        )
    return len(artifacts)


def execute_generation_run_task(run_id: UUID) -> None:
    db = SessionLocal()
    try:
        execute_generation_run(run_id, db)
    finally:
        db.close()


def retry_generation_run(run_id: UUID, db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    payload = GenerationRunCreate.model_validate(run.request_payload)
    return create_generation_run(payload, db)


def list_generation_runs(db: Session, *, limit: int = 20) -> list[GenerationRun]:
    safe_limit = max(1, min(limit, 50))
    return list(
        db.scalars(
            select(GenerationRun)
            .options(
                selectinload(GenerationRun.assets),
                selectinload(GenerationRun.agents),
                selectinload(GenerationRun.events),
                selectinload(GenerationRun.artifacts),
            )
            .order_by(GenerationRun.created_at.desc())
            .limit(safe_limit)
        ).all()
    )


def get_generation_run(run_id: UUID, db: Session) -> GenerationRun:
    db.expire_all()
    run = db.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run_id)
        .options(
            selectinload(GenerationRun.assets),
            selectinload(GenerationRun.agents),
            selectinload(GenerationRun.events),
            selectinload(GenerationRun.artifacts),
        )
    )
    if run is None:
        raise LookupError("Generation run not found")
    if _has_pending_video_artifacts(run):
        try:
            sync_result = _sync_pending_video_artifacts(run, db)
            if sync_result.get("updated"):
                db.add(run)
                db.commit()
                db.expire_all()
                run = db.scalar(
                    select(GenerationRun)
                    .where(GenerationRun.id == run_id)
                    .options(
                        selectinload(GenerationRun.assets),
                        selectinload(GenerationRun.agents),
                        selectinload(GenerationRun.events),
                        selectinload(GenerationRun.artifacts),
                    )
                )
                if run is None:
                    raise LookupError("Generation run not found")
        except Exception as exc:
            run.error_message = _limit_text(str(exc), 600)
            _add_event(
                db,
                run.id,
                len(run.events) + 1,
                "shot_clip_polling",
                "failed",
                f"Seedance polling failed: {_limit_text(str(exc), 300)}",
                {"error": _limit_text(str(exc), 600)},
            )
            db.add(run)
            db.commit()
    return run


def get_generation_export(run_id: UUID, db: Session) -> dict[str, Any]:
    run = get_generation_run(run_id, db)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "summary": run.summary,
        "preview": run.preview,
        "export_manifest": run.export_manifest,
        "artifacts": [
            {
                "type": artifact.artifact_type,
                "title": artifact.title,
                "provider": artifact.provider,
                "status": artifact.status,
                "payload": artifact.payload,
            }
            for artifact in run.artifacts
        ],
    }


def patch_storyboard_shot(run_id: UUID, shot_id: str, updates: dict[str, Any], db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    storyboard = [dict(shot) for shot in run.storyboard]
    changed = False
    for shot in storyboard:
        if shot.get("shot_id") != shot_id:
            continue
        for key, value in updates.items():
            if key == "selected_asset_slice_id":
                shot[key] = value
                changed = True
            elif value is not None:
                shot[key] = value
                changed = True
    if not changed:
        raise LookupError("Storyboard shot not found")
    if updates.get("order_index") is not None:
        storyboard = _reorder_storyboard(storyboard, shot_id, int(updates["order_index"]))
    storyboard = _normalize_storyboard_duration_total(
        storyboard,
        int(run.script.get("duration_seconds") or run.request_payload.get("duration_seconds") or 12),
    )
    run.storyboard = storyboard
    run.preview = _build_preview_from_storyboard(run)
    _sync_preview_timeline_segments(run)
    _add_event(
        db,
        run.id,
        len(run.events) + 1,
        "storyboard_edit_saved",
        "completed",
        f"{shot_id} was edited. Full smart editing remains provider pending.",
        {"shot_id": shot_id, "updates": updates},
    )
    db.add(run)
    db.commit()
    return get_generation_run(run.id, db)


def queue_regenerate_shot_clip(run_id: UUID, shot_id: str, db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    if not any(shot.get("shot_id") == shot_id for shot in run.storyboard):
        raise LookupError("Storyboard shot not found")
    _add_event(
        db,
        run.id,
        len(run.events) + 1,
        "clip_regeneration_queued",
        "queued",
        f"{shot_id} clip regeneration was queued.",
        {"shot_id": shot_id},
    )
    run.preview = {
        **(run.preview or {}),
        "video_task_status": "processing",
        "active_regeneration_shot_id": shot_id,
    }
    _sync_preview_timeline_segments(run)
    db.add(run)
    db.commit()
    return get_generation_run(run.id, db)


def execute_regenerate_shot_clip_task(run_id: UUID, shot_id: str) -> None:
    db = SessionLocal()
    try:
        run = get_generation_run(run_id, db)
        shot = next((dict(item) for item in run.storyboard if item.get("shot_id") == shot_id), None)
        if shot is None:
            raise LookupError("Storyboard shot not found")
        draft_artifact = _artifact_dict(_draft_video_artifact(run))
        artifact = video_provider.generate_replacement_clip(shot, run.storyboard, run.script, run.request_payload, draft_artifact)
        _upsert_seedance_replacement_clip_artifact(db, run, artifact)
        _sync_preview_timeline_segments(run)
        status = str(artifact.get("status") or "")
        payload = artifact.get("payload", {})
        if status == "real_generated":
            event_type = "replacement_clip_completed"
            event_status = "completed"
            message = f"{shot_id} replacement clip is ready."
        elif status == "real_task_pending":
            event_type = "replacement_clip_submitted"
            event_status = "running"
            message = f"{shot_id} replacement Seedance task was submitted."
        elif status == "provider_failed":
            event_type = "replacement_clip_failed"
            event_status = "failed"
            message = str(payload.get("failure_reason") or f"{shot_id} replacement clip failed.")
        else:
            event_type = "replacement_clip_failed" if status == "provider_failed" else "replacement_clip_submitted"
            event_status = "completed" if status == "mock_missing_config" else "running"
            message = f"{shot_id} replacement clip recorded status {status}."
        _add_event(
            db,
            run.id,
            len(run.events) + 1,
            event_type,
            event_status,
            message,
            {"shot_id": shot_id, "task_id": payload.get("task_id"), "status": status},
        )
        db.add(run)
        db.commit()
    except Exception as exc:
        failed_run = db.get(GenerationRun, run_id)
        if failed_run is not None:
            _add_event(
                db,
                failed_run.id,
                len(failed_run.events) + 1,
                "replacement_clip_failed",
                "failed",
                _limit_text(str(exc), 600),
                {"shot_id": shot_id, "error": _limit_text(str(exc), 600)},
            )
            db.add(failed_run)
            db.commit()
    finally:
        db.close()


def regenerate_storyboard_shot(run_id: UUID, shot_id: str, db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    updates = {
        "voiceover": f"Fresh provider-pending rewrite for {shot_id}: show one sharper proof moment before the offer.",
        "subtitle": "Sharper proof, same offer.",
        "image_prompt": f"Regenerated image prompt for {shot_id}, provider pending, use existing asset slices.",
        "video_prompt": f"Regenerated video prompt for {shot_id}, provider pending, keep 9:16 commerce pacing.",
    }
    return patch_storyboard_shot(run_id, shot_id, updates, db)


def render_preview(run_id: UUID, db: Session) -> GenerationRun:
    run = get_generation_run(run_id, db)
    sync_result = _sync_pending_video_artifacts(run, db)
    run.preview = _build_preview_from_storyboard(run)
    _sync_preview_timeline_segments(run)
    _add_event(
        db,
        run.id,
        len(run.events) + 1,
        "preview_rerendered",
        "completed",
        "Preview was refreshed from storyboard and provider task status.",
        {"mode": run.preview.get("mode"), "video_sync": sync_result},
    )
    db.add(run)
    db.commit()
    return get_generation_run(run.id, db)


def _has_pending_video_artifacts(run: GenerationRun) -> bool:
    for artifact in run.artifacts:
        if artifact.artifact_type not in {"video_real", "seedance_shot_clip", "seedance_draft_video", "seedance_replacement_clip"}:
            continue
        payload = artifact.payload or {}
        if artifact.status in {"real_task_pending", "mock_missing_config"} and payload.get("query_url"):
            return True
        task_status = str(payload.get("task_status") or "").lower()
        if task_status in {"submitted", "running", "pending", "processing", "queued"}:
            return True
    return False


def _sync_pending_video_artifacts(run: GenerationRun, db: Session) -> dict[str, Any]:
    settings = get_settings()
    if not settings.seedance_api_key:
        return {"checked": False, "reason": "Seedance provider is not connected."}
    checked = 0
    updated = 0
    for artifact in run.artifacts:
        if artifact.artifact_type not in {"video_real", "seedance_shot_clip", "seedance_draft_video", "seedance_replacement_clip"}:
            continue
        payload = dict(artifact.payload or {})
        previous_status = artifact.status
        task_status = str(payload.get("task_status") or "").lower()
        if artifact.status == "real_generated" and payload.get("video_url"):
            continue
        query_url = str(payload.get("query_url") or "")
        if not query_url:
            continue
        checked += 1
        provider_data = _query_seedance_task(query_url, settings.seedance_api_key)
        content = provider_data.get("content") if isinstance(provider_data.get("content"), dict) else {}
        status = str(provider_data.get("status") or task_status or "unknown").lower()
        payload["task_status"] = status
        payload["raw_provider_fields"] = _public_provider_fields(provider_data)
        if content.get("video_url"):
            payload["video_url"] = content.get("video_url")
        if content.get("last_frame_url"):
            payload["last_frame_url"] = content.get("last_frame_url")
        duration = content.get("duration") or provider_data.get("duration")
        if duration:
            payload["duration_seconds"] = duration
            payload["provider_duration_seconds"] = duration
        if status == "succeeded" and payload.get("video_url"):
            artifact.status = "real_generated"
            updated += 1
            if artifact.artifact_type == "seedance_draft_video" and previous_status != "real_generated":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "draft_video_completed",
                    "completed",
                    "Continuous Seedance draft video is ready.",
                    {"task_id": payload.get("task_id"), "video_url": payload.get("video_url")},
                )
            elif artifact.artifact_type == "seedance_replacement_clip" and previous_status != "real_generated":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "replacement_clip_completed",
                    "completed",
                    f"{payload.get('shot_id')} replacement clip is ready.",
                    {"shot_id": payload.get("shot_id"), "video_url": payload.get("video_url")},
                )
            elif artifact.artifact_type == "seedance_shot_clip" and previous_status != "real_generated":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "shot_clip_completed",
                    "completed",
                    f"{payload.get('shot_id')} Seedance clip is ready.",
                    {"shot_id": payload.get("shot_id"), "video_url": payload.get("video_url")},
                )
            run.export_manifest = {
                **(run.export_manifest or {}),
                "is_real_output": True,
                "provider_duration_seconds": payload.get("provider_duration_seconds"),
            }
        elif status in {"failed", "cancelled", "canceled"}:
            artifact.status = "provider_failed"
            payload["failure_reason"] = f"Seedance task ended with status {status}."
            if artifact.artifact_type == "seedance_draft_video" and previous_status != "provider_failed":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "draft_video_failed",
                    "failed",
                    f"Continuous Seedance draft video failed with status {status}.",
                    {"task_id": payload.get("task_id"), "status": status},
                )
            elif artifact.artifact_type == "seedance_replacement_clip" and previous_status != "provider_failed":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "replacement_clip_failed",
                    "failed",
                    f"{payload.get('shot_id')} replacement clip failed with status {status}.",
                    {"shot_id": payload.get("shot_id"), "task_id": payload.get("task_id"), "status": status},
                )
            elif artifact.artifact_type == "seedance_shot_clip" and previous_status != "provider_failed":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "shot_clip_failed",
                    "failed",
                    f"{payload.get('shot_id')} Seedance clip failed with status {status}.",
                    {"shot_id": payload.get("shot_id"), "task_id": payload.get("task_id"), "status": status},
                )
            run.status = "failed"
            run.error_message = payload["failure_reason"]
            updated += 1
        else:
            artifact.status = "real_task_pending"
            if artifact.artifact_type == "seedance_draft_video" and previous_status != "real_task_pending":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "draft_video_polling",
                    "running",
                    "Continuous Seedance draft video is still processing.",
                    {"task_id": payload.get("task_id"), "status": status},
                )
            elif artifact.artifact_type == "seedance_replacement_clip" and previous_status != "real_task_pending":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "replacement_clip_polling",
                    "running",
                    f"{payload.get('shot_id')} replacement clip is still processing.",
                    {"shot_id": payload.get("shot_id"), "task_id": payload.get("task_id"), "status": status},
                )
            elif artifact.artifact_type == "seedance_shot_clip" and previous_status != "real_task_pending":
                _add_event(
                    db,
                    run.id,
                    len(run.events) + 1,
                    "shot_clip_polling",
                    "running",
                    f"{payload.get('shot_id')} Seedance clip is still processing.",
                    {"shot_id": payload.get("shot_id"), "task_id": payload.get("task_id"), "status": status},
                )
            updated += 1
        artifact.payload = payload
        db.add(artifact)
    if checked:
        _sync_preview_timeline_segments(run)
    return {"checked": checked, "updated": updated}


def _sync_preview_timeline_segments(run: GenerationRun) -> None:
    draft = _draft_video_artifact(run)
    draft_payload = draft.payload if draft else {}
    replacements_by_shot = {
        str(artifact.payload.get("shot_id")): artifact
        for artifact in run.artifacts
        if artifact.artifact_type in {"seedance_replacement_clip", "seedance_shot_clip"} and artifact.payload.get("shot_id")
    }
    cursor = 0
    timeline_segments = []
    for shot in sorted(run.storyboard, key=lambda item: int(item.get("order_index") or 0)):
        duration = int(shot.get("duration_seconds") or 4)
        start = cursor
        cursor += duration
        replacement = replacements_by_shot.get(str(shot.get("shot_id")))
        replacement_payload = replacement.payload if replacement else {}
        replacement_ready = bool(replacement and replacement.status == "real_generated" and replacement_payload.get("video_url"))
        artifact = replacement if replacement_ready else draft
        payload = replacement_payload if replacement_ready else draft_payload
        source = "replacement_clip" if replacement_ready else "draft_video"
        timeline_segments.append(
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
                "artifact_id": str(artifact.id) if artifact else None,
                "artifact_type": artifact.artifact_type if artifact else None,
                "artifact_status": artifact.status if artifact else "waiting",
                "source": source,
                "source_label": "Replacement clip" if replacement_ready else "Draft slice",
                "draft_video_url": draft_payload.get("video_url"),
                "replacement_video_url": replacement_payload.get("video_url"),
                "task_id": payload.get("task_id"),
                "task_status": payload.get("task_status"),
                "video_url": payload.get("video_url"),
                "last_frame_url": payload.get("last_frame_url"),
                "prompt": replacement_payload.get("prompt") if replacement_ready else shot.get("video_prompt"),
                "draft_prompt": draft_payload.get("prompt"),
                "failure_reason": payload.get("failure_reason"),
                "mock_reason": payload.get("mock_reason"),
            }
        )
    draft_status = str(draft.status if draft else "").lower()
    draft_task_status = str(draft_payload.get("task_status") or "").lower()
    replacement_statuses = [str(artifact.status or "").lower() for artifact in replacements_by_shot.values()]
    replacement_task_statuses = [str((artifact.payload or {}).get("task_status") or "").lower() for artifact in replacements_by_shot.values()]
    if draft_status == "real_generated":
        aggregate = "succeeded"
    elif draft_status == "provider_failed" or draft_task_status in {"failed", "cancelled", "canceled"}:
        aggregate = "failed"
    elif draft_status == "real_task_pending" or draft_task_status in {"submitted", "running", "pending", "processing", "queued"}:
        aggregate = "processing"
    elif draft_status == "mock_missing_config":
        aggregate = "not_connected"
    else:
        aggregate = "pending"
    if any(status == "real_task_pending" or task in {"submitted", "running", "pending", "processing", "queued"} for status, task in zip(replacement_statuses, replacement_task_statuses, strict=False)):
        replacement_status = "processing"
    elif any(status == "provider_failed" or task in {"failed", "cancelled", "canceled"} for status, task in zip(replacement_statuses, replacement_task_statuses, strict=False)):
        replacement_status = "failed"
    elif replacement_statuses:
        replacement_status = "ready"
    else:
        replacement_status = "none"
    run.preview = {
        **(run.preview or {}),
        "mode": "ai_draft_timeline" if draft_payload.get("video_url") else (run.preview or {}).get("mode", "provider_preview_package"),
        "timeline_segments": timeline_segments,
        "timeline_clips": timeline_segments,
        "active_segment_sources": {
            str(segment.get("shot_id")): str(segment.get("source") or "draft_video")
            for segment in timeline_segments
            if segment.get("shot_id")
        },
        "video_task_status": aggregate,
        "draft_video_status": draft.status if draft else None,
        "draft_video_url": draft_payload.get("video_url"),
        "replacement_clip_status": replacement_status,
        "video_task_id": draft_payload.get("task_id") or (run.preview or {}).get("video_task_id"),
        "video_url": draft_payload.get("video_url") or (run.preview or {}).get("video_url"),
        "total_duration_seconds": cursor or (run.preview or {}).get("total_duration_seconds"),
    }


def _sync_preview_timeline_clips(run: GenerationRun) -> None:
    _sync_preview_timeline_segments(run)


def _draft_video_artifact(run: GenerationRun) -> MediaArtifact | None:
    return next(
        (
            artifact
            for artifact in reversed(run.artifacts)
            if artifact.artifact_type in {"seedance_draft_video", "video_real"}
        ),
        None,
    )


def _artifact_dict(artifact: MediaArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "provider": artifact.provider,
        "status": artifact.status,
        "payload": artifact.payload,
    }


def _query_seedance_task(query_url: str, api_key: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=get_settings().provider_request_timeout_seconds) as client:
        response = client.get(query_url, headers=headers)
        _raise_for_status(response, "Seedance query task")
        data = response.json()
    return data if isinstance(data, dict) else {}


def _summarize_run(request_payload: dict, state: dict) -> str:
    product = request_payload["product_name"]
    shot_count = len(state.get("storyboard", []))
    artifacts = state.get("artifacts", [])
    artifact_count = len(artifacts)
    real_count = len([artifact for artifact in artifacts if str(artifact.get("status", "")).startswith("real_")])
    hook = state.get("strategy", {}).get("hook", "")
    return f"{product}: {shot_count} storyboard shots, {artifact_count} provider artifacts, {real_count} real provider outputs. Hook: {hook}"


def _dedupe_factors(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for factor in factors:
        key = str(factor.get("factor_key") or factor.get("id") or factor.get("name"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(factor)
    return deduped


def _event_type_for_agent(agent_name: str) -> str:
    if "Viral Strategy" in agent_name:
        return "factor_planning"
    if "Script" in agent_name:
        return "script_generation"
    if "Render" in agent_name:
        return "render_and_review"
    return "agent_completed"


def _build_preview_from_storyboard(run: GenerationRun) -> dict[str, Any]:
    cursor = 0
    timeline = []
    for shot in run.storyboard:
        start = cursor
        cursor += int(shot.get("duration_seconds") or 0)
        timeline.append(
            {
                "shot_id": shot.get("shot_id"),
                "time_range": f"{start}-{cursor}s",
                "beat": shot.get("beat"),
                "caption": shot.get("subtitle"),
                "visual": shot.get("visual_description"),
            }
        )
    return {
        **(run.preview or {}),
        "mode": run.preview.get("mode") or "provider_preview_package",
        "aspect_ratio": "9:16",
        "total_duration_seconds": cursor,
        "cover_text": timeline[0]["caption"] if timeline else run.script.get("title", ""),
        "timeline": timeline,
    }


def _reorder_storyboard(storyboard: list[dict[str, Any]], shot_id: str, order_index: int) -> list[dict[str, Any]]:
    items = [dict(shot) for shot in storyboard]
    moving = next((shot for shot in items if shot.get("shot_id") == shot_id), None)
    if moving is None:
        return storyboard
    items = [shot for shot in items if shot.get("shot_id") != shot_id]
    target = max(0, min(order_index - 1, len(items)))
    items.insert(target, moving)
    return [{**shot, "order_index": index} for index, shot in enumerate(items, start=1)]


def _normalize_storyboard_duration_total(storyboard: list[dict[str, Any]], target_seconds: int) -> list[dict[str, Any]]:
    if not storyboard:
        return storyboard
    target = max(1, min(int(target_seconds or 12), 12))
    durations = [max(1, int(shot.get("duration_seconds") or 1)) for shot in storyboard]
    if len(durations) > target:
        durations = [1 for _ in durations]
    while sum(durations) > target:
        index = max(range(len(durations)), key=lambda item: durations[item])
        if durations[index] <= 1:
            break
        durations[index] -= 1
    index = len(durations) - 1
    while sum(durations) < target:
        durations[index] += 1
        index = (index - 1) % len(durations)
    return [{**shot, "duration_seconds": durations[index]} for index, shot in enumerate(storyboard)]


def _upsert_seedance_shot_clip_artifact(db: Session, run: GenerationRun, artifact: dict[str, Any]) -> None:
    payload = artifact.get("payload", {})
    shot_id = str(payload.get("shot_id") or "")
    existing = next(
        (
            item
            for item in run.artifacts
            if item.artifact_type == "seedance_shot_clip" and str((item.payload or {}).get("shot_id") or "") == shot_id
        ),
        None,
    )
    if existing is None:
        db.add(
            MediaArtifact(
                run_id=run.id,
                order_index=len(run.artifacts) + 1,
                artifact_type=artifact["artifact_type"],
                title=artifact["title"],
                provider=artifact["provider"],
                status=artifact["status"],
                payload=artifact["payload"],
            )
        )
        return
    existing.title = artifact["title"]
    existing.provider = artifact["provider"]
    existing.status = artifact["status"]
    existing.payload = artifact["payload"]
    db.add(existing)


def _upsert_seedance_replacement_clip_artifact(db: Session, run: GenerationRun, artifact: dict[str, Any]) -> None:
    payload = artifact.get("payload", {})
    shot_id = str(payload.get("shot_id") or "")
    existing = next(
        (
            item
            for item in run.artifacts
            if item.artifact_type == "seedance_replacement_clip" and str((item.payload or {}).get("shot_id") or "") == shot_id
        ),
        None,
    )
    if existing is None:
        db.add(
            MediaArtifact(
                run_id=run.id,
                order_index=len(run.artifacts) + 1,
                artifact_type=artifact["artifact_type"],
                title=artifact["title"],
                provider=artifact["provider"],
                status=artifact["status"],
                payload=artifact["payload"],
            )
        )
        return
    existing.title = artifact["title"]
    existing.provider = artifact["provider"]
    existing.status = artifact["status"]
    existing.payload = artifact["payload"]
    db.add(existing)


def _summarize_errors(errors: list[dict]) -> str | None:
    if not errors:
        return None
    return "; ".join(error.get("message", "unknown error") for error in errors)


def _persist_source_assets(
    run_id: UUID,
    asset_inputs: list[dict[str, Any]],
    db: Session,
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    upload_root = Path(get_settings().upload_dir) / str(run_id)
    for index, asset in enumerate(asset_inputs, start=1):
        filename = _safe_filename(str(asset.get("filename") or f"asset-{index}"))
        content_type = str(asset.get("content_type") or "application/octet-stream")
        content = asset.get("content")
        storage_path = str(asset.get("storage_path") or "")
        size_bytes = int(asset.get("size_bytes") or 0)
        if isinstance(content, bytes):
            upload_root.mkdir(parents=True, exist_ok=True)
            file_path = upload_root / filename
            file_path.write_bytes(content)
            storage_path = str(file_path)
            size_bytes = len(content)
        description = str(
            asset.get("description")
            or f"{filename} ({content_type}) submitted as source material for this run."
        )
        asset_kind = str(asset.get("asset_kind") or _asset_kind(content_type))
        record = SourceAsset(
            run_id=run_id,
            order_index=index,
            filename=filename,
            content_type=content_type,
            asset_kind=asset_kind,
            size_bytes=size_bytes,
            storage_path=storage_path,
            description=description,
            metadata_payload={
                "source": "multipart_upload" if isinstance(content, bytes) else "json_metadata",
                "usable_by_agent": True,
            },
        )
        db.add(record)
        metadata.append(
            {
                "filename": filename,
                "content_type": content_type,
                "asset_kind": asset_kind,
                "size_bytes": size_bytes,
                "storage_path": storage_path,
                "description": description,
            }
        )
    return metadata


def _add_event(
    db: Session,
    run_id: UUID,
    order_index: int,
    event_type: str,
    status: str,
    message: str,
    payload: dict[str, Any],
    *,
    agent_name: str | None = None,
) -> None:
    db.add(
        RunEvent(
            run_id=run_id,
            order_index=order_index,
            event_type=event_type,
            agent_name=agent_name,
            status=status,
            message=message,
            payload=payload,
        )
    )


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip(".-")
    return cleaned or "uploaded-asset"


def _asset_kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "reference"


def _limit_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
