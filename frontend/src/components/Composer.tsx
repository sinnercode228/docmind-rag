import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { IconSend, IconStop } from './icons'

interface Props {
  streaming: boolean
  onSend: (text: string) => void
  onStop: () => void
  scopeLabel?: string | null
}

export function Composer({ streaming, onSend, onStop, scopeLabel }: Props) {
  const [text, setText] = useState('')
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (!text.trim() || streaming) return
    onSend(text)
    setText('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl">
      {scopeLabel && (
        <div className="mb-1.5 text-xs text-slate-500 dark:text-slate-400">Searching in: {scopeLabel}</div>
      )}
      <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-indigo-400 focus-within:ring-4 focus-within:ring-indigo-100 dark:border-slate-700 dark:bg-slate-900 dark:focus-within:ring-indigo-500/20">
        <label htmlFor="question" className="sr-only">Ask a question</label>
        <textarea
          id="question"
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about your documents… / Спросите о документах…"
          className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-slate-900 outline-none placeholder:text-slate-400 field-sizing-content dark:text-slate-100"
        />
        {streaming ? (
          <button type="button" onClick={onStop} className="grid h-10 w-10 place-items-center rounded-xl bg-slate-800 text-white hover:bg-slate-700" aria-label="Stop generating">
            <IconStop />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!text.trim()}
            className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-300 dark:disabled:bg-slate-700"
            aria-label="Send"
          >
            <IconSend />
          </button>
        )}
      </div>
      <p className="mt-1.5 text-center text-[11px] text-slate-400">Enter to send · Shift+Enter for a new line · answers cite their sources</p>
    </form>
  )
}
