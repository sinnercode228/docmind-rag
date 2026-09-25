from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from docmind.domain import Chunk, ScoredChunk
from docmind.embeddings.hashing import HashingEmbedder
from docmind.embeddings.openai_compat import OpenAICompatibleEmbedder
from docmind.errors import ProviderError
from docmind.retrieval.mmr import mmr_select
from docmind.retrieval.retriever import RetrievalParams, Retriever
from docmind.text import best_sentence, content_terms, stem
from docmind.vectorstore.memory import MemoryVectorStore

CORPUS = {
    "vac": "Employees receive 25 working days of paid vacation per year.",
    "carry": "Up to 5 unused vacation days can be carried over until March 31.",
    "laptop": "Laptops are replaced every three years from the standard catalogue.",
    "pwd": "Passwords must be at least 14 characters and stored in the password manager.",
    "ru": "Сотрудники получают 25 рабочих дней оплачиваемого отпуска в год.",
}


def make_chunks(doc_id: str = "doc_1") -> list[Chunk]:
    return [
        Chunk(id=f"{doc_id}:{key}", document_id=doc_id, ordinal=i, text=text, end=len(text))
        for i, (key, text) in enumerate(CORPUS.items())
    ]


class TestHashingEmbedder:
    async def test_deterministic_and_normalised(self) -> None:
        a, b = HashingEmbedder(128), HashingEmbedder(128)
        va = await a.embed_query("vacation policy")
        vb = await b.embed_query("vacation policy")
        assert va.dtype == np.float32 and va.shape == (128,)
        assert np.allclose(va, vb)
        assert np.isclose(np.linalg.norm(va), 1.0, atol=1e-5)

    async def test_lexical_similarity(self) -> None:
        emb = HashingEmbedder(384)
        query = await emb.embed_query("how many vacation days do I get")
        docs = await emb.embed_documents([CORPUS["vac"], CORPUS["laptop"]])
        assert float(query @ docs[0]) > float(query @ docs[1])

    async def test_russian_morphology_via_char_ngrams(self) -> None:
        emb = HashingEmbedder(384)
        query = await emb.embed_query("сколько дней отпуска")
        docs = await emb.embed_documents([CORPUS["ru"], CORPUS["pwd"]])
        assert float(query @ docs[0]) > float(query @ docs[1])

    def test_rejects_tiny_dimension(self) -> None:
        with pytest.raises(ValueError, match="dim"):
            HashingEmbedder(8)


async def test_openai_compatible_embedder_batches_and_sorts() -> None:
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["input"])
        assert request.headers["authorization"] == "Bearer sk-test"
        data = [
            {"index": i, "embedding": [float(i + 1), 0.0, 0.0, 0.0]}
            for i in range(len(body["input"]))
        ][::-1]  # out of order on purpose
        return httpx.Response(200, json={"data": data})

    emb = OpenAICompatibleEmbedder(
        base_url="https://emb.test/v1",
        model="m",
        dim=4,
        api_key="sk-test",
        batch_size=2,
        transport=httpx.MockTransport(handler),
    )
    vectors = await emb.embed_documents(["a", "b", "c"])
    assert calls == [["a", "b"], ["c"]]
    assert len(vectors) == 3
    assert np.allclose(vectors[0], [1, 0, 0, 0])
    await emb.aclose()


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (500, True), (401, False)])
async def test_openai_compatible_embedder_errors(status: int, retryable: bool) -> None:
    emb = OpenAICompatibleEmbedder(
        base_url="https://emb.test/v1",
        model="m",
        dim=4,
        transport=httpx.MockTransport(lambda _: httpx.Response(status)),
    )
    with pytest.raises(ProviderError) as info:
        await emb.embed_query("x")
    assert info.value.retryable is retryable


async def test_openai_compatible_embedder_dim_mismatch() -> None:
    emb = OpenAICompatibleEmbedder(
        base_url="https://emb.test/v1",
        model="m",
        dim=8,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})
        ),
    )
    with pytest.raises(ProviderError, match="dim mismatch"):
        await emb.embed_query("x")


class TestMemoryVectorStore:
    async def test_search_isolation_and_delete(self) -> None:
        emb = HashingEmbedder(256)
        store = MemoryVectorStore(256)
        chunks = make_chunks()
        await store.upsert("tenant_a", chunks, await emb.embed_documents([c.text for c in chunks]))

        hits = await store.search("tenant_a", await emb.embed_query("vacation days"), 2)
        assert hits[0].chunk.id in {"doc_1:vac", "doc_1:carry"}
        assert hits[0].score >= hits[1].score
        assert hits[0].embedding is not None

        assert await store.search("tenant_b", await emb.embed_query("vacation"), 3) == []
        assert await store.count("tenant_a") == len(CORPUS)
        assert await store.delete_document("tenant_a", "doc_1") == len(CORPUS)
        assert await store.count("tenant_a") == 0

    async def test_upsert_replaces_same_ids(self) -> None:
        store = MemoryVectorStore(16)
        chunk = Chunk(id="c1", document_id="d", ordinal=0, text="old")
        vec = np.ones(16, dtype=np.float32) / 4
        await store.upsert("t", [chunk], [vec])
        await store.upsert("t", [Chunk(id="c1", document_id="d", ordinal=0, text="new")], [vec])
        assert await store.count("t") == 1
        hits = await store.search("t", vec, 5)
        assert hits[0].chunk.text == "new"

    async def test_document_filter(self) -> None:
        emb = HashingEmbedder(64)
        store = MemoryVectorStore(64)
        for doc in ("d1", "d2"):
            chunks = make_chunks(doc)
            await store.upsert("t", chunks, await emb.embed_documents([c.text for c in chunks]))
        hits = await store.search("t", await emb.embed_query("laptops"), 10, document_ids=["d2"])
        assert hits and all(h.chunk.document_id == "d2" for h in hits)

    async def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        emb = HashingEmbedder(64)
        store = MemoryVectorStore(64, tmp_path)
        chunks = make_chunks()
        await store.upsert(
            "tn/../evil", chunks, await emb.embed_documents([c.text for c in chunks])
        )
        assert all(p.parent == tmp_path for p in tmp_path.iterdir())

        reloaded = MemoryVectorStore(64, tmp_path)
        assert await reloaded.count("tn/../evil") == len(CORPUS)
        assert MemoryVectorStore(128, tmp_path)._collections == {}  # dim mismatch ignored

    async def test_validation(self) -> None:
        store = MemoryVectorStore(8)
        with pytest.raises(ValueError, match="same length"):
            await store.upsert("t", make_chunks(), [])
        with pytest.raises(ValueError, match="dim"):
            await store.upsert("t", make_chunks()[:1], [np.ones(4, dtype=np.float32)])


def _scored(key: str, score: float, vec: list[float]) -> ScoredChunk:
    v = np.asarray(vec, dtype=np.float32)
    return ScoredChunk(
        Chunk(id=key, document_id="d", ordinal=0, text=key), score, v / np.linalg.norm(v)
    )


class TestMMR:
    def test_prefers_diverse_results(self) -> None:
        candidates = [
            _scored("a", 0.95, [1, 0, 0]),
            _scored("a-dup", 0.94, [1, 0.01, 0]),
            _scored("b", 0.80, [0, 1, 0]),
        ]
        assert [c.chunk.id for c in mmr_select(candidates, 2, 0.5)] == ["a", "b"]
        assert [c.chunk.id for c in mmr_select(candidates, 2, 1.0)] == ["a", "a-dup"]

    def test_edge_cases(self) -> None:
        assert mmr_select([], 3) == []
        no_vec = [ScoredChunk(Chunk(id="x", document_id="d", ordinal=0, text="x"), 0.3)]
        assert mmr_select(no_vec, 3) == no_vec
        with pytest.raises(ValueError, match="lambda"):
            mmr_select(no_vec, 1, 1.5)


async def test_retriever_dedupes_and_thresholds() -> None:
    emb = HashingEmbedder(256)
    store = MemoryVectorStore(256)
    chunks = [*make_chunks("d1"), *make_chunks("d2")]  # identical texts in two documents
    await store.upsert("t", chunks, await emb.embed_documents([c.text for c in chunks]))
    retriever = Retriever(emb, store, RetrievalParams(top_k=3, fetch_k=10, min_score=0.05))
    hits = await retriever.retrieve("t", "vacation days carried over")
    texts = [h.chunk.text for h in hits]
    assert len(texts) == len(set(texts))
    assert any("carried over" in t for t in texts)


def test_text_helpers() -> None:
    assert stem("отпуска") == stem("отпуск") == "отпуск"
    assert stem("laptops") == "laptop"
    assert "the" not in content_terms("the laptop")
    text = "Intro sentence. Laptops are replaced every three years. Outro."
    span = best_sentence(text, "when are laptops replaced?")
    assert span is not None
    assert text[span[0] : span[1]] == "Laptops are replaced every three years."
    assert best_sentence(text, "the a") is None
