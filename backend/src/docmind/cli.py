"""``docmind`` command-line interface: tenants, local ingestion, Q&A and demo-KB export."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from docmind.config import Settings, get_settings
from docmind.container import build_container
from docmind.db import repositories as repo
from docmind.ingestion.chunking import chunk_document
from docmind.ingestion.loaders import detect_mime_type, extract
from docmind.rag.service import DeltaEvent, DoneEvent, SourcesEvent


async def cmd_create_tenant(settings: Settings, name: str) -> None:
    container = await build_container(settings)
    await container.start()
    try:
        async with container.sessions() as session:
            tenant, key = await repo.create_tenant(session, name, label="cli")
            await session.commit()
        print(
            f"tenant_id: {tenant.id}\napi_key:   {key}\n(store the key now; it is not shown again)"
        )
    finally:
        await container.stop()


async def cmd_ingest(settings: Settings, api_key: str, paths: list[Path]) -> None:
    container = await build_container(settings)
    await container.start()
    try:
        async with container.sessions() as session:
            tenant = await repo.ensure_bootstrap_tenant(session, api_key)
            jobs = []
            for path in paths:
                files = (
                    sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
                )
                for file in files:
                    data = file.read_bytes()
                    mime = detect_mime_type(file.name, None, data)
                    _, job = await repo.add_document(
                        session,
                        tenant_id=tenant.id,
                        title=file.name,
                        source_type="upload",
                        source=file.name,
                        mime_type=mime,
                        data=data,
                    )
                    jobs.append(job.id)
            await session.commit()
        for job_id in jobs:
            await container.jobs.enqueue(job_id)
        await container.jobs.join()
        async with container.sessions() as session:
            for document in await repo.list_documents(session, tenant.id):
                note = f" ({document.error})" if document.error else ""
                print(
                    f"{document.status:10} {document.chunk_count:4} chunks  {document.title}{note}"
                )
    finally:
        await container.stop()


async def cmd_ask(settings: Settings, api_key: str, question: str) -> None:
    container = await build_container(settings)
    await container.start()
    try:
        async with container.sessions() as session:
            tenant = await repo.tenant_for_key(session, api_key)
        if tenant is None:
            raise SystemExit("Unknown API key")
        async for event in container.rag.stream_answer(tenant.id, question):
            if isinstance(event, DeltaEvent):
                sys.stdout.write(event.text)
                sys.stdout.flush()
            elif isinstance(event, SourcesEvent):
                sources = event.citations
            elif isinstance(event, DoneEvent):
                print("\n")
                for c in sources:
                    mark = "*" if c.index in event.cited else " "
                    print(f"{mark}[{c.index}] {c.document_title} (score {c.score:.2f})")
    finally:
        await container.stop()


def export_demo_kb(source_dir: Path, out: Path, chunk_size: int, chunk_overlap: int) -> None:
    """Pre-chunk a folder of Markdown files into JSON for the in-browser demo mode."""
    documents: list[dict[str, Any]] = []
    for index, file in enumerate(sorted(source_dir.glob("*.md")), start=1):
        data = file.read_bytes()
        extracted = extract(
            data, mime_type=detect_mime_type(file.name, None, data), filename=file.name
        )
        doc_id = f"demo-{index:02d}"
        chunks = chunk_document(
            extracted, doc_id, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        documents.append(
            {
                "id": doc_id,
                "title": extracted.title,
                "source": file.name,
                "lang": "ru" if file.stem.endswith(".ru") or "-ru" in file.stem else "en",
                "chunks": [
                    {"id": c.id, "text": c.text, "heading": c.heading, "ordinal": c.ordinal}
                    for c in chunks
                ],
            }
        )
    payload = {
        "generator": "docmind export-demo-kb",
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "documents": documents,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(d["chunks"]) for d in documents)
    print(f"wrote {out} ({len(documents)} documents, {total} chunks)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="docmind", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_tenant = sub.add_parser("create-tenant", help="create a tenant and print its API key")
    p_tenant.add_argument("name")

    p_ingest = sub.add_parser("ingest", help="index local files/folders (in-process)")
    p_ingest.add_argument("--api-key", required=True, help="tenant key (created if new)")
    p_ingest.add_argument("paths", nargs="+", type=Path)

    p_ask = sub.add_parser("ask", help="ask a question against a tenant's knowledge base")
    p_ask.add_argument("--api-key", required=True)
    p_ask.add_argument("question")

    p_export = sub.add_parser("export-demo-kb", help="pre-chunk Markdown for the web demo")
    p_export.add_argument("source_dir", type=Path)
    p_export.add_argument("out", type=Path)
    p_export.add_argument("--chunk-size", type=int, default=700)
    p_export.add_argument("--chunk-overlap", type=int, default=100)

    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "create-tenant":
        asyncio.run(cmd_create_tenant(settings, args.name))
    elif args.command == "ingest":
        asyncio.run(cmd_ingest(settings, args.api_key, args.paths))
    elif args.command == "ask":
        asyncio.run(cmd_ask(settings, args.api_key, args.question))
    elif args.command == "export-demo-kb":
        export_demo_kb(args.source_dir, args.out, args.chunk_size, args.chunk_overlap)


if __name__ == "__main__":
    main()
