"""Yandex SpeechKit API client — async speech recognition."""

import asyncio
import logging

import httpx

from src.services.iam import IAMTokenManager

logger = logging.getLogger(__name__)

RECOGNIZE_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATION_URL = "https://operation.api.cloud.yandex.net/operations"
POLL_INTERVAL = 5  # seconds
MAX_POLL_TIME = 1800  # 30 minutes


class SpeechKitError(Exception):
    """Raised when SpeechKit API calls fail."""
    pass


class SpeechKitClient:
    """Client for Yandex SpeechKit async (deferred) speech recognition.

    Submits audio for recognition, polls for completion, and returns text.
    """

    def __init__(
        self,
        iam_manager: IAMTokenManager,
        folder_id: str,
        api_endpoint: str = "https://transcribe.api.cloud.yandex.net",
    ) -> None:
        self._iam = iam_manager
        self._folder_id = folder_id
        self._recognize_url = f"{api_endpoint}/speech/stt/v2/longRunningRecognize"

    async def _get_headers(self) -> dict[str, str]:
        token = await self._iam.get_token()
        return {
            "Authorization": f"Bearer {token}",
        }

    async def recognize(
        self,
        audio_uri: str,
        language: str = "ru-RU",
        model: str = "general",
        sample_rate: int = 48000,
    ) -> str:
        """Submit audio for recognition and wait for the result.

        Args:
            audio_uri: HTTPS URI to the audio file in Object Storage.
            language: Recognition language code.
            model: Recognition model name.
            sample_rate: Audio sample rate in Hz.

        Returns:
            Concatenated recognized text from all chunks.

        Raises:
            SpeechKitError: On API errors or timeout.
        """
        operation_id = await self._submit(audio_uri, language, model, sample_rate)
        logger.info("SpeechKit operation started: %s", operation_id)

        result = await self._poll_until_done(operation_id)
        text = self._extract_text(result)
        logger.info("Recognition complete: %d characters", len(text))
        return text

    async def _submit(
        self,
        audio_uri: str,
        language: str,
        model: str,
        sample_rate: int,
    ) -> str:
        """Submit a recognition request and return the operation ID."""
        headers = await self._get_headers()
        body = {
            "config": {
                "specification": {
                    "languageCode": language,
                    "model": model,
                    "audioEncoding": "OGG_OPUS",
                    "sampleRateHertz": sample_rate,
                    "audioChannelCount": 1,
                }
            },
            "audio": {
                "uri": audio_uri,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._recognize_url,
                json=body,
                headers=headers,
                timeout=60.0,
            )

        if response.status_code != 200:
            raise SpeechKitError(
                f"Recognition submit failed: {response.status_code} — {response.text}"
            )

        data = response.json()
        operation_id = data.get("id")
        if not operation_id:
            raise SpeechKitError("No operation ID in response")
        return operation_id

    async def _poll_until_done(self, operation_id: str) -> dict:
        """Poll the operation status until completion or timeout."""
        url = f"{OPERATION_URL}/{operation_id}"
        elapsed = 0

        while elapsed < MAX_POLL_TIME:
            headers = await self._get_headers()
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=30.0)

            if response.status_code != 200:
                raise SpeechKitError(
                    f"Operation poll failed: {response.status_code} — {response.text}"
                )

            data = response.json()

            if data.get("error"):
                error = data["error"]
                raise SpeechKitError(
                    f"Recognition error: [{error.get('code')}] {error.get('message')}"
                )

            if data.get("done"):
                return data

            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        raise SpeechKitError(
            f"Recognition timed out after {MAX_POLL_TIME} seconds for operation {operation_id}"
        )

    @staticmethod
    def _extract_text(operation_result: dict) -> str:
        """Extract and concatenate text from all recognition chunks."""
        response = operation_result.get("response", {})
        chunks = response.get("chunks", [])

        texts = []
        for chunk in chunks:
            alternatives = chunk.get("alternatives", [])
            if alternatives:
                # Take the first (best) alternative
                texts.append(alternatives[0].get("text", ""))

        return " ".join(texts)
