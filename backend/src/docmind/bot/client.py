"""Async HTTP client for the DocMind API (used by the Telegram bot and the CLI)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Parse a ``text/event-stream`` body into ``(event, json_payload)`` pairs."""
    event = "message"
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    if data:
        yield event, json.loads("\n".join(data))


class DocMindAPIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class DocMindClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout_s,
            transport=transport,
        )

    async def stream_chat(
        self, question: str, conversation_id: str | None = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        payload = {"question": question, "conversation_id": conversation_id}
        async with self._client.stream("POST", "/v1/chat/stream", json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                try:
                    message = json.loads(body).get("message") or json.loads(body).get("detail")
                except ValueError:
                    message = body[:200]
                raise DocMindAPIError(response.status_code, str(message))
            async for item in iter_sse(response.aiter_lines()):
                yield item

    async def aclose(self) -> None:
        await self._client.aclose()
