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

    database_url: str = "postgresql+asyncpg://drop:drop@localhost:5432/drop"

    rabbitmq_url: str = "amqp://drop:drop@localhost:5672/"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "drop"
    s3_secret_key: str = "dropdropdrop"
    s3_bucket: str = "drops"
    s3_region: str = "us-east-1"

    max_upload_size_bytes: int = 100 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
