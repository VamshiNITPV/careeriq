"""An LLM that answers from a script (ADR-007).

Every test that exercises a prompt path uses this, so the suite runs offline, in
constant time, and gives the same answer twice. A test suite that calls a real
model is measuring the model, not the code, and it fails on a train.

It also records what it was asked. That is what lets a test assert the property
that actually matters about prompt construction -- that the resume went into the
context block and not into the instruction -- rather than only checking the
result came back.
"""

from __future__ import annotations

from collections import deque

from app.integrations.llm.base import LLMError, LLMResponse, Prompt


class FakeLLMProvider:
    """Returns queued replies in order; records every prompt it was given."""

    def __init__(
        self,
        replies: list[str] | None = None,
        *,
        model: str = "fake-1",
        error: Exception | None = None,
    ) -> None:
        self._replies: deque[str] = deque(replies or [])
        self._model = model
        #: Raised instead of answering, for exercising failure paths.
        self._error = error
        #: Every prompt received, in order, for assertions.
        self.calls: list[Prompt] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, prompt: Prompt) -> LLMResponse:
        self.calls.append(prompt)

        if self._error is not None:
            raise self._error

        if not self._replies:
            # Loud rather than returning "". A test that ran out of scripted
            # answers has diverged from what its author expected, and an empty
            # string would be silently parsed as "the model said nothing useful".
            raise LLMError(
                f"FakeLLMProvider ran out of replies on call {len(self.calls)}",
                provider=self.name,
            )

        return LLMResponse(text=self._replies.popleft(), model=self._model)

    @property
    def last_rendered(self) -> str:
        """The most recent prompt as the provider would have sent it."""
        if not self.calls:
            raise AssertionError("no prompts were sent")
        return self.calls[-1].render()
