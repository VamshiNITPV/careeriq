"""Object storage behind an interface (ADR-011, ADR-018).

Resume files never live on the application filesystem in production: a container
has no persistent disk worth trusting, and ADR-014 requires uploads to be stored
outside the app's own filesystem regardless. The local adapter exists so
development needs no cloud account.

**The Cloud Storage adapter arrived 2026-09-16, with the deployment.** Until
then the factory returned the local adapter unconditionally while the production
config refused `STORAGE_PROVIDER=local` -- so setting anything else passed the
check and wrote to the container's disk anyway, silently. A safety rule that can
be satisfied without being obeyed is worse than no rule, because it reads as
one.

Keys are generated UUIDv7 paths, never derived from the client filename — that
is what makes path traversal structurally impossible rather than filtered.
"""

from __future__ import annotations

import asyncio
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.core.config import get_settings
from app.core.exceptions import ResourceNotFoundError
from app.core.ids import uuid7
from app.core.logging import get_logger

log = get_logger(__name__)


def build_storage_key(*, user_id: str, extension: str) -> str:
    """Generate an opaque storage key.

    Partitioned by user so a listing never mixes tenants and a bulk delete for
    one user is a prefix operation. The filename component is a fresh UUIDv7,
    so two uploads of the same file never collide and nothing about the
    original name survives into the path.
    """
    return f"resumes/{user_id}/{uuid7()}{extension}"


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes, *, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    @property
    def name(self) -> str: ...


class LocalObjectStorage:
    """Filesystem-backed storage for development and tests."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return f"local://{self._root}"

    def _resolve(self, key: str) -> Path:
        """Map a key to a path, refusing anything that escapes the root.

        Keys are generated internally, so this should be unreachable. It is here
        because "should be unreachable" is exactly the assumption that stops
        holding when a later feature accepts a key from a request.
        """
        candidate = (self._root / key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return candidate

    async def put(self, key: str, content: bytes, *, content_type: str) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name then rename. rename is atomic on POSIX, so a
        # crash mid-write leaves no half-written file that later reads as a
        # corrupt PDF.
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(content)
        temporary.replace(path)
        log.debug("stored object", key=key, bytes=len(content), content_type=content_type)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise ResourceNotFoundError("Stored file")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def clear(self) -> None:
        """Test helper. Never called by application code."""
        shutil.rmtree(self._root, ignore_errors=True)
        self._root.mkdir(parents=True, exist_ok=True)


class GcsObjectStorage:
    """Google Cloud Storage.

    The client is synchronous, so every call runs on a worker thread. That is
    not a compromise: `google-cloud-storage` has no async interface, and the
    alternative -- reimplementing signed requests over httpx -- would mean owning
    authentication, retries and resumable uploads to avoid one `to_thread`.

    The client is built lazily and reused. Constructing it reads credentials and
    can perform network I/O, which must not happen at import time on a machine
    that has none.
    """

    def __init__(self, bucket: str) -> None:
        if not bucket:
            raise ValueError("STORAGE_BUCKET is required when STORAGE_PROVIDER is 'gcs'.")
        self._bucket_name = bucket
        self._bucket: Any | None = None

    @property
    def name(self) -> str:
        return f"gs://{self._bucket_name}"

    def _handle(self) -> Any:
        if self._bucket is None:
            from google.cloud import storage as gcs

            self._bucket = gcs.Client().bucket(self._bucket_name)
        return self._bucket

    async def put(self, key: str, content: bytes, *, content_type: str) -> None:
        def _upload() -> None:
            self._handle().blob(key).upload_from_string(content, content_type=content_type)

        await asyncio.to_thread(_upload)
        log.debug("stored object", key=key, bytes=len(content), content_type=content_type)

    async def get(self, key: str) -> bytes:
        from google.cloud.exceptions import NotFound

        def _download() -> bytes:
            return self._handle().blob(key).download_as_bytes()

        try:
            return await asyncio.to_thread(_download)
        except NotFound as exc:
            # The same error the local adapter raises, so callers do not have to
            # know which storage they are talking to.
            raise ResourceNotFoundError("Stored file") from exc

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            # Matches the local adapter's `unlink(missing_ok=True)`: deleting
            # something already gone is the outcome the caller wanted.
            self._handle().blob(key).delete(if_generation_match=None)

        from google.cloud.exceptions import NotFound

        try:
            await asyncio.to_thread(_delete)
        except NotFound:
            return

    async def exists(self, key: str) -> bool:
        def _exists() -> bool:
            return bool(self._handle().blob(key).exists())

        return await asyncio.to_thread(_exists)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    settings = get_settings()

    if settings.storage_provider == "gcs":
        return GcsObjectStorage(settings.storage_bucket)

    return LocalObjectStorage(Path(settings.storage_local_path))
