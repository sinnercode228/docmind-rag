"""Transport-agnostic bot logic: conversation state, progressive replies, Telegram HTML."""

from __future__ import annotations

import html
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from docmind.bot.client import DocMindAPIError

TELEGRAM_LIMIT = 4096
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")
_ITALIC = re.compile(r"(?<![\w*])_(.+?)_(?![\w*])")
_CITE = re.compile(r"\[(\d{1,2})\]")


class ChatBackend(Protocol):
    def stream_chat(
        self, question: str, conversation_id: str | None = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]: ...


def markdown_to_telegram_html(text: str) -> str:
    """Tiny Markdown subset -> Telegram HTML (escape first, then re-apply safe tags)."""
    out = html.escape(text, quote=False)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    out = re.sub(r"^\s*[-*]\s+", "• ", out, flags=re.MULTILINE)
    return _CITE.sub(r"<b>[\1]</b>", out)


def format_sources(citations: list[dict[str, Any]], cited: list[int]) -> str:
    wanted = [c for c in citations if c["index"] in cited] or citations[:3]
    if not wanted:
        return ""
    lines = ["", "<b>Sources / Источники:</b>"]
    for c in wanted:
        where = f", p. {c['page']}" if c.get("page") else ""
        heading = f" — {html.escape(c['heading'])}" if c.get("heading") else ""
        lines.append(f"[{c['index']}] {html.escape(c['document_title'])}{where}{heading}")
    return "\n".join(lines)


def truncate(text: str, limit: int = TELEGRAM_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class BotService:
    backend: ChatBackend
    edit_interval_s: float = 1.2
    clock: Callable[[], float] = time.monotonic
    conversations: dict[int, str] = field(default_factory=dict)

    def reset(self, chat_id: int) -> None:
        self.conversations.pop(chat_id, None)

    async def answer(
        self,
        chat_id: int,
        question: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Stream an answer; call ``on_progress`` with partial plain text (throttled).

        Returns the final Telegram-HTML message (answer + sources), within Telegram's limit.
        """
        parts: list[str] = []
        citations: list[dict[str, Any]] = []
        cited: list[int] = []
        last_edit = self.clock()
        try:
            async for event, data in self.backend.stream_chat(
                question, self.conversations.get(chat_id)
            ):
                if event == "meta":
                    self.conversations[chat_id] = data["conversation_id"]
                elif event == "sources":
                    citations = data["citations"]
                elif event == "delta":
                    parts.append(data["text"])
                    now = self.clock()
                    if on_progress and now - last_edit >= self.edit_interval_s:
                        last_edit = now
                        await on_progress(truncate("".join(parts) + " ▍"))
                elif event == "done":
                    cited = data.get("cited", [])
                elif event == "error":
                    return f"Error: {html.escape(data.get('message', 'unknown error'))}"
        except DocMindAPIError as exc:
            if exc.status == 404:  # conversation was deleted server-side: start fresh
                self.reset(chat_id)
            return f"Error: {html.escape(exc.message)}"
        body = markdown_to_telegram_html("".join(parts).strip())
        sources = format_sources(citations, cited)
        return truncate(body + ("\n" + sources if sources else ""))
