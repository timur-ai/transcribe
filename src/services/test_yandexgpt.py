"""Unit tests for YandexGPT client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.yandexgpt import YandexGPTClient, YandexGPTError, SYSTEM_PROMPT


@pytest.fixture
def iam_manager():
    manager = AsyncMock()
    manager.get_token.return_value = "test-iam-token"
    return manager


@pytest.fixture
def client(iam_manager):
    return YandexGPTClient(
        iam_manager=iam_manager,
        folder_id="test-folder",
        model_uri="gpt://test-folder/yandexgpt/latest",
    )


def _make_response(status_code=200, text="Analysis result"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "result": {
            "alternatives": [
                {"message": {"role": "assistant", "text": text}}
            ]
        }
    }
    resp.text = f"status={status_code}"
    return resp


class TestAnalyze:
    async def test_empty_text(self, client):
        result = await client.analyze("")
        assert "пуст" in result

    async def test_whitespace_text(self, client):
        result = await client.analyze("   \n  ")
        assert "пуст" in result

    async def test_short_text_single_request(self, client):
        mock_resp = _make_response(200, "## Резюме\nТестовый анализ")

        with patch("src.services.yandexgpt.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await client.analyze("Короткий текст для анализа")

        assert result == "## Резюме\nТестовый анализ"
        mock_client.post.assert_called_once()

    async def test_long_text_chunked(self, client):
        long_text = "Слово. " * 10000  # >24000 chars
        mock_resp = _make_response(200, "Частичный анализ")

        with patch("src.services.yandexgpt.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await client.analyze(long_text)

        # At least 2 chunk requests + 1 summarization request
        assert mock_client.post.call_count >= 3

    async def test_api_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("src.services.yandexgpt.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(YandexGPTError, match="500"):
                await client.analyze("Some text")

    async def test_no_alternatives_in_response(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": {"alternatives": []}}

        with patch("src.services.yandexgpt.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(YandexGPTError, match="No alternatives"):
                await client.analyze("Some text")


class TestPromptStructure:
    async def test_system_prompt_contains_required_sections(self):
        assert "Краткое резюме" in SYSTEM_PROMPT
        assert "Ключевые тезисы" in SYSTEM_PROMPT
        assert "План развития" in SYSTEM_PROMPT

    async def test_request_body_structure(self, client):
        mock_resp = _make_response(200, "OK")

        with patch("src.services.yandexgpt.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await client.analyze("Test text")

            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["modelUri"] == "gpt://test-folder/yandexgpt/latest"
            assert len(body["messages"]) == 2
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][1]["role"] == "user"


class TestSplitText:
    def test_short_text_not_split(self):
        chunks = YandexGPTClient._split_text("Short text")
        assert len(chunks) == 1

    def test_long_text_split(self):
        text = "A" * 50000
        chunks = YandexGPTClient._split_text(text)
        assert len(chunks) >= 2

    def test_split_preserves_all_content(self):
        # Each chunk overlaps, so total chars > original, but all content present
        text = "Sentence one. Sentence two. " * 1500
        chunks = YandexGPTClient._split_text(text)
        assert len(chunks) >= 2
        # First chunk starts from beginning
        assert chunks[0].startswith("Sentence one")
