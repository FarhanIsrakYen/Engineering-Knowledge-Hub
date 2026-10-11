from typing import BinaryIO, Protocol


class ObjectStorageError(Exception):
    pass


class ObjectStorage(Protocol):
    async def ensure_bucket(self) -> None: ...

    async def upload_file(
        self,
        storage_key: str,
        file: BinaryIO,
        content_type: str,
    ) -> None: ...

    async def delete_file(self, storage_key: str) -> None: ...

    async def download_file(self, storage_key: str) -> bytes: ...

    async def is_available(self) -> bool: ...

    async def close(self) -> None: ...
