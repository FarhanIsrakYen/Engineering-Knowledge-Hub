from typing import BinaryIO


class InMemoryObjectStorage:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted_keys: list[str] = []
        self.closed = False

    async def ensure_bucket(self) -> None:
        return None

    async def upload_file(
        self,
        storage_key: str,
        file: BinaryIO,
        content_type: str,
    ) -> None:
        self.objects[storage_key] = (file.read(), content_type)

    async def delete_file(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)
        self.deleted_keys.append(storage_key)

    async def download_file(self, storage_key: str) -> bytes:
        return self.objects[storage_key][0]

    async def is_available(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True
