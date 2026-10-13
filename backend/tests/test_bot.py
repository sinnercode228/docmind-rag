from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from docmind.bot.service import BotService, markdown_to_telegram_html


class ScriptedBackend:
    def __init__(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        self.events = events

    async def stream_chat(
        self, question: str, conversation_id: str | None = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        for event in self.events:
            yield event


def citation(index: int, title: str) -> dict[str, Any]:
    return {"index": index, "document_title": title, "heading": None, "page": None}


def test_only_markers_in_source_range_are_bold() -> None:
    html = markdown_to_telegram_html("Zero [0], one [1], two [2], three [3].", available=2)
    assert html == "Zero [0], one <b>[1]</b>, two <b>[2]</b>, three [3]."


def test_markdown_subset_is_escaped_then_formatted() -> None:
    html = markdown_to_telegram_html("- **25** days <b>, see `HR portal` [1]", available=1)
    assert html == "• <b>25</b> days &lt;b&gt;, see <code>HR portal</code> <b>[1]</b>"


async def test_answer_does_not_bold_zero_marker() -> None:
    backend = ScriptedBackend(
        [
            ("meta", {"conversation_id": "cv_1"}),
            ("sources", {"citations": [citation(1, "Employee Handbook")]}),
            ("delta", {"text": "25 working days [1]. See also [0]."}),
            ("done", {"cited": [1]}),
        ]
    )
    service = BotService(backend)
    reply = await service.answer(42, "How many vacation days?")
    assert reply.startswith("25 working days <b>[1]</b>. See also [0].")
    assert "[1] Employee Handbook" in reply
    assert service.conversations[42] == "cv_1"
