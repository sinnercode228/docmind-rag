/** Wire types shared by the HTTP client and the in-browser demo backend. */

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed'

export interface DocumentInfo {
  id: string
  title: string
  source_type: 'file' | 'url' | 'text' | 'demo' | string
  source: string
  status: DocumentStatus
  error: string | null
  chunk_count: number
  size_bytes: number
  created_at: string
}

export interface Citation {
  index: number
  document_id: string
  document_title: string
  chunk_id: string
  snippet: string
  score: number
  page?: number | null
  heading?: string | null
  /** `[start, end)` offsets of the most relevant sentence inside `snippet`. */
  highlight?: [number, number] | number[] | null
  cited?: boolean
}

export interface DoneInfo {
  answer: string
  cited: number[]
  model: string
  stop_reason: string
  message_id?: string
}

export type ChatEvent =
  | { type: 'meta'; conversation_id: string }
  | { type: 'sources'; citations: Citation[] }
  | { type: 'delta'; text: string }
  | { type: 'done'; done: DoneInfo }
  | { type: 'error'; error: string; message: string }

export interface ChatParams {
  question: string
  conversationId?: string
  documentIds?: string[]
  signal?: AbortSignal
}

export interface BackendInfo {
  mode: 'demo' | 'api'
  llm: string
  embedder: string
  tenant?: string
}

/** Everything the UI needs from a backend. Implemented by `HttpClient` and `DemoClient`. */
export interface DocMindClient {
  readonly mode: 'demo' | 'api'
  info(): Promise<BackendInfo>
  listDocuments(): Promise<DocumentInfo[]>
  getDocument(id: string): Promise<DocumentInfo>
  uploadFile(file: File): Promise<DocumentInfo>
  ingestUrl(url: string): Promise<DocumentInfo>
  deleteDocument(id: string): Promise<void>
  chat(params: ChatParams): AsyncIterable<ChatEvent>
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}
