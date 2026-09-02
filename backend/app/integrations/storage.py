"""Object storage behind an interface (ADR-011, ADR-018).

Resume files never live on the application filesystem in production: Cloud Run
containers have no persistent disk, and ADR-014 requires uploads to be stored
outside the app's own filesystem regardless. The local adapter exists so
development needs no cloud account; the interface is shaped for Cloud Storage.

Keys are generated UUIDv7 paths, never derived from the client filename — that
is what makes path traversal structurally impossible rather than filtered.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

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


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    # Only the local adapter exists today. The Cloud Storage adapter lands in
    # Phase 11; adding it is a new class and a config value, not a change to any
    # caller.
    return LocalObjectStorage(Path(settings.storage_local_path))
