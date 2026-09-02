"""Email content.

Plain functions returning (subject, text, html) rather than a template engine:
there are five messages, and Jinja would add a dependency, a loader, and a
directory of files to render a handful of paragraphs.

Every message is escaped before interpolation. A display name comes from user
input, and an unescaped one turns a security notification into an HTML
injection vector delivered straight to the user's inbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

BRAND = "CareerIQ"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _layout(heading: str, body_html: str) -> str:
    # Table-based, inline-styled layout. Email clients strip <style> blocks and
    # have no meaningful flexbox support, so ordinary CSS does not survive.
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:24px;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;border:1px solid #e2e8f0;">
    <tr><td style="padding:24px 28px 8px;">
      <p style="margin:0;font-size:18px;font-weight:bold;color:#4f46e5;">{BRAND}</p>
    </td></tr>
    <tr><td style="padding:0 28px 24px;">
      <h1 style="margin:12px 0 16px;font-size:20px;">{heading}</h1>
      {body_html}
    </td></tr>
    <tr><td style="padding:0 28px 24px;border-top:1px solid #e2e8f0;">
      <p style="margin:16px 0 0;font-size:12px;color:#64748b;">
        You received this because an account is registered with this address.
      </p>
    </td></tr>
  </table>
</body></html>"""


def _button(url: str, label: str) -> str:
    return (
        f'<p style="margin:24px 0;"><a href="{escape(url)}" '
        'style="background:#4f46e5;color:#ffffff;padding:12px 20px;border-radius:6px;'
        'text-decoration:none;font-weight:bold;display:inline-block;">'
        f"{escape(label)}</a></p>"
        '<p style="margin:16px 0 0;font-size:13px;color:#475569;">'
        f"If the button does not work, paste this into your browser:<br>"
        f'<span style="word-break:break-all;">{escape(url)}</span></p>'
    )


def verify_email(*, name: str | None, url: str, ttl_hours: int) -> RenderedEmail:
    greeting = f"Hi {name}," if name else "Hi,"
    return RenderedEmail(
        subject=f"Confirm your email for {BRAND}",
        text=(
            f"{greeting}\n\n"
            f"Welcome to {BRAND}. Confirm your email address to finish setting up "
            f"your account:\n\n{url}\n\n"
            f"This link expires in {ttl_hours} hours.\n\n"
            "If you did not create this account, you can ignore this message.\n"
        ),
        html=_layout(
            "Confirm your email",
            f"<p style='margin:0;'>{escape(greeting)}</p>"
            f"<p style='margin:12px 0 0;'>Welcome to {BRAND}. Confirm your email address "
            "to finish setting up your account.</p>"
            + _button(url, "Confirm email")
            + f"<p style='margin:16px 0 0;font-size:13px;color:#475569;'>This link expires in "
            f"{ttl_hours} hours. If you did not create this account, you can ignore this message.</p>",
        ),
    )


def password_reset(*, name: str | None, url: str, ttl_minutes: int) -> RenderedEmail:
    greeting = f"Hi {name}," if name else "Hi,"
    return RenderedEmail(
        subject=f"Reset your {BRAND} password",
        text=(
            f"{greeting}\n\n"
            "We received a request to reset your password. Use this link to choose a "
            f"new one:\n\n{url}\n\n"
            f"This link expires in {ttl_minutes} minutes and can only be used once.\n\n"
            "If you did not request this, no action is needed — your password has not "
            "changed.\n"
        ),
        html=_layout(
            "Reset your password",
            f"<p style='margin:0;'>{escape(greeting)}</p>"
            "<p style='margin:12px 0 0;'>We received a request to reset your password.</p>"
            + _button(url, "Choose a new password")
            + f"<p style='margin:16px 0 0;font-size:13px;color:#475569;'>This link expires in "
            f"{ttl_minutes} minutes and can only be used once. If you did not request this, "
            "no action is needed — your password has not changed.</p>",
        ),
    )


def password_changed(*, name: str | None) -> RenderedEmail:
    """Sent after a successful change or reset.

    Not a courtesy. If an attacker changes the password, this is the only signal
    the real owner gets while they can still act on it.
    """
    greeting = f"Hi {name}," if name else "Hi,"
    return RenderedEmail(
        subject=f"Your {BRAND} password was changed",
        text=(
            f"{greeting}\n\n"
            "Your password was changed just now, and every other signed-in session "
            "was ended.\n\n"
            "If this was not you, reset your password immediately — whoever made this "
            "change currently has access to your account.\n"
        ),
        html=_layout(
            "Your password was changed",
            f"<p style='margin:0;'>{escape(greeting)}</p>"
            "<p style='margin:12px 0 0;'>Your password was changed just now, and every "
            "other signed-in session was ended.</p>"
            "<p style='margin:12px 0 0;color:#b91c1c;'><strong>If this was not you</strong>, "
            "reset your password immediately — whoever made this change currently has "
            "access to your account.</p>",
        ),
    )


def sessions_revoked(*, name: str | None) -> RenderedEmail:
    """Sent when refresh-token reuse is detected.

    Without this the user is simply logged out with no explanation, which makes
    the reuse detection built in Step 2 look like a bug rather than a defence.
    """
    greeting = f"Hi {name}," if name else "Hi,"
    return RenderedEmail(
        subject=f"You were signed out of {BRAND}",
        text=(
            f"{greeting}\n\n"
            "We signed you out of all devices because a sign-in token was used twice. "
            "That usually means a token was copied.\n\n"
            "Signing in again is enough to continue. If you did not expect this, change "
            "your password as well.\n"
        ),
        html=_layout(
            "You were signed out",
            f"<p style='margin:0;'>{escape(greeting)}</p>"
            "<p style='margin:12px 0 0;'>We signed you out of all devices because a "
            "sign-in token was used twice. That usually means a token was copied.</p>"
            "<p style='margin:12px 0 0;'>Signing in again is enough to continue. If you "
            "did not expect this, change your password as well.</p>",
        ),
    )
