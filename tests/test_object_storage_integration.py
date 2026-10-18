import asyncio
import os
from io import BytesIO
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.storage import S3ObjectStorage


@pytest.mark.integration
def test_minio_upload_and_delete() -> None:
    if os.getenv("EKH_TEST_OBJECT_STORAGE") != "true":
        pytest.skip("EKH_TEST_OBJECT_STORAGE=true is required for the MinIO test")

    settings = Settings(_env_file=None)
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
    )
    storage_key = f"integration-tests/{uuid4()}.txt"

    async def exercise_storage() -> None:
        await storage.ensure_bucket()
        assert await storage.is_available() is True
        await storage.upload_file(storage_key, BytesIO(b"storage test"), "text/plain")
        assert await storage.download_file(storage_key) == b"storage test"
        await storage.delete_file(storage_key)
        await storage.close()

    asyncio.run(exercise_storage())
