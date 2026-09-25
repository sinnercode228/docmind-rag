"""Deterministic, offline "LLM" that answers extractively from the retrieved sources.

Used by the test-suite and by demo deployments without an API key. It never invents text:
every statement is a sentence quoted from a source, tagged with that source's ``[n]`` marker.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from docmind.llm.base import Completion, LLMEvent, LLMRequest, TextDelta
from docmind.text import best_sentence, is_cyrillic

_TOKENS = re.compile(r"\S+\s*")

COPY = {
    "en": {
        "intro": "Here is what the knowledge base says:",
        "none": "I could not find an answer to that in the uploaded documents.",
        "note": "_Extractive answer by the offline Fake provider. "
        "Configure Claude or an OpenAI-compatible model for generated answers._",
    },
    "ru": {
        "intro": "Вот что говорится в базе знаний:",
        "none": "Не нашёл ответа на этот вопрос в загруженных документах.",
        "note": "_Экстрактивный ответ офлайн-провайдера Fake. "
        "Подключите Claude или OpenAI-совместимую модель для генеративных ответов._",
    },
}


class FakeLLM:
    def __init__(self, *, delay_s: float = 0.0, max_points: int = 3) -> None:
        self._delay_s = delay_s
        self._max_points = max_points

    @property
    def name(self) -> str:
        return "fake"

    def compose(self, request: LLMRequest) -> str:
        copy = COPY["ru" if is_cyrillic(request.question) else "en"]
        points: list[str] = []
        for source in request.sources:
            span = best_sentence(source.text, request.question)
            if span is None:
                continue
            sentence = source.text[span[0] : span[1]].strip()
            points.append(f"- {sentence} [{source.index}]")
            if len(points) >= self._max_points:
                break
        if not points:
            return copy["none"]
        return "\n".join([copy["intro"], "", *points, "", copy["note"]])

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        answer = self.compose(request)
        count = 0
        for token in _TOKENS.findall(answer):
            count += 1
            if self._delay_s:
                await asyncio.sleep(self._delay_s)
            yield TextDelta(token)
        yield Completion(stop_reason="end_turn", model="fake-extractive", output_tokens=count)

    async def aclose(self) -> None:
        return None
