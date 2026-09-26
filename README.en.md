# DocMind

[Русский](README.md) · **English**

You upload a PDF, DOCX, Markdown, HTML or TXT file, or a link, and ask a question. The answer streams in with `[1]`, `[2]` markers, and clicking a marker scrolls to a card with the source snippet and the highlighted sentence. The FastAPI backend (Python 3.12+, async SQLAlchemy, SQLite or Postgres + pgvector) indexes documents in the background. It comes with a CLI, a Telegram bot on aiogram 3 and a web UI built with React 19, TypeScript, Vite and Tailwind v4. With no API keys, a deterministic `FakeLLM` answers with quotes from the retrieved passages. Claude via the Anthropic SDK, or an OpenAI-compatible API, is plugged in with environment variables.

Demo: https://sinnercode228.github.io/docmind-rag/ (runs entirely in the browser). The knowledge base holds six documents from Lumenfold Labs, a made-up company: four in English and two in Russian. `What is the learning budget?` is a good first question.

![Answer with citations in demo mode](docs/screenshots/02-answer-citations.png)

In the demo, the answer is put together without an LLM, from one highlighted sentence per source. Cards 2–4 didn't pass the selection thresholds, so the second half of the question, about the conference, went unanswered.

## What happens when you ask a question

The answer comes over SSE, with events in the order `meta → sources → delta… → done`. If something fails after the stream has started, an `error` event arrives. Here's the stream from `make api` with `sample-kb/` loaded, for the question `What is the learning budget?` (trimmed):

```
event: meta
data: {"conversation_id": "cv_…", "user_message_id": "msg_…"}

event: sources
data: {"citations": [{"index": 1, "document_title": "Lumenfold Labs Employee Handbook", "snippet": "Each employee has a learning budget of 1,000 EUR per year…", "score": 0.4292, "heading": "Learning budget", "highlight": [0, 93], …}, …]}

event: delta
data: {"text": "Here "}
…
event: done
data: {"message_id": "msg_…", "answer": "…", "cited": [1, 2], "model": "fake-extractive", "stop_reason": "end_turn", "usage": {"input_tokens": null, "output_tokens": 56}}
```

1. [`useChat`](frontend/src/state/useChat.ts) sends `POST /v1/chat/stream` through [`HttpClient.chat`](frontend/src/api/httpClient.ts), with the key in `X-API-Key`. The body holds the question, `conversation_id` and the selected `document_ids`. I read the stream with `fetch` because `EventSource` only does GET and can't send custom headers.
2. The parser in [`lib/sse.ts`](frontend/src/lib/sse.ts) normalizes CRLF to `\n`, joins multi-line `data:` fields, buffers a message that's split between chunks, and still reads the last message if the stream closes without a blank line. [`sse.test.ts`](frontend/src/lib/sse.test.ts) covers these cases. Bytes are decoded by `TextDecoder` with `stream: true`, so a Cyrillic letter split between chunks doesn't turn into `�`.
3. [`routes_chat.py`](backend/src/docmind/api/routes_chat.py) checks `conversation_id` before opening the stream, so a conversation that doesn't exist or belongs to someone else gets a plain 404. Then the question is saved and `meta` goes out. By this point the 200 status has already been sent, so any later errors come as an `error` event. The frontend doesn't send the history: the backend pulls the last 4 question–answer pairs from its own database.
4. [`Retriever`](backend/src/docmind/retrieval/retriever.py) takes the chunks closest to the question by cosine similarity, drops weak matches and duplicate texts, and MMR keeps 5 of them. The default embedder is lexical: feature hashing of words, bigrams and character trigrams ([`hashing.py`](backend/src/docmind/embeddings/hashing.py)). So "closest" here means "uses similar words", not "is about the same thing".
5. Sources go out as a `sources` event before the model is called ([`rag/service.py`](backend/src/docmind/rag/service.py)). The cards show up before the first token, and each `[n]` in the stream becomes a button right away; a number higher than the source count stays plain text ([`AnswerText.tsx`](frontend/src/components/AnswerText.tsx)). [`best_sentence`](backend/src/docmind/text.py) picks the sentence to highlight by the words it shares with the question, not with the answer, so with a real LLM the highlighted sentence may not be the one the model relied on.
6. Then come `delta` events with pieces of text. `done` carries the full answer, `model`, `stop_reason`, usage and `cited` (the `[n]` numbers from the answer that don't exceed the number of sources). Cited cards get their number filled in, and the answer is saved to the database along with its sources, each with a `cited` flag. The event order comes from a single async generator, `_chat_events`. The non-streaming `/v1/chat` runs it to the end and builds JSON from the events, so the logic of the two endpoints can't diverge.

Every request to `/v1` carries a tenant key, in `X-API-Key` or as a Bearer token. The database stores only the key's sha256, and documents, vectors and conversations are queried with a `tenant_id` filter. `test_tenants_are_isolated` in [`test_api.py`](backend/tests/test_api.py) checks that with another tenant's key you can't find a document in the list, by id, or through search.

In Docker, nginx sits between the browser and the API. For `/v1/`, [`frontend/nginx.conf`](frontend/nginx.conf) turns off `proxy_buffering` and `proxy_cache`; otherwise nginx would hold the deltas in its buffer and the text would arrive in bursts. `proxy_read_timeout` is raised to 300 s. On top of that, the backend responds with `X-Accel-Buffering: no`, a header nginx reads from the upstream response, so the stream won't get stuck even behind an nginx with someone else's config.

The Telegram bot ([`bot/telegram.py`](backend/src/docmind/bot/telegram.py)) calls the same `/v1/chat/stream` as a regular client and streams the answer by editing a single message, at most once every 1.2 s ([`bot/service.py`](backend/src/docmind/bot/service.py)). Markdown in the answer is converted to Telegram's HTML markup. If Telegram rejects it (`TelegramBadRequest`), the final edit is retried with `parse_mode=None`.

## Chunking

The loader ([`loaders.py`](backend/src/docmind/ingestion/loaders.py)), built on pypdf, python-docx and BeautifulSoup, first splits a document into sections: Markdown by headings, DOCX by `Heading*` styles (all tables are appended to the end of the last section as `cell | cell` rows), HTML by `h1`–`h4` after stripping `nav`, `footer`, `script` and other boilerplate, and PDF by page. TXT, Markdown and HTML are decoded by trying utf-8 → cp1251 → latin-1 in turn, so a Russian `.txt` in cp1251 reads fine as is.

The splitter ([`chunking.py`](backend/src/docmind/ingestion/chunking.py)) works inside a single section and never crosses its boundary, so a chunk always has one heading and one page. The defaults are 900 characters per chunk and a 150-character overlap (`DOCMIND_CHUNK_SIZE`, `DOCMIND_CHUNK_OVERLAP`); the demo knowledge base is exported with 700/100.

- It splits recursively: first on `\n\n`; if a piece is still over the limit, on `\n`, then on `. `, `? `, `! `, `; `, `, ` and a space. When no separators are left, it cuts by length.
- Then it greedily merges neighboring pieces back together as long as the chunk fits in `chunk_size`.
- Overlap comes from stepping back over whole pieces and never exceeds `chunk_overlap`. The step back is limited by the condition `k - 1 > i`: the next chunk starts at least one piece further than the previous one, so the loop can't hang. `test_chunks_respect_size_and_cover_text` checks this for every pair of adjacent chunks.
- Text is only split down to the level where the pieces fit in `chunk_size`. If paragraphs are shorter than the limit, the pieces stay whole paragraphs, and overlap only appears when a chunk's last paragraph is no longer than `chunk_overlap`. In `sample-kb` every section fits in one chunk anyway (39 sections, 39 chunks), so there's no overlap there.
- For Markdown, `heading` holds the heading path, e.g. `Time off › Paid vacation`. The H1 counts as the document title and stays out of the path if there's a subheading under it. A `#` inside a code block isn't treated as a heading.

## SSRF when uploading by URL

The URL is downloaded in a background job through [`fetch.py`](backend/src/docmind/ingestion/fetch.py):

- only the `http` and `https` schemes are allowed, and a URL with `user:pass@` is rejected;
- the host is resolved, and all of its addresses must be global: if the name resolves to one public IP and `127.0.0.1`, the request isn't sent. The checked IP isn't pinned, though: when connecting, httpx resolves the name again, which leaves a window for DNS rebinding between the check and the request;
- httpx doesn't follow redirects itself (`follow_redirects=False`); every `Location` goes through the same guard again, up to 5 hops;
- size is checked against `Content-Length` before the body is read, and against the actual bytes during the streaming read; the limit is the same as for file uploads, 20 MB. The 15 s httpx timeout applies to each operation, and there's no overall limit on download time.

[`test_fetch.py`](backend/tests/test_fetch.py) covers `ftp://` and `file://`, the addresses `10.0.0.7` and `169.254.169.254`, a redirect from a public host to `169.254.169.254`, a redirect loop, and a response with a `Content-Length` over the limit. A rejected URL doesn't crash the API: the document gets the `failed` status with the error text (`test_url_blocked_by_ssrf_guard_fails_job` in [`test_api.py`](backend/tests/test_api.py)). For an internal network, `DOCMIND_ALLOW_PRIVATE_URLS=true` turns the check off.

## The BM25 demo client

The Pages build (`npm run build:pages`) takes `VITE_DOCMIND_MODE=demo` from [`.env.pages`](frontend/.env.pages), and the UI gets [`DemoClient`](frontend/src/demo/demoClient.ts) instead of `HttpClient`. Both implement `DocMindClient`, the demo client emits events in the same order, and `useChat` doesn't know about the swap. You can add your own `.md` and `.txt` files up to 2 MB right in the browser; PDF, DOCX and links need the API. The Settings dialog switches to a real backend, and the API URL and key are saved in `localStorage`.

The knowledge base lives in [`kb.json`](frontend/src/demo/kb.json). `docmind export-demo-kb` (`make demo-kb`) builds it from `sample-kb/*.md` with the same loaders and `chunk_document` as the server: 6 documents, 39 chunks. Files are processed in sorted name order, and a chunk id is a blake2b hash of the document id, the sequence number and the text, so a repeated export produces a byte-for-byte identical file.

Search runs in the browser: BM25 (k1 = 1.4, b = 0.75) over stemmed words, with the heading indexed together with the text ([`bm25.ts`](frontend/src/lib/bm25.ts)). Of 16 candidates, MMR keeps 4, using Jaccard similarity between word sets. Tokenization, the suffix stemmer for Russian and English, and sentence selection are ported from `text.py` to [`text.ts`](frontend/src/lib/text.ts). The answer is built from a template: the source's highlighted sentence plus `[n]`, at most three points. A source with a normalized score below 0.35 is skipped, and each following point has to cover at least 75% as many of the question's words as the first one did. As with `FakeLLM`, the answer language is picked by whether the question contains Cyrillic.

## What's simplified

- Backend search is vector search with MMR, with no hybrid search and no reranker; BM25 exists only in the browser demo.
- Failed indexing isn't retried on its own and stays `failed` until `POST /v1/documents/{id}/reindex`. After a restart, only unfinished jobs go back into the queue ([`runner.py`](backend/src/docmind/jobs/runner.py)).
- Prompt injection protection is one line in the system prompt ([`prompt.py`](backend/src/docmind/rag/prompt.py)). The source's title and location are escaped, but the snippet text itself goes to the model as is.
- The schema is created with `create_all`; there are no migrations. `content_hash` is stored but not checked, so a file uploaded again gets indexed again.

## Running it

The quickest way to see it is the demo linked above. Locally, with the backend:

```bash
make setup                                        # backend/.venv + npm install
DOCMIND_MEMORY_STORE_PATH=data/vectors make api   # http://localhost:8000/docs: SQLite, FakeLLM, key dm_local_dev_key
make web                                          # http://localhost:5173: UI in api mode, Vite proxies /v1 to :8000
```

Without `DOCMIND_MEMORY_STORE_PATH`, vectors live only in process memory: after an API restart (including one triggered by `--reload` when you edit code), documents in SQLite are still listed as `ready`, but search comes back empty. With the variable set, the store writes a snapshot to `backend/data/vectors` after every change (`data/` is in `.gitignore`). The CLI commands `ingest` and `ask` run as separate processes, so for them the variable is required:

```bash
cd backend
export DOCMIND_MEMORY_STORE_PATH=data/vectors
.venv/bin/docmind ingest --api-key dm_local_dev_key ../sample-kb
.venv/bin/docmind ask --api-key dm_local_dev_key "How many vacation days do employees get?"
```

By default `FakeLLM` answers: it goes through the retrieved snippets in order, takes the best sentence from each (three at most) and puts `[n]` after it. A real model is plugged in with environment variables or through `backend/.env`:

```bash
DOCMIND_LLM_PROVIDER=anthropic DOCMIND_ANTHROPIC_API_KEY=... make api
DOCMIND_LLM_PROVIDER=openai DOCMIND_OPENAI_BASE_URL=http://localhost:11434/v1 DOCMIND_OPENAI_MODEL=llama3.1 make api
```

On `stop_reason: refusal`, the Anthropic provider appends a note to the answer saying the model declined to answer. Semantic search needs `DOCMIND_EMBEDDER=openai`, an OpenAI-compatible `/embeddings` endpoint (`DOCMIND_EMBEDDING_BASE_URL`, `DOCMIND_EMBEDDING_MODEL`, `DOCMIND_EMBEDDING_API_KEY`) and `DOCMIND_EMBEDDING_DIM` set to the model's dimension: the request doesn't pass a `dimensions` parameter, and 384 is expected by default. `.env.example` only has the main variables; the full list of settings is in [`config.py`](backend/src/docmind/config.py).

Docker brings up Postgres 17 with pgvector (an HNSW cosine index), the API, and the UI behind nginx. Compose passes `DOCMIND_BOOTSTRAP_API_KEY` into the frontend build as `VITE_DOCMIND_API_KEY`, so the key ends up in the JS bundle. That's convenient locally, but a setup like this must not be exposed publicly (CORS also defaults to `*`), and you should replace the key from `.env.example` with your own.

```bash
cp .env.example .env
docker compose up --build                      # UI: http://localhost:8080, API: http://localhost:8000/docs
docker compose --profile telegram up --build   # plus the bot: needs DOCMIND_TELEGRAM_BOT_TOKEN and DOCMIND_TELEGRAM_API_KEY
```

## Tests

| | What | How many |
|---|---|---|
| Backend | pytest + pytest-asyncio. In the API tests the LLM is `FakeLLM` and embeddings use offline hashing; the Anthropic and OpenAI-compatible API clients and `fetch.py` are tested through `httpx.MockTransport`, with DNS stubbed out. No network or Docker needed | 101 tests, 76% coverage (branches included) |
| Frontend | Vitest + Testing Library: SSE parser, HTTP client, BM25, text utilities, demo client, App | 26 tests |

```bash
make test && make lint   # ruff, ruff format --check, mypy (strict); eslint, tsc
```

The pgvector store, the Telegram bot and the CLI have no tests: they're at 0% in the coverage report. CI ([`ci.yml`](.github/workflows/ci.yml)) runs linters, type checks, tests, the demo build and `docker compose build` on Python 3.13 and Node 22; [`pages.yml`](.github/workflows/pages.yml) deploys the demo.

---

Built by Грешный Котик (sinnercode). I take freelance work like this: Telegram [@sinnercode](https://t.me/sinnercode). License: [MIT](LICENSE).
