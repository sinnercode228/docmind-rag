"""Claude via the official Anthropic Python SDK (streaming Messages API)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic

from docmind.errors import ProviderError
from docmind.llm.base import Completion, LLMEvent, LLMRequest, TextDelta

#: Server-side refusal fallback (beta). "default" lets the API pick the fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

REFUSAL_NOTICE = "\n\n_The model declined to answer this request. Try rephrasing the question._"


class AnthropicLLM:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "claude-opus-5",
        effort: str | None = None,
        use_fallbacks: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        # With api_key=None the SDK resolves credentials from the environment
        # (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile).
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
        self._model = model
        self._effort = effort
        self._use_fallbacks = use_fallbacks

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    def _params(self, request: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if self._effort:
            params["output_config"] = {"effort": self._effort}
        return params

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        params = self._params(request)
        try:
            if self._use_fallbacks:
                manager: Any = self._client.beta.messages.stream(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                manager = self._client.messages.stream(**params)
            async with manager as stream:
                async for text in stream.text_stream:
                    yield TextDelta(text)
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic authentication failed: check the API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("Anthropic API key lacks permission for this model") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Unknown Anthropic model {self._model!r}") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"Anthropic rejected the request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"Anthropic API error (HTTP {exc.status_code})", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Cannot reach the Anthropic API", retryable=True) from exc

        stop_reason = final.stop_reason or "end_turn"
        if stop_reason == "refusal":
            yield TextDelta(REFUSAL_NOTICE)
        yield Completion(
            stop_reason=stop_reason,
            model=final.model,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )

    async def aclose(self) -> None:
        await self._client.close()
