import { useState } from 'react'
import type { Citation } from '../api/types'

interface Props {
  citation: Citation
  active?: boolean
  cited?: boolean
}

function toSpan(highlight: Citation['highlight']): [number, number] {
  const [start = 0, end = 0] = highlight ?? []
  return [start, end]
}

export function HighlightedSnippet({ text, highlight }: { text: string; highlight?: Citation['highlight'] }) {
  const [start, end] = toSpan(highlight)
  if (!(end > start)) return <>{text}</>
  return (
    <>
      {text.slice(0, start)}
      <mark className="rounded bg-amber-200/80 px-0.5 text-slate-900 dark:bg-amber-400/30 dark:text-amber-50">
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </>
  )
}

/** A window of the passage centred on the highlighted sentence. */
function Excerpt({ text, highlight }: { text: string; highlight?: Citation['highlight'] }) {
  const [hs, he] = toSpan(highlight)
  let from = he > hs ? Math.max(0, hs - 90) : 0
  if (from > 0) {
    // Snap to a word boundary and skip tiny leftovers of the previous paragraph.
    const space = text.slice(from, hs).search(/\s/)
    from = space === -1 ? hs : from + space + 1
    const para = text.lastIndexOf('\n', hs)
    if (para >= from) from = para + 1
  }
  const to = Math.min(text.length, he > hs ? Math.max(he + 90, from + 240) : 240)
  const shifted: [number, number] | null = he > hs ? [hs - from, he - from] : null
  return (
    <>
      {from > 0 && '… '}
      <HighlightedSnippet text={text.slice(from, to)} highlight={shifted} />
      {to < text.length && ' …'}
    </>
  )
}

export function CitationCard({ citation, active = false, cited = false }: Props) {
  const [expanded, setExpanded] = useState(false)
  const long = citation.snippet.length > 260
  return (
    <div
      id={`cite-${citation.chunk_id}`}
      className={`min-w-0 rounded-xl border p-3 text-sm transition ${
        active
          ? 'border-indigo-400 bg-indigo-50 ring-2 ring-indigo-200 dark:border-indigo-400 dark:bg-indigo-500/10 dark:ring-indigo-500/30'
          : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'
      }`}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className={`inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 text-[11px] font-semibold ${
            cited ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-200'
          }`}
        >
          {citation.index}
        </span>
        <span className="truncate font-medium text-slate-800 dark:text-slate-100" title={citation.document_title}>
          {citation.document_title}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-slate-400" title="Relevance score">
          {citation.score.toFixed(2)}
        </span>
      </div>
      {(citation.heading || citation.page) && (
        <div className="mb-1 text-xs text-slate-500 dark:text-slate-400">
          {[citation.page ? `p. ${citation.page}` : null, citation.heading].filter(Boolean).join(' · ')}
        </div>
      )}
      <p className="whitespace-pre-line text-slate-600 dark:text-slate-300">
        {long && !expanded ? (
          <Excerpt text={citation.snippet} highlight={citation.highlight} />
        ) : (
          <HighlightedSnippet text={citation.snippet} highlight={citation.highlight} />
        )}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-300"
        >
          {expanded ? 'Show less' : 'Show full passage'}
        </button>
      )}
    </div>
  )
}
