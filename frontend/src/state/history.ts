import type { Citation } from '../api/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  cited?: number[]
  model?: string
  streaming?: boolean
  error?: string
}

export interface Conversation {
  id: string
  /** Conversation id assigned by the backend (keeps multi-turn context server-side). */
  serverId?: string
  title: string
  messages: ChatMessage[]
  updatedAt: number
}

const KEY = (mode: string) => `docmind.history.${mode}`
const MAX_CONVERSATIONS = 30

export function newId(prefix = 'id'): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export function loadHistory(mode: string): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY(mode))
    const list = raw ? (JSON.parse(raw) as Conversation[]) : []
    return list.map((c) => ({
      ...c,
      messages: c.messages.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    }))
  } catch {
    return []
  }
}

export function saveHistory(mode: string, conversations: Conversation[]): void {
  try {
    const trimmed = conversations
      .filter((c) => c.messages.length > 0)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS)
    localStorage.setItem(KEY(mode), JSON.stringify(trimmed))
  } catch {
    /* quota or privacy mode: history is best-effort */
  }
}
