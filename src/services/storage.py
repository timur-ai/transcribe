"""Yandex Object Storage client — upload and delete files via S3 API."""

import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when Object Storage operations fail."""
    pass


class ObjectStorageClient:
    """Client for Yandex Object Storage (S3-compatible).

    Handles uploading audio files for SpeechKit processing
    and cleaning them up after transcription.
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket: str,
        endpoint: str = "https://storage.yandexcloud.net",
    ) -> None:
        self._bucket = bucket
        self._endpoint = endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def upload_file(self, local_path: str, remote_key: str) -> str:
        """Upload a local file to Object Storage.

        Args:
            local_path: Path to the local file.
            remote_key: Key (path) in the bucket.

        Returns:
            S3 URI in the format ``s3://bucket/key``.

        Raises:
            StorageError: If the upload fails.
        """
        path = Path(local_path)
        if not path.exists():
            raise StorageError(f"File not found: {local_path}")

        try:
            self._client.upload_file(str(path), self._bucket, remote_key)
        except ClientError as e:
            raise StorageError(f"Upload failed: {e}") from e

        uri = f"s3://{self._bucket}/{remote_key}"
        logger.info("Uploaded %s → %s", local_path, uri)
        return uri

    def delete_file(self, remote_key: str) -> None:
        """Delete a file from Object Storage.

        Args:
            remote_key: Key (path) in the bucket.

        Raises:
            StorageError: If the deletion fails.
        """
        try:
            self._client.delete_object(Bucket=self._bucket, Key=remote_key)
        except ClientError as e:
            raise StorageError(f"Delete failed: {e}") from e
        logger.info("Deleted s3://%s/%s", self._bucket, remote_key)

    def get_storage_uri(self, remote_key: str) -> str:
        """Build the HTTPS URI for SpeechKit to access the file.

        SpeechKit requires ``https://storage.yandexcloud.net/bucket/key`` format.
        """
        return f"{self._endpoint}/{self._bucket}/{remote_key}"
