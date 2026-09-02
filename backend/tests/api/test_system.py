"""Tests for health, readiness, error envelope consistency, and CORS."""

from __future__ import annotations

from httpx import AsyncClient

API = "/api/v1"


class TestHealth:
    async def test_liveness_is_ok(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"

    async def test_liveness_requires_no_authentication(self, client: AsyncClient) -> None:
        # A probe that needs credentials is a probe the platform cannot run.
        assert (await client.get(f"{API}/health")).status_code == 200

    async def test_readiness_reports_each_dependency(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/health/ready")

        assert response.status_code == 200
        checks = response.json()["checks"]
        assert checks["database"]["status"] == "ok"
        # Redis is not wired up until Phase 10. Reporting "ok" would be a lie.
        assert checks["redis"]["status"] == "not_configured"


class TestErrorEnvelope:
    async def test_unknown_route_uses_the_standard_envelope(self, client: AsyncClient) -> None:
        # Starlette's default 404 body is {"detail": ...}. Left unhandled it
        # would be the one response shape in the API that differs.
        response = await client.get(f"{API}/does-not-exist")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "RESOURCE_NOT_FOUND"
        assert "message" in error

    async def test_wrong_method_uses_the_standard_envelope(self, client: AsyncClient) -> None:
        response = await client.delete(f"{API}/health")

        assert response.status_code == 405
        assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"

    async def test_every_error_carries_a_correlation_id(self, client: AsyncClient) -> None:
        # This is what ties a user's bug report to a specific log entry.
        response = await client.get(f"{API}/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["correlation_id"]

    async def test_validation_errors_list_the_offending_fields(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/auth/register", json={"email": "nope"})

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert {f["field"] for f in fields} >= {"email", "password"}


class TestRequestContext:
    async def test_response_carries_a_correlation_id_header(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/health")
        assert response.headers["x-correlation-id"]

    async def test_inbound_correlation_id_is_preserved(self, client: AsyncClient) -> None:
        # Lets a trace span multiple services rather than restarting at ours.
        supplied = "01927b3e-9c4a-7f21-8e3d-2b1a5c8f9d47"
        response = await client.get(f"{API}/health", headers={"X-Correlation-ID": supplied})
        assert response.headers["x-correlation-id"] == supplied

    async def test_response_time_header_present(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/health")
        assert float(response.headers["x-response-time-ms"]) >= 0


class TestOpenApi:
    async def test_schema_is_served_outside_production(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")

        assert response.status_code == 200
        paths = response.json()["paths"]
        assert f"{API}/auth/register" in paths
        assert f"{API}/auth/login" in paths
        assert f"{API}/health" in paths
