/**
 * Language-light text utilities (English + Russian), a TypeScript port of
 * `backend/src/docmind/text.py` so demo retrieval behaves like the server's.
 */

const TOKEN = /[\p{L}\p{N}]+/gu
const SENTENCE = /[^\n]+?(?:[.!?]+(?=\s)|$)/gmu
const CYRILLIC = /[а-яё]/i

export const STOPWORDS = new Set(
  `a an the and or but if then else of to in on at by for with about from into over after
  before is are was were be been being do does did have has had i you he she it we they me
  my your our their this that these those what which who whom how when where why can could
  should would will shall may might must not no yes as so than too very just also there
  here any all some each more most other such only own same s t don doesn и в во не что он
  на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от
  меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас
  нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы
  тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того
  потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда
  зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти
  нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда
  лучше чуть том нельзя такой им более всегда конечно всю между это как`.split(/\s+/),
)

const RU_SUFFIXES = `иями ями ами ией ого ему ому ыми ими ешь ишь ете ите ются ится ется ать ять ить еть
  уть ала ила ыла ела али или ыли ели ует уют ова ева ам ям ах ях ой ей ий ый ая яя ое
  ее ую юю ом ем ов ев ы и а я о е у ю ь`
  .split(/\s+/)
  .sort((a, b) => b.length - a.length)

const EN_SUFFIXES = [
  'ational', 'fulness', 'ingly', 'ation', 'ments', 'ment', 'ings', 'ing', 'edly',
  'ies', 'ied', 'ed', 'es', 'ly', 's',
]

export function isCyrillic(text: string): boolean {
  return CYRILLIC.test(text)
}

export function stem(token: string): string {
  const t = token.toLowerCase().replaceAll('ё', 'е')
  const suffixes = isCyrillic(t) ? RU_SUFFIXES : EN_SUFFIXES
  for (const suffix of suffixes) {
    if (t.endsWith(suffix) && t.length - suffix.length >= 3) return t.slice(0, -suffix.length)
  }
  return t
}

export function tokenize(text: string): string[] {
  return (text.match(TOKEN) ?? []).map((t) => t.toLowerCase().replaceAll('ё', 'е'))
}

/** Stemmed tokens without stopwords or single characters. */
export function contentTerms(text: string): string[] {
  return tokenize(text)
    .filter((t) => !STOPWORDS.has(t) && t.length > 1)
    .map(stem)
}

/** `[start, end)` spans of sentences/lines in `text`, whitespace-trimmed. */
export function sentences(text: string): Array<[number, number]> {
  const spans: Array<[number, number]> = []
  for (const match of text.matchAll(SENTENCE)) {
    let start = match.index ?? 0
    let end = start + match[0].length
    while (start < end && /\s/.test(text[start] ?? '')) start++
    while (end > start && /\s/.test(text[end - 1] ?? '')) end--
    if (end - start > 1) spans.push([start, end])
  }
  return spans
}

/** Span of the sentence sharing the most stemmed terms with `query` (facts get a bonus). */
export function bestSentence(text: string, query: string): [number, number] | null {
  const queryTerms = new Set(contentTerms(query))
  if (queryTerms.size === 0) return null
  let best: { score: number; span: [number, number] } | null = null
  for (const [start, end] of sentences(text)) {
    if (text[start] === '#') continue
    const sentence = text.slice(start, end)
    const terms = contentTerms(sentence)
    if (terms.length === 0) continue
    const overlap = new Set(terms.filter((t) => queryTerms.has(t))).size
    if (overlap === 0) continue
    const hasFact = /\d/.test(sentence)
    const score = overlap + overlap / Math.sqrt(terms.length) + (hasFact ? 0.5 : 0)
    if (!best || score > best.score) best = { score, span: [start, end] }
  }
  return best?.span ?? null
}
