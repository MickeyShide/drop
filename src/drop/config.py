from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Drop"
    app_env: str = "local"
    debug: bool = False

    database_url: str

    rabbitmq_url: str
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str = "us-east-1"

    max_upload_size_bytes: int = 100 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
