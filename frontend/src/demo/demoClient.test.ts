import { describe, expect, it } from 'vitest'
import type { ChatEvent } from '../api/types'
import { DemoClient } from './demoClient'

async function collect(it: AsyncIterable<ChatEvent>): Promise<ChatEvent[]> {
  const out: ChatEvent[] = []
  for await (const e of it) out.push(e)
  return out
}

describe('DemoClient', () => {
  const client = new DemoClient({ tokenDelayMs: 0 })

  it('ships the bundled fictional handbook', async () => {
    const docs = await client.listDocuments()
    expect(docs.length).toBeGreaterThanOrEqual(6)
    expect(docs.every((d) => d.status === 'ready' && d.chunk_count > 0)).toBe(true)
  })

  it('streams meta -> sources -> deltas -> done with grounded citations', async () => {
    const events = await collect(client.chat({ question: 'What is the learning budget?' }))
    const types = events.map((e) => e.type)
    expect(types[0]).toBe('meta')
    expect(types[1]).toBe('sources')
    expect(types.at(-1)).toBe('done')
    const done = events.at(-1)
    const streamed = events.map((e) => (e.type === 'delta' ? e.text : '')).join('')
    if (done?.type !== 'done') throw new Error('no done event')
    expect(streamed).toBe(done.done.answer)
    expect(done.done.answer).toContain('1,000 EUR')
    expect(done.done.cited.length).toBeGreaterThan(0)
    const sources = events[1]
    if (sources?.type !== 'sources') throw new Error('no sources')
    const first = sources.citations[0]!
    expect(first.highlight).toHaveLength(2)
  })

  it('answers Russian questions in Russian from Russian documents', async () => {
    const events = await collect(client.chat({ question: 'Сколько дней отпуска положено сотруднику?' }))
    const done = events.at(-1)
    if (done?.type !== 'done') throw new Error('no done event')
    expect(done.done.answer).toMatch(/^Вот что говорится/)
  })

  it('says so when nothing relevant is found', async () => {
    const events = await collect(client.chat({ question: 'quantum chromodynamics lattice' }))
    const done = events.at(-1)
    if (done?.type !== 'done') throw new Error('no done event')
    expect(done.done.cited).toEqual([])
    expect(done.done.answer).toMatch(/could not find/)
  })

  it('indexes uploaded Markdown in the browser and can delete it', async () => {
    const local = new DemoClient({ tokenDelayMs: 0 })
    const file = new File(['# Parking\n\nThe office parking garage opens at 06:30 on weekdays.'], 'parking.md')
    const doc = await local.uploadFile(file)
    expect(doc.title).toBe('Parking')
    const hits = local.retrieve('when does the parking garage open')
    expect(hits[0]?.document_id).toBe(doc.id)
    await local.deleteDocument(doc.id)
    expect(local.retrieve('parking garage').some((c) => c.document_id === doc.id)).toBe(false)
  })

  it('rejects formats and URL ingestion that need the real backend', async () => {
    await expect(client.uploadFile(new File(['x'], 'a.pdf'))).rejects.toMatchObject({ code: 'demo_unsupported' })
    await expect(client.ingestUrl()).rejects.toMatchObject({ status: 501 })
  })

  it('can be aborted mid-stream', async () => {
    const slow = new DemoClient({ tokenDelayMs: 5 })
    const controller = new AbortController()
    const run = async () => {
      for await (const e of slow.chat({ question: 'vacation days', signal: controller.signal })) {
        if (e.type === 'delta') controller.abort()
      }
    }
    await expect(run()).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('DemoClient answer quality', () => {
  it('does not pad answers with loosely related sentences', async () => {
    const client = new DemoClient({ tokenDelayMs: 0 })
    const citations = client.retrieve('How many vacation days do employees get?')
    const { answer, cited } = client.compose('How many vacation days do employees get?', citations)
    expect(answer).toContain('25 working days')
    expect(answer).not.toContain('onboarding buddy')
    expect(cited).toEqual([1])
  })
})
