"""Streaming chat via any OpenAI-compatible ``/chat/completions`` endpoint.

Works with self-hosted runtimes (Ollama, vLLM, LM Studio, llama.cpp server) and hosted
gateways that speak the same wire format.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from docmind.errors import ProviderError
from docmind.llm.base import Completion, LLMEvent, LLMRequest, TextDelta


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )
        self._model = model

    @property
    def name(self) -> str:
        return f"openai-compatible:{self._model}"

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        return {
            "model": self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        finish_reason = "stop"
        usage: dict[str, Any] = {}
        model = self._model
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=self._payload(request)
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        f"LLM endpoint returned HTTP {response.status_code}",
                        retryable=response.status_code == 429 or response.status_code >= 500,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    model = event.get("model") or model
                    usage = event.get("usage") or usage
                    for choice in event.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield TextDelta(delta)
                        finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cannot reach LLM endpoint: {exc}", retryable=True) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("LLM endpoint sent a malformed stream event") from exc
        yield Completion(
            stop_reason=finish_reason,
            model=model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
