import asyncio
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.base import ObjectStorageError


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(
                self._client.head_bucket,
                Bucket=self._bucket,
            )
            return
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                raise ObjectStorageError("Bucket check failed") from exc
        except (BotoCoreError, OSError) as exc:
            raise ObjectStorageError("Bucket check failed") from exc

        try:
            create_options: dict[str, Any] = {"Bucket": self._bucket}
            if self._client.meta.region_name != "us-east-1":
                create_options["CreateBucketConfiguration"] = {
                    "LocationConstraint": self._client.meta.region_name
                }
            await asyncio.to_thread(
                self._client.create_bucket,
                **create_options,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObjectStorageError("Bucket creation failed") from exc

    async def upload_file(
        self,
        storage_key: str,
        file: BinaryIO,
        content_type: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._client.upload_fileobj,
                file,
                self._bucket,
                storage_key,
                ExtraArgs={"ContentType": content_type},
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObjectStorageError("Object upload failed") from exc

    async def delete_file(self, storage_key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=storage_key,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObjectStorageError("Object deletion failed") from exc

    async def is_available(self) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_bucket,
                Bucket=self._bucket,
            )
        except (BotoCoreError, ClientError, OSError):
            return False
        return True

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)
