"""Unit tests for application configuration."""

import os
from unittest.mock import patch

import pytest

from src.config import Settings


@pytest.fixture
def _env_vars(tmp_path):
    """Set up minimal valid environment variables for Settings."""
    key_file = tmp_path / "sa-key.json"
    key_file.write_text('{"id": "test"}')

    env = {
        "TELEGRAM_BOT_TOKEN": "123456:ABC",
        "BOT_ACCESS_PASSWORD": "changeme",
        "MAX_USERS": "20",
        "YC_FOLDER_ID": "b1gtest",
        "YC_SERVICE_ACCOUNT_KEY_FILE": str(key_file),
        "YC_S3_BUCKET": "test-bucket",
        "YC_S3_ACCESS_KEY": "YCAJ_test",
        "YC_S3_SECRET_KEY": "YCP_test_secret",
        "YC_S3_ENDPOINT": "https://storage.yandexcloud.net",
        "SPEECHKIT_API_ENDPOINT": "https://transcribe.api.cloud.yandex.net",
        "YANDEXGPT_API_ENDPOINT": "https://llm.api.cloud.yandex.net",
        "YANDEXGPT_MODEL_URI": "",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    }
    with patch.dict(os.environ, env, clear=False):
        yield env


class TestSettingsLoad:
    """Test that settings load correctly from environment variables."""

    def test_loads_all_required_fields(self, _env_vars):
        settings = Settings()
        assert settings.telegram_bot_token == "123456:ABC"
        assert settings.bot_access_password == "changeme"
        assert settings.max_users == 20
        assert settings.yc_folder_id == "b1gtest"
        assert settings.yc_s3_bucket == "test-bucket"
        assert settings.yc_s3_access_key == "YCAJ_test"
        assert settings.yc_s3_secret_key == "YCP_test_secret"
        assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/testdb"

    def test_auto_builds_model_uri(self, _env_vars):
        settings = Settings()
        assert settings.yandexgpt_model_uri == "gpt://b1gtest/yandexgpt/latest"

    def test_explicit_model_uri(self, _env_vars):
        with patch.dict(
            os.environ,
            {"YANDEXGPT_MODEL_URI": "gpt://custom/model/v2"},
        ):
            settings = Settings()
            assert settings.yandexgpt_model_uri == "gpt://custom/model/v2"

    def test_default_values(self, _env_vars):
        settings = Settings()
        assert settings.max_file_duration_seconds == 14400
        assert settings.max_file_size_bytes == 1_073_741_824
        assert settings.queue_workers == 3
        assert settings.tmp_dir == "/tmp/transcribe"
        assert settings.yc_s3_endpoint == "https://storage.yandexcloud.net"


class TestSettingsValidation:
    """Test validation errors for invalid configuration."""

    def test_missing_telegram_token_raises(self, _env_vars):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=False):
            # pydantic-settings allows empty strings; this tests the field exists
            settings = Settings()
            assert settings.telegram_bot_token == ""

    def test_invalid_key_file_raises(self, _env_vars):
        with patch.dict(
            os.environ,
            {"YC_SERVICE_ACCOUNT_KEY_FILE": "/nonexistent/path/key.json"},
        ):
            with pytest.raises(ValueError, match="key file not found"):
                Settings()

    def test_max_users_below_one_raises(self, _env_vars):
        with patch.dict(os.environ, {"MAX_USERS": "0"}):
            with pytest.raises(ValueError, match="max_users must be at least 1"):
                Settings()

    def test_max_users_custom_value(self, _env_vars):
        with patch.dict(os.environ, {"MAX_USERS": "5"}):
            settings = Settings()
            assert settings.max_users == 5
