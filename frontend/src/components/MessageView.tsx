import { useState } from 'react'
import type { ChatMessage } from '../state/history'
import { AnswerText } from './AnswerText'
import { CitationCard } from './CitationCard'

export function MessageView({ message }: { message: ChatMessage }) {
  const [activeCite, setActiveCite] = useState<number | null>(null)
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-white shadow-sm">
          {message.content}
        </div>
      </div>
    )
  }

  const citations = message.citations ?? []
  const cited = new Set(message.cited ?? [])
  const showCitation = (n: number) => {
    setActiveCite(n)
    const target = citations.find((c) => c.index === n)
    if (target) document.getElementById(`cite-${target.chunk_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  return (
    <div className="flex gap-3">
      <div className="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-900 text-xs font-bold text-white dark:bg-slate-100 dark:text-slate-900">
        D
      </div>
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white px-4 py-3 text-slate-800 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100">
          {message.content ? (
            <AnswerText text={message.content} onCite={showCitation} available={citations.length} />
          ) : message.streaming ? (
            <span className="inline-flex items-center gap-2 text-sm text-slate-500">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-500 [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-500 [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-500" />
              </span>
              {citations.length ? `Reading ${citations.length} sources…` : 'Searching the knowledge base…'}
            </span>
          ) : null}
          {message.streaming && message.content && (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-indigo-500 align-middle" />
          )}
          {message.error && (
            <p role="alert" className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
              {message.error}
            </p>
          )}
        </div>
        {citations.length > 0 && (
          <details className="group mt-2" open>
            <summary className="cursor-pointer select-none list-none text-xs font-medium uppercase tracking-wide text-slate-500 hover:text-slate-700 dark:text-slate-400">
              <span className="inline-block transition group-open:rotate-90">›</span> Sources ({citations.length})
              {message.model && <span className="ml-2 normal-case tracking-normal text-slate-400">· {message.model}</span>}
            </summary>
            <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
              {citations.map((c) => (
                <CitationCard key={c.chunk_id} citation={c} active={activeCite === c.index} cited={cited.has(c.index)} />
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  )
}
