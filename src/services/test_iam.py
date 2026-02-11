"""Unit tests for IAM token manager."""

import json
import time

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.iam import IAMTokenManager, IAMTokenError


@pytest.fixture
def sa_key_file(tmp_path):
    """Create a temporary service account key file."""
    key_data = {
        "id": "key-id-123",
        "service_account_id": "sa-id-456",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MhgHcTz6sE2I2yPB\naFDrBz9vFqU5xTL0Hm5PcCXn1P7v1qqGU/ayLnxCz9PnO+sPNwU1h5hvPlGa3Hf\nnpGPWv5rO3IjyHmWZ05CRKmP4K3G3yvOQntXjJY4EenV0BEcCryr8FgHzJGBpIml\ne1HxeDMy3FEfPJjGR7AtkBaBCbcR0NnfYbG2VM8OjETOd3PB8IYOAB9hOyP5d0XO\nQyHE3MdCGsBwLIPO5Ma0MXWJLE7IXFUfNAJk0fHxr8OhLHR3WXQE1mXvT8xXFDB\nnNTEBGpUhGPD3io85LIWBUJgjHFzBl99P7kM9QIDAQABAoIBAC5RgZ+hBx7xHNaM\npPgwGMnCd2vHoqFYHaAmWz3mMHMM2hxiOJHj7GF4KUdWpn2ZSHkDktMwMGpUN+Rd\n5l8A7vHBlxQ2cHlFSh5dN2qMaGGFnjYx5OPJV+NDB3V/jqRUslxMPNiKHNqZJm1L\n3YqL1sMLh3CC5Q6yrVVdXm2JJEE5UbSFOWPSwT3JLc4hm8MnOM4Jn1JFAbFCGe1r\n4DXOP3GXYVv3F1DBLPF09XwZI4lKNnMOjIBejL4Vb4iaHJLJHtGxVPr/j+cVAhvN\nhRFHmof9GKiR+867gIav7VH6BCLX7b2v7SBMBHEJJE2U1Rn3pU0sSLx8KT6SJr0B\n7nN3H4ECgYEA7wURp9MhZ3DZpxPdHOanJU+vRHkVIHVODL+4UWGCxC0BNN6MF0Xg\njGR+R0bcQFPG2sN0G9+tNlh04lfai04G0BlMebhp5uJXkE0NqJrPjT9LidqFvmkn\nloZpzMafnZvG3TjV7jIG0QLd1n6MHMHFuxVbtR1x0IN0G3bL7b7j0dkCgYEA4I4m\nt3oPIxBXcBD0Csc5CDXO6ZLQE3m0W7tyMLlk/ReyUoNjZ3gLp3u4sPH0FN3mVEcV\nv+9vB5j6IjjxKFETGBMFFp3YFVaCj+Of/pMfDFdOF1W4rfWIhGLqf9RTCYgFfP2o\n4GLnM8JBN4daFMNSMb2M3nZvT7F3X5sQS+VZZ0ECgYB2mI+MjpV7o1uZ1TkbQFfA\ndKJkG2jVN3uOCFJG7T8aR/GkrJCx7maQjXTe/HxRqfP2K8Gs1BLT5J3HOyxMUV4r\nv4GFlJmOuoX9vqJHqDm3GDBfFiDPiXDSIvPGCfK2GHJgZNgGpJe6cWfRK+O8e3h6\nvf44G1Hj5DqFpq//VLq02QKBgQCpN7ISfWpIm5SBEi83+n8q4N0cdXR11oI9KUfA\noEf0xNZ2rPLBhqHbSr6e2h9F/fqj9fkC4N4eLMcE3HkCjPr6ZFF70+sXxH7W/4fy\nZ2IEyF6CVWXO1c3qD8j3m8BjFxbGhf7PNJ7gV8rI5kDJfBQ6F3VJb7S5pVMXsM5F\n0zHoAQKBgQCL4m0QMBF0r6KFSuh5wb4K45HCbm6mGbBytDWrkDGGExio8hGLjad0\nMPb+9HGsAl8v4s5pLw9m6x3BSOMT/IB1TOL3Fe/p3RCygMvA9W3UGr/sK+pLPGis\nPyqJ7B+fvFMqfnsoMqfaIMaHxN7BSJmZQthqtBxLu5v6JJfJxpI8CA==\n-----END RSA PRIVATE KEY-----\n",
    }
    file_path = tmp_path / "sa-key.json"
    file_path.write_text(json.dumps(key_data))
    return str(file_path)


class TestIAMTokenManager:
    def test_load_key_success(self, sa_key_file):
        manager = IAMTokenManager(sa_key_file)
        assert manager._key_data["id"] == "key-id-123"

    def test_load_key_file_not_found(self):
        with pytest.raises(IAMTokenError, match="not found"):
            IAMTokenManager("/nonexistent/key.json")

    def test_load_key_missing_fields(self, tmp_path):
        bad_key = tmp_path / "bad.json"
        bad_key.write_text('{"id": "123"}')
        with pytest.raises(IAMTokenError, match="Missing field"):
            IAMTokenManager(str(bad_key))

    async def test_get_token_caches(self, sa_key_file):
        manager = IAMTokenManager(sa_key_file)
        manager._token = "cached-token"
        manager._expires_at = time.time() + 3600

        token = await manager.get_token()
        assert token == "cached-token"

    async def test_get_token_refreshes_on_expiry(self, sa_key_file):
        manager = IAMTokenManager(sa_key_file)
        manager._token = "old-token"
        manager._expires_at = time.time() - 1  # expired

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"iamToken": "new-token-abc"}

        with patch.object(manager, "_create_jwt", return_value="fake-jwt"):
            with patch("src.services.iam.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                token = await manager.get_token()
                assert token == "new-token-abc"

    async def test_get_token_api_error(self, sa_key_file):
        manager = IAMTokenManager(sa_key_file)
        manager._expires_at = 0

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch.object(manager, "_create_jwt", return_value="fake-jwt"):
            with patch("src.services.iam.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                with pytest.raises(IAMTokenError, match="403"):
                    await manager.get_token()

    def test_invalidate(self, sa_key_file):
        manager = IAMTokenManager(sa_key_file)
        manager._token = "some-token"
        manager._expires_at = time.time() + 3600

        manager.invalidate()
        assert manager._token is None
        assert manager._expires_at == 0
