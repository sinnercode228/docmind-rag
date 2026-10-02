# DocMind

A question-answering assistant over your own documents (RAG). You upload a PDF, DOCX, Markdown, HTML or text file, or give it a URL; it is indexed in the background, and the answer streams back with `[1]`, `[2]` markers. Clicking a marker scrolls to a card with the source passage and the sentence the answer rests on highlighted.

- Backend: FastAPI on Python 3.12+, async SQLAlchemy, SQLite or Postgres with pgvector. A CLI uses the same core directly; a Telegram bot (aiogram 3) talks to the same HTTP API.
- Frontend: React 19, TypeScript, Vite and Tailwind v4.
- Models: with no API keys, a deterministic `FakeLLM` answers by quoting the retrieved passages. Claude (through the Anthropic SDK) or any OpenAI-compatible server is switched on with environment variables.

Live demo: https://sinnercode228.github.io/docmind-rag/. It runs entirely in the browser, with no server and no model behind it. `What is the learning budget?` is a good first question.

All the data is made up. Lumenfold Labs does not exist: I wrote the six handbook files in [`sample-kb/`](sample-kb) for it, four in English and two in Russian, so there is something to ask about. This is a portfolio project, not a client product. The notes below go through the decisions and their trade-offs rather than a feature list. A short summary in Russian is at the end.

![Answer with citations in demo mode](docs/screenshots/02-answer-citations.png)

The demo answer above was assembled without an LLM, from one highlighted sentence per source. Card 2 scored 0.47 but was dropped by the coverage rule described under the demo below, and cards 3 and 4 fell under the 0.35 score threshold, so the second half of the question, about booking a conference, went unanswered.

## Why do the sources have to reach the screen before the first answer token?

This is the problem the rest of the design follows from. The answer streams and cites inline: `Employees get 25 working days [1]`. If the citation list arrived with the final event, the reader would spend the whole stream looking at `[1]` badges that point at nothing, and the UI could not tell a real `[7]` from one the model made up. So the order of events on `POST /v1/chat/stream` is fixed: `meta → sources → delta… → done`, plus `error` if something fails after the stream has started. This is the stream from `make api` with `sample-kb/` loaded, for `What is the learning budget?` (trimmed):

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

What happens, step by step:

1. [`useChat`](frontend/src/state/useChat.ts) sends `POST /v1/chat/stream` through [`HttpClient.chat`](frontend/src/api/httpClient.ts), with the key in `X-API-Key`. The body holds the question, `conversation_id` and the selected `document_ids`. I read the stream with `fetch` because `EventSource` only does GET and cannot send custom headers.
2. The parser in [`lib/sse.ts`](frontend/src/lib/sse.ts) normalises CRLF to `\n`, joins multi-line `data:` fields, buffers a message split between chunks, and still reads the last message if the stream closes without a blank line; [`sse.test.ts`](frontend/src/lib/sse.test.ts) covers these cases. Bytes are decoded by `TextDecoder` with `stream: true`, so a Cyrillic letter split between two chunks does not turn into `�`.
3. [`routes_chat.py`](backend/src/docmind/api/routes_chat.py) checks `conversation_id` before opening the stream ([line 121](backend/src/docmind/api/routes_chat.py#L121)), so a conversation that does not exist or belongs to another tenant gets a plain 404. Then the conversation row and the question are committed and `meta` goes out first, so the client holds the conversation id even if the model call fails later. The 200 status has been sent by then, so any later failure arrives as `event: error` inside the 200 response. The frontend does not send history: the backend loads the last 4 question–answer pairs from its own database.
4. [`Retriever`](backend/src/docmind/retrieval/retriever.py) takes the chunks closest to the question, drops weak matches and duplicate texts, and MMR keeps 5 of them (details below).
5. `RAGService.stream_answer` ([`rag/service.py`](backend/src/docmind/rag/service.py)) yields the full citation list as `sources` and only then opens the model stream. The cards are on screen before the first token, and each `[n]` in the stream becomes a button as soon as it appears; a number higher than the source count stays plain text ([`AnswerText.tsx`](frontend/src/components/AnswerText.tsx)).
6. Then come `delta` events. `done` repeats the whole answer and adds `model`, `stop_reason`, usage and `cited`: the `[n]` numbers a regex finds in the answer, capped at the number of sources. The UI uses `cited` to separate "retrieved" from "used": cited cards get a filled number badge, the others stay grey ([`CitationCard.tsx`](frontend/src/components/CitationCard.tsx)). The answer is saved with its sources, each carrying a `cited` flag. One async generator, `_chat_events`, produces this sequence; the non-streaming `/v1/chat` runs it to the end and builds JSON from the events, so the two endpoints cannot drift apart.

The highlight is computed on the server too. [`best_sentence`](backend/src/docmind/text.py) picks the sentence in the chunk that shares the most stemmed terms with the question, skips Markdown headings, and adds 0.5 for a sentence containing a digit, because in a handbook the sentence with the number is usually the answer. It is sent as `[start, end)` offsets into the snippet rather than as a copy of the text, so the client wraps a `<mark>` without re-tokenising anything. The same function is ported to TypeScript in [`lib/text.ts`](frontend/src/lib/text.ts), so the browser demo highlights the sentence the server would have picked. The trade-off: the sentence is chosen against the question, not the answer, so with a real LLM the highlighted sentence may not be the one the model relied on.

## What sits between the stream and the reader?

In Docker, nginx stands between the browser and the API. For `/v1/`, [`frontend/nginx.conf`](frontend/nginx.conf) turns off `proxy_buffering` and `proxy_cache`; otherwise nginx would hold the deltas in its buffer and the text would arrive in bursts. `proxy_read_timeout` is raised to 300 s. The backend also responds with `X-Accel-Buffering: no`, a header nginx reads from the upstream response, so the stream does not stall behind an nginx with someone else's config either.

The Telegram bot ([`bot/telegram.py`](backend/src/docmind/bot/telegram.py)) calls the same `/v1/chat/stream` as an ordinary client and streams the answer by editing one message, at most once every 1.2 s ([`bot/service.py`](backend/src/docmind/bot/service.py)). Markdown in the answer is converted to Telegram's HTML subset; if Telegram rejects it (`TelegramBadRequest`), the final edit is retried with `parse_mode=None`.

## How is one tenant kept out of another's documents?

Every tenant endpoint under `/v1` needs a tenant key, in `X-API-Key` or as a Bearer token ([`api/deps.py`](backend/src/docmind/api/deps.py)). The database stores only the key's SHA-256; a generated key is shown once. Documents, vectors and conversations are looked up with a `tenant_id` filter. `test_tenants_are_isolated` in [`test_api.py`](backend/tests/test_api.py) checks that with another tenant's key a document cannot be found in the list, by id, or through search.

`DOCMIND_BOOTSTRAP_API_KEY` creates a tenant named `default` with that key on startup. More tenants come from `POST /v1/admin/tenants`, which takes a separate `X-Admin-Token` header and answers 404 unless `DOCMIND_ADMIN_TOKEN` is set.

## How are documents cut, and why keep offsets instead of text?

The loaders ([`loaders.py`](backend/src/docmind/ingestion/loaders.py)), built on pypdf, python-docx and BeautifulSoup, first split a document into sections that carry a location. MIME detection checks the PDF signature first, then the file extension, then the declared content type, then the DOCX zip signature.

- Markdown is split by headings, and `heading` holds the breadcrumb, for example `Time off › Paid vacation`. The H1 counts as the document title and stays out of the path when there is a subheading under it; a `#` inside a fenced code block is not a heading.
- DOCX is split by `Heading*` styles; tables become `cell | cell` rows (see the limitations for where they end up).
- HTML is split by `h1`–`h4` after `script`, `style`, `noscript`, `nav`, `header`, `footer`, `aside` and `form` are removed.
- PDF sections are pages.
- Text, Markdown and HTML are decoded by trying UTF-8 (with or without BOM), then cp1251, then latin-1, so a Russian `.txt` saved in cp1251 reads as is.

The splitter ([`chunking.py`](backend/src/docmind/ingestion/chunking.py)) works inside one section and never crosses its boundary, so a chunk always has one heading and one page. Defaults are 900 characters per chunk and 150 of overlap (`DOCMIND_CHUNK_SIZE`, `DOCMIND_CHUNK_OVERLAP`); the test suite uses 400/60 and the demo export 700/100.

- It splits recursively: first on `\n\n`; a piece still over the limit is split on `\n`, then on `. `, `? `, `! `, `; `, `, ` and a space. When no separator is left, it cuts by length.
- It then packs neighbouring pieces back together greedily while the chunk fits `chunk_size`.
- Overlap comes from stepping back over whole pieces and never exceeds `chunk_overlap`. The step back is bounded by `k - 1 > i`, so the next chunk starts at least one piece after the previous one and the loop cannot stall; `test_chunks_respect_size_and_cover_text` checks this for every pair of neighbouring chunks.
- Text is only split down to the level where pieces fit `chunk_size`. If paragraphs are shorter than the limit, pieces stay whole paragraphs, and overlap appears only when the last paragraph of a chunk is no longer than `chunk_overlap`. In `sample-kb` every section fits in one chunk (39 sections, the longest 469 characters, 39 chunks), so there is no overlap there at all.

Every chunk keeps `start` and `end` offsets into its section, and its id is a blake2b hash of the document id, the ordinal and the text. Offsets rather than copies is the same decision as the highlight span: the UI receives positions, never a second copy of the text to keep in sync. Because ids are deterministic and files are read in sorted order, `make demo-kb` reproduces [`kb.json`](frontend/src/demo/kb.json) byte for byte.

## What stops a URL upload from reaching internal addresses?

The URL is downloaded in a background job by [`fetch.py`](backend/src/docmind/ingestion/fetch.py):

- only `http` and `https` are accepted, and a URL with `user:pass@` is rejected;
- the host is resolved and every address it returns must be global: a name that resolves to one public IP and `127.0.0.1` is refused;
- httpx does not follow redirects itself (`follow_redirects=False`); each `Location` goes through the same check again, up to 5 hops;
- size is checked against `Content-Length` before the body is read and against the actual bytes while streaming, with the same 20 MB limit as file uploads.

[`test_fetch.py`](backend/tests/test_fetch.py) covers `ftp://` and `file://`, hosts resolving to `10.0.0.7` and `169.254.169.254`, a redirect from a public host to `169.254.169.254`, a redirect loop and a response whose `Content-Length` is over the limit. A rejected URL does not break the API: the document is marked `failed` with the error text (`test_url_blocked_by_ssrf_guard_fails_job` in [`test_api.py`](backend/tests/test_api.py)). `DOCMIND_ALLOW_PRIVATE_URLS=true` turns the check off for an internal network. The two gaps I know of, DNS rebinding and the lack of an overall download deadline, are in the limitations.

## How does retrieval choose five passages?

Overlapping chunks are near-duplicates by construction, and a plain top-5 by cosine tends to return the same paragraph two or three times in slightly different windows. [`Retriever`](backend/src/docmind/retrieval/retriever.py) therefore fetches `fetch_k` = 24 nearest neighbours, drops anything under `min_score` = 0.05 and anything whose text repeats an earlier hit, then runs greedy Maximal Marginal Relevance ([`mmr.py`](backend/src/docmind/retrieval/mmr.py), lambda = 0.6) down to `top_k` = 5. The vector store returns embeddings with its results ([`vectorstore/base.py`](backend/src/docmind/vectorstore/base.py)) so that MMR needs no second round trip. There is no hybrid search and no reranker on the backend; BM25 exists only in the browser demo.

The default embedder ([`hashing.py`](backend/src/docmind/embeddings/hashing.py)) is the hashing trick: stemmed words, word bigrams and character trigrams hashed into a signed 384-dimensional vector. It is lexical, not semantic: "closest" means "uses similar words", not "is about the same thing". In return it is deterministic, needs no model download and runs in the test suite, and the character trigrams let Russian inflections of one word land near each other (`test_russian_morphology_via_char_ngrams`). For semantic retrieval, `DOCMIND_EMBEDDER=openai` points at any OpenAI-compatible `/embeddings` endpoint ([`embeddings/openai_compat.py`](backend/src/docmind/embeddings/openai_compat.py)); it checks the returned dimension against `DOCMIND_EMBEDDING_DIM` and fails rather than store vectors of the wrong size.

Two stores sit behind one `VectorStore` protocol: [`pgvector.py`](backend/src/docmind/vectorstore/pgvector.py) (one table, HNSW index with cosine ops, every query filtered by tenant id) for Docker, and [`memory.py`](backend/src/docmind/vectorstore/memory.py) (a numpy matrix per tenant, with optional on-disk snapshots) for development and tests.

## What is the LLM interface, and why is it this small?

[`llm/base.py`](backend/src/docmind/llm/base.py) defines a `Protocol` with a `name`, a `stream(request)` that yields `TextDelta` events followed by exactly one `Completion`, and `aclose()`. `LLMRequest` carries the rendered messages (system prompt, trimmed history, final user turn with the sources) and, next to them, the structured `question` and `sources`. A real model reads the messages; the Fake provider reads the structured view. That is the whole contract: adding a provider means one class plus a branch in [`factories.py`](backend/src/docmind/factories.py) and a name in [`config.py`](backend/src/docmind/config.py). There are three:

- `AnthropicLLM` ([`anthropic_provider.py`](backend/src/docmind/llm/anthropic_provider.py)): the official SDK's streaming Messages API, an optional effort level, and server-side fallbacks (a beta) on by default, switched off with `DOCMIND_ANTHROPIC_FALLBACKS=false`. A `refusal` stop reason appends a short notice instead of leaving an empty bubble.
- `OpenAICompatibleLLM` ([`openai_compat.py`](backend/src/docmind/llm/openai_compat.py)): `/chat/completions` over httpx, for Ollama, vLLM, LM Studio or anything else with that wire format. It asks for `stream_options.include_usage` so token counts come back where the server supports it.
- `FakeLLM` ([`fake.py`](backend/src/docmind/llm/fake.py)): deterministic and offline. It goes through the sources in order, quotes the best sentence from each (three at most) with `[n]`, switches to Russian copy when the question contains Cyrillic, and says in a footnote that the answer is extractive. The test suite and `make api` use it, which keeps the whole stack runnable without a key. It has no relevance cut-off: on `sample-kb`, `How many vacation days do employees get?` returns the 25-day sentence and, as a second point, an onboarding sentence that only shares "days" and gets the digit bonus. The demo client has a rule against this kind of padding; the Fake provider does not.

Provider failures become one `ProviderError` (HTTP 502, or `event: error` inside a stream) with a `retryable` flag. The prompt ([`rag/prompt.py`](backend/src/docmind/rag/prompt.py)) renders sources as numbered `<source index= title= location=>` blocks and asks the model to cite inline, to say plainly when the sources do not contain the answer, to reply in the language of the question, and to treat source text as material rather than instructions. The last 4 question–answer pairs of the conversation go along (`DOCMIND_HISTORY_TURNS`).

## How does the demo answer without a model?

GitHub Pages serves static files, so the demo cannot have a backend. [`DemoClient`](frontend/src/demo/demoClient.ts) implements the same `DocMindClient` interface as `HttpClient` ([`api/types.ts`](frontend/src/api/types.ts)) and emits events in the same order, so `useChat` does not know which one it holds. The Pages build (`npm run build:pages`) takes `VITE_DOCMIND_MODE=demo` from [`.env.pages`](frontend/.env.pages); the Settings dialog switches to a real backend and keeps the API URL and key in `localStorage`.

The knowledge base is [`kb.json`](frontend/src/demo/kb.json): 6 documents and 39 chunks, produced from `sample-kb/*.md` by `docmind export-demo-kb` (`make demo-kb`) with the backend's own loader and splitter, so the bundled documents are chunked exactly as the API would chunk them.

Search runs in the browser: BM25 ([`bm25.ts`](frontend/src/lib/bm25.ts), k1 = 1.4, b = 0.75) over stemmed terms, with the heading indexed together with the text, then MMR over the Jaccard similarity of term sets (lambda = 0.7), 16 candidates down to 4. Different similarity from the backend, same shape of algorithm; tokenisation, stop words and the Russian and English suffix stemmer are a port of `text.py`.

The answer is a template: an intro line, up to three highlighted sentences with `[n]`, and a note that no model was involved. A source scoring under 0.35 of the top hit is skipped, and each further point has to cover at least 75% as many question terms as the first one. The rule keeps the demo from padding a good answer with loosely related lines; `does not pad answers with loosely related sentences` in [`demoClient.test.ts`](frontend/src/demo/demoClient.test.ts) pins it. The cost is visible in both screenshots: a two-part question gets only its first part answered, because the sentence for the second part covers fewer of the question's terms. Tokens stream with a 14 ms delay for the typing effect, and with none under `prefers-reduced-motion`.

You can drop your own `.md` or `.txt` (up to 2 MB) and it is indexed in the browser. Those files go through a simpler chunker ([`lib/chunking.ts`](frontend/src/lib/chunking.ts)) than the bundled ones: no overlap, and a paragraph over 700 characters is cut by length. PDF, DOCX and URLs need the API, and the demo client says so with a 415 or a 501. The amber banner and the footnote in every answer say there is no LLM behind it. `?q=…` in the URL asks a question on load.

## How do I run it?

The quickest look is the demo linked above. Locally you need Python 3.12 or newer and Node 22 (the version CI and the frontend Dockerfile use):

```bash
make setup                                        # backend/.venv with dev extras, npm install in frontend/
DOCMIND_MEMORY_STORE_PATH=data/vectors make api   # http://localhost:8000/docs: SQLite, in-memory vectors, FakeLLM, key dm_local_dev_key
make web                                          # http://localhost:5173: UI in api mode, Vite proxies /v1 to :8000
```

Without `DOCMIND_MEMORY_STORE_PATH`, vectors live only in the API process: after a restart (including one triggered by `--reload` when you edit code), documents are still listed as `ready` in SQLite, but search comes back empty ([issue #1](https://github.com/sinnercode228/docmind-rag/issues/1)). With the variable set, the store writes a snapshot to `backend/data/vectors` after every change (`data/` is in `.gitignore`).

The CLI runs from `backend/`. `ingest` and `ask` are separate processes, so for them the variable is required; without it `ask` answers that it found nothing:

```bash
cd backend
export DOCMIND_MEMORY_STORE_PATH=data/vectors
.venv/bin/docmind ingest --api-key dm_local_dev_key ../sample-kb
.venv/bin/docmind ask --api-key dm_local_dev_key "How many vacation days do employees get?"
```

`ingest` creates the tenant if the key is new; `docmind create-tenant NAME` prints a fresh key.

A real model is plugged in with environment variables or through `backend/.env`:

```bash
DOCMIND_LLM_PROVIDER=anthropic DOCMIND_ANTHROPIC_API_KEY=... make api
DOCMIND_LLM_PROVIDER=openai DOCMIND_OPENAI_BASE_URL=http://localhost:11434/v1 DOCMIND_OPENAI_MODEL=llama3.1 make api
```

Semantic search needs `DOCMIND_EMBEDDER=openai`, an OpenAI-compatible `/embeddings` endpoint (`DOCMIND_EMBEDDING_BASE_URL`, `DOCMIND_EMBEDDING_MODEL`, `DOCMIND_EMBEDDING_API_KEY`) and `DOCMIND_EMBEDDING_DIM` equal to the model's dimension: no `dimensions` parameter is sent, and 384 is expected by default. [`.env.example`](.env.example) has the main variables; the full list of settings, all prefixed `DOCMIND_`, is in [`config.py`](backend/src/docmind/config.py).

The full stack in Docker: Postgres 17 with pgvector, the API, and the UI behind nginx. Read the limitation about the API key in the UI bundle before exposing it anywhere, and replace the key from `.env.example` with your own.

```bash
cp .env.example .env
docker compose up --build                      # UI: http://localhost:8080, API: http://localhost:8000/docs
docker compose --profile telegram up --build   # plus the bot; needs DOCMIND_TELEGRAM_BOT_TOKEN and DOCMIND_TELEGRAM_API_KEY
```

Talking to the API directly, from the repository root with `make api` running:

```bash
KEY=dm_local_dev_key
curl -H "X-API-Key: $KEY" -F file=@sample-kb/01-employee-handbook.md http://localhost:8000/v1/documents   # 202: document + job
curl -H "X-API-Key: $KEY" http://localhost:8000/v1/jobs/<job id>                                            # queued → running → succeeded
curl -N -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
     -d '{"question":"What is the learning budget?"}' http://localhost:8000/v1/chat/stream
```

Endpoints: `/v1/documents` (upload, `url`, `text`, list, get, `reindex`, delete), `/v1/jobs/{id}`, `/v1/chat`, `/v1/chat/stream`, `/v1/search` (retrieval only), `/v1/conversations`, `/v1/me`, `/v1/admin/tenants`, `/healthz`, `/readyz`. OpenAPI is at http://localhost:8000/docs.

The static demo alone: `cd frontend && npm run build:pages` writes `dist/` with base `/docmind-rag/`; set `VITE_BASE=/` for another host.

## What is rough, missing or wrong?

Things I know about and have not fixed, with where to look.

- **The in-memory vector store is not persisted by default** ([`config.py:33`](backend/src/docmind/config.py#L33), [`factories.py:58`](backend/src/docmind/factories.py#L58)). After a restart documents read `ready` while `/v1/search` returns nothing until `POST /v1/documents/{id}/reindex`, and the CLI pair finds nothing without `DOCMIND_MEMORY_STORE_PATH` ([`cli.py:34-92`](backend/src/docmind/cli.py#L34-L92)). Tracked in [issue #1](https://github.com/sinnercode228/docmind-rag/issues/1). Even with the variable, a snapshot is read only at startup and each save rewrites the tenant's whole collection ([`memory.py:35-52`](backend/src/docmind/vectorstore/memory.py#L35-L52)), so an API and a CLI running at the same time do not see each other's writes, and the last one to save wins. Use pgvector for anything that has to outlive a process.
- **The Docker UI ships the tenant key, and CORS is open.** `docker-compose.yml` passes `DOCMIND_BOOTSTRAP_API_KEY` into the UI build ([`docker-compose.yml:45`](docker-compose.yml#L45)), and [`frontend/Dockerfile:8-9`](frontend/Dockerfile#L8-L9) bakes it into the JavaScript bundle, so anyone who can load the UI has the key. CORS defaults to `*` ([`config.py:27`](backend/src/docmind/config.py#L27)). Fine for a single-tenant stack on a laptop, not for the open internet.
- **The SSRF guard has a DNS time-of-check gap, and downloads have no overall deadline.** [`fetch.py:76-77`](backend/src/docmind/ingestion/fetch.py#L76-L77) resolves the host to validate it, then httpx resolves it again to connect; a name that rebinds in between can reach a private address. Pinning the checked IP in the transport would close it and is not done. The 15 s timeout ([`fetch.py:69`](backend/src/docmind/ingestion/fetch.py#L69)) applies to each network operation, so a server that trickles bytes can hold one of the two ingestion workers ([`config.py:45`](backend/src/docmind/config.py#L45)) for a long time.
- **Source text goes into the prompt unescaped.** [`rag/prompt.py:36-39`](backend/src/docmind/rag/prompt.py#L36-L39) escapes the title and location but not the body, so a document containing `</source>` can close its block early. The system prompt's instruction to treat sources as material is the only defence against prompt injection.
- **Background jobs run in one process and are never retried.** `Job.attempts` ([`db/models.py:90`](backend/src/docmind/db/models.py#L90)) counts starts, `ProviderError.retryable` ([`errors.py:48-50`](backend/src/docmind/errors.py#L48-L50)) is set by every provider and read by nobody, and the worker ([`jobs/runner.py:60-68`](backend/src/docmind/jobs/runner.py#L60-L68)) logs the exception and moves on; a failed document stays `failed` until a manual reindex. The queue is an in-process `asyncio.Queue` ([`runner.py:24`](backend/src/docmind/jobs/runner.py#L24)), and every process re-queues all `queued` and `running` jobs at startup ([`container.py:44-45`](backend/src/docmind/container.py#L44-L45)), so two API replicas would both pick up the same pending jobs and index those documents twice.
- **Reindexing is not atomic.** [`ingestion/pipeline.py:114-115`](backend/src/docmind/ingestion/pipeline.py#L114-L115) deletes the old vectors and then upserts the new ones; a search in between sees nothing for that document, and a failure after the delete leaves it `failed` with no vectors.
- **The hashing embedder blocks the event loop.** [`hashing.py:61-62`](backend/src/docmind/embeddings/hashing.py#L61-L62) loops synchronously inside an `async def`. Text extraction is pushed to a thread ([`pipeline.py:106`](backend/src/docmind/ingestion/pipeline.py#L106)) but embedding is not, so indexing a large PDF stalls every other request for its duration.
- **The pgvector store has no automated test.** [`pyproject.toml:55`](backend/pyproject.toml#L55) declares an `integration` marker that no test uses, coverage for `pgvector.py` is 0%, and CI only builds the Docker images. The tenant and document filters are plain `WHERE` clauses on top of the HNSW ordering ([`pgvector.py:118-125`](backend/src/docmind/vectorstore/pgvector.py#L118-L125)), so a selective filter can return fewer than `fetch_k` rows; `hnsw.ef_search` is left at its default.
- **No migrations, no duplicate detection.** The schema comes from `create_all` ([`db/session.py:41-44`](backend/src/docmind/db/session.py#L41-L44)), so changing `DOCMIND_EMBEDDING_DIM` against an existing pgvector table fails at insert time instead of migrating. `content_hash` is written ([`db/repositories.py:87`](backend/src/docmind/db/repositories.py#L87)) but never compared, so the same file uploaded twice is indexed twice.
- **Follow-up questions are not rewritten before retrieval.** [`rag/service.py:110`](backend/src/docmind/rag/service.py#L110) retrieves with the raw question, so "and for managers?" is searched on those words alone. History reaches the model ([`service.py:122`](backend/src/docmind/rag/service.py#L122)) but never the retriever.
- **Only `[1]` and `[1][2]` count as citations** ([`rag/service.py:16`](backend/src/docmind/rag/service.py#L16), [`AnswerText.tsx:9`](frontend/src/components/AnswerText.tsx#L9)). A model that writes `[1, 2]` produces a correct answer with `cited: []`, every badge stays grey, and the markers are not clickable.
- **Extraction loses structure.** DOCX tables are appended after all paragraphs ([`loaders.py:175-179`](backend/src/docmind/ingestion/loaders.py#L175-L179)), under whichever heading came last, so their place in the document is lost. PDFs have no OCR (a scanned one is rejected at [`loaders.py:239-240`](backend/src/docmind/ingestion/loaders.py#L239-L240)) and no heading detection: a section is a page.

## What do the tests cover, and what do they skip?

[![CI](https://github.com/sinnercode228/docmind-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/sinnercode228/docmind-rag/actions/workflows/ci.yml)

| | What | How many |
|---|---|---|
| Backend | pytest + pytest-asyncio. The API tests run on SQLite in memory with `FakeLLM`, the hashing embedder and a stubbed URL fetcher; the Anthropic and OpenAI-compatible clients and `fetch.py` are tested through `httpx.MockTransport` with DNS stubbed. No network or Docker needed | 101 tests, 76% coverage with branches in CI |
| Frontend | Vitest + Testing Library under jsdom: SSE parser, HTTP client, BM25 and MMR, text utilities, demo client, App | 26 tests |

```bash
make test    # pytest in backend/, Vitest in frontend/
make lint    # ruff check, ruff format --check, mypy (strict); ESLint with zero warnings, tsc -b
```

[`ci.yml`](.github/workflows/ci.yml) runs linters, type checks and tests on Python 3.13 and Node 22, builds the Pages demo, then runs `docker compose build`. [`pages.yml`](.github/workflows/pages.yml) builds the demo with `VITE_BASE=/<repo>/`, copies `index.html` to `404.html` and publishes it through `deploy-pages`.

Tests worth reading before the code:

- `backend/tests/test_api.py::TestChat::test_streaming_chat_and_history`: event order on the stream, the concatenated deltas equal the `done` answer, and a follow-up in the same conversation.
- `frontend/src/demo/demoClient.test.ts`: the same order for the browser path, and the rule against padding answers.
- `backend/tests/test_fetch.py`: a redirect to a private address is blocked hop by hop, and the size cap holds.
- `backend/tests/test_retrieval.py::TestMMR`: lambda = 1 keeps the near-duplicate, lambda = 0.5 does not.

Not covered: the pgvector store, the Telegram bot and the CLI (0% in the coverage report), and the real Anthropic and OpenAI-compatible endpoints, which are only exercised against mocked transports.

## Where is what?

```
backend/src/docmind/
  api/          FastAPI routes, dependencies, Pydantic schemas
  ingestion/    loaders (PDF, DOCX, Markdown, HTML, text), chunking, URL fetch with SSRF guard, pipeline
  embeddings/   hashing embedder, OpenAI-compatible embedder
  vectorstore/  pgvector, in-memory numpy
  retrieval/    retriever (fetch_k, min_score, dedupe) and MMR
  llm/          LLMProvider protocol: Anthropic, OpenAI-compatible, Fake
  rag/          prompt assembly and the event stream
  jobs/         in-process job runner
  db/           SQLAlchemy models and repositories (tenants, keys, documents, jobs, conversations)
  bot/          Telegram bot (aiogram 3) talking to the API over HTTP
  cli.py        create-tenant, ingest, ask, export-demo-kb
backend/tests/
frontend/src/
  api/          DocMindClient interface and HttpClient (SSE)
  demo/         DemoClient and the bundled kb.json
  lib/          BM25 + MMR, Markdown chunker, text utilities, SSE parser
  components/   chat, citations, documents panel, settings
  state/        useChat and localStorage history
sample-kb/      six fictional handbook files, EN and RU
docs/           screenshots
```

Chat history in the web UI is kept in `localStorage` only ([`state/history.ts`](frontend/src/state/history.ts), 30 conversations); the server's `/v1/conversations` endpoints exist, but `DocMindClient` ([`api/types.ts:61-70`](frontend/src/api/types.ts#L61-L70)) has no methods for them, so history does not follow you to another browser.

Built by Грешный Котик ([sinnercode228](https://github.com/sinnercode228) on GitHub). I take freelance work like this: Telegram [@sinnercode](https://t.me/sinnercode). Licence: [MIT](LICENSE).

## Коротко по-русски

DocMind — ассистент вопросов и ответов по документам (RAG). Бэкенд на FastAPI индексирует в фоне PDF, DOCX, Markdown, HTML, текст и ссылки; векторы лежат в pgvector или в памяти процесса. Ответ дают Claude через официальный SDK, любой OpenAI-совместимый сервер (Ollama, vLLM, LM Studio) или детерминированный `FakeLLM`, который собирает ответ из цитат и работает без ключа. Веб-клиент на React показывает ответ потоком, карточки источников и подсвеченное предложение; Telegram-бот ходит в тот же HTTP API, а CLI использует то же ядро напрямую.

Главное решение: карточки источников появляются на экране раньше первого токена ответа, иначе ссылки `[1]`, `[2]` в тексте ведут в пустоту, пока идёт стрим. Поэтому порядок событий SSE жёсткий: `meta → sources → delta… → done`, поиск выполняется до вызова модели, а в `done` приходит список номеров, на которые ответ действительно сослался. Подсветка передаётся смещениями внутри фрагмента, а не копией текста.

Демо на GitHub Pages работает целиком в браузере: заранее нарезанная тем же сплиттером база (`frontend/src/demo/kb.json`), BM25 со стеммингом для русского и английского, MMR по Жаккару и шаблонный ответ из цитат. Модели там нет, и интерфейс об этом пишет. Компания Lumenfold Labs выдумана, документы в `sample-kb/` я написал для демо; это учебный проект, а не работа для заказчика.

Запуск: `make setup`, `DOCMIND_MEMORY_STORE_PATH=data/vectors make api`, `make web`; весь стек в Docker: `cp .env.example .env && docker compose up --build`. Без `DOCMIND_MEMORY_STORE_PATH` векторы в памяти не переживают перезапуск, и `docmind ask` после `docmind ingest` ничего не находит ([issue #1](https://github.com/sinnercode228/docmind-rag/issues/1)). Остальные известные проблемы со ссылками на файлы и строки собраны выше, в разделе «What is rough, missing or wrong?».

![Ответ на русский вопрос в демо](docs/screenshots/03-russian-answer.png)
