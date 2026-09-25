import { useCallback, useEffect, useRef, useState } from 'react'
import type { DocMindClient } from '../api/types'
import { loadHistory, newId, saveHistory, type ChatMessage, type Conversation } from './history'

export interface ChatState {
  conversations: Conversation[]
  active: Conversation | null
  streaming: boolean
  send: (question: string, documentIds?: string[]) => Promise<void>
  stop: () => void
  select: (id: string | null) => void
  remove: (id: string) => void
}

export function useChat(client: DocMindClient): ChatState {
  const [conversations, setConversations] = useState<Conversation[]>(() => loadHistory(client.mode))
  const [activeId, setActiveId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!streaming) saveHistory(client.mode, conversations)
  }, [conversations, streaming, client.mode])

  const patch = useCallback((id: string, fn: (c: Conversation) => Conversation) => {
    setConversations((list) => list.map((c) => (c.id === id ? fn(c) : c)))
  }, [])

  const patchMessage = useCallback(
    (conversationId: string, messageId: string, fn: (m: ChatMessage) => ChatMessage) => {
      patch(conversationId, (c) => ({
        ...c,
        updatedAt: Date.now(),
        messages: c.messages.map((m) => (m.id === messageId ? fn(m) : m)),
      }))
    },
    [patch],
  )

  const send = useCallback(
    async (question: string, documentIds?: string[]) => {
      const text = question.trim()
      if (!text || streaming) return
      const existing = conversations.find((c) => c.id === activeId)
      const conversation: Conversation = existing ?? {
        id: newId('conv'),
        title: text.slice(0, 80),
        messages: [],
        updatedAt: Date.now(),
      }
      const userMessage: ChatMessage = { id: newId('msg'), role: 'user', content: text }
      const reply: ChatMessage = { id: newId('msg'), role: 'assistant', content: '', streaming: true }
      const cid = conversation.id
      setConversations((list) => [
        { ...conversation, messages: [...conversation.messages, userMessage, reply], updatedAt: Date.now() },
        ...list.filter((c) => c.id !== cid),
      ])
      setActiveId(cid)
      setStreaming(true)
      const controller = new AbortController()
      abortRef.current = controller
      try {
        for await (const event of client.chat({
          question: text,
          conversationId: conversation.serverId,
          documentIds,
          signal: controller.signal,
        })) {
          switch (event.type) {
            case 'meta':
              patch(cid, (c) => ({ ...c, serverId: event.conversation_id }))
              break
            case 'sources':
              patchMessage(cid, reply.id, (m) => ({ ...m, citations: event.citations }))
              break
            case 'delta':
              patchMessage(cid, reply.id, (m) => ({ ...m, content: m.content + event.text }))
              break
            case 'done':
              patchMessage(cid, reply.id, (m) => ({
                ...m,
                content: event.done.answer,
                cited: event.done.cited,
                model: event.done.model,
                streaming: false,
              }))
              break
            case 'error':
              patchMessage(cid, reply.id, (m) => ({ ...m, error: event.message, streaming: false }))
              break
          }
        }
      } catch (err) {
        const aborted = err instanceof DOMException && err.name === 'AbortError'
        patchMessage(cid, reply.id, (m) => ({
          ...m,
          streaming: false,
          error: aborted ? undefined : err instanceof Error ? err.message : String(err),
          content: aborted ? `${m.content}${m.content ? ' ' : ''}_(stopped)_` : m.content,
        }))
      } finally {
        patchMessage(cid, reply.id, (m) => ({ ...m, streaming: false }))
        abortRef.current = null
        setStreaming(false)
      }
    },
    [activeId, client, conversations, patch, patchMessage, streaming],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const remove = useCallback((id: string) => {
    setConversations((list) => list.filter((c) => c.id !== id))
    setActiveId((current) => (current === id ? null : current))
  }, [])

  return {
    conversations,
    active: conversations.find((c) => c.id === activeId) ?? null,
    streaming,
    send,
    stop,
    select: setActiveId,
    remove,
  }
}
