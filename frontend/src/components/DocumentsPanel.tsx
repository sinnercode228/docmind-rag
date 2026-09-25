import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import type { DocMindClient, DocumentInfo } from '../api/types'
import { IconFile, IconLink, IconTrash, IconUpload } from './icons'

interface Props {
  client: DocMindClient
  selected: Set<string>
  onToggle: (id: string) => void
  onClearSelection: () => void
}

const STATUS_STYLE: Record<string, string> = {
  ready: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  queued: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200',
  processing: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
  failed: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function DocumentsPanel({ client, selected, onToggle, onClearSelection }: Props) {
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [url, setUrl] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setDocuments(await client.listDocuments())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [client])

  useEffect(() => {
    let cancelled = false
    client
      .listDocuments()
      .then((docs) => !cancelled && setDocuments(docs))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [client])

  // Background ingestion: poll while anything is still queued/processing.
  const pending = documents.some((d) => d.status === 'queued' || d.status === 'processing')
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => void refresh(), 1500)
    return () => clearInterval(timer)
  }, [pending, refresh])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
      await refresh()
    }
  }

  const uploadFiles = (files: FileList | File[]) =>
    run(async () => {
      for (const file of Array.from(files)) await client.uploadFile(file)
    })

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files)
  }

  const onUrl = (e: FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    void run(async () => {
      await client.ingestUrl(url.trim())
      setUrl('')
    })
  }

  const accept = client.mode === 'demo' ? '.md,.markdown,.txt' : '.pdf,.docx,.md,.markdown,.txt,.html,.htm'
  const totalChunks = documents.reduce((n, d) => n + d.chunk_count, 0)

  return (
    <section aria-labelledby="docs-title" className="flex h-full flex-col">
      <div className="flex items-baseline justify-between">
        <h2 id="docs-title" className="text-sm font-semibold text-slate-900 dark:text-slate-100">Knowledge base</h2>
        <span className="text-xs text-slate-500">{documents.length} docs · {totalChunks} chunks</span>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`mt-3 rounded-xl border-2 border-dashed p-4 text-center transition ${
          dragging ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10' : 'border-slate-300 dark:border-slate-700'
        }`}
      >
        <IconUpload className="mx-auto text-slate-400" width={22} height={22} />
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          Drop files or{' '}
          <button type="button" onClick={() => inputRef.current?.click()} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300" disabled={busy}>
            browse
          </button>
        </p>
        <p className="mt-0.5 text-xs text-slate-400">
          {client.mode === 'demo' ? 'Demo: .md / .txt, indexed in your browser' : 'PDF, DOCX, Markdown, HTML, TXT'}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          data-testid="file-input"
          onChange={(e) => {
            if (e.target.files?.length) void uploadFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      <form onSubmit={onUrl} className="mt-2 flex gap-2">
        <label htmlFor="ingest-url" className="sr-only">Web page URL</label>
        <div className="relative flex-1">
          <IconLink className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" width={15} height={15} />
          <input
            id="ingest-url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://… (web page or PDF)"
            className="w-full rounded-lg border border-slate-300 bg-white py-1.5 pl-8 pr-2 text-sm outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-900"
          />
        </div>
        <button type="submit" disabled={busy || !url.trim()} className="rounded-lg bg-slate-900 px-3 text-sm font-medium text-white disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900">
          Add
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
          {error}
        </p>
      )}

      <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
        <span>{selected.size ? `${selected.size} selected: questions are scoped to them` : 'Tick documents to scope questions'}</span>
        {selected.size > 0 && (
          <button type="button" onClick={onClearSelection} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300">Clear</button>
        )}
      </div>
      <ul className="mt-2 -mx-1 flex-1 space-y-1 overflow-y-auto px-1">
        {documents.map((doc) => (
          <li key={doc.id} className="group flex items-start gap-2 rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800/60">
            <input
              type="checkbox"
              className="mt-1 accent-indigo-600"
              checked={selected.has(doc.id)}
              onChange={() => onToggle(doc.id)}
              disabled={doc.status !== 'ready'}
              aria-label={`Scope questions to ${doc.title}`}
            />
            <IconFile className="mt-0.5 shrink-0 text-slate-400" width={16} height={16} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100" title={doc.title}>{doc.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                <span className={`rounded px-1.5 py-px font-medium ${STATUS_STYLE[doc.status] ?? ''}`}>{doc.status}</span>
                <span>{doc.chunk_count} chunks</span>
                <span>· {formatSize(doc.size_bytes)}</span>
              </div>
              {doc.error && <div className="mt-0.5 text-[11px] text-rose-600">{doc.error}</div>}
            </div>
            <button
              type="button"
              onClick={() => void run(() => client.deleteDocument(doc.id))}
              className="rounded p-1 text-slate-400 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 group-hover:opacity-100 dark:hover:bg-rose-500/10"
              aria-label={`Delete ${doc.title}`}
            >
              <IconTrash width={15} height={15} />
            </button>
          </li>
        ))}
        {documents.length === 0 && <li className="p-2 text-sm text-slate-500">No documents yet.</li>}
      </ul>
    </section>
  )
}
