import { readSse } from '../lib/sse'
import {
  ApiError,
  type BackendInfo,
  type ChatEvent,
  type ChatParams,
  type DocMindClient,
  type DocumentInfo,
} from './types'

/** Client for the real DocMind FastAPI backend (`/v1/*`, API-key auth, SSE streaming). */
export class HttpClient implements DocMindClient {
  readonly mode = 'api' as const
  private readonly baseUrl: string
  private readonly apiKey: string
  private readonly fetchImpl: typeof fetch

  constructor(baseUrl: string, apiKey: string, fetchImpl: typeof fetch = fetch.bind(globalThis)) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.apiKey = apiKey
    this.fetchImpl = fetchImpl
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    if (this.apiKey) headers.set('X-API-Key', this.apiKey)
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers })
    if (!response.ok) throw await toApiError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  async info(): Promise<BackendInfo> {
    const me = await this.request<{ tenant: { name: string }; llm: string; embedder: string }>('/v1/me')
    return { mode: 'api', llm: me.llm, embedder: me.embedder, tenant: me.tenant.name }
  }

  listDocuments(): Promise<DocumentInfo[]> {
    return this.request('/v1/documents')
  }

  getDocument(id: string): Promise<DocumentInfo> {
    return this.request(`/v1/documents/${encodeURIComponent(id)}`)
  }

  async uploadFile(file: File): Promise<DocumentInfo> {
    const form = new FormData()
    form.append('file', file)
    const accepted = await this.request<{ document: DocumentInfo }>('/v1/documents', {
      method: 'POST',
      body: form,
    })
    return accepted.document
  }

  async ingestUrl(url: string): Promise<DocumentInfo> {
    const accepted = await this.request<{ document: DocumentInfo }>('/v1/documents/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    return accepted.document
  }

  deleteDocument(id: string): Promise<void> {
    return this.request(`/v1/documents/${encodeURIComponent(id)}`, { method: 'DELETE' })
  }

  async *chat(params: ChatParams): AsyncGenerator<ChatEvent> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    if (this.apiKey) headers['X-API-Key'] = this.apiKey
    const response = await this.fetchImpl(`${this.baseUrl}/v1/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        question: params.question,
        conversation_id: params.conversationId ?? null,
        document_ids: params.documentIds?.length ? params.documentIds : null,
      }),
      signal: params.signal,
    })
    if (!response.ok || !response.body) throw await toApiError(response)
    for await (const message of readSse(response.body)) {
      const data = JSON.parse(message.data) as Record<string, unknown>
      switch (message.event) {
        case 'meta':
          yield { type: 'meta', conversation_id: String(data.conversation_id) }
          break
        case 'sources':
          yield { type: 'sources', citations: data.citations as never }
          break
        case 'delta':
          yield { type: 'delta', text: String(data.text) }
          break
        case 'done':
          yield { type: 'done', done: data as never }
          break
        case 'error':
          yield { type: 'error', error: String(data.error), message: String(data.message) }
          break
      }
    }
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`
  let message = response.statusText || 'Request failed'
  try {
    const body = (await response.json()) as { error?: string; message?: string; detail?: unknown }
    if (body.error) code = body.error
    if (body.message) message = body.message
    else if (typeof body.detail === 'string') message = body.detail
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(response.status, code, message)
}
