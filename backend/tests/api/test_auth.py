"""API tests for the authentication endpoints.

Each test maps to an acceptance criterion in docs/requirements.md. Where a test
encodes a security property rather than a feature, the reasoning is stated
inline — those are the ones most likely to be "simplified" later by someone who
does not know why they exist.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.models.user import RefreshToken, User

API = "/api/v1"


class TestRegister:
    async def test_creates_account_and_returns_tokens(
        self, client: AsyncClient, user_payload: dict[str, str]
    ) -> None:
        response = await client.post(f"{API}/auth/register", json=user_payload)

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == user_payload["email"]
        assert body["user"]["role"] == "USER"
        assert body["user"]["is_active"] is True
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]
        assert body["tokens"]["token_type"] == "bearer"
        assert body["tokens"]["expires_in"] == 1800  # US-1.3 AC1

    async def test_response_never_contains_password_or_hash(
        self, client: AsyncClient, user_payload: dict[str, str]
    ) -> None:
        # US-1.1 AC2. Asserted on the raw text so a nested or renamed field
        # cannot smuggle it through.
        response = await client.post(f"{API}/auth/register", json=user_payload)

        assert user_payload["password"] not in response.text
        assert "password_hash" not in response.text
        assert "$2b$" not in response.text

    async def test_creates_a_profile(
        self, client: AsyncClient, db_session: AsyncSession, user_payload: dict[str, str]
    ) -> None:
        # Every later feature assumes a profile exists rather than handling None.
        response = await client.post(f"{API}/auth/register", json=user_payload)
        user_id = response.json()["user"]["id"]

        profile = await db_session.scalar(select(Profile).where(Profile.user_id == user_id))
        assert profile is not None
        assert profile.full_name == user_payload["full_name"]
        assert profile.target_roles == []

    async def test_password_is_stored_hashed(
        self, client: AsyncClient, db_session: AsyncSession, user_payload: dict[str, str]
    ) -> None:
        await client.post(f"{API}/auth/register", json=user_payload)

        user = await db_session.scalar(select(User).where(User.email == user_payload["email"]))
        assert user is not None
        assert user.password_hash is not None
        assert user.password_hash != user_payload["password"]
        assert user.password_hash.startswith("$2b$")

    async def test_duplicate_email_does_not_confirm_the_account_exists(
        self, client: AsyncClient, user_payload: dict[str, str]
    ) -> None:
        """US-1.1 AC3 — the endpoint must not be an account-existence oracle."""
        await client.post(f"{API}/auth/register", json=user_payload)
        response = await client.post(f"{API}/auth/register", json=user_payload)

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "REGISTRATION_FAILED"
        # The message must not say "already registered", "exists", or similar.
        assert "exist" not in error["message"].lower()
        assert "already" not in error["message"].lower()
        assert "taken" not in error["message"].lower()

    async def test_email_is_case_insensitive(
        self, client: AsyncClient, user_payload: dict[str, str]
    ) -> None:
        # CITEXT column: Priya@... and priya@... are the same account.
        await client.post(f"{API}/auth/register", json=user_payload)
        response = await client.post(
            f"{API}/auth/register",
            json={**user_payload, "email": user_payload["email"].upper()},
        )
        assert response.status_code == 409

    async def test_rejects_short_password(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/register", json={"email": "a@b.com", "password": "short1"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_password_without_a_digit(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": "a@b.com", "password": "no-digits-here"},
        )
        assert response.status_code == 422

    async def test_rejects_password_without_a_letter(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/register", json={"email": "a@b.com", "password": "1234567890"}
        )
        assert response.status_code == 422

    async def test_validation_error_does_not_echo_the_password(self, client: AsyncClient) -> None:
        # Pydantic's default error payload includes the rejected input; the
        # handler strips it so a password never lands in a log or a proxy cache.
        secret = "short1"
        response = await client.post(
            f"{API}/auth/register", json={"email": "a@b.com", "password": secret}
        )
        assert secret not in response.text

    async def test_rejects_invalid_email(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/register",
            json={"email": "not-an-email", "password": "correct-horse-9"},
        )
        assert response.status_code == 422


class TestLogin:
    async def test_valid_credentials_return_tokens(
        self, client: AsyncClient, registered_user: dict, user_payload: dict[str, str]
    ) -> None:
        response = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )

        assert response.status_code == 200
        assert response.json()["tokens"]["access_token"]

    async def test_records_last_login(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )
        user = await db_session.scalar(select(User).where(User.email == user_payload["email"]))
        assert user is not None
        assert user.last_login_at is not None

    async def test_wrong_password_and_unknown_email_are_indistinguishable(
        self, client: AsyncClient, registered_user: dict, user_payload: dict[str, str]
    ) -> None:
        """Different responses here would let an attacker enumerate accounts."""
        wrong_password = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": "wrong-password-1"},
        )
        unknown_email = await client.post(
            f"{API}/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password-1"},
        )

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]
        assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]

    async def test_inactive_account_cannot_log_in(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        user = await db_session.scalar(select(User).where(User.email == user_payload["email"]))
        assert user is not None
        user.is_active = False
        await db_session.flush()

        response = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )
        assert response.status_code == 401
        # Same generic error: "account disabled" would confirm registration.
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


class TestCurrentUser:
    async def test_returns_the_authenticated_user(
        self, client: AsyncClient, auth_headers: dict[str, str], user_payload: dict
    ) -> None:
        response = await client.get(f"{API}/auth/me", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["email"] == user_payload["email"]

    async def test_requires_a_token(self, client: AsyncClient) -> None:
        response = await client.get(f"{API}/auth/me")

        assert response.status_code == 401
        # Must use the standard envelope, not FastAPI's default {"detail": ...}.
        assert "error" in response.json()

    async def test_rejects_a_malformed_token(self, client: AsyncClient) -> None:
        response = await client.get(
            f"{API}/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_TOKEN"

    async def test_rejects_a_refresh_token_used_as_an_access_token(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        # Refresh tokens are opaque strings, not JWTs, so this must fail at
        # decode. Asserts the two token types are not interchangeable.
        refresh = registered_user["tokens"]["refresh_token"]
        response = await client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {refresh}"}
        )
        assert response.status_code == 401


class TestRefreshRotation:
    async def test_returns_a_new_token_pair(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        original = registered_user["tokens"]["refresh_token"]
        response = await client.post(f"{API}/auth/refresh", json={"refresh_token": original})

        assert response.status_code == 200
        assert response.json()["refresh_token"] != original

    async def test_old_token_stops_working_after_rotation(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        original = registered_user["tokens"]["refresh_token"]
        await client.post(f"{API}/auth/refresh", json={"refresh_token": original})

        replayed = await client.post(f"{API}/auth/refresh", json={"refresh_token": original})
        assert replayed.status_code == 401

    async def test_reuse_revokes_the_entire_family(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        """US-1.3 AC2 — the property that makes rotation worth having.

        Rotating alone is not enough: if a stolen token is replayed we cannot
        tell attacker from victim, so every token in the chain must die,
        including the one the current holder just received.
        """
        first = registered_user["tokens"]["refresh_token"]

        second = (await client.post(f"{API}/auth/refresh", json={"refresh_token": first})).json()[
            "refresh_token"
        ]

        # Replay the consumed token — the reuse signal.
        replay = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TOKEN_REUSE_DETECTED"

        # The legitimate holder's newer token must now also be dead.
        after = await client.post(f"{API}/auth/refresh", json={"refresh_token": second})
        assert after.status_code == 401

    async def test_rotation_keeps_tokens_in_one_family(
        self, client: AsyncClient, db_session: AsyncSession, registered_user: dict
    ) -> None:
        first = registered_user["tokens"]["refresh_token"]
        await client.post(f"{API}/auth/refresh", json={"refresh_token": first})

        tokens = list((await db_session.scalars(select(RefreshToken))).all())
        assert len(tokens) == 2
        assert len({t.family_id for t in tokens}) == 1

        revoked = [t for t in tokens if t.revoked_at is not None]
        assert len(revoked) == 1
        # The revoked token points at its replacement, so the chain is walkable.
        assert revoked[0].replaced_by_id is not None

    async def test_unknown_token_rejected(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/auth/refresh", json={"refresh_token": "made-up-token"})
        assert response.status_code == 401

    async def test_refresh_token_is_stored_only_as_a_hash(
        self, client: AsyncClient, db_session: AsyncSession, registered_user: dict
    ) -> None:
        plaintext = registered_user["tokens"]["refresh_token"]

        stored = list((await db_session.scalars(select(RefreshToken))).all())
        assert len(stored) == 1
        # A database dump must not yield usable sessions.
        assert stored[0].token_hash != plaintext
        assert len(stored[0].token_hash) == 64


class TestLogout:
    async def test_revokes_the_token(self, client: AsyncClient, registered_user: dict) -> None:
        token = registered_user["tokens"]["refresh_token"]

        assert (
            await client.post(f"{API}/auth/logout", json={"refresh_token": token})
        ).status_code == 200

        after = await client.post(f"{API}/auth/refresh", json={"refresh_token": token})
        assert after.status_code == 401

    async def test_is_idempotent(self, client: AsyncClient, registered_user: dict) -> None:
        token = registered_user["tokens"]["refresh_token"]
        await client.post(f"{API}/auth/logout", json={"refresh_token": token})
        second = await client.post(f"{API}/auth/logout", json={"refresh_token": token})

        assert second.status_code == 200

    async def test_unknown_token_still_succeeds(self, client: AsyncClient) -> None:
        # Returning 404 would turn logout into a token-validity oracle.
        response = await client.post(f"{API}/auth/logout", json={"refresh_token": "never-existed"})
        assert response.status_code == 200


class TestChangePassword:
    async def test_changes_the_password(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        user_payload: dict[str, str],
    ) -> None:
        response = await client.post(
            f"{API}/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": user_payload["password"],
                "new_password": "brand-new-password-7",
            },
        )
        assert response.status_code == 200

        old = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )
        assert old.status_code == 401

        new = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": "brand-new-password-7"},
        )
        assert new.status_code == 200

    async def test_revokes_all_existing_sessions(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        # If the password was changed because it leaked, leaving other sessions
        # alive defeats the purpose.
        refresh = registered_user["tokens"]["refresh_token"]

        await client.post(
            f"{API}/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": user_payload["password"],
                "new_password": "brand-new-password-7",
            },
        )

        after = await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
        assert after.status_code == 401

    async def test_wrong_current_password_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            f"{API}/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": "not-the-password-1",
                "new_password": "brand-new-password-7",
            },
        )
        assert response.status_code == 401

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            f"{API}/auth/change-password",
            json={
                "current_password": "whatever-1",
                "new_password": "brand-new-password-7",
            },
        )
        assert response.status_code == 401

    async def test_new_password_must_meet_policy(
        self, client: AsyncClient, auth_headers: dict[str, str], user_payload: dict
    ) -> None:
        response = await client.post(
            f"{API}/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": user_payload["password"],
                "new_password": "weak",
            },
        )
        assert response.status_code == 422
