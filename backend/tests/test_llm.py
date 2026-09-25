from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
import httpx2
import pytest

from docmind.domain import ChatTurn
from docmind.errors import ProviderError
from docmind.llm.anthropic_provider import FALLBACK_BETA, AnthropicLLM
from docmind.llm.base import Completion, LLMEvent, LLMProvider, LLMRequest, SourceBlock, TextDelta
from docmind.llm.fake import FakeLLM
from docmind.llm.openai_compat import OpenAICompatibleLLM
from docmind.rag.prompt import SYSTEM_PROMPT, build_request, render_sources

SOURCES = [
    SourceBlock(1, "Handbook", "Employees receive 25 days of paid vacation per year.", "Time off"),
    SourceBlock(2, "Security", "Laptops must use full-disk encryption.", None),
]


async def collect(provider: LLMProvider, request: LLMRequest) -> tuple[str, Completion]:
    text, completion = [], None
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            text.append(event.text)
        else:
            completion = event
    assert completion is not None
    return "".join(text), completion


def request_for(question: str, sources: list[SourceBlock] | None = None) -> LLMRequest:
    return build_request(question, SOURCES if sources is None else sources, [], max_tokens=512)


class TestPrompt:
    def test_request_shape(self) -> None:
        history = [ChatTurn("user", "hi"), ChatTurn("assistant", "hello")]
        request = build_request("How long is vacation?", SOURCES, history, max_tokens=100)
        assert request.system == SYSTEM_PROMPT
        assert request.messages[:2] == history
        final = request.messages[-1].content
        assert final.endswith("Question: How long is vacation?")
        assert '<source index="1" title="Handbook" location="Time off">' in final

    def test_sources_are_escaped(self) -> None:
        rendered = render_sources([SourceBlock(1, 'A "quoted" <title>', "body")])
        assert 'title="A &quot;quoted&quot; &lt;title&gt;"' in rendered

    def test_no_sources_placeholder(self) -> None:
        request = build_request("q", [], [], max_tokens=10)
        assert "no relevant passages" in request.messages[-1].content


class TestFakeLLM:
    async def test_extractive_answer_with_citation(self) -> None:
        text, completion = await collect(FakeLLM(), request_for("How many vacation days?"))
        assert "25 days of paid vacation" in text
        assert "[1]" in text
        assert "[2]" not in text
        assert completion.stop_reason == "end_turn"

    async def test_russian_question_gets_russian_copy(self) -> None:
        sources = [SourceBlock(1, "Справочник", "Отпуск составляет 25 рабочих дней в год.")]
        text, _ = await collect(FakeLLM(), request_for("Сколько дней отпуск?", sources))
        assert text.startswith("Вот что говорится")

    async def test_no_answer(self) -> None:
        text, _ = await collect(FakeLLM(), request_for("quantum chromodynamics", []))
        assert "could not find" in text


# --- Anthropic (official SDK, HTTP mocked at the transport layer) ----------------------------


def sse_body(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def claude_stream(texts: list[str], stop_reason: str = "end_turn") -> bytes:
    events: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 42, "output_tokens": 1},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        *[
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}
            for t in texts
        ],
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 7},
        },
        {"type": "message_stop"},
    ]
    return sse_body(events)


def claude_client(handler: Any) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


class TestAnthropicLLM:
    async def test_streams_text_and_sends_fallbacks(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["path"] = request.url.path
            seen["beta"] = request.headers.get("anthropic-beta", "")
            seen["body"] = json.loads(request.content)
            return httpx2.Response(
                200,
                content=claude_stream(["Vacation is ", "25 days [1]."]),
                headers={"content-type": "text/event-stream"},
            )

        llm = AnthropicLLM(api_key=None, effort="low", client=claude_client(handler))
        text, completion = await collect(llm, request_for("How long is vacation?"))

        assert text == "Vacation is 25 days [1]."
        assert completion.stop_reason == "end_turn"
        assert completion.model == "claude-opus-5"
        assert (completion.input_tokens, completion.output_tokens) == (42, 7)
        assert seen["path"] == "/v1/messages"
        assert FALLBACK_BETA in seen["beta"]
        body = seen["body"]
        assert body["model"] == "claude-opus-5"
        assert body["fallbacks"] == "default"
        assert body["stream"] is True
        assert body["system"] == SYSTEM_PROMPT
        assert body["output_config"] == {"effort": "low"}
        assert body["messages"][-1]["role"] == "user"
        await llm.aclose()

    async def test_without_fallbacks_uses_stable_endpoint(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["beta"] = request.headers.get("anthropic-beta")
            seen["body"] = json.loads(request.content)
            return httpx2.Response(
                200, content=claude_stream(["ok"]), headers={"content-type": "text/event-stream"}
            )

        llm = AnthropicLLM(api_key=None, use_fallbacks=False, client=claude_client(handler))
        text, _ = await collect(llm, request_for("q"))
        assert text == "ok"
        assert seen["beta"] is None
        assert "fallbacks" not in seen["body"]
        assert "output_config" not in seen["body"]

    async def test_refusal_is_surfaced_politely(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                content=claude_stream([], stop_reason="refusal"),
                headers={"content-type": "text/event-stream"},
            )

        llm = AnthropicLLM(api_key=None, client=claude_client(handler))
        text, completion = await collect(llm, request_for("q"))
        assert completion.stop_reason == "refusal"
        assert "declined" in text

    @pytest.mark.parametrize(
        ("status", "error_type", "retryable"),
        [
            (401, "authentication_error", False),
            (429, "rate_limit_error", True),
            (529, "overloaded_error", True),
            (400, "invalid_request_error", False),
        ],
    )
    async def test_errors_become_provider_errors(
        self, status: int, error_type: str, retryable: bool
    ) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                status, json={"type": "error", "error": {"type": error_type, "message": "nope"}}
            )

        llm = AnthropicLLM(api_key=None, client=claude_client(handler))
        with pytest.raises(ProviderError) as info:
            await collect(llm, request_for("q"))
        assert info.value.retryable is retryable


# --- OpenAI-compatible (Ollama / vLLM / LM Studio ...) ---------------------------------------


def openai_stream(chunks: list[str]) -> bytes:
    lines = []
    for i, piece in enumerate(chunks):
        finish = "stop" if i == len(chunks) - 1 else None
        event = {
            "model": "llama3.1",
            "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": finish}],
        }
        lines.append(f"data: {json.dumps(event)}\n\n")
    usage = {
        "model": "llama3.1",
        "choices": [],
        "usage": {"prompt_tokens": 9, "completion_tokens": 3},
    }
    lines.append(f"data: {json.dumps(usage)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


async def test_openai_compatible_streaming() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=openai_stream(["Hel", "lo"]))

    llm = OpenAICompatibleLLM(
        base_url="http://llm.test/v1", model="llama3.1", transport=httpx.MockTransport(handler)
    )
    text, completion = await collect(llm, request_for("q"))
    assert text == "Hello"
    assert completion.stop_reason == "stop"
    assert completion.output_tokens == 3
    assert seen["body"]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert seen["body"]["stream"] is True
    await llm.aclose()


@pytest.mark.parametrize(("status", "retryable"), [(503, True), (404, False)])
async def test_openai_compatible_http_errors(status: int, retryable: bool) -> None:
    llm = OpenAICompatibleLLM(
        base_url="http://llm.test/v1",
        model="m",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="err")),
    )
    with pytest.raises(ProviderError) as info:
        await collect(llm, request_for("q"))
    assert info.value.retryable is retryable


async def test_openai_compatible_malformed_stream() -> None:
    llm = OpenAICompatibleLLM(
        base_url="http://llm.test/v1",
        model="m",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"data: {oops\n\n")),
    )
    with pytest.raises(ProviderError, match="malformed"):
        await collect(llm, request_for("q"))


def test_providers_satisfy_protocol() -> None:
    providers: list[object] = [
        FakeLLM(),
        AnthropicLLM(api_key="x"),
        OpenAICompatibleLLM(base_url="http://x", model="m"),
    ]
    assert all(isinstance(p, LLMProvider) for p in providers)
    events: list[LLMEvent] = [TextDelta("a"), Completion("end_turn", "m")]
    assert len(events) == 2
