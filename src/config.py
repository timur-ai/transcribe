"""Application configuration — loads and validates environment variables."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Telegram ──────────────────────────────────────────────
    telegram_bot_token: str

    # ── Access control ────────────────────────────────────────
    bot_access_password: str = "changeme"
    max_users: int = 20

    # ── Yandex Cloud common ───────────────────────────────────
    yc_folder_id: str
    yc_service_account_key_file: str

    # ── Yandex Object Storage (S3) ────────────────────────────
    yc_s3_bucket: str = "transcribe-bot-audio"
    yc_s3_access_key: str
    yc_s3_secret_key: str
    yc_s3_endpoint: str = "https://storage.yandexcloud.net"

    # ── Yandex SpeechKit ──────────────────────────────────────
    speechkit_api_endpoint: str = "https://transcribe.api.cloud.yandex.net"

    # ── YandexGPT ─────────────────────────────────────────────
    yandexgpt_api_endpoint: str = "https://llm.api.cloud.yandex.net"
    yandexgpt_model_uri: str = ""

    # ── PostgreSQL ────────────────────────────────────────────
    database_url: str

    # ── Processing ────────────────────────────────────────────
    max_file_duration_seconds: int = 14400  # 4 hours
    max_file_size_bytes: int = 1_073_741_824  # 1 GB
    queue_workers: int = 3
    tmp_dir: str = "/tmp/transcribe"

    @field_validator("yandexgpt_model_uri", mode="before")
    @classmethod
    def build_model_uri(cls, v: str, info) -> str:  # noqa: N805
        if v:
            return v
        folder_id = info.data.get("yc_folder_id", "")
        return f"gpt://{folder_id}/yandexgpt/latest"

    @field_validator("yc_service_account_key_file")
    @classmethod
    def validate_key_file(cls, v: str) -> str:
        if v and not Path(v).exists():
            raise ValueError(
                f"Service account key file not found: {v}"
            )
        return v

    @field_validator("max_users")
    @classmethod
    def validate_max_users(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_users must be at least 1")
        return v


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
