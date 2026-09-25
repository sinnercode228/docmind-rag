import { describe, expect, it } from 'vitest'
import { bestSentence, contentTerms, isCyrillic, sentences, stem } from './text'

describe('text utils', () => {
  it('stems English and Russian inflections to shared roots', () => {
    expect(stem('requests')).toBe(stem('request'))
    expect(stem('replacing')).toBe(stem('replaced'))
    expect(stem('отпуска')).toBe(stem('отпуск'))
  })

  it('drops stopwords and single characters', () => {
    expect(contentTerms('What is the vacation policy?')).toEqual(['vacation', 'policy'].map(stem))
    expect(contentTerms('Как оформить отпуск?')).toEqual(['оформить', 'отпуск'].map(stem))
  })

  it('detects Cyrillic', () => {
    expect(isCyrillic('Привет')).toBe(true)
    expect(isCyrillic('hello')).toBe(false)
  })

  it('splits sentences with trimmed spans', () => {
    const text = 'First one. Second one!\nThird line'
    expect(sentences(text).map(([s, e]) => text.slice(s, e))).toEqual(['First one.', 'Second one!', 'Third line'])
  })

  it('prefers the factual sentence as the highlight', () => {
    const text =
      'Each employee has a learning budget of 1,000 EUR per year. Conference travel does not count against the learning budget.'
    const span = bestSentence(text, 'What is the learning budget?')
    expect(span).not.toBeNull()
    expect(text.slice(...span!)).toContain('1,000 EUR')
    expect(bestSentence(text, 'the a')).toBeNull()
  })
})
