import { describe, expect, it } from 'vitest'
import { readSse, SseParser } from './sse'

describe('SseParser', () => {
  it('handles messages split across chunks and CRLF', () => {
    const parser = new SseParser()
    expect(parser.push('event: delta\r\ndata: {"text":"He')).toEqual([])
    expect(parser.push('llo"}\r\n\r\nevent: done\ndata: {}\n\n: comment\n\n')).toEqual([
      { event: 'delta', data: '{"text":"Hello"}' },
      { event: 'done', data: '{}' },
    ])
  })

  it('joins multi-line data and defaults the event name', () => {
    expect(new SseParser().push('data: a\ndata: b\n\n')).toEqual([{ event: 'message', data: 'a\nb' }])
  })

  it('reads a byte stream, including a trailing message without blank line', async () => {
    const bytes = new TextEncoder().encode('event: x\ndata: 1\n\nevent: y\ndata: 2')
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 7))
        controller.enqueue(bytes.slice(7))
        controller.close()
      },
    })
    const out = []
    for await (const m of readSse(stream)) out.push(m)
    expect(out).toEqual([
      { event: 'x', data: '1' },
      { event: 'y', data: '2' },
    ])
  })
})
