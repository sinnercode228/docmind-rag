export interface TextChunk {
  text: string
  heading: string | null
}

/**
 * Minimal Markdown-aware chunker for files added in demo mode: split on headings, then pack
 * paragraphs into chunks of at most `maxChars` characters.
 */
export function chunkMarkdown(source: string, maxChars = 700): { title: string | null; chunks: TextChunk[] } {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  let title: string | null = null
  let heading: string | null = null
  let paragraphs: string[] = []
  let current: string[] = []
  const chunks: TextChunk[] = []

  const flushParagraph = () => {
    const p = current.join('\n').trim()
    if (p) paragraphs.push(p)
    current = []
  }
  const flushSection = () => {
    flushParagraph()
    let buffer = ''
    for (const p of paragraphs) {
      if (buffer && buffer.length + p.length + 2 > maxChars) {
        chunks.push({ text: buffer, heading })
        buffer = ''
      }
      if (p.length > maxChars) {
        for (let i = 0; i < p.length; i += maxChars) chunks.push({ text: p.slice(i, i + maxChars), heading })
        continue
      }
      buffer = buffer ? `${buffer}\n\n${p}` : p
    }
    if (buffer) chunks.push({ text: buffer, heading })
    paragraphs = []
  }

  for (const line of lines) {
    const match = /^(#{1,6})\s+(.*)$/.exec(line)
    if (match) {
      flushSection()
      const text = (match[2] ?? '').trim()
      if (match[1] === '#' && title === null) title = text
      heading = text
    } else if (!line.trim()) {
      flushParagraph()
    } else {
      current.push(line)
    }
  }
  flushSection()
  return { title, chunks }
}
