import type { AppConfig } from '../config'
import { DemoClient } from '../demo/demoClient'
import { HttpClient } from './httpClient'
import type { DocMindClient } from './types'

export function createClient(config: AppConfig): DocMindClient {
  return config.mode === 'api' ? new HttpClient(config.apiUrl, config.apiKey) : new DemoClient()
}

export * from './types'
