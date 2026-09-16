"""The Cloud Storage adapter (ADR-011).

No network, no credentials, no bucket. `google-cloud-storage` is synchronous and
its client reads credentials on construction, so the tests substitute a fake
bucket at the one seam the adapter has for it — `_handle()`.

What these pin is the part a caller depends on: that this behaves like the local
adapter. Anything that has to know which storage it is talking to would push
cloud detail into every call site, which is what the Protocol exists to prevent.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ResourceNotFoundError
from app.integrations.storage import GcsObjectStorage, ObjectStorage


class FakeNotFound(Exception):
    """Stands in for `google.cloud.exceptions.NotFound`."""


class FakeBlob:
    def __init__(self, store: dict[str, tuple[bytes, str]], key: str) -> None:
        self._store = store
        self._key = key

    def upload_from_string(self, content: bytes, content_type: str) -> None:
        self._store[self._key] = (content, content_type)

    def download_as_bytes(self) -> bytes:
        if self._key not in self._store:
            raise FakeNotFound(self._key)
        return self._store[self._key][0]

    def delete(self, if_generation_match: object = None) -> None:
        if self._key not in self._store:
            raise FakeNotFound(self._key)
        del self._store[self._key]

    def exists(self) -> bool:
        return self._key in self._store


class FakeBucket:
    def __init__(self) -> None:
        self.store: dict[str, tuple[bytes, str]] = {}

    def blob(self, key: str) -> FakeBlob:
        return FakeBlob(self.store, key)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> GcsObjectStorage:
    adapter = GcsObjectStorage("demo-bucket")
    bucket = FakeBucket()
    monkeypatch.setattr(adapter, "_handle", lambda: bucket)

    # The adapter imports NotFound inside each method so the module stays
    # importable without the library. Point that import at the fake.
    import sys
    import types

    module = types.ModuleType("google.cloud.exceptions")
    module.NotFound = FakeNotFound  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.cloud.exceptions", module)
    return adapter


class TestItBehavesLikeTheLocalAdapter:
    def test_it_satisfies_the_protocol(self) -> None:
        """Structural, not nominal. A caller depends on the Protocol, so an
        adapter that drifts from it fails here rather than at the call site."""
        assert isinstance(GcsObjectStorage("demo-bucket"), ObjectStorage)

    async def test_what_goes_in_comes_back(self, storage: GcsObjectStorage) -> None:
        await storage.put("resumes/u1/a.pdf", b"%PDF-1.7", content_type="application/pdf")

        assert await storage.get("resumes/u1/a.pdf") == b"%PDF-1.7"

    async def test_the_content_type_is_kept(self, storage: GcsObjectStorage) -> None:
        """Served straight back by the download endpoint. Losing it means a
        browser guessing, which the endpoint sets `nosniff` to prevent."""
        await storage.put("k", b"x", content_type="application/pdf")

        assert storage._handle().store["k"][1] == "application/pdf"

    async def test_a_missing_object_raises_the_same_error_as_local(
        self, storage: GcsObjectStorage
    ) -> None:
        """`ResourceNotFoundError`, not the vendor's exception. A caller that
        had to catch `google.cloud.exceptions.NotFound` would know which storage
        it was talking to, which is the coupling the Protocol removes."""
        with pytest.raises(ResourceNotFoundError):
            await storage.get("resumes/u1/absent.pdf")

    async def test_deleting_something_absent_is_not_an_error(
        self, storage: GcsObjectStorage
    ) -> None:
        """Matches the local adapter's `unlink(missing_ok=True)`. The caller
        wanted it gone, and it is gone."""
        await storage.delete("never-existed")

    async def test_exists_reports_both_ways(self, storage: GcsObjectStorage) -> None:
        assert await storage.exists("k") is False

        await storage.put("k", b"x", content_type="text/plain")

        assert await storage.exists("k") is True

    async def test_delete_removes_it(self, storage: GcsObjectStorage) -> None:
        await storage.put("k", b"x", content_type="text/plain")

        await storage.delete("k")

        assert await storage.exists("k") is False


class TestConstruction:
    def test_the_name_says_where_it_points(self) -> None:
        """Logged at startup. "gcs" alone would not say which bucket, which is
        the one thing worth knowing when a deployment reads the wrong one."""
        assert GcsObjectStorage("careeriq-uploads").name == "gs://careeriq-uploads"

    def test_a_missing_bucket_is_refused(self) -> None:
        with pytest.raises(ValueError, match="STORAGE_BUCKET"):
            GcsObjectStorage("")

    def test_no_client_is_built_until_it_is_used(self) -> None:
        """Constructing a client reads credentials and can do network I/O.
        Doing that at import time breaks every developer machine and every test
        run that has neither."""
        adapter = GcsObjectStorage("demo-bucket")

        assert adapter._bucket is None
