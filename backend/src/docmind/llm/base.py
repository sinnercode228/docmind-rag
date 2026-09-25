"""Provider-agnostic LLM interface: a streaming generator of text deltas + a final completion."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from docmind.domain import ChatTurn


@dataclass(slots=True, frozen=True)
class SourceBlock:
    index: int
    title: str
    text: str
    location: str | None = None


@dataclass(slots=True, frozen=True)
class LLMRequest:
    system: str
    #: Full message list sent to the model (history + final user turn with sources).
    messages: list[ChatTurn]
    #: Structured view of the same request, used by the deterministic Fake provider.
    question: str = ""
    sources: list[SourceBlock] = field(default_factory=list)
    max_tokens: int = 4096


@dataclass(slots=True, frozen=True)
class TextDelta:
    text: str


@dataclass(slots=True, frozen=True)
class Completion:
    stop_reason: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


LLMEvent = TextDelta | Completion


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Yield ``TextDelta`` events, then exactly one ``Completion``."""
        ...

    async def aclose(self) -> None: ...
