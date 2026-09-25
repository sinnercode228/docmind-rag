import { contentTerms } from './text'

export interface IndexedChunk {
  id: string
  documentId: string
  documentTitle: string
  text: string
  heading: string | null
}

export interface Hit {
  chunk: IndexedChunk
  score: number
  terms: Set<string>
}

/**
 * Okapi BM25 over stemmed content terms. Headings are indexed together with the chunk text
 * (they carry a lot of signal in handbooks), and results can be diversified with MMR.
 */
export class Bm25Index {
  private readonly k1: number
  private readonly b: number
  private docs: Array<{ chunk: IndexedChunk; tf: Map<string, number>; length: number }> = []
  private df = new Map<string, number>()
  private avgLength = 0

  constructor(options: { k1?: number; b?: number } = {}) {
    this.k1 = options.k1 ?? 1.4
    this.b = options.b ?? 0.75
  }

  get size(): number {
    return this.docs.length
  }

  add(chunks: IndexedChunk[]): void {
    for (const chunk of chunks) {
      const terms = contentTerms(`${chunk.heading ?? ''} ${chunk.text}`)
      const tf = new Map<string, number>()
      for (const term of terms) tf.set(term, (tf.get(term) ?? 0) + 1)
      for (const term of tf.keys()) this.df.set(term, (this.df.get(term) ?? 0) + 1)
      this.docs.push({ chunk, tf, length: terms.length })
    }
    this.recomputeAverage()
  }

  removeDocument(documentId: string): number {
    const removed = this.docs.filter((d) => d.chunk.documentId === documentId)
    for (const doc of removed) {
      for (const term of doc.tf.keys()) {
        const n = (this.df.get(term) ?? 1) - 1
        if (n <= 0) this.df.delete(term)
        else this.df.set(term, n)
      }
    }
    this.docs = this.docs.filter((d) => d.chunk.documentId !== documentId)
    this.recomputeAverage()
    return removed.length
  }

  private recomputeAverage(): void {
    const total = this.docs.reduce((sum, d) => sum + d.length, 0)
    this.avgLength = this.docs.length ? total / this.docs.length : 0
  }

  idf(term: string): number {
    const n = this.docs.length
    const df = this.df.get(term) ?? 0
    return Math.log(1 + (n - df + 0.5) / (df + 0.5))
  }

  search(query: string, limit = 10, documentIds?: string[]): Hit[] {
    const queryTerms = [...new Set(contentTerms(query))]
    if (queryTerms.length === 0 || this.docs.length === 0) return []
    const allowed = documentIds?.length ? new Set(documentIds) : null
    const hits: Hit[] = []
    for (const doc of this.docs) {
      if (allowed && !allowed.has(doc.chunk.documentId)) continue
      let score = 0
      for (const term of queryTerms) {
        const f = doc.tf.get(term)
        if (!f) continue
        const norm = 1 - this.b + this.b * (doc.length / (this.avgLength || 1))
        score += this.idf(term) * ((f * (this.k1 + 1)) / (f + this.k1 * norm))
      }
      if (score > 0) hits.push({ chunk: doc.chunk, score, terms: new Set(doc.tf.keys()) })
    }
    return hits.sort((a, b) => b.score - a.score).slice(0, limit)
  }
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let inter = 0
  for (const t of a) if (b.has(t)) inter++
  return inter / (a.size + b.size - inter)
}

/**
 * Maximal Marginal Relevance: greedily pick hits that are relevant (normalised BM25) but not
 * redundant with already-selected ones (Jaccard similarity of their term sets).
 */
export function mmr(hits: Hit[], k: number, lambda = 0.7): Hit[] {
  if (hits.length === 0) return []
  const max = hits[0]?.score ?? 1
  const pool = hits.map((h) => ({ hit: h, rel: h.score / max }))
  const selected: typeof pool = []
  while (selected.length < k && pool.length > 0) {
    let bestIndex = 0
    let bestValue = -Infinity
    pool.forEach((candidate, i) => {
      const redundancy = selected.length
        ? Math.max(...selected.map((s) => jaccard(candidate.hit.terms, s.hit.terms)))
        : 0
      const value = lambda * candidate.rel - (1 - lambda) * redundancy
      if (value > bestValue) {
        bestValue = value
        bestIndex = i
      }
    })
    selected.push(...pool.splice(bestIndex, 1))
  }
  return selected.map((s) => s.hit)
}
