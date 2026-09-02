"""API tests for password reset, email verification, and security notifications.

The recurring theme: none of these endpoints may reveal whether an email address
has an account. That property is easy to break with a well-meaning "helpful"
error message, so it is asserted explicitly rather than assumed.
"""

from __future__ import annotations

import re

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email import CapturingEmailProvider
from app.models.enums import VerificationPurpose
from app.models.user import User
from app.models.verification import VerificationToken

API = "/api/v1"


def extract_token(body: str) -> str:
    """Pull the token out of a link in an email body."""
    match = re.search(r"[?&]token=([A-Za-z0-9_\-%]+)", body)
    assert match is not None, f"no token found in email body:\n{body}"
    return match.group(1)


class TestVerificationEmailOnRegister:
    async def test_registration_sends_a_verification_email(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        await client.post(f"{API}/auth/register", json=user_payload)

        message = emails.last_to(user_payload["email"])
        assert message is not None
        assert "confirm" in message.subject.lower()
        assert "/verify-email?token=" in message.text_body

    async def test_account_is_usable_before_verifying(
        self, client: AsyncClient, user_payload: dict[str, str]
    ) -> None:
        # Verification confirms the address; it does not gate access. Blocking
        # sign-in would strand anyone whose mail is delayed or filtered.
        await client.post(f"{API}/auth/register", json=user_payload)

        response = await client.post(
            f"{API}/auth/login",
            json={"email": user_payload["email"], "password": user_payload["password"]},
        )
        assert response.status_code == 200
        assert response.json()["user"]["email_verified_at"] is None

    async def test_email_body_is_not_empty_in_either_part(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        # Clients that strip HTML must still show something.
        await client.post(f"{API}/auth/register", json=user_payload)
        message = emails.last_to(user_payload["email"])

        assert message is not None
        assert len(message.text_body.strip()) > 0
        assert message.html_body is not None and len(message.html_body.strip()) > 0


class TestEmailVerification:
    async def test_valid_link_marks_the_email_verified(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        await client.post(f"{API}/auth/register", json=user_payload)
        message = emails.last_to(user_payload["email"])
        assert message is not None

        response = await client.post(
            f"{API}/auth/verify-email", json={"token": extract_token(message.text_body)}
        )

        assert response.status_code == 200
        assert response.json()["email_verified_at"] is not None

    async def test_verification_needs_no_session(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        # The link is routinely opened on a different device from the one that
        # registered, where no session exists.
        await client.post(f"{API}/auth/register", json=user_payload)
        message = emails.last_to(user_payload["email"])
        assert message is not None

        response = await client.post(
            f"{API}/auth/verify-email", json={"token": extract_token(message.text_body)}
        )
        assert response.status_code == 200

    async def test_token_cannot_be_reused(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        await client.post(f"{API}/auth/register", json=user_payload)
        message = emails.last_to(user_payload["email"])
        assert message is not None
        token = extract_token(message.text_body)

        assert (
            await client.post(f"{API}/auth/verify-email", json={"token": token})
        ).status_code == 200

        replay = await client.post(f"{API}/auth/verify-email", json={"token": token})
        assert replay.status_code == 401

    async def test_unknown_token_rejected(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/auth/verify-email", json={"token": "not-a-real-token"})
        assert response.status_code == 401

    async def test_resend_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"{API}/auth/resend-verification")
        assert response.status_code == 401

    async def test_resend_invalidates_the_previous_link(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        auth_headers: dict[str, str],
        user_payload: dict[str, str],
    ) -> None:
        # Otherwise clicking "resend" three times leaves three working keys to
        # the account sitting in an inbox.
        first = emails.last_to(user_payload["email"])
        assert first is not None
        first_token = extract_token(first.text_body)

        await client.post(f"{API}/auth/resend-verification", headers=auth_headers)

        second = emails.last_to(user_payload["email"])
        assert second is not None
        assert extract_token(second.text_body) != first_token

        stale = await client.post(f"{API}/auth/verify-email", json={"token": first_token})
        assert stale.status_code == 401


class TestForgotPassword:
    async def test_sends_a_reset_link_for_a_real_account(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        emails.clear()
        response = await client.post(
            f"{API}/auth/forgot-password", json={"email": user_payload["email"]}
        )

        assert response.status_code == 200
        message = emails.last_to(user_payload["email"])
        assert message is not None
        assert "/reset-password?token=" in message.text_body

    async def test_unknown_address_is_indistinguishable_from_a_real_one(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        """The property that stops this endpoint enumerating accounts."""
        known = await client.post(
            f"{API}/auth/forgot-password", json={"email": user_payload["email"]}
        )
        unknown = await client.post(
            f"{API}/auth/forgot-password", json={"email": "nobody@example.com"}
        )

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()

    async def test_no_email_is_sent_to_an_unknown_address(
        self, client: AsyncClient, emails: CapturingEmailProvider
    ) -> None:
        await client.post(f"{API}/auth/forgot-password", json={"email": "nobody@example.com"})
        assert emails.last_to("nobody@example.com") is None

    async def test_requesting_twice_invalidates_the_first_link(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        await client.post(f"{API}/auth/forgot-password", json={"email": user_payload["email"]})
        first_token = extract_token(emails.last_to(user_payload["email"]).text_body)  # type: ignore[union-attr]

        await client.post(f"{API}/auth/forgot-password", json={"email": user_payload["email"]})
        second_token = extract_token(emails.last_to(user_payload["email"]).text_body)  # type: ignore[union-attr]

        assert first_token != second_token

        stale = await client.post(
            f"{API}/auth/reset-password",
            json={"token": first_token, "new_password": "brand-new-password-7"},
        )
        assert stale.status_code == 401

    async def test_token_is_stored_only_as_a_hash(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        emails.clear()
        await client.post(f"{API}/auth/forgot-password", json={"email": user_payload["email"]})
        plaintext = extract_token(emails.last_to(user_payload["email"]).text_body)  # type: ignore[union-attr]

        stored = list(
            (
                await db_session.scalars(
                    select(VerificationToken).where(
                        VerificationToken.purpose == VerificationPurpose.PASSWORD_RESET
                    )
                )
            ).all()
        )
        assert len(stored) == 1
        # A database leak must not hand over live reset links.
        assert stored[0].token_hash != plaintext
        assert len(stored[0].token_hash) == 64


class TestResetPassword:
    async def _request_reset(
        self, client: AsyncClient, emails: CapturingEmailProvider, email: str
    ) -> str:
        emails.clear()
        await client.post(f"{API}/auth/forgot-password", json={"email": email})
        message = emails.last_to(email)
        assert message is not None
        return extract_token(message.text_body)

    async def test_sets_the_new_password(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        token = await self._request_reset(client, emails, user_payload["email"])

        response = await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "brand-new-password-7"},
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

    async def test_link_is_single_use(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        # A reset link is forwarded, logged by mail scanners, and left in
        # browser history. It must work exactly once.
        token = await self._request_reset(client, emails, user_payload["email"])

        first = await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "brand-new-password-7"},
        )
        assert first.status_code == 200

        second = await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "another-password-8"},
        )
        assert second.status_code == 401

    async def test_revokes_every_existing_session(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        # A reset usually follows losing control of the account, so leaving
        # sessions alive would defeat the purpose.
        refresh = registered_user["tokens"]["refresh_token"]
        token = await self._request_reset(client, emails, user_payload["email"])

        await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "brand-new-password-7"},
        )

        after = await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
        assert after.status_code == 401

    async def test_completing_a_reset_also_verifies_the_email(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        # Receiving the link proves control of the mailbox, which is exactly
        # what verification asks for.
        token = await self._request_reset(client, emails, user_payload["email"])
        await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "brand-new-password-7"},
        )

        user = await db_session.scalar(select(User).where(User.email == user_payload["email"]))
        assert user is not None
        assert user.email_verified_at is not None

    async def test_sends_a_confirmation_notice(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        token = await self._request_reset(client, emails, user_payload["email"])
        emails.clear()

        await client.post(
            f"{API}/auth/reset-password",
            json={"token": token, "new_password": "brand-new-password-7"},
        )

        message = emails.last_to(user_payload["email"])
        assert message is not None
        assert "changed" in message.subject.lower()

    async def test_rejects_a_weak_new_password(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        token = await self._request_reset(client, emails, user_payload["email"])

        response = await client.post(
            f"{API}/auth/reset-password", json={"token": token, "new_password": "weak"}
        )
        assert response.status_code == 422

    async def test_verification_token_cannot_reset_a_password(
        self, client: AsyncClient, emails: CapturingEmailProvider, user_payload: dict[str, str]
    ) -> None:
        """Purposes must not be interchangeable.

        A verification link lives for 24 hours and is handed out at signup; a
        reset link lives 30 minutes. If one could be used as the other, the
        weaker guarantee would silently govern the stronger action.
        """
        await client.post(f"{API}/auth/register", json=user_payload)
        message = emails.last_to(user_payload["email"])
        assert message is not None

        response = await client.post(
            f"{API}/auth/reset-password",
            json={
                "token": extract_token(message.text_body),
                "new_password": "brand-new-password-7",
            },
        )
        assert response.status_code == 401


class TestSecurityNotifications:
    async def test_changing_a_password_notifies_the_owner(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        auth_headers: dict[str, str],
        user_payload: dict[str, str],
    ) -> None:
        emails.clear()
        await client.post(
            f"{API}/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": user_payload["password"],
                "new_password": "brand-new-password-7",
            },
        )

        message = emails.last_to(user_payload["email"])
        assert message is not None
        assert "changed" in message.subject.lower()

    async def test_token_reuse_notifies_the_owner(
        self,
        client: AsyncClient,
        emails: CapturingEmailProvider,
        registered_user: dict,
        user_payload: dict[str, str],
    ) -> None:
        """Without this the reuse defence looks like a bug.

        The user is signed out of every device with no explanation, and the one
        person who might recognise the activity as suspicious never hears of it.
        """
        first = registered_user["tokens"]["refresh_token"]
        await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
        emails.clear()

        replay = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
        assert replay.status_code == 401

        message = emails.last_to(user_payload["email"])
        assert message is not None
        assert "signed out" in message.subject.lower()
