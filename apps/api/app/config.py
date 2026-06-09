from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ViralCutAI API"
    database_url: str = "postgresql+psycopg://viralcutai:viralcutai@localhost:5432/viralcutai"
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    volcengine_api_key: str | None = None
    volcengine_base_url: str | None = None
    volcengine_endpoint_id: str | None = None
    volcengine_text_model: str | None = None
    volcengine_image_model: str | None = None
    seedance_api_key: str | None = None
    seedance_base_url: str | None = None
    seedance_endpoint_id: str | None = None
    seedance_model: str | None = None
    fastmoss_api_key: str | None = None
    fastmoss_client_id: str | None = None
    fastmoss_client_secret: str | None = None
    fastmoss_base_url: str = "https://openapi.fastmoss.com"
    provider_request_timeout_seconds: int = 120
    seedance_poll_seconds: int = 90
    seedance_poll_interval_seconds: int = 5
    upload_dir: str = "storage/uploads"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
