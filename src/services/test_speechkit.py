"""Unit tests for SpeechKit client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.speechkit import SpeechKitClient, SpeechKitError


@pytest.fixture
def iam_manager():
    """Mock IAM token manager."""
    manager = AsyncMock()
    manager.get_token.return_value = "test-iam-token"
    return manager


@pytest.fixture
def client(iam_manager):
    """Create a SpeechKit client."""
    return SpeechKitClient(
        iam_manager=iam_manager,
        folder_id="test-folder",
    )


def _make_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    return resp


class TestRecognize:
    async def test_successful_recognition(self, client):
        """Test full flow: submit → poll (not done) → poll (done) → text."""
        submit_resp = _make_response(200, {"id": "op-123"})
        poll_pending = _make_response(200, {"id": "op-123", "done": False})
        poll_done = _make_response(200, {
            "id": "op-123",
            "done": True,
            "response": {
                "chunks": [
                    {"alternatives": [{"text": "Привет мир"}]},
                    {"alternatives": [{"text": "Как дела"}]},
                ]
            },
        })

        with patch("src.services.speechkit.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = submit_resp
            mock_client.get.side_effect = [poll_pending, poll_done]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("src.services.speechkit.asyncio.sleep", new_callable=AsyncMock):
                text = await client.recognize("https://storage.yandexcloud.net/bucket/audio.ogg")

        assert text == "Привет мир Как дела"

    async def test_submit_failure(self, client):
        submit_resp = _make_response(400, {"error": "bad request"})

        with patch("src.services.speechkit.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = submit_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(SpeechKitError, match="400"):
                await client.recognize("https://storage.yandexcloud.net/bucket/audio.ogg")

    async def test_operation_error(self, client):
        submit_resp = _make_response(200, {"id": "op-123"})
        error_resp = _make_response(200, {
            "id": "op-123",
            "error": {"code": 3, "message": "Invalid audio"},
        })

        with patch("src.services.speechkit.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = submit_resp
            mock_client.get.return_value = error_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(SpeechKitError, match="Invalid audio"):
                await client.recognize("https://storage.yandexcloud.net/bucket/audio.ogg")

    async def test_timeout(self, client):
        submit_resp = _make_response(200, {"id": "op-123"})
        pending_resp = _make_response(200, {"id": "op-123", "done": False})

        with patch("src.services.speechkit.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = submit_resp
            mock_client.get.return_value = pending_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("src.services.speechkit.MAX_POLL_TIME", 0):
                with pytest.raises(SpeechKitError, match="timed out"):
                    await client.recognize("https://storage.yandexcloud.net/bucket/audio.ogg")


class TestExtractText:
    def test_single_chunk(self):
        result = {
            "response": {
                "chunks": [
                    {"alternatives": [{"text": "Один текст"}]},
                ]
            }
        }
        assert SpeechKitClient._extract_text(result) == "Один текст"

    def test_multiple_chunks(self):
        result = {
            "response": {
                "chunks": [
                    {"alternatives": [{"text": "Первая часть"}]},
                    {"alternatives": [{"text": "Вторая часть"}]},
                    {"alternatives": [{"text": "Третья часть"}]},
                ]
            }
        }
        assert SpeechKitClient._extract_text(result) == "Первая часть Вторая часть Третья часть"

    def test_empty_chunks(self):
        result = {"response": {"chunks": []}}
        assert SpeechKitClient._extract_text(result) == ""

    def test_no_response(self):
        assert SpeechKitClient._extract_text({}) == ""
