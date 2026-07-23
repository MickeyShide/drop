from typing import BinaryIO, TYPE_CHECKING
import boto3

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from drop.config import get_settings


class S3Storage:
    def __init__(self) -> None:
        settings = get_settings()

        self._bucket = settings.s3_bucket

        self._client: "S3Client" = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def upload(
        self, file: BinaryIO, storage_key: str, content_type: str | None
    ) -> None:
        extra_args: dict[str, str] = {}

        if content_type:
            extra_args["ContentType"] = content_type

        self._client.upload_fileobj(
            Fileobj=file,
            Bucket=self._bucket,
            Key=storage_key,
            ExtraArgs=extra_args or None,
        )

    def delete(self, storage_key: str) -> None:
        self._client.delete_object(
            Bucket=self._bucket,
            Key=storage_key,
        )

    def exists(self, storage_key: str) -> bool:
        try:
            self._client.head_object(
                Bucket=self._bucket,
                Key=storage_key,
            )
        except self._client.exceptions.ClientError:
            return False

        return True

    def create_download_url(
        self,
        storage_key: str,
        expires_in: int = 60,
    ) -> str:
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self._bucket,
                "Key": storage_key,
            },
            ExpiresIn=expires_in,
        )
