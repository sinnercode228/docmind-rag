import { Bm25Index, mmr, type Hit } from '../lib/bm25'
import { chunkMarkdown } from '../lib/chunking'
import { bestSentence, contentTerms, isCyrillic } from '../lib/text'
import {
  ApiError,
  type BackendInfo,
  type ChatEvent,
  type ChatParams,
  type Citation,
  type DocMindClient,
  type DocumentInfo,
} from '../api/types'
import kb from './kb.json'

export interface DemoKb {
  documents: Array<{
    id: string
    title: string
    source: string
    chunks: Array<{ id: string; text: string; heading: string | null }>
  }>
}

export interface DemoOptions {
  /** Delay between streamed tokens, ms. 0 disables the typing effect (tests). */
  tokenDelayMs?: number
  topK?: number
  kb?: DemoKb
}

const COPY = {
  en: {
    intro: 'Here is what the knowledge base says:',
    none: 'I could not find an answer to that in the loaded documents. Try rephrasing, or ask about vacation, security, onboarding or travel expenses.',
    note: '_Demo mode: this answer was assembled in your browser from quoted passages (BM25 + MMR retrieval, no LLM). Connect the API for generated answers._',
  },
  ru: {
    intro: 'Вот что говорится в базе знаний:',
    none: 'Не нашёл ответа в загруженных документах. Попробуйте переформулировать или спросите про отпуск, безопасность, онбординг или командировки.',
    note: '_Демо-режим: ответ собран в браузере из цитат найденных фрагментов (поиск BM25 + MMR, без LLM). Подключите API для генеративных ответов._',
  },
}

const TOKENS = /\S+\s*/g
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })

/**
 * A complete in-browser stand-in for the DocMind API, used by the GitHub Pages demo.
 * It ships a pre-chunked fictional handbook (exported by `docmind export-demo-kb`), ranks
 * chunks with BM25 + MMR and answers extractively, quoting the best sentence of each source.
 */
export class DemoClient implements DocMindClient {
  readonly mode = 'demo' as const
  private readonly index = new Bm25Index()
  private readonly documents = new Map<string, DocumentInfo>()
  private readonly tokenDelayMs: number
  private readonly topK: number
  private uploads = 0

  constructor(options: DemoOptions = {}) {
    // Respect reduced-motion users: no artificial typing effect.
    const reducedMotion =
      typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    this.tokenDelayMs = options.tokenDelayMs ?? (reducedMotion ? 0 : 14)
    this.topK = options.topK ?? 4
    const created = new Date().toISOString()
    for (const doc of (options.kb ?? (kb as DemoKb)).documents) {
      this.documents.set(doc.id, {
        id: doc.id,
        title: doc.title,
        source_type: 'demo',
        source: doc.source,
        status: 'ready',
        error: null,
        chunk_count: doc.chunks.length,
        size_bytes: doc.chunks.reduce((n, c) => n + c.text.length, 0),
        created_at: created,
      })
      this.index.add(
        doc.chunks.map((c) => ({
          id: c.id,
          documentId: doc.id,
          documentTitle: doc.title,
          text: c.text,
          heading: c.heading,
        })),
      )
    }
  }

  async info(): Promise<BackendInfo> {
    return { mode: 'demo', llm: 'demo-extractive', embedder: 'bm25 (in-browser)', tenant: 'demo' }
  }

  async listDocuments(): Promise<DocumentInfo[]> {
    return [...this.documents.values()]
  }

  async getDocument(id: string): Promise<DocumentInfo> {
    const doc = this.documents.get(id)
    if (!doc) throw new ApiError(404, 'not_found', 'Document not found')
    return doc
  }

  async uploadFile(file: File): Promise<DocumentInfo> {
    if (!/\.(md|markdown|txt)$/i.test(file.name)) {
      throw new ApiError(
        415,
        'demo_unsupported',
        'Demo mode indexes .md and .txt files in the browser. PDF/DOCX parsing needs the API backend.',
      )
    }
    if (file.size > MAX_UPLOAD_BYTES) throw new ApiError(413, 'too_large', 'Demo uploads are limited to 2 MB')
    const text = await file.text()
    const { title, chunks } = chunkMarkdown(text)
    if (chunks.length === 0) throw new ApiError(400, 'empty', 'The file contains no text')
    const id = `upload-${++this.uploads}`
    const docTitle = title ?? file.name.replace(/\.[^.]+$/, '')
    this.index.add(
      chunks.map((c, i) => ({ id: `${id}-${i}`, documentId: id, documentTitle: docTitle, ...c })),
    )
    const info: DocumentInfo = {
      id,
      title: docTitle,
      source_type: 'file',
      source: file.name,
      status: 'ready',
      error: null,
      chunk_count: chunks.length,
      size_bytes: file.size,
      created_at: new Date().toISOString(),
    }
    this.documents.set(id, info)
    return info
  }

  async ingestUrl(): Promise<DocumentInfo> {
    throw new ApiError(
      501,
      'demo_unsupported',
      'Fetching URLs requires the API backend (browsers block cross-site reads). Switch to API mode in settings.',
    )
  }

  async deleteDocument(id: string): Promise<void> {
    if (!this.documents.delete(id)) throw new ApiError(404, 'not_found', 'Document not found')
    this.index.removeDocument(id)
  }

  /** Retrieval only: BM25 top candidates re-ranked with MMR, as numbered citations. */
  retrieve(question: string, documentIds?: string[]): Citation[] {
    const hits: Hit[] = mmr(this.index.search(question, 16, documentIds), this.topK)
    const max = hits[0]?.score ?? 1
    return hits.map((hit, i) => ({
      index: i + 1,
      document_id: hit.chunk.documentId,
      document_title: hit.chunk.documentTitle,
      chunk_id: hit.chunk.id,
      snippet: hit.chunk.text,
      heading: hit.chunk.heading,
      score: Math.round((hit.score / max) * 1000) / 1000,
      highlight: bestSentence(hit.chunk.text, question),
    }))
  }

  compose(question: string, citations: Citation[]): { answer: string; cited: number[] } {
    const copy = COPY[isCyrillic(question) ? 'ru' : 'en']
    const points: string[] = []
    const cited: number[] = []
    const queryTerms = new Set(contentTerms(question))
    let firstOverlap = 0
    for (const c of citations) {
      if (c.score < 0.35 || !c.highlight) continue
      const [start, end] = c.highlight
      const sentence = c.snippet.slice(start, end).trim()
      // Supporting points must cover a comparable share of the question as the best one.
      const overlap = new Set(contentTerms(sentence).filter((t) => queryTerms.has(t))).size
      if (points.length === 0) firstOverlap = overlap
      else if (overlap < Math.max(1, Math.ceil(firstOverlap * 0.75))) continue
      points.push(`- ${sentence} [${c.index}]`)
      cited.push(c.index)
      if (points.length >= 3) break
    }
    if (points.length === 0) return { answer: copy.none, cited }
    return { answer: [copy.intro, '', ...points, '', copy.note].join('\n'), cited }
  }

  async *chat(params: ChatParams): AsyncGenerator<ChatEvent> {
    const conversationId = params.conversationId ?? `demo-${Date.now().toString(36)}`
    yield { type: 'meta', conversation_id: conversationId }
    const citations = this.retrieve(params.question, params.documentIds)
    yield { type: 'sources', citations }
    const { answer, cited } = this.compose(params.question, citations)
    for (const token of answer.match(TOKENS) ?? []) {
      if (this.tokenDelayMs) await sleep(this.tokenDelayMs, params.signal)
      yield { type: 'delta', text: token }
    }
    yield {
      type: 'done',
      done: { answer, cited, model: 'demo-extractive', stop_reason: 'end_turn' },
    }
  }
}
