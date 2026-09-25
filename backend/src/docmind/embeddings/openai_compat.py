"""Embeddings via any OpenAI-compatible ``/embeddings`` endpoint (OpenAI, Ollama, vLLM, TEI...)."""

from __future__ import annotations

import httpx
import numpy as np

from docmind.domain import Vector
from docmind.embeddings.base import l2_normalize
from docmind.errors import ProviderError


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        api_key: str | None = None,
        batch_size: int = 64,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout_s, transport=transport
        )
        self._model = model
        self._dim = dim
        self._batch_size = batch_size

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"openai-compatible:{self._model}"

    async def _embed_batch(self, texts: list[str]) -> list[Vector]:
        try:
            response = await self._client.post(
                "/embeddings", json={"model": self._model, "input": texts}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
            raise ProviderError(
                f"Embedding request failed: HTTP {exc.response.status_code}", retryable=retryable
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Embedding request failed: {exc}", retryable=True) from exc
        items = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [l2_normalize(np.asarray(item["embedding"], dtype=np.float32)) for item in items]
        for vector in vectors:
            if vector.shape[0] != self._dim:
                raise ProviderError(
                    f"Embedding dim mismatch: got {vector.shape[0]}, expected {self._dim}. "
                    "Set DOCMIND_EMBEDDING_DIM to match the model."
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[Vector]:
        out: list[Vector] = []
        for i in range(0, len(texts), self._batch_size):
            out.extend(await self._embed_batch(texts[i : i + self._batch_size]))
        return out

    async def embed_query(self, text: str) -> Vector:
        return (await self._embed_batch([text]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()
