import { describe, expect, it, vi } from 'vitest'
import { HttpClient } from './httpClient'
import type { ChatEvent } from './types'

function sseResponse(body: string): Response {
  return new Response(new TextEncoder().encode(body), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

describe('HttpClient', () => {
  it('sends the API key and maps SSE events', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      sseResponse(
        'event: meta\ndata: {"conversation_id":"c1","user_message_id":"m1"}\n\n' +
          'event: sources\ndata: {"citations":[{"index":1,"document_id":"d","document_title":"T","chunk_id":"k","snippet":"s","score":0.9}]}\n\n' +
          'event: delta\ndata: {"text":"Hi [1]"}\n\n' +
          'event: done\ndata: {"answer":"Hi [1]","cited":[1],"model":"fake","stop_reason":"end_turn"}\n\n',
      ),
    )
    const client = new HttpClient('http://api.test/', 'dm_key', fetchMock)
    const events: ChatEvent[] = []
    for await (const e of client.chat({ question: 'q', conversationId: 'c1' })) events.push(e)

    expect(events.map((e) => e.type)).toEqual(['meta', 'sources', 'delta', 'done'])
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('http://api.test/v1/chat/stream')
    expect((init?.headers as Record<string, string>)['X-API-Key']).toBe('dm_key')
    expect(JSON.parse(String(init?.body))).toMatchObject({ question: 'q', conversation_id: 'c1', document_ids: null })
  })

  it('turns error responses into ApiError with the server message', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ error: 'unauthorized', message: 'Invalid API key' }), { status: 401 }),
    )
    const client = new HttpClient('', 'bad', fetchMock)
    await expect(client.listDocuments()).rejects.toMatchObject({ status: 401, code: 'unauthorized', message: 'Invalid API key' })
  })

  it('uploads files as multipart and unwraps the accepted document', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ document: { id: 'd1', status: 'queued' }, job: {} }), { status: 202 }),
    )
    const doc = await new HttpClient('', 'k', fetchMock).uploadFile(new File(['x'], 'a.md'))
    expect(doc).toMatchObject({ id: 'd1', status: 'queued' })
    expect(fetchMock.mock.calls[0]![1]?.body).toBeInstanceOf(FormData)
  })
})
