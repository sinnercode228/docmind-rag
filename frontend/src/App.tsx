import { useEffect, useMemo, useRef, useState } from 'react'
import { createClient, type BackendInfo } from './api'
import { DocumentsPanel } from './components/DocumentsPanel'
import { Composer } from './components/Composer'
import { MessageView } from './components/MessageView'
import { SettingsDialog } from './components/SettingsDialog'
import { IconBook, IconChat, IconMenu, IconPlus, IconSettings, IconTrash, IconX, Logo } from './components/icons'
import { loadConfig, saveConfig, type AppConfig } from './config'
import { useChat } from './state/useChat'

const SUGGESTIONS = [
  'How many vacation days do employees get?',
  'What are the password requirements?',
  'What is the daily meal allowance on business trips?',
  'Что делать при подозрении на фишинг?',
]

export default function App() {
  const [config, setConfig] = useState<AppConfig>(loadConfig)
  const [settingsOpen, setSettingsOpen] = useState(false)
  return (
    <>
      {/* Re-mount the workspace when the backend changes: fresh client, history and state. */}
      <Workspace key={JSON.stringify(config)} config={config} onOpenSettings={() => setSettingsOpen(true)} />
      <SettingsDialog
        open={settingsOpen}
        config={config}
        onClose={() => setSettingsOpen(false)}
        onSave={(next) => {
          saveConfig(next)
          setConfig(next)
          setSettingsOpen(false)
        }}
      />
    </>
  )
}

function Workspace({ config, onOpenSettings }: { config: AppConfig; onOpenSettings: () => void }) {
  const client = useMemo(() => createClient(config), [config])
  const chat = useChat(client)
  const [info, setInfo] = useState<BackendInfo | null>(null)
  const [infoError, setInfoError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    client
      .info()
      .then((i) => !cancelled && setInfo(i))
      .catch((err: unknown) => !cancelled && setInfoError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [client])

  // Deep link: `?q=question` asks it on load (handy for sharing demo questions).
  const askedFromUrl = useRef(false)
  const { send: chatSend } = chat
  useEffect(() => {
    if (askedFromUrl.current) return
    askedFromUrl.current = true
    const q = new URLSearchParams(window.location.search).get('q')
    if (q) void chatSend(q)
  }, [chatSend])

  const messages = chat.active?.messages ?? []
  const lastContent = messages.at(-1)?.content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, lastContent])

  const send = (text: string) => void chat.send(text, [...selected])
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const demo = config.mode === 'demo'

  return (
    <div className="flex h-dvh flex-col bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      {demo && (
        <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-900 dark:bg-amber-500/15 dark:text-amber-200">
          <strong>Demo mode</strong> · runs entirely in your browser on a fictional handbook: BM25 retrieval and quoted,
          templated answers (no LLM). <span className="hidden sm:inline">Демо-режим: без сервера и без LLM.</span>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {/* History sidebar */}
        <aside
          className={`${sidebarOpen ? 'fixed inset-y-0 left-0 z-30 flex shadow-2xl' : 'hidden'} w-72 shrink-0 flex-col border-r border-slate-200 bg-white p-3 lg:static lg:flex lg:shadow-none dark:border-slate-800 dark:bg-slate-900`}
        >
          <div className="flex items-center gap-2 px-1 py-1">
            <Logo className="h-8 w-8" />
            <div className="leading-tight">
              <div className="font-semibold">DocMind</div>
              <div className="text-[11px] text-slate-500">RAG document assistant</div>
            </div>
            <button type="button" className="ml-auto rounded p-1 lg:hidden" onClick={() => setSidebarOpen(false)} aria-label="Close menu">
              <IconX />
            </button>
          </div>
          <button
            type="button"
            onClick={() => {
              chat.select(null)
              setSidebarOpen(false)
            }}
            className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
          >
            <IconPlus width={16} height={16} /> New chat
          </button>
          <h2 className="mt-5 px-1 text-xs font-medium uppercase tracking-wide text-slate-400">History</h2>
          <ul className="mt-1 flex-1 space-y-0.5 overflow-y-auto">
            {chat.conversations.map((c) => (
              <li key={c.id} className="group relative">
                <button
                  type="button"
                  onClick={() => {
                    chat.select(c.id)
                    setSidebarOpen(false)
                  }}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 pr-8 text-left text-sm ${
                    chat.active?.id === c.id ? 'bg-slate-100 font-medium dark:bg-slate-800' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                  }`}
                >
                  <IconChat className="shrink-0 text-slate-400" width={15} height={15} />
                  <span className="truncate">{c.title}</span>
                </button>
                <button
                  type="button"
                  onClick={() => chat.remove(c.id)}
                  className="absolute right-1 top-1.5 rounded p-1 text-slate-400 opacity-0 hover:text-rose-600 focus:opacity-100 group-hover:opacity-100"
                  aria-label={`Delete conversation ${c.title}`}
                >
                  <IconTrash width={14} height={14} />
                </button>
              </li>
            ))}
            {chat.conversations.length === 0 && <li className="px-2 py-2 text-sm text-slate-400">No conversations yet.</li>}
          </ul>
          <div className="mt-3 rounded-xl border border-slate-200 p-3 text-xs text-slate-500 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${info ? 'bg-emerald-500' : infoError ? 'bg-rose-500' : 'bg-slate-300'}`} />
              <span className="font-medium text-slate-700 dark:text-slate-200">{demo ? 'Demo backend' : 'DocMind API'}</span>
            </div>
            {info && (
              <div className="mt-1">LLM: {info.llm} · retrieval: {info.embedder}</div>
            )}
            {infoError && <div className="mt-1 text-rose-600">{infoError}</div>}
            <button type="button" onClick={onOpenSettings} className="mt-2 inline-flex items-center gap-1 font-medium text-indigo-600 hover:underline dark:text-indigo-300">
              <IconSettings width={14} height={14} /> Settings
            </button>
          </div>
        </aside>

        {/* Chat */}
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b border-slate-200 bg-white/70 px-4 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
            <button type="button" className="rounded-lg p-1.5 hover:bg-slate-100 lg:hidden dark:hover:bg-slate-800" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
              <IconMenu />
            </button>
            <h1 className="truncate text-sm font-semibold">{chat.active?.title ?? 'New conversation'}</h1>
            <span className={`ml-1 hidden rounded-full px-2 py-0.5 text-[11px] font-medium sm:inline ${demo ? 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200' : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200'}`}>
              {demo ? 'demo' : 'api'}
            </span>
            <button
              type="button"
              onClick={() => setDocsOpen((v) => !v)}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm hover:bg-slate-100 xl:hidden dark:border-slate-700 dark:hover:bg-slate-800"
            >
              <IconBook width={16} height={16} /> Documents
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4">
            <div className="mx-auto max-w-3xl space-y-6 py-6">
              {messages.length === 0 ? (
                <div className="pt-6 text-center sm:pt-14">
                  <Logo className="mx-auto h-12 w-12" />
                  <h2 className="mt-4 text-2xl font-semibold tracking-tight">Ask your documents anything</h2>
                  <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500 dark:text-slate-400">
                    DocMind retrieves the most relevant passages, answers with numbered citations and shows the exact
                    sentence it relied on. {demo && 'The demo knowledge base is the handbook of Lumenfold Labs, a fictional company.'}
                  </p>
                  <div className="mx-auto mt-6 grid max-w-2xl gap-2 sm:grid-cols-2">
                    {SUGGESTIONS.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => send(q)}
                        className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 shadow-sm transition hover:border-indigo-300 hover:shadow dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m) => <MessageView key={m.id} message={m} />)
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t border-slate-200 bg-slate-50 px-4 pb-2 pt-3 dark:border-slate-800 dark:bg-slate-950">
            <Composer
              streaming={chat.streaming}
              onSend={send}
              onStop={chat.stop}
              scopeLabel={selected.size ? `${selected.size} selected document${selected.size > 1 ? 's' : ''}` : null}
            />
            <footer className="mx-auto mt-1 max-w-3xl text-center text-[11px] text-slate-400">
              Demo project / Демо-проект · DocMind and Lumenfold Labs are fictional brands ·{' '}
              <a className="hover:underline" href="https://github.com/sinnercode228/docmind-rag" target="_blank" rel="noreferrer">source on GitHub</a>
            </footer>
          </div>
        </main>

        {/* Documents panel */}
        <aside
          className={`${docsOpen ? 'fixed inset-y-0 right-0 z-30 flex shadow-2xl' : 'hidden'} w-[22rem] max-w-[92vw] shrink-0 flex-col border-l border-slate-200 bg-white p-4 xl:static xl:flex xl:shadow-none dark:border-slate-800 dark:bg-slate-900`}
        >
          <button type="button" className="mb-2 self-end rounded p-1 xl:hidden" onClick={() => setDocsOpen(false)} aria-label="Close documents">
            <IconX />
          </button>
          <DocumentsPanel client={client} selected={selected} onToggle={toggle} onClearSelection={() => setSelected(new Set())} />
        </aside>
      </div>
      {(sidebarOpen || docsOpen) && (
        <div className="fixed inset-0 z-20 bg-slate-900/30 lg:hidden" onClick={() => { setSidebarOpen(false); setDocsOpen(false) }} aria-hidden />
      )}

    </div>
  )
}
