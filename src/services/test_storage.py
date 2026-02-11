"""Unit tests for Object Storage client."""

import pytest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from src.services.storage import ObjectStorageClient, StorageError


@pytest.fixture
def storage(tmp_path):
    """Create a storage client with mocked boto3."""
    with patch("src.services.storage.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        client = ObjectStorageClient(
            access_key="test-key",
            secret_key="test-secret",
            bucket="test-bucket",
            endpoint="https://storage.yandexcloud.net",
        )
        client._mock_s3 = mock_s3
        yield client


class TestUploadFile:
    def test_upload_success(self, storage, tmp_path):
        test_file = tmp_path / "audio.ogg"
        test_file.write_bytes(b"fake audio")

        uri = storage.upload_file(str(test_file), "uploads/audio.ogg")

        assert uri == "s3://test-bucket/uploads/audio.ogg"
        storage._mock_s3.upload_file.assert_called_once_with(
            str(test_file), "test-bucket", "uploads/audio.ogg"
        )

    def test_upload_file_not_found(self, storage):
        with pytest.raises(StorageError, match="File not found"):
            storage.upload_file("/nonexistent/file.ogg", "key")

    def test_upload_s3_error(self, storage, tmp_path):
        test_file = tmp_path / "audio.ogg"
        test_file.write_bytes(b"data")

        storage._mock_s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Server Error"}},
            "upload_file",
        )

        with pytest.raises(StorageError, match="Upload failed"):
            storage.upload_file(str(test_file), "key")


class TestDeleteFile:
    def test_delete_success(self, storage):
        storage.delete_file("uploads/audio.ogg")

        storage._mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="uploads/audio.ogg"
        )

    def test_delete_s3_error(self, storage):
        storage._mock_s3.delete_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "delete_object",
        )
        with pytest.raises(StorageError, match="Delete failed"):
            storage.delete_file("nonexistent")


class TestGetStorageUri:
    def test_builds_correct_uri(self, storage):
        uri = storage.get_storage_uri("uploads/audio.ogg")
        assert uri == "https://storage.yandexcloud.net/test-bucket/uploads/audio.ogg"
