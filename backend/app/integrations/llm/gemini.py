"""Google Gemini adapter (ADR-007, ml.md section 6).

The only file that knows Gemini's request shape, field names, status codes and
refusal vocabulary. Everything above it speaks `Prompt` and `LLMResponse`.

Spoken over plain HTTP with `httpx` rather than through `google-generativeai`.
The SDK brings a large transitive dependency surface for what is one POST with a
JSON body, and it makes tests either hit the network or mock an object graph --
whereas `httpx.MockTransport` lets the whole adapter be exercised offline against
real recorded payloads. The same reasoning ADR-007 gives for rejecting LangChain
applies one level down.

**No retries.** A 429 on a free tier means the quota is gone; spending another
call to re-ask makes it worse, and the caller is better placed to decide whether
to wait, queue, or tell the user. This matches the jobs provider's stance and is
a decision rather than an omission.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.llm.base import (
    LLMError,
    LLMQuotaError,
    LLMResponse,
    LLMSafetyError,
    Prompt,
)

#: Reasons Gemini gives for stopping that mean "I declined", not "I finished".
#:
#: Treated as a distinct failure because retrying is pointless and the cause is
#: the content, which is a thing worth telling the user.
_REFUSAL_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


class GeminiProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: int = 60,
        temperature: float = 0.2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # Low by default. These tasks are constrained rewriting and structured
        # extraction, where a more "creative" sampler mostly produces more ways
        # to be wrong -- and for resume text, invention is the failure mode the
        # whole feature is built to avoid.
        self._temperature = temperature
        # A seam for tests, which pass httpx.MockTransport so no socket opens.
        self._transport = transport
        # No AsyncClient held here: the provider is cached per process, and a
        # cached client binds to whichever event loop first touches it and then
        # fails on every later one. Same reasoning as the jobs adapter.

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, prompt: Prompt) -> LLMResponse:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt.render()}]}],
            "generationConfig": {"temperature": self._temperature},
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/models/{self._model}:generateContent",
                    json=body,
                    # The key goes in a header, never the query string: URLs are
                    # logged by proxies and servers as a matter of course.
                    headers={
                        "x-goog-api-key": self._api_key,
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            # Several httpx errors carry an empty message, so the type name is
            # included -- "request failed: " tells an operator nothing.
            detail = str(exc) or "no detail"
            raise LLMError(f"{type(exc).__name__}: {detail}", provider=self.name) from exc

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise LLMQuotaError(
                "Gemini quota exhausted or rate limited.",
                provider=self.name,
                status_code=429,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )

        if response.status_code >= 400:
            raise LLMError(
                f"Gemini returned {response.status_code}: {_error_detail(response)}",
                provider=self.name,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError("Gemini returned a body that is not JSON.", provider=self.name) from exc

        return self._parse(payload)

    def _parse(self, payload: dict[str, Any]) -> LLMResponse:
        # A prompt blocked before generation reports at the top level, with no
        # candidates at all.
        feedback = payload.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise LLMSafetyError(
                f"Gemini declined the prompt: {feedback['blockReason']}.",
                provider=self.name,
            )

        candidates = payload.get("candidates") or []
        if not candidates:
            raise LLMError("Gemini returned no candidates.", provider=self.name)

        first = candidates[0]
        reason = first.get("finishReason")
        if reason in _REFUSAL_REASONS:
            raise LLMSafetyError(f"Gemini declined to answer: {reason}.", provider=self.name)

        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            # MAX_TOKENS lands here when the limit was hit before any text: a
            # truncation, not a refusal, and worth naming because the fix is a
            # different one.
            raise LLMError(
                f"Gemini returned an empty completion (finishReason={reason}).",
                provider=self.name,
            )

        usage = payload.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=payload.get("modelVersion") or self._model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )


def _error_detail(response: httpx.Response) -> str:
    """Gemini's message when it has one, the raw body when it does not."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "no body"
    message = (payload.get("error") or {}).get("message")
    return message or response.text[:200] or "no detail"
