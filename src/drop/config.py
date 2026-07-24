from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str
    app_env: str
    debug: bool

    database_url: str

    rabbitmq_url: str
    redis_url: str

    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str

    max_upload_size_bytes: int

    drop_token_pepper: str
    session_pepper: str

    rate_limit_create_max: int
    rate_limit_create_window: int

    rate_limit_metadata_max: int
    rate_limit_metadata_window: int

    rate_limit_download_max: int
    rate_limit_download_window: int

    rate_limit_invalid_token_max: int
    rate_limit_invalid_token_window: int
    rate_limit_invalid_token_ban_seconds: int

    rate_limit_upload_max: int
    rate_limit_upload_window: int
    rate_limit_upload_bytes: int
    rate_limit_upload_bytes_window: int
    rate_limit_download_per_drop_max: int
    rate_limit_download_per_drop_window: int
    rate_limit_download_per_session_max: int
    rate_limit_download_per_session_window: int
    download_stream_lock_seconds: int
    trusted_proxy_ips: str
    session_cookie_secure: bool

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() in {
            "release",
            "production",
        }:
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
