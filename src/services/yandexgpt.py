"""YandexGPT API client — text analysis and plan generation."""

import logging

import httpx

from src.services.iam import IAMTokenManager

logger = logging.getLogger(__name__)

# Approximate token limit for a single request (conservative)
MAX_INPUT_CHARS = 24000  # ~6000 tokens for Russian text
CHUNK_OVERLAP_CHARS = 500

SYSTEM_PROMPT = """Ты — профессиональный аналитик. Тебе дана текстовая расшифровка аудио/видеозаписи.

Проанализируй текст и предоставь результат в следующем формате:

## Краткое резюме
Сжатое описание содержания записи в 3-5 предложениях.

## Ключевые тезисы
Пронумерованный список основных мыслей, идей и фактов из записи.

## План развития / Рекомендации
Конкретные, действенные рекомендации и шаги для дальнейшей работы на основе содержания записи.

Отвечай только на русском языке. Используй Markdown-форматирование."""

SUMMARIZE_PROMPT = """Ты — профессиональный аналитик. Ниже приведены результаты анализа нескольких частей одной записи.

Объедини их в единый связный анализ, убрав дубликаты и сохранив структуру:

## Краткое резюме
## Ключевые тезисы
## План развития / Рекомендации

Отвечай только на русском языке. Используй Markdown-форматирование."""


class YandexGPTError(Exception):
    """Raised when YandexGPT API calls fail."""
    pass


class YandexGPTClient:
    """Client for YandexGPT text analysis.

    Sends transcription text for analysis and returns a structured
    summary with key points and recommendations.
    """

    def __init__(
        self,
        iam_manager: IAMTokenManager,
        folder_id: str,
        model_uri: str,
        api_endpoint: str = "https://llm.api.cloud.yandex.net",
    ) -> None:
        self._iam = iam_manager
        self._folder_id = folder_id
        self._model_uri = model_uri
        self._api_endpoint = api_endpoint

    async def _get_headers(self) -> dict[str, str]:
        token = await self._iam.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "x-folder-id": self._folder_id,
        }

    async def analyze(self, transcription_text: str) -> str:
        """Analyze transcription text and generate a structured report.

        If the text is too long, it will be split into chunks,
        each analyzed separately, then combined with a final summary.

        Args:
            transcription_text: Full transcription text.

        Returns:
            Markdown-formatted analysis string.

        Raises:
            YandexGPTError: On API errors.
        """
        if not transcription_text or not transcription_text.strip():
            return "_Текст транскрибации пуст. Анализ невозможен._"

        if len(transcription_text) <= MAX_INPUT_CHARS:
            return await self._analyze_single(transcription_text)

        return await self._analyze_chunked(transcription_text)

    async def _analyze_single(self, text: str) -> str:
        """Analyze a single piece of text."""
        return await self._complete(SYSTEM_PROMPT, text)

    async def _analyze_chunked(self, text: str) -> str:
        """Split long text into chunks, analyze each, then summarize."""
        chunks = self._split_text(text)
        logger.info("Text split into %d chunks for analysis", len(chunks))

        partial_results = []
        for i, chunk in enumerate(chunks, 1):
            logger.info("Analyzing chunk %d/%d", i, len(chunks))
            result = await self._complete(
                SYSTEM_PROMPT,
                f"[Часть {i} из {len(chunks)}]\n\n{chunk}",
            )
            partial_results.append(result)

        # Final summarization
        combined = "\n\n---\n\n".join(
            f"### Результат анализа части {i}\n{r}"
            for i, r in enumerate(partial_results, 1)
        )
        return await self._complete(SUMMARIZE_PROMPT, combined)

    async def _complete(self, system_prompt: str, user_text: str) -> str:
        """Send a completion request to YandexGPT API."""
        headers = await self._get_headers()
        url = f"{self._api_endpoint}/foundationModels/v1/completion"

        body = {
            "modelUri": self._model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": 2000,
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_text},
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=body,
                headers=headers,
                timeout=120.0,
            )

        if response.status_code != 200:
            raise YandexGPTError(
                f"YandexGPT request failed: {response.status_code} — {response.text}"
            )

        data = response.json()
        result = data.get("result", {})
        alternatives = result.get("alternatives", [])
        if not alternatives:
            raise YandexGPTError("No alternatives in YandexGPT response")

        message = alternatives[0].get("message", {})
        return message.get("text", "")

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """Split text into chunks respecting sentence boundaries."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + MAX_INPUT_CHARS
            if end >= len(text):
                chunks.append(text[start:])
                break

            # Try to split at sentence boundary
            split_pos = text.rfind(". ", start + MAX_INPUT_CHARS // 2, end)
            if split_pos == -1:
                split_pos = text.rfind(" ", start + MAX_INPUT_CHARS // 2, end)
            if split_pos == -1:
                split_pos = end

            chunks.append(text[start : split_pos + 1])
            start = split_pos + 1 - CHUNK_OVERLAP_CHARS  # overlap for context

        return chunks
