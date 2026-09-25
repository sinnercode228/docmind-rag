import { Fragment, type ReactNode } from 'react'

interface Props {
  text: string
  onCite?: (index: number) => void
  available?: number
}

const INLINE = /(\[\d{1,2}\])|(\*\*[^*]+\*\*)|(`[^`]+`)|(_[^_\n]+_)/g

/** Tiny, safe Markdown subset renderer: paragraphs, lists, bold/italic/code and [n] citations. */
export function AnswerText({ text, onCite, available = Infinity }: Props) {
  const blocks: ReactNode[] = []
  let list: string[] = []
  const flushList = (key: number) => {
    if (!list.length) return
    blocks.push(
      <ul key={`ul-${key}`} className="my-2 list-disc space-y-1.5 pl-5 marker:text-indigo-400">
        {list.map((item, i) => (
          <li key={i}>{renderInline(item, onCite, available)}</li>
        ))}
      </ul>,
    )
    list = []
  }
  text.split('\n').forEach((line, i) => {
    const item = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(line)
    if (item) {
      list.push(item[1] ?? '')
      return
    }
    flushList(i)
    if (line.trim()) {
      blocks.push(
        <p key={i} className="my-2 first:mt-0 last:mb-0">
          {renderInline(line, onCite, available)}
        </p>,
      )
    }
  })
  flushList(-1)
  return <div className="leading-relaxed">{blocks}</div>
}

function renderInline(text: string, onCite: Props['onCite'], available: number): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0
    if (start > last) out.push(text.slice(last, start))
    const token = match[0]
    if (match[1]) {
      const n = Number(token.slice(1, -1))
      out.push(
        n <= available ? (
          <button
            key={start}
            type="button"
            onClick={() => onCite?.(n)}
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-indigo-100 px-1 align-text-top text-[11px] font-semibold text-indigo-700 transition hover:bg-indigo-600 hover:text-white dark:bg-indigo-500/20 dark:text-indigo-200"
            aria-label={`Show source ${n}`}
          >
            {n}
          </button>
        ) : (
          token
        ),
      )
    } else if (match[2]) {
      out.push(<strong key={start}>{token.slice(2, -2)}</strong>)
    } else if (match[3]) {
      out.push(
        <code key={start} className="rounded bg-slate-100 px-1 py-0.5 text-[0.9em] dark:bg-slate-800">
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      out.push(
        <em key={start} className="text-slate-500 dark:text-slate-400">
          {token.slice(1, -1)}
        </em>,
      )
    }
    last = start + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out.map((node, i) => <Fragment key={i}>{node}</Fragment>)
}
