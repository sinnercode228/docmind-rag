from __future__ import annotations

from typing import Any

import httpx
import pytest

from docmind.container import Container
from tests.conftest import ADMIN_TOKEN, API_KEY
from tests.helpers import make_pdf, parse_sse


async def upload(
    client: httpx.AsyncClient,
    container: Container,
    name: str,
    data: bytes,
    content_type: str = "text/markdown",
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/documents", files={"file": (name, data, content_type)}, data=extra
    )
    assert response.status_code == 202, response.text
    await container.jobs.join()
    document_id = response.json()["document"]["id"]
    return (await client.get(f"/v1/documents/{document_id}")).json()  # type: ignore[no-any-return]


async def new_tenant(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        "/v1/admin/tenants", json={"name": name}, headers={"X-Admin-Token": ADMIN_TOKEN}
    )
    assert response.status_code == 201, response.text
    key: str = response.json()["api_key"]
    assert key.startswith("dm_")
    return key


class TestSystem:
    async def test_health_and_ready(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/healthz")).json()["status"] == "ok"
        ready = (await client.get("/readyz")).json()
        assert ready == {
            "status": "ready",
            "workers": True,
            "llm": "fake",
            "embedder": "hashing-384",
            "vector_store": "memory",
        }

    async def test_openapi_schema(self, client: httpx.AsyncClient) -> None:
        schema = (await client.get("/openapi.json")).json()
        assert "/v1/chat/stream" in schema["paths"]
        assert schema["info"]["title"] == "DocMind API"


class TestAuth:
    async def test_missing_key(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/v1/documents", headers={"X-API-Key": ""})
        assert response.status_code == 401

    async def test_invalid_key(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/v1/documents", headers={"X-API-Key": "dm_nope"})
        assert response.status_code == 401

    async def test_bearer_token_accepted(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/v1/me", headers={"X-API-Key": "", "Authorization": f"Bearer {API_KEY}"}
        )
        assert response.status_code == 200
        assert response.json()["tenant"]["name"] == "default"

    async def test_admin_requires_token(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/v1/admin/tenants", json={"name": "x"})
        assert response.status_code == 403
        response = await client.post(
            "/v1/admin/tenants", json={"name": "x"}, headers={"X-Admin-Token": "wrong"}
        )
        assert response.status_code == 403


class TestDocuments:
    async def test_markdown_upload_is_indexed(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        document = await upload(client, container, "handbook.md", handbook_md)
        assert document["status"] == "ready"
        assert document["chunk_count"] > 5
        assert document["title"] == "Lumenfold Labs Employee Handbook"
        assert document["mime_type"] == "text/markdown"

        me = (await client.get("/v1/me")).json()
        assert me["documents"] == 1
        assert me["chunks"] == document["chunk_count"]

        listed = (await client.get("/v1/documents")).json()
        assert [d["id"] for d in listed] == [document["id"]]

    async def test_pdf_upload_keeps_pages(
        self, client: httpx.AsyncClient, container: Container
    ) -> None:
        pdf = make_pdf(["Expenses above 250 EUR need approval.", "Hotels cost up to 170 EUR."])
        document = await upload(client, container, "expenses.pdf", pdf, "application/pdf")
        assert document["status"] == "ready"
        hits = (await client.post("/v1/search", json={"query": "hotel price per night"})).json()
        assert hits["results"][0]["page"] == 2

    async def test_custom_title_is_kept(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        document = await upload(client, container, "h.md", handbook_md, title="HR handbook")
        assert document["title"] == "HR handbook"

    async def test_text_and_url_ingestion(
        self, client: httpx.AsyncClient, container: Container
    ) -> None:
        response = await client.post(
            "/v1/documents/text",
            json={"title": "FAQ", "text": "## Parking\nParking is free for cyclists."},
        )
        assert response.status_code == 202
        response = await client.post(
            "/v1/documents/url", json={"url": "https://docs.example.com/security"}
        )
        assert response.status_code == 202
        job_id = response.json()["job"]["id"]
        await container.jobs.join()

        job = (await client.get(f"/v1/jobs/{job_id}")).json()
        assert job["status"] == "succeeded"
        assert job["attempts"] == 1
        docs = {d["title"]: d for d in (await client.get("/v1/documents")).json()}
        assert set(docs) == {"FAQ", "Security Policy"}
        assert docs["Security Policy"]["mime_type"] == "text/html"
        assert docs["Security Policy"]["size_bytes"] > 0

    async def test_url_blocked_by_ssrf_guard_fails_job(
        self, client: httpx.AsyncClient, container: Container
    ) -> None:
        response = await client.post(
            "/v1/documents/url", json={"url": "http://169.254.169.254/latest"}
        )
        await container.jobs.join()
        document = (await client.get(f"/v1/documents/{response.json()['document']['id']}")).json()
        assert document["status"] == "failed"
        assert "private" in document["error"]

    async def test_unsupported_and_oversized(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/documents", files={"file": ("x.png", b"\x89PNG....", "image/png")}
        )
        assert response.status_code == 415
        assert response.json()["error"] == "unsupported_document"

        big = b"a" * (1024 * 1024 + 1)
        response = await client.post(
            "/v1/documents", files={"file": ("big.txt", big, "text/plain")}
        )
        assert response.status_code == 413

        response = await client.post("/v1/documents", files={"file": ("e.txt", b"", "text/plain")})
        assert response.status_code == 400

    async def test_failed_extraction_marks_document_failed(
        self, client: httpx.AsyncClient, container: Container
    ) -> None:
        document = await upload(
            client, container, "broken.pdf", b"%PDF-1.4 broken", "application/pdf"
        )
        assert document["status"] == "failed"
        assert "PDF" in document["error"]

    async def test_delete_removes_vectors(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        document = await upload(client, container, "handbook.md", handbook_md)
        tenant_id = (await client.get("/v1/me")).json()["tenant"]["id"]
        assert await container.store.count(tenant_id) == document["chunk_count"]

        assert (await client.delete(f"/v1/documents/{document['id']}")).status_code == 204
        assert await container.store.count(tenant_id) == 0
        assert (await client.get(f"/v1/documents/{document['id']}")).status_code == 404

    async def test_reindex(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        document = await upload(client, container, "handbook.md", handbook_md)
        response = await client.post(f"/v1/documents/{document['id']}/reindex")
        assert response.status_code == 202
        await container.jobs.join()
        again = (await client.get(f"/v1/documents/{document['id']}")).json()
        assert again["status"] == "ready"
        assert again["chunk_count"] == document["chunk_count"]
        tenant_id = (await client.get("/v1/me")).json()["tenant"]["id"]
        assert await container.store.count(tenant_id) == document["chunk_count"]


class TestChat:
    async def test_json_chat_with_citations(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        await upload(client, container, "handbook.md", handbook_md)
        response = await client.post(
            "/v1/chat", json={"question": "How many vacation days can I carry over?"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "5 unused vacation days" in body["answer"]
        assert body["cited"], "answer should cite at least one source"
        cited = body["citations"][body["cited"][0] - 1]
        assert cited["document_title"] == "Lumenfold Labs Employee Handbook"
        assert cited["heading"] == "Time off › Paid vacation"
        start, end = cited["highlight"]
        assert "carried over" in cited["snippet"][start:end]
        assert body["model"] == "fake-extractive"

    async def test_streaming_chat_and_history(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        await upload(client, container, "handbook.md", handbook_md)
        response = await client.post(
            "/v1/chat/stream", json={"question": "What is the learning budget?"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.text)
        names = [name for name, _ in events]
        assert names[0] == "meta" and names[1] == "sources" and names[-1] == "done"
        assert names.count("delta") > 3
        streamed = "".join(data["text"] for name, data in events if name == "delta")
        done = events[-1][1]
        assert streamed == done["answer"]
        assert "1,000 EUR" in streamed

        conversation_id = events[0][1]["conversation_id"]
        follow_up = await client.post(
            "/v1/chat",
            json={"question": "And the home office budget?", "conversation_id": conversation_id},
        )
        assert follow_up.json()["conversation_id"] == conversation_id
        assert "600 EUR" in follow_up.json()["answer"]

        conversations = (await client.get("/v1/conversations")).json()
        assert conversations[0]["id"] == conversation_id
        assert conversations[0]["title"] == "What is the learning budget?"
        messages = (await client.get(f"/v1/conversations/{conversation_id}/messages")).json()
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[1]["citations"][0]["cited"] in {True, False}

        assert (await client.delete(f"/v1/conversations/{conversation_id}")).status_code == 204
        assert (await client.get("/v1/conversations")).json() == []

    async def test_empty_knowledge_base(self, client: httpx.AsyncClient) -> None:
        body = (await client.post("/v1/chat", json={"question": "What is our VPN?"})).json()
        assert body["citations"] == []
        assert "could not find" in body["answer"]

    async def test_unknown_conversation(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/chat/stream", json={"question": "hi", "conversation_id": "cv_missing"}
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x", "top_k": 99}])
    async def test_validation(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
        assert (await client.post("/v1/chat", json=payload)).status_code == 422


class TestTenancy:
    async def test_tenants_are_isolated(
        self, client: httpx.AsyncClient, container: Container, handbook_md: bytes
    ) -> None:
        document = await upload(client, container, "handbook.md", handbook_md)
        other_key = await new_tenant(client, "Other team")
        other = {"X-API-Key": other_key}

        assert (await client.get("/v1/documents", headers=other)).json() == []
        assert (
            await client.get(f"/v1/documents/{document['id']}", headers=other)
        ).status_code == 404
        assert (
            await client.delete(f"/v1/documents/{document['id']}", headers=other)
        ).status_code == 404
        results = (
            await client.post("/v1/search", json={"query": "vacation days"}, headers=other)
        ).json()
        assert results["results"] == []

        mine = (await client.post("/v1/search", json={"query": "vacation days"})).json()
        assert mine["results"]

    async def test_conversations_are_isolated(self, client: httpx.AsyncClient) -> None:
        conversation_id = (await client.post("/v1/chat", json={"question": "hi"})).json()[
            "conversation_id"
        ]
        other = {"X-API-Key": await new_tenant(client, "Other")}
        response = await client.get(f"/v1/conversations/{conversation_id}/messages", headers=other)
        assert response.status_code == 404
        response = await client.post(
            "/v1/chat", json={"question": "hi", "conversation_id": conversation_id}, headers=other
        )
        assert response.status_code == 404
