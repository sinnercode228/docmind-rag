export type Mode = 'demo' | 'api'

export interface AppConfig {
  mode: Mode
  apiUrl: string
  apiKey: string
}

const STORAGE_KEY = 'docmind.config'

function envMode(): Mode {
  return import.meta.env.VITE_DOCMIND_MODE === 'api' ? 'api' : 'demo'
}

export const defaultConfig: AppConfig = {
  mode: envMode(),
  apiUrl: (import.meta.env.VITE_DOCMIND_API_URL as string | undefined) ?? '',
  apiKey: (import.meta.env.VITE_DOCMIND_API_KEY as string | undefined) ?? '',
}

/** Build-time defaults, overridable at runtime from the settings dialog (saved per browser). */
export function loadConfig(): AppConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...defaultConfig, ...(JSON.parse(raw) as Partial<AppConfig>) }
  } catch {
    /* storage unavailable: fall back to defaults */
  }
  return defaultConfig
}

export function saveConfig(config: AppConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    /* ignore */
  }
}
