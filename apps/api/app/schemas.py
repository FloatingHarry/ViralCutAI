from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerationRunCreate(BaseModel):
    generation_mode: str = Field(default="auto_mix", pattern="^(viral_rewrite|template_fusion|auto_mix)$")
    asset_collection_id: UUID | None = None
    product_name: str = Field(min_length=1, max_length=240)
    category: str = Field(default="beauty", max_length=120)
    selling_points: list[str] = Field(default_factory=list)
    target_audience: str = Field(default="short-video shoppers", max_length=240)
    price_offer: str = Field(default="", max_length=240)
    material_notes: str = Field(default="", max_length=800)
    creative_goal: str = Field(default="Generate a conversion-oriented commerce video", max_length=800)
    reference_style: str = Field(default="fast native short-video product demo", max_length=400)
    visual_style: str = Field(default="clean studio, bright product close-ups", max_length=400)
    duration_seconds: int = Field(default=12, ge=12, le=12)
    platform: str = Field(default="TikTok Shop", max_length=120)
    source_assets: list[dict] = Field(default_factory=list)
    asset_ids: list[UUID] = Field(default_factory=list)
    asset_slice_ids: list[UUID] = Field(default_factory=list)
    reference_video_id: UUID | None = None
    template_id: UUID | None = None
    factor_ids: list[UUID] = Field(default_factory=list)
    auto_retrieve_assets: bool = True
    auto_retrieve_factors: bool = True


class AssetCreate(BaseModel):
    collection_id: UUID | None = None
    filename: str = Field(default="manual-asset", max_length=260)
    content_type: str = Field(default="text/plain", max_length=120)
    asset_kind: str = Field(default="reference", max_length=60)
    category: str = Field(default="general", max_length=120)
    description: str = Field(default="", max_length=1200)


class AssetCollectionCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=220)
    category: str = Field(default="general", max_length=120)
    description: str = Field(default="", max_length=1200)
    usage_notes: str = Field(default="", max_length=1200)


class AssetCollectionUpdate(BaseModel):
    product_name: str | None = Field(default=None, min_length=1, max_length=220)
    category: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1200)
    usage_notes: str | None = Field(default=None, max_length=1200)


class AssetPatch(BaseModel):
    category: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1200)
    analysis_status: str | None = Field(default=None, max_length=40)


class AssetSlicePatch(BaseModel):
    summary: str | None = Field(default=None, max_length=1600)
    usable_for: str | None = Field(default=None, max_length=80)
    is_pinned: bool | None = None


class AssetSliceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    order_index: int
    slice_type: str
    start_seconds: int
    end_seconds: int
    summary: str
    features: dict
    usable_for: str
    source_frame_path: str
    is_pinned: bool
    created_at: datetime


class AssetTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    name: str
    tag_type: str
    confidence: int
    source: str
    created_at: datetime


class AssetEmbeddingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    model: str
    vector: list[float]
    created_at: datetime


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID | None = None
    filename: str
    content_type: str
    asset_kind: str
    category: str
    size_bytes: int
    storage_path: str
    description: str
    analysis: dict
    analysis_status: str
    provider_status: str
    provider_message: str
    slices: list[AssetSliceRead]
    tags: list[AssetTagRead]
    embedding: AssetEmbeddingRead | None = None
    created_at: datetime
    updated_at: datetime


class AssetSearchResultRead(BaseModel):
    collection: dict | None = None
    asset: AssetRead
    score: float
    retrieval_mode: str
    matched_tags: list[str]
    matched_slices: list[dict]
    usable_for: list[str]
    reason: str


class AssetCollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_name: str
    category: str
    description: str
    usage_notes: str
    status: str
    summary: str
    coverage: dict
    tags: list[str]
    assets: list[AssetRead]
    created_at: datetime
    updated_at: datetime


class ViralVideoAnalyzeCreate(BaseModel):
    title: str = Field(default="Reference commerce video", max_length=220)
    source_url: str = Field(default="", max_length=1000)
    platform: str = Field(default="TikTok", max_length=120)
    category: str = Field(default="general", max_length=120)
    product_type: str = Field(default="", max_length=160)
    country: str = Field(default="", max_length=120)
    language: str = Field(default="English", max_length=120)
    metrics: dict = Field(default_factory=dict)
    published_at: str = Field(default="", max_length=80)
    thumbnail_url: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=1200)
    source_statement: str = Field(default="User submitted reference for structured analysis.", max_length=800)


class FastMossVideoImportCreate(BaseModel):
    keywords: str = Field(min_length=1, max_length=240)
    region: str = Field(default="US", max_length=20)
    product_category_id: int | None = Field(default=None, ge=1)
    creator_category_id: int | None = Field(default=None, ge=1)
    order_by: str = Field(default="play_count desc", max_length=80)
    pagesize: int = Field(default=10, ge=1, le=20)
    page: int = Field(default=1, ge=1)


class FastMossImportItemRead(BaseModel):
    status: str
    video_id: str
    title: str = ""
    source_url: str = ""
    reference_id: UUID | None = None
    factor_count: int = 0
    message: str = ""
    metrics: dict = Field(default_factory=dict)


class FastMossVideoImportRead(BaseModel):
    status: str
    summary: str
    provider_status: str
    provider_message: str
    request: dict
    imported_count: int
    skipped_count: int
    failed_count: int
    factor_count: int
    items: list[FastMossImportItemRead] = Field(default_factory=list)
    raw_total: int | None = None


class CreativeTemplateBuildCreate(BaseModel):
    name: str = Field(default="", max_length=180)
    category: str = Field(default="", max_length=120)
    reference_ids: list[UUID] = Field(min_length=2, max_length=5)
    notes: str = Field(default="", max_length=800)


class ViralVideoAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source_url: str
    category: str
    source_statement: str
    analysis: dict
    created_at: datetime
    updated_at: datetime


class ViralFactorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    factor_key: str
    name: str
    category: str
    source: str
    description: str
    metadata_payload: dict
    created_at: datetime


class CreativeTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
    strategy: str
    factor_keys: list[str]
    structure: dict
    created_at: datetime


class SourceAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    order_index: int
    filename: str
    content_type: str
    asset_kind: str
    size_bytes: int
    storage_path: str
    description: str
    metadata_payload: dict
    created_at: datetime


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    order_index: int
    agent_name: str
    status: str
    provider: str
    model: str
    execution_mode: str = "mock_missing_config"
    provider_status: str = "missing_config"
    provider_message: str = ""
    input: dict
    output: dict
    duration_ms: int
    fallback: str
    error: str | None = None
    created_at: datetime


class MediaArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    order_index: int
    artifact_type: str
    title: str
    provider: str
    status: str
    payload: dict
    created_at: datetime


class RunEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    order_index: int
    event_type: str
    agent_name: str | None
    status: str
    message: str
    payload: dict
    created_at: datetime


class GenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    status: str
    summary: str
    request_payload: dict
    assets: list[SourceAssetRead]
    agents: list[AgentStepRead]
    events: list[RunEventRead]
    strategy: dict
    viral_factors: list[dict]
    script: dict
    storyboard: list[dict]
    preview: dict
    export_manifest: dict
    artifacts: list[MediaArtifactRead]
    compliance: dict
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StoryboardPatch(BaseModel):
    order_index: int | None = Field(default=None, ge=1, le=3)
    duration_seconds: int | None = Field(default=None, ge=1, le=12)
    beat: str | None = Field(default=None, max_length=160)
    visual_description: str | None = Field(default=None, max_length=1200)
    camera_motion: str | None = Field(default=None, max_length=400)
    voiceover: str | None = Field(default=None, max_length=1200)
    subtitle: str | None = Field(default=None, max_length=400)
    tts_line: str | None = Field(default=None, max_length=1200)
    bgm_cue: str | None = Field(default=None, max_length=300)
    image_prompt: str | None = Field(default=None, max_length=1600)
    video_prompt: str | None = Field(default=None, max_length=1600)
    selected_asset_slice_id: UUID | None = None


class StoryboardCreate(BaseModel):
    order_index: int | None = Field(default=None, ge=1, le=3)
    duration_seconds: int = Field(default=3, ge=1, le=12)
    beat: str = Field(default="New beat", max_length=160)
    visual_description: str = Field(default="", max_length=1200)
    camera_motion: str = Field(default="", max_length=400)
    voiceover: str = Field(default="", max_length=1200)
    subtitle: str = Field(default="", max_length=400)
    tts_line: str = Field(default="", max_length=1200)
    bgm_cue: str = Field(default="", max_length=300)
    image_prompt: str = Field(default="", max_length=1600)
    video_prompt: str = Field(default="", max_length=1600)
    selected_asset_slice_id: UUID | None = None


class AssemblyPreviewCreate(BaseModel):
    aspect_ratio: str = Field(default="9:16", pattern="^(9:16|16:9|1:1)$")
    include_bgm: bool = True


class EditorTimelineClip(BaseModel):
    clip_id: str | None = Field(default=None, max_length=80)
    source_type: str = Field(pattern="^(draft_segment|replacement_clip|asset_slice)$")
    shot_id: str | None = Field(default=None, max_length=80)
    asset_slice_id: UUID | None = None
    label: str = Field(default="", max_length=240)
    subtitle: str = Field(default="", max_length=400)
    voiceover: str = Field(default="", max_length=1200)
    source_start_seconds: int = Field(default=0, ge=0, le=3600)
    source_end_seconds: int | None = Field(default=None, ge=1, le=3600)
    duration_seconds: int = Field(default=4, ge=1, le=30)
    enabled: bool = True


class EditorTimelineUpdate(BaseModel):
    clips: list[EditorTimelineClip] = Field(min_length=1, max_length=12)


class ExperimentVariantMetricCreate(BaseModel):
    run_id: UUID
    label: str | None = Field(default=None, max_length=80)
    views: int = Field(ge=1)
    watch_completion_rate: float = Field(ge=0, le=100)
    avg_watch_seconds: float = Field(ge=0, le=12)
    ctr: float = Field(ge=0, le=100)
    cvr: float = Field(ge=0, le=100)
    orders: int = Field(ge=0)
    revenue: float = Field(ge=0)


class ExperimentAnalyzeCreate(BaseModel):
    title: str = Field(default="A/B attribution analysis", max_length=220)
    run_ids: list[UUID] = Field(min_length=2, max_length=4)
    objective: str = Field(default="Compare factor impact and recommend the next iteration.", max_length=600)
    variant_metrics: list[ExperimentVariantMetricCreate] = Field(default_factory=list)


class ExperimentVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    run_id: UUID
    order_index: int
    label: str
    metrics: dict
    created_at: datetime


class FactorAttributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    factor_key: str
    factor_name: str
    category: str
    score: int
    lift: int
    evidence: str
    created_at: datetime


class ExperimentAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    experiment_id: UUID
    title: str
    status: str
    summary: str
    winner_run_id: UUID | None
    input_payload: dict
    result: dict
    trace: list[dict]
    variants: list[ExperimentVariantRead]
    attributions: list[FactorAttributionRead]
    created_at: datetime
    updated_at: datetime


class HealthRead(BaseModel):
    status: str
    graph: str
    providers: dict
