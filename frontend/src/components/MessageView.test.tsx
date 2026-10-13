import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Citation } from '../api/types'
import type { ChatMessage } from '../state/history'
import { MessageView } from './MessageView'

function citation(index: number, chunk_id: string, snippet: string): Citation {
  return {
    index,
    document_id: 'doc_1',
    document_title: 'Employee Handbook',
    chunk_id,
    snippet,
    score: 0.5,
    highlight: null,
  }
}

const shared = citation(1, 'ch_shared', 'Each employee has a learning budget of 1,000 EUR per year.')

const first: ChatMessage = {
  id: 'msg_first',
  role: 'assistant',
  content: 'The learning budget is 1,000 EUR [1].',
  citations: [shared],
  cited: [1],
}

const second: ChatMessage = {
  id: 'msg_second',
  role: 'assistant',
  content: 'Conference travel is separate [2], and the budget is 1,000 EUR [1].',
  citations: [shared, citation(2, 'ch_travel', 'Conference travel does not count against the learning budget.')],
  cited: [1, 2],
}

describe('MessageView', () => {
  afterEach(() => vi.restoreAllMocks())

  it('scrolls to the card of its own answer when two answers retrieved the same chunk', async () => {
    const scrolled: Element[] = []
    vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
      scrolled.push(this)
    })
    render(
      <>
        <section aria-label="first answer">
          <MessageView message={first} />
        </section>
        <section aria-label="second answer">
          <MessageView message={second} />
        </section>
      </>,
    )
    const secondAnswer = screen.getByRole('region', { name: 'second answer' })

    await userEvent.setup().click(within(secondAnswer).getByRole('button', { name: 'Show source 1' }))

    expect(scrolled).toHaveLength(1)
    expect(secondAnswer).toContainElement(scrolled[0] as HTMLElement)
    expect(scrolled[0]).toHaveTextContent('learning budget of 1,000 EUR')
  })

  it('gives every citation card a unique id', () => {
    const { container } = render(
      <>
        <MessageView message={first} />
        <MessageView message={second} />
      </>,
    )
    const ids = [...container.querySelectorAll('[id^="cite-"]')].map((el) => el.id)
    expect(ids).toHaveLength(3)
    expect(new Set(ids).size).toBe(3)
  })
})
