"""Build concrete providers from settings. The only place that knows every implementation."""

from __future__ import annotations

from docmind.config import Settings
from docmind.embeddings.base import Embedder
from docmind.embeddings.hashing import HashingEmbedder
from docmind.embeddings.openai_compat import OpenAICompatibleEmbedder
from docmind.llm.anthropic_provider import AnthropicLLM
from docmind.llm.base import LLMProvider
from docmind.llm.fake import FakeLLM
from docmind.llm.openai_compat import OpenAICompatibleLLM
from docmind.vectorstore.base import VectorStore
from docmind.vectorstore.memory import MemoryVectorStore


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else None


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedder == "openai":
        return OpenAICompatibleEmbedder(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
            api_key=_secret(settings.embedding_api_key),
            batch_size=settings.embedding_batch_size,
        )
    return HashingEmbedder(settings.embedding_dim)


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(
            api_key=_secret(settings.anthropic_api_key),
            model=settings.anthropic_model,
            effort=settings.anthropic_effort,
            use_fallbacks=settings.anthropic_fallbacks,
        )
    if settings.llm_provider == "openai":
        return OpenAICompatibleLLM(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=_secret(settings.openai_api_key),
        )
    return FakeLLM(delay_s=0.0 if settings.env == "test" else 0.015)


async def build_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_store == "pgvector":
        from docmind.vectorstore.pgvector import PgVectorStore

        store = PgVectorStore.from_url(settings.database_url, settings.embedding_dim)
        await store.init()
        return store
    return MemoryVectorStore(settings.embedding_dim, settings.memory_store_path)
