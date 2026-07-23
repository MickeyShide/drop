import io
import uuid
from unittest.mock import MagicMock, patch

from drop.infrastructure.storage.s3 import S3Storage


def test_s3_storage_lifecycle_with_mock() -> None:
    mock_boto_client = MagicMock()
    mock_boto_client.generate_presigned_url.return_value = "https://s3.local/presigned-url"

    with patch("boto3.client", return_value=mock_boto_client):
        storage = S3Storage()
        storage_key = f"test/{uuid.uuid4()}/file.txt"
        file_data = io.BytesIO(b"Hello S3 Storage Test")

        # 1. Upload
        storage.upload(file_data, storage_key, "text/plain")
        mock_boto_client.upload_fileobj.assert_called_once()

        # 2. Exists check
        mock_boto_client.head_object.return_value = {}
        assert storage.exists(storage_key) is True

        # 3. Download URL presigning
        url = storage.create_download_url(storage_key, expires_in=60)
        assert url == "https://s3.local/presigned-url"

        # 4. Delete
        storage.delete(storage_key)
        mock_boto_client.delete_object.assert_called_once_with(
            Bucket=storage._bucket,
            Key=storage_key,
        )


def test_s3_storage_exists_returns_false_on_client_error() -> None:
    mock_boto_client = MagicMock()
    # Simulate ClientError exception when object does not exist
    mock_boto_client.exceptions.ClientError = Exception
    mock_boto_client.head_object.side_effect = Exception("NoSuchKey")

    with patch("boto3.client", return_value=mock_boto_client):
        storage = S3Storage()
        assert storage.exists("non-existent-key") is False
