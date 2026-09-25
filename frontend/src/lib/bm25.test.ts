import { describe, expect, it } from 'vitest'
import { Bm25Index, mmr, type IndexedChunk } from './bm25'
import { chunkMarkdown } from './chunking'

const chunk = (id: string, text: string, documentId = 'd1', heading: string | null = null): IndexedChunk => ({
  id,
  documentId,
  documentTitle: documentId,
  text,
  heading,
})

describe('Bm25Index', () => {
  const index = new Bm25Index()
  index.add([
    chunk('a', 'Employees receive 28 vacation days per year.', 'hr', 'Vacation'),
    chunk('b', 'Passwords must be at least 14 characters long.', 'sec', 'Passwords'),
    chunk('c', 'Laptops are replaced every three years.', 'it'),
    chunk('d', 'Vacation requests are approved by your manager.', 'hr', 'Vacation'),
  ])

  it('ranks the matching chunk first', () => {
    const hits = index.search('how long must a password be')
    expect(hits[0]?.chunk.id).toBe('b')
  })

  it('uses headings as signal and returns nothing for unknown terms', () => {
    expect(index.search('vacation').map((h) => h.chunk.id)).toEqual(expect.arrayContaining(['a', 'd']))
    expect(index.search('zebra')).toEqual([])
  })

  it('filters by document id and supports removal', () => {
    expect(index.search('vacation laptops', 10, ['it']).map((h) => h.chunk.id)).toEqual(['c'])
    const copy = new Bm25Index()
    copy.add([chunk('x', 'alpha beta', 'one'), chunk('y', 'alpha gamma', 'two')])
    expect(copy.removeDocument('one')).toBe(1)
    expect(copy.size).toBe(1)
    expect(copy.search('beta')).toEqual([])
  })

  it('MMR skips near-duplicates in favour of diverse hits', () => {
    const dup = new Bm25Index()
    dup.add([
      chunk('1', 'refund policy refunds within 30 days of purchase'),
      chunk('2', 'refund policy refunds within 30 days of purchase receipt'),
      chunk('3', 'refund requests for travel are handled by finance'),
    ])
    const picked = mmr(dup.search('refund policy', 10), 2, 0.5).map((h) => h.chunk.id)
    expect(picked[0]).toBe('1')
    expect(picked).toContain('3')
  })
})

describe('chunkMarkdown', () => {
  it('splits by headings and keeps the title', () => {
    const { title, chunks } = chunkMarkdown('# Guide\n\nIntro text.\n\n## Setup\n\nInstall it.\n\nRun it.')
    expect(title).toBe('Guide')
    expect(chunks).toEqual([
      { text: 'Intro text.', heading: 'Guide' },
      { text: 'Install it.\n\nRun it.', heading: 'Setup' },
    ])
  })

  it('respects the maximum chunk size', () => {
    const para = 'word '.repeat(60).trim()
    const { chunks } = chunkMarkdown([para, para, para].join('\n\n'), 400)
    expect(chunks.length).toBeGreaterThan(1)
    expect(chunks.every((c) => c.text.length <= 400)).toBe(true)
  })
})
