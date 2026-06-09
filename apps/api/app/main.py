import json
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, init_db
from app.schemas import (
    AssetCreate,
    AssetCollectionCreate,
    AssetCollectionRead,
    AssetCollectionUpdate,
    AssetPatch,
    AssetRead,
    AssetSearchResultRead,
    AssetSlicePatch,
    AssetSliceRead,
    AssemblyPreviewCreate,
    CreativeTemplateBuildCreate,
    CreativeTemplateRead,
    EditorTimelineUpdate,
    ExperimentAnalysisRead,
    ExperimentAnalyzeCreate,
    FastMossVideoImportCreate,
    FastMossVideoImportRead,
    GenerationRunCreate,
    GenerationRunRead,
    HealthRead,
    StoryboardPatch,
    StoryboardCreate,
    ViralFactorRead,
    ViralVideoAnalysisRead,
    ViralVideoAnalyzeCreate,
)
from app.services.asset_library import (
    add_asset_to_collection,
    analyze_asset,
    create_asset,
    create_collection,
    get_asset,
    get_collection,
    list_assets,
    list_collections,
    search_assets,
    update_asset,
    update_asset_slice,
    update_collection,
)
from app.services.preset_seed import seed_preset_workspace
from app.services.experiments import create_experiment_analysis, get_experiment, list_experiments
from app.services.ffmpeg_assembly import AssemblyError, assembled_video_path, editor_clip_video_path, execute_assembly_preview_task, queue_assembly_preview
from app.services.fastmoss_import import attach_source_video_to_reference, import_fastmoss_videos
from app.services.generation_runs import (
    add_storyboard_shot,
    create_generation_run,
    delete_storyboard_shot,
    duplicate_storyboard_shot,
    execute_generation_run_task,
    get_generation_export,
    get_generation_run,
    get_editor_timeline,
    list_generation_runs,
    patch_storyboard_shot,
    queue_regenerate_shot_clip,
    regenerate_storyboard_shot,
    render_preview,
    retry_generation_run,
    execute_regenerate_shot_clip_task,
    split_storyboard_shot,
    update_editor_timeline,
)
from app.services.viral_library import (
    analyze_reference_video,
    build_creative_template,
    list_templates,
    list_viral_factors,
    list_viral_videos,
    viral_reference_cover_path,
)


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health", response_model=HealthRead)
def health() -> dict[str, Any]:
    settings = get_settings()
    text_configured = bool(settings.volcengine_api_key and (settings.volcengine_endpoint_id or settings.volcengine_text_model))
    image_configured = bool(settings.volcengine_api_key and settings.volcengine_image_model)
    video_configured = bool(settings.seedance_api_key and (settings.seedance_endpoint_id or settings.seedance_model))
    fastmoss_configured = bool(settings.fastmoss_api_key or (settings.fastmoss_client_id and settings.fastmoss_client_secret))
    return {
        "status": "ok",
        "graph": "langgraph-generation-and-experiment-graphs",
        "providers": {
            "text_provider": "configured" if text_configured else "missing_config",
            "image_understanding_provider": "configured" if text_configured else "missing_config",
            "video_frame_understanding_provider": "configured" if text_configured else "missing_config",
            "image_plan_provider": "configured" if text_configured else "missing_config",
            "image_generation_provider": "configured" if image_configured else "missing_config",
            "video_provider": "configured" if video_configured else "missing_config",
            "fastmoss_provider": "configured" if fastmoss_configured else "missing_config",
            "experiment_provider": "configured" if text_configured else "missing_config",
        },
    }


@app.post("/preset-assets/seed")
def seed_preset_assets(db: Session = Depends(get_db)):
    return seed_preset_workspace(db)


@app.post("/asset-collections", response_model=AssetCollectionRead)
def create_asset_collection(payload: AssetCollectionCreate, db: Session = Depends(get_db)):
    return create_collection(payload, db)


@app.get("/asset-collections", response_model=list[AssetCollectionRead])
def list_asset_collections(db: Session = Depends(get_db)):
    return list_collections(db)


@app.get("/asset-collections/{collection_id}", response_model=AssetCollectionRead)
def read_asset_collection(collection_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_collection(collection_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset collection not found") from None


@app.patch("/asset-collections/{collection_id}", response_model=AssetCollectionRead)
def patch_asset_collection(collection_id: UUID, payload: AssetCollectionUpdate, db: Session = Depends(get_db)):
    try:
        return update_collection(collection_id, payload, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset collection not found") from None


@app.post("/asset-collections/{collection_id}/assets", response_model=list[AssetRead])
async def add_collection_assets(collection_id: UUID, request: Request, db: Session = Depends(get_db)):
    try:
        payloads = await _parse_collection_asset_request(collection_id, request)
        _validate_user_video_decomposition_payloads(payloads)
        return [
            add_asset_to_collection(collection_id, payload, db, content=content)
            for payload, content in payloads
        ]
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset collection not found") from None


@app.post("/assets", response_model=AssetRead)
async def create_asset_endpoint(request: Request, db: Session = Depends(get_db)):
    payload, content = await _parse_asset_request(request)
    _validate_user_video_decomposition_payloads([(payload, content)])
    return create_asset(payload, db, content=content)


@app.get("/assets", response_model=list[AssetRead])
def list_assets_endpoint(db: Session = Depends(get_db)):
    return list_assets(db)


@app.get("/assets/search", response_model=list[AssetSearchResultRead])
def search_assets_endpoint(
    q: str = Query(default=""),
    tag: str = Query(default=""),
    category: str = Query(default=""),
    asset_kind: str = Query(default=""),
    mode: str = Query(default="hybrid", pattern="^(keyword|tag|vector|hybrid)$"),
    limit: int = Query(default=12, ge=1, le=50),
    include_slices: bool = Query(default=True),
    collection_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return search_assets(
        db,
        query=q,
        tag=tag,
        category=category,
        asset_kind=asset_kind,
        mode=mode,
        limit=limit,
        include_slices=include_slices,
        collection_id=collection_id,
    )


@app.get("/assets/{asset_id}", response_model=AssetRead)
def read_asset(asset_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_asset(asset_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset not found") from None


@app.get("/assets/{asset_id}/file")
def read_asset_file(asset_id: UUID, db: Session = Depends(get_db)):
    try:
        asset = get_asset(asset_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset not found") from None
    if not asset.storage_path:
        raise HTTPException(status_code=404, detail="Asset has no stored file")
    return FileResponse(asset.storage_path, media_type=asset.content_type, filename=asset.filename)


@app.patch("/assets/{asset_id}", response_model=AssetRead)
def patch_asset(asset_id: UUID, payload: AssetPatch, db: Session = Depends(get_db)):
    try:
        return update_asset(asset_id, payload.model_dump(exclude_unset=True), db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset not found") from None


@app.post("/assets/{asset_id}/analyze", response_model=AssetRead)
def analyze_asset_endpoint(asset_id: UUID, db: Session = Depends(get_db)):
    try:
        return analyze_asset(asset_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset not found") from None


@app.patch("/asset-slices/{slice_id}", response_model=AssetSliceRead)
def patch_asset_slice(slice_id: UUID, payload: AssetSlicePatch, db: Session = Depends(get_db)):
    try:
        return update_asset_slice(slice_id, payload.model_dump(exclude_unset=True), db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Asset slice not found") from None


@app.get("/viral-videos", response_model=list[ViralVideoAnalysisRead])
def list_viral_videos_endpoint(
    q: str = Query(default=""),
    category: str = Query(default=""),
    factor_category: str = Query(default=""),
    db: Session = Depends(get_db),
):
    return list_viral_videos(db, query=q, category=category, factor_category=factor_category)


@app.post("/viral-videos/analyze", response_model=ViralVideoAnalysisRead)
def analyze_viral_video(payload: ViralVideoAnalyzeCreate, db: Session = Depends(get_db)):
    return analyze_reference_video(payload, db)


@app.post("/viral-videos/import-fastmoss", response_model=FastMossVideoImportRead)
def import_fastmoss_viral_videos(payload: FastMossVideoImportCreate, db: Session = Depends(get_db)):
    return import_fastmoss_videos(payload, db)


@app.post("/viral-videos/{reference_id}/attach-source-video", response_model=ViralVideoAnalysisRead)
async def attach_viral_source_video(reference_id: UUID, request: Request, db: Session = Depends(get_db)):
    try:
        filename, content_type, content = await _parse_single_file_request(request)
        return attach_source_video_to_reference(
            reference_id,
            filename=filename,
            content_type=content_type,
            content=content,
            db=db,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Viral reference not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/viral-videos/{reference_id}/cover")
def read_viral_video_cover(reference_id: UUID, db: Session = Depends(get_db)):
    try:
        path = viral_reference_cover_path(reference_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Viral reference not found") from None
    if path is None:
        raise HTTPException(status_code=404, detail="Viral reference cover not found")
    return FileResponse(path, media_type="image/jpeg", filename=f"viral-reference-{reference_id}.jpg")


@app.get("/viral-factors", response_model=list[ViralFactorRead])
def list_viral_factors_endpoint(
    q: str = Query(default=""),
    category: str = Query(default=""),
    db: Session = Depends(get_db),
):
    return list_viral_factors(db, query=q, category=category)


@app.get("/creative-templates", response_model=list[CreativeTemplateRead])
def list_creative_templates_endpoint(
    q: str = Query(default=""),
    category: str = Query(default=""),
    db: Session = Depends(get_db),
):
    return list_templates(db, query=q, category=category)


@app.post("/creative-templates/build", response_model=CreativeTemplateRead)
def build_creative_template_endpoint(payload: CreativeTemplateBuildCreate, db: Session = Depends(get_db)):
    try:
        return build_creative_template(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs", response_model=GenerationRunRead)
async def create_run(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        payload, assets = await _parse_generation_request(request)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    run = create_generation_run(payload, db, asset_inputs=assets)
    background_tasks.add_task(execute_generation_run_task, run.id)
    return run


@app.get("/generation-runs", response_model=list[GenerationRunRead])
def list_runs(limit: int = Query(default=20, ge=1, le=50), db: Session = Depends(get_db)):
    return list_generation_runs(db, limit=limit)


@app.get("/generation-runs/{run_id}", response_model=GenerationRunRead)
def read_run(run_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_generation_run(run_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None


@app.get("/generation-runs/{run_id}/export")
def export_run(run_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_generation_export(run_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None


@app.get("/generation-runs/{run_id}/editor-timeline")
def read_editor_timeline(run_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_editor_timeline(run_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/generation-runs/{run_id}/editor-timeline", response_model=GenerationRunRead)
def patch_editor_timeline(run_id: UUID, payload: EditorTimelineUpdate, db: Session = Depends(get_db)):
    try:
        return update_editor_timeline(run_id, payload.model_dump(mode="json"), db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs/{run_id}/retry", response_model=GenerationRunRead)
def retry_run(run_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        run = retry_generation_run(run_id, db)
        background_tasks.add_task(execute_generation_run_task, run.id)
        return run
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None


@app.patch("/generation-runs/{run_id}/storyboard/{shot_id}", response_model=GenerationRunRead)
def patch_shot(run_id: UUID, shot_id: str, payload: StoryboardPatch, db: Session = Depends(get_db)):
    try:
        return patch_storyboard_shot(run_id, shot_id, payload.model_dump(mode="json", exclude_unset=True), db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs/{run_id}/storyboard", response_model=GenerationRunRead)
def add_shot(run_id: UUID, payload: StoryboardCreate, db: Session = Depends(get_db)):
    try:
        return add_storyboard_shot(run_id, payload.model_dump(mode="json", exclude_unset=True), db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/generation-runs/{run_id}/storyboard/{shot_id}", response_model=GenerationRunRead)
def delete_shot(run_id: UUID, shot_id: str, db: Session = Depends(get_db)):
    try:
        return delete_storyboard_shot(run_id, shot_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs/{run_id}/storyboard/{shot_id}/duplicate", response_model=GenerationRunRead)
def duplicate_shot(run_id: UUID, shot_id: str, db: Session = Depends(get_db)):
    try:
        return duplicate_storyboard_shot(run_id, shot_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs/{run_id}/storyboard/{shot_id}/split", response_model=GenerationRunRead)
def split_shot(run_id: UUID, shot_id: str, db: Session = Depends(get_db)):
    try:
        return split_storyboard_shot(run_id, shot_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/generation-runs/{run_id}/storyboard/{shot_id}/regenerate", response_model=GenerationRunRead)
def regenerate_shot(run_id: UUID, shot_id: str, db: Session = Depends(get_db)):
    try:
        return regenerate_storyboard_shot(run_id, shot_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/generation-runs/{run_id}/storyboard/{shot_id}/regenerate-clip", response_model=GenerationRunRead)
def regenerate_shot_clip(run_id: UUID, shot_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        run = queue_regenerate_shot_clip(run_id, shot_id, db)
        background_tasks.add_task(execute_regenerate_shot_clip_task, run.id, shot_id)
        return run
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/generation-runs/{run_id}/render-preview", response_model=GenerationRunRead)
def render_run_preview(run_id: UUID, db: Session = Depends(get_db)):
    try:
        return render_preview(run_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None


@app.post("/generation-runs/{run_id}/assemble-preview", response_model=GenerationRunRead)
def assemble_run_preview(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    payload: AssemblyPreviewCreate | None = None,
    db: Session = Depends(get_db),
):
    try:
        request = payload or AssemblyPreviewCreate()
        run = queue_assembly_preview(run_id, db, aspect_ratio=request.aspect_ratio, include_bgm=request.include_bgm)
        background_tasks.add_task(execute_assembly_preview_task, run.id, request.aspect_ratio, request.include_bgm)
        return run
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None
    except AssemblyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/generation-runs/{run_id}/assembled-video")
def read_assembled_video(run_id: UUID, aspect_ratio: str = Query(default=""), db: Session = Depends(get_db)):
    try:
        path = assembled_video_path(run_id, db, aspect_ratio=aspect_ratio or None)
    except LookupError:
        raise HTTPException(status_code=404, detail="Assembled video file not found") from None
    suffix = aspect_ratio.replace(":", "x") if aspect_ratio else "assembled"
    return FileResponse(path, media_type="video/mp4", filename=f"viralcutai-{run_id}-{suffix}.mp4")


@app.get("/generation-runs/{run_id}/editor-clip-video")
def read_editor_clip_video(
    run_id: UUID,
    clip_id: str = Query(default=""),
    shot_id: str = Query(default=""),
    source_type: str = Query(default="draft_segment"),
    db: Session = Depends(get_db),
):
    try:
        path = editor_clip_video_path(run_id, db, clip_id=clip_id, shot_id=shot_id, source_type=source_type)
    except LookupError:
        raise HTTPException(status_code=404, detail="Generation run not found") from None
    except AssemblyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    suffix = clip_id or shot_id or "clip"
    return FileResponse(path, media_type="video/mp4", filename=f"viralcutai-{run_id}-{suffix}.mp4")


@app.post("/experiments/analyze", response_model=ExperimentAnalysisRead)
def analyze_experiment(payload: ExperimentAnalyzeCreate, db: Session = Depends(get_db)):
    try:
        return create_experiment_analysis(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/experiments", response_model=list[ExperimentAnalysisRead])
def list_experiments_endpoint(db: Session = Depends(get_db)):
    return list_experiments(db)


@app.get("/experiments/{experiment_id}", response_model=ExperimentAnalysisRead)
def read_experiment(experiment_id: UUID, db: Session = Depends(get_db)):
    try:
        return get_experiment(experiment_id, db)
    except LookupError:
        raise HTTPException(status_code=404, detail="Experiment analysis not found") from None


async def _parse_generation_request(request: Request) -> tuple[GenerationRunCreate, list[dict[str, Any]]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_payload = form.get("payload")
        if isinstance(raw_payload, str) and raw_payload.strip():
            payload_data = json.loads(raw_payload)
        else:
            payload_data = {
                "generation_mode": str(form.get("generation_mode") or "auto_mix"),
                "asset_collection_id": str(form.get("asset_collection_id") or "") or None,
                "product_name": str(form.get("product_name") or ""),
                "category": str(form.get("category") or "beauty"),
                "selling_points": _parse_points(str(form.get("selling_points") or "")),
                "target_audience": str(form.get("target_audience") or "short-video shoppers"),
                "price_offer": str(form.get("price_offer") or ""),
                "material_notes": str(form.get("material_notes") or ""),
                "creative_goal": str(form.get("creative_goal") or "Generate a conversion-oriented commerce video"),
                "reference_style": str(form.get("reference_style") or "fast native short-video beauty product reveal"),
                "visual_style": str(form.get("visual_style") or "clean studio, bright product close-ups"),
                "duration_seconds": int(str(form.get("duration_seconds") or "12")),
                "platform": str(form.get("platform") or "TikTok Shop"),
            }
        assets: list[dict[str, Any]] = []
        for file in form.getlist("assets"):
            if not hasattr(file, "filename") or not hasattr(file, "read"):
                continue
            content = await file.read()
            filename = str(getattr(file, "filename", "") or "uploaded-asset")
            content_type_value = str(getattr(file, "content_type", "") or "application/octet-stream")
            assets.append(
                {
                    "filename": filename,
                    "content_type": content_type_value,
                    "asset_kind": _asset_kind(content_type_value),
                    "size_bytes": len(content),
                    "content": content,
                    "description": _asset_description(filename, content_type_value, len(content)),
                }
            )
        payload_data["source_assets"] = [
            {key: value for key, value in asset.items() if key != "content"} for asset in assets
        ]
        return GenerationRunCreate.model_validate(payload_data), assets

    payload_data = await request.json()
    payload = GenerationRunCreate.model_validate(payload_data)
    return payload, list(payload.source_assets)


async def _parse_asset_request(request: Request) -> tuple[AssetCreate, bytes | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_payload = form.get("payload")
        file = form.get("file")
        content: bytes | None = None
        filename = str(form.get("filename") or "asset")
        content_type_value = str(form.get("content_type") or "application/octet-stream")
        if hasattr(file, "filename") and hasattr(file, "read"):
            content = await file.read()
            filename = str(getattr(file, "filename", "") or filename)
            content_type_value = str(getattr(file, "content_type", "") or content_type_value)
        payload_data = json.loads(raw_payload) if isinstance(raw_payload, str) and raw_payload.strip() else {}
        payload_data = {
            "collection_id": payload_data.get("collection_id") or str(form.get("collection_id") or "") or None,
            "filename": payload_data.get("filename") or filename,
            "content_type": payload_data.get("content_type") or content_type_value,
            "asset_kind": payload_data.get("asset_kind") or _asset_kind(content_type_value),
            "category": payload_data.get("category") or str(form.get("category") or "general"),
            "description": payload_data.get("description") or str(form.get("description") or ""),
        }
        return AssetCreate.model_validate(payload_data), content
    return AssetCreate.model_validate(await request.json()), None


async def _parse_single_file_request(request: Request) -> tuple[str, str, bytes]:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("Expected multipart/form-data with a file field.")
    form = await request.form()
    file = form.get("file") or form.get("source_video") or form.get("video")
    if not hasattr(file, "filename") or not hasattr(file, "read"):
        raise ValueError("Missing uploaded video file.")
    content = await file.read()
    filename = str(getattr(file, "filename", "") or "source-video.mp4")
    content_type_value = str(getattr(file, "content_type", "") or "application/octet-stream")
    if content_type_value == "application/octet-stream" and filename.lower().endswith(".mp4"):
        content_type_value = "video/mp4"
    return filename, content_type_value, content


async def _parse_collection_asset_request(collection_id: UUID, request: Request) -> list[tuple[AssetCreate, bytes | None]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        raw_payload = form.get("payload")
        payload_data = json.loads(raw_payload) if isinstance(raw_payload, str) and raw_payload.strip() else {}
        files = [file for file in [*form.getlist("files"), *form.getlist("file")] if hasattr(file, "filename") and hasattr(file, "read")]
        if not files:
            return [
                (
                    AssetCreate.model_validate(
                        {
                            "collection_id": collection_id,
                            "filename": payload_data.get("filename") or str(form.get("filename") or "manual-asset"),
                            "content_type": payload_data.get("content_type") or str(form.get("content_type") or "text/plain"),
                            "asset_kind": payload_data.get("asset_kind") or str(form.get("asset_kind") or "reference"),
                            "category": payload_data.get("category") or str(form.get("category") or "general"),
                            "description": payload_data.get("description") or str(form.get("description") or ""),
                        }
                    ),
                    None,
                )
            ]
        items: list[tuple[AssetCreate, bytes | None]] = []
        for file in files:
            content = await file.read()
            filename = str(getattr(file, "filename", "") or "uploaded-asset")
            content_type_value = str(getattr(file, "content_type", "") or "application/octet-stream")
            items.append(
                (
                    AssetCreate.model_validate(
                        {
                            "collection_id": collection_id,
                            "filename": filename,
                            "content_type": content_type_value,
                            "asset_kind": payload_data.get("asset_kind") or _asset_kind(content_type_value),
                            "category": payload_data.get("category") or str(form.get("category") or "general"),
                            "description": payload_data.get("description") or str(form.get("description") or ""),
                        }
                    ),
                    content,
                )
            )
        return items
    payload_data = await request.json()
    payload_data["collection_id"] = str(collection_id)
    return [(AssetCreate.model_validate(payload_data), None)]


def _validate_user_video_decomposition_payloads(payloads: list[tuple[AssetCreate, bytes | None]]) -> None:
    for payload, content in payloads:
        if payload.asset_kind != "user_video_decomposition":
            continue
        if content is None:
            raise HTTPException(status_code=400, detail="User video decomposition requires an uploaded video file.")
        if not payload.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="User video decomposition only accepts video files.")


def _parse_points(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [point.strip() for point in value.split(",") if point.strip()]


def _asset_kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "reference"


def _asset_description(filename: str, content_type: str, size_bytes: int) -> str:
    size_kb = round(size_bytes / 1024, 1)
    return f"{filename} ({content_type}, {size_kb} KB) submitted as source material for this run."
