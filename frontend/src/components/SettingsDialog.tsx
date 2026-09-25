import { useEffect, useRef, useState } from 'react'
import type { AppConfig } from '../config'

interface Props {
  open: boolean
  config: AppConfig
  onClose: () => void
  onSave: (config: AppConfig) => void
}

export function SettingsDialog({ open, config, onClose, onSave }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [draft, setDraft] = useState(config)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      setDraft(config)
      dialog.showModal?.()
    } else if (!open && dialog.open) dialog.close?.()
  }, [open, config])

  const field = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-900'
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white p-0 text-slate-800 shadow-2xl backdrop:bg-slate-900/40 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"
    >
      <form
        method="dialog"
        onSubmit={() => onSave(draft)}
        className="space-y-4 p-5"
      >
        <h2 className="text-base font-semibold">Connection settings</h2>
        <fieldset className="grid grid-cols-2 gap-2">
          <legend className="mb-1 text-sm font-medium">Backend</legend>
          {(['demo', 'api'] as const).map((mode) => (
            <label
              key={mode}
              className={`cursor-pointer rounded-xl border p-3 text-sm ${
                draft.mode === mode ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10' : 'border-slate-200 dark:border-slate-700'
              }`}
            >
              <input type="radio" name="mode" value={mode} checked={draft.mode === mode} onChange={() => setDraft({ ...draft, mode })} className="sr-only" />
              <span className="font-medium">{mode === 'demo' ? 'Demo (in-browser)' : 'DocMind API'}</span>
              <span className="mt-0.5 block text-xs text-slate-500">
                {mode === 'demo' ? 'Bundled fictional handbook, BM25, no server' : 'FastAPI backend, real LLM + vector store'}
              </span>
            </label>
          ))}
        </fieldset>
        {draft.mode === 'api' && (
          <>
            <label className="block text-sm font-medium">
              API URL
              <input className={field} value={draft.apiUrl} placeholder="http://localhost:8000 (empty = same origin)" onChange={(e) => setDraft({ ...draft, apiUrl: e.target.value })} />
            </label>
            <label className="block text-sm font-medium">
              API key
              <input className={field} type="password" autoComplete="off" value={draft.apiKey} placeholder="dm_…" onChange={(e) => setDraft({ ...draft, apiKey: e.target.value })} />
              <span className="mt-1 block text-xs font-normal text-slate-500">Stored only in this browser's localStorage.</span>
            </label>
          </>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">Cancel</button>
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">Save</button>
        </div>
      </form>
    </dialog>
  )
}
