"""URL validation shared by the schemas that accept one.

Its own module rather than an import between two sibling schema modules: a
profile importing a helper out of a job schema reads like an accident, this
reads like a decision. Profile links and a job's application link have the same
rules and must not drift apart, because both end up in an `href`.
"""

from __future__ import annotations

from typing import Any

from pydantic import AnyHttpUrl, ValidationError

# The profile default, matching those columns. Callers with a wider column pass
# their own; see MAX_JOB_URL in schemas/job.py.
MAX_URL = 500


def normalize_url(value: Any, *, max_length: int = MAX_URL, required: bool = False) -> Any:
    """Validate a URL and return it as a plain string.

    Deliberately not typed as `HttpUrl` on the field. Pydantic normalises that
    type on serialisation — lowercasing the host, appending a trailing slash —
    so the value echoed back would differ from what the user typed, and the
    input would appear to change itself on save.

    A missing scheme is added rather than rejected: people write
    "linkedin.com/in/priya", and 422-ing that is pedantry.

    **This is also the scheme guard, and that is not obvious.** Only http and
    https skip the prefix, so every other scheme gets "https://" glued on front
    and then fails AnyHttpUrl on the resulting invalid port — "javascript:...",
    "data:...", and "vbscript:..." are all rejected here, verified. http/https
    is therefore the accepted set *by construction*. Do not "simplify" the
    prefix branch away: it would quietly put javascript: URLs back into hrefs.
    """
    if value is None or not isinstance(value, str):
        return value

    candidate = value.strip()
    if not candidate:
        # A required field must say what is wrong. Returning None there would
        # reach Pydantic as a missing str and surface as "Input should be a
        # valid string", which tells the user nothing about the actual problem.
        if required:
            raise ValueError("Enter a valid URL.")
        return None

    # Case-insensitive: "HTTPS://acme.com" otherwise gets a second scheme glued
    # on front, and "https://HTTPS://acme.com" is accepted by AnyHttpUrl as a
    # host of "https" — a link that validates and then goes nowhere.
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    try:
        AnyHttpUrl(candidate)
    except ValidationError as exc:
        raise ValueError("Enter a valid URL.") from exc

    if len(candidate) > max_length:
        raise ValueError(f"URL must be at most {max_length} characters.")
    return candidate
