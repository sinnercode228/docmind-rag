/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DOCMIND_MODE?: 'demo' | 'api'
  readonly VITE_DOCMIND_API_URL?: string
  readonly VITE_DOCMIND_API_KEY?: string
}
