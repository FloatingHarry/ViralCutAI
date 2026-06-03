import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class GenerationRun(Base, TimestampMixin):
    __tablename__ = "generation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    status: Mapped[str] = mapped_column(String(40), default="running")
    summary: Mapped[str] = mapped_column(Text, default="")
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    viral_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    script: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    storyboard: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    export_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    compliance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    assets: Mapped[list["SourceAsset"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SourceAsset.order_index",
    )
    agents: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.order_index",
    )
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunEvent.order_index",
    )
    artifacts: Mapped[list["MediaArtifact"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="MediaArtifact.order_index",
    )

    @property
    def run_id(self) -> uuid.UUID:
        return self.id


class AssetCollection(Base, TimestampMixin):
    __tablename__ = "asset_collections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    product_name: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(120), default="general")
    description: Mapped[str] = mapped_column(Text, default="")
    usage_notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)

    assets: Mapped[list["Asset"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="Asset.created_at.desc()",
    )


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_collections.id", ondelete="CASCADE"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(260))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    asset_kind: Mapped[str] = mapped_column(String(60), default="reference")
    category: Mapped[str] = mapped_column(String(120), default="general")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_path: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    analysis_status: Mapped[str] = mapped_column(String(40), default="pending")
    provider_status: Mapped[str] = mapped_column(String(40), default="missing_config")
    provider_message: Mapped[str] = mapped_column(Text, default="")

    collection: Mapped[AssetCollection | None] = relationship(back_populates="assets")
    slices: Mapped[list["AssetSlice"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetSlice.order_index",
    )
    tags: Mapped[list["AssetTag"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetTag.name",
    )
    embedding: Mapped["AssetEmbedding | None"] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AssetSlice(Base, TimestampMixin):
    __tablename__ = "asset_slices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    slice_type: Mapped[str] = mapped_column(String(80), default="visual")
    start_seconds: Mapped[int] = mapped_column(Integer, default=0)
    end_seconds: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usable_for: Mapped[str] = mapped_column(String(80), default="")
    source_frame_path: Mapped[str] = mapped_column(Text, default="")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    asset: Mapped[Asset] = relationship(back_populates="slices")


class AssetTag(Base, TimestampMixin):
    __tablename__ = "asset_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    tag_type: Mapped[str] = mapped_column(String(80), default="keyword")
    confidence: Mapped[int] = mapped_column(Integer, default=80)
    source: Mapped[str] = mapped_column(String(40), default="provider")

    asset: Mapped[Asset] = relationship(back_populates="tags")


class AssetEmbedding(Base, TimestampMixin):
    __tablename__ = "asset_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True)
    model: Mapped[str] = mapped_column(String(120), default="mock-multimodal-embedding-v1")
    vector: Mapped[list[float]] = mapped_column(JSONB, default=list)

    asset: Mapped[Asset] = relationship(back_populates="embedding")


class ViralVideoAnalysis(Base, TimestampMixin):
    __tablename__ = "viral_video_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(220))
    source_url: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="general")
    source_statement: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ViralFactor(Base, TimestampMixin):
    __tablename__ = "viral_factors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    factor_key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(120), default="dynamic_mock")
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CreativeTemplate(Base, TimestampMixin):
    __tablename__ = "creative_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(120), default="general")
    strategy: Mapped[str] = mapped_column(Text, default="")
    factor_keys: Mapped[list[str]] = mapped_column(JSONB, default=list)
    structure: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SourceAsset(Base, TimestampMixin):
    __tablename__ = "source_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(260))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    asset_kind: Mapped[str] = mapped_column(String(60), default="reference")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_path: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped[GenerationRun] = relationship(back_populates="assets")


class AgentStep(Base, TimestampMixin):
    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    agent_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="succeeded")
    provider: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    execution_mode: Mapped[str] = mapped_column(String(40), default="mock_missing_config")
    provider_status: Mapped[str] = mapped_column(String(40), default="missing_config")
    provider_message: Mapped[str] = mapped_column(Text, default="")
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    fallback: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[GenerationRun] = relationship(back_populates="agents")

    @property
    def input(self) -> dict[str, Any]:
        return self.input_payload

    @property
    def output(self) -> dict[str, Any]:
        return self.output_payload

    @property
    def error(self) -> str | None:
        return self.error_message


class RunEvent(Base, TimestampMixin):
    __tablename__ = "run_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(60))
    agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped[GenerationRun] = relationship(back_populates="events")


class MediaArtifact(Base, TimestampMixin):
    __tablename__ = "media_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    artifact_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="mock_generated")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped[GenerationRun] = relationship(back_populates="artifacts")


class ExperimentAnalysis(Base, TimestampMixin):
    __tablename__ = "experiment_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(220))
    status: Mapped[str] = mapped_column(String(40), default="succeeded")
    summary: Mapped[str] = mapped_column(Text, default="")
    winner_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    variants: Mapped[list["ExperimentVariant"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="ExperimentVariant.order_index",
    )
    attributions: Mapped[list["FactorAttribution"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="FactorAttribution.score",
    )

    @property
    def experiment_id(self) -> uuid.UUID:
        return self.id


class ExperimentVariant(Base, TimestampMixin):
    __tablename__ = "experiment_variants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_analyses.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    experiment: Mapped[ExperimentAnalysis] = relationship(back_populates="variants")


class FactorAttribution(Base, TimestampMixin):
    __tablename__ = "factor_attributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_analyses.id", ondelete="CASCADE"))
    factor_key: Mapped[str] = mapped_column(String(120))
    factor_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80))
    score: Mapped[int] = mapped_column(Integer, default=0)
    lift: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[str] = mapped_column(Text, default="")

    experiment: Mapped[ExperimentAnalysis] = relationship(back_populates="attributions")
