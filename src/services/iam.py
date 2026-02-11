"""Yandex IAM token management — obtain and refresh tokens from service account key."""

import asyncio
import json
import time
from pathlib import Path

import httpx
import jwt

IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
TOKEN_LIFETIME_SECONDS = 3600  # Request 1-hour tokens
TOKEN_REFRESH_MARGIN = 300  # Refresh 5 minutes before expiry


class IAMTokenError(Exception):
    """Raised when IAM token acquisition fails."""
    pass


class IAMTokenManager:
    """Manages IAM tokens for Yandex Cloud API authentication.

    Reads a service account key JSON file, creates a JWT, exchanges it
    for an IAM token, and caches the token with automatic refresh.
    """

    def __init__(self, key_file_path: str) -> None:
        self._key_data = self._load_key(key_file_path)
        self._token: str | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _load_key(path: str) -> dict:
        """Load service account key JSON."""
        key_path = Path(path)
        if not key_path.exists():
            raise IAMTokenError(f"Service account key file not found: {path}")
        with open(key_path) as f:
            data = json.load(f)
        required_fields = ["id", "service_account_id", "private_key"]
        for field in required_fields:
            if field not in data:
                raise IAMTokenError(f"Missing field '{field}' in service account key file")
        return data

    def _create_jwt(self) -> str:
        """Create a signed JWT for IAM token exchange."""
        now = int(time.time())
        payload = {
            "aud": IAM_TOKEN_URL,
            "iss": self._key_data["service_account_id"],
            "iat": now,
            "exp": now + TOKEN_LIFETIME_SECONDS,
        }
        headers = {
            "kid": self._key_data["id"],
        }
        return jwt.encode(
            payload,
            self._key_data["private_key"],
            algorithm="PS256",
            headers=headers,
        )

    async def _exchange_jwt_for_token(self, encoded_jwt: str) -> tuple[str, float]:
        """Exchange a JWT for an IAM token via Yandex API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                IAM_TOKEN_URL,
                json={"jwt": encoded_jwt},
                timeout=30.0,
            )
        if response.status_code != 200:
            raise IAMTokenError(
                f"IAM token request failed: {response.status_code} — {response.text}"
            )
        data = response.json()
        iam_token = data.get("iamToken")
        if not iam_token:
            raise IAMTokenError("No iamToken in response")
        expires_at = time.time() + TOKEN_LIFETIME_SECONDS - TOKEN_REFRESH_MARGIN
        return iam_token, expires_at

    async def get_token(self) -> str:
        """Get a valid IAM token, refreshing if necessary (thread-safe)."""
        if self._token and time.time() < self._expires_at:
            return self._token

        async with self._lock:
            # Double-check after acquiring lock
            if self._token and time.time() < self._expires_at:
                return self._token

            encoded_jwt = self._create_jwt()
            self._token, self._expires_at = await self._exchange_jwt_for_token(encoded_jwt)
            return self._token

    def invalidate(self) -> None:
        """Force token refresh on next get_token() call."""
        self._token = None
        self._expires_at = 0
