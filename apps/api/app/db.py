from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401

    _reset_incompatible_agent_tables()
    Base.metadata.create_all(bind=engine)
    _ensure_agent_step_truth_columns()
    _ensure_asset_library_columns()


def _reset_incompatible_agent_tables() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "generation_runs" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("generation_runs")}
    required_columns = {
        "request_payload",
        "strategy",
        "viral_factors",
        "script",
        "storyboard",
        "preview",
        "export_manifest",
        "compliance",
    }
    required_tables = {
        "generation_runs",
        "asset_collections",
        "assets",
        "asset_slices",
        "asset_tags",
        "asset_embeddings",
        "viral_video_analyses",
        "viral_factors",
        "creative_templates",
        "source_assets",
        "agent_steps",
        "run_events",
        "media_artifacts",
        "experiment_analyses",
        "experiment_variants",
        "factor_attributions",
    }
    if required_columns.issubset(columns) and required_tables.issubset(table_names):
        return

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS media_artifacts CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS run_events CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS agent_steps CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS source_assets CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS factor_attributions CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS experiment_variants CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS experiment_analyses CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS creative_templates CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS viral_factors CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS viral_video_analyses CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS asset_embeddings CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS asset_tags CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS asset_slices CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS assets CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS asset_collections CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS generation_runs CASCADE"))


def _ensure_agent_step_truth_columns() -> None:
    inspector = inspect(engine)
    if "agent_steps" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("agent_steps")}
    with engine.begin() as connection:
        if "execution_mode" not in columns:
            connection.execute(
                text("ALTER TABLE agent_steps ADD COLUMN execution_mode VARCHAR(40) NOT NULL DEFAULT 'mock_missing_config'")
            )
        if "provider_status" not in columns:
            connection.execute(
                text("ALTER TABLE agent_steps ADD COLUMN provider_status VARCHAR(40) NOT NULL DEFAULT 'missing_config'")
            )
        if "provider_message" not in columns:
            connection.execute(text("ALTER TABLE agent_steps ADD COLUMN provider_message TEXT NOT NULL DEFAULT ''"))


def _ensure_asset_library_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "assets" in table_names:
            columns = {column["name"] for column in inspector.get_columns("assets")}
            if "collection_id" not in columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN collection_id UUID NULL"))
                connection.execute(
                    text(
                        "ALTER TABLE assets ADD CONSTRAINT fk_assets_collection_id "
                        "FOREIGN KEY (collection_id) REFERENCES asset_collections(id) ON DELETE CASCADE"
                    )
                )
            if "analysis_status" not in columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN analysis_status VARCHAR(40) NOT NULL DEFAULT 'pending'"))
            if "provider_status" not in columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN provider_status VARCHAR(40) NOT NULL DEFAULT 'missing_config'"))
            if "provider_message" not in columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN provider_message TEXT NOT NULL DEFAULT ''"))

        if "asset_slices" in table_names:
            columns = {column["name"] for column in inspector.get_columns("asset_slices")}
            if "usable_for" not in columns:
                connection.execute(text("ALTER TABLE asset_slices ADD COLUMN usable_for VARCHAR(80) NOT NULL DEFAULT ''"))
            if "source_frame_path" not in columns:
                connection.execute(text("ALTER TABLE asset_slices ADD COLUMN source_frame_path TEXT NOT NULL DEFAULT ''"))
            if "is_pinned" not in columns:
                connection.execute(text("ALTER TABLE asset_slices ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT false"))

        if "asset_tags" in table_names:
            columns = {column["name"] for column in inspector.get_columns("asset_tags")}
            if "source" not in columns:
                connection.execute(text("ALTER TABLE asset_tags ADD COLUMN source VARCHAR(40) NOT NULL DEFAULT 'provider'"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
