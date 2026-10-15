import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AnswerText } from './AnswerText'

const citeButtons = () => screen.queryAllByRole('button', { name: /Show source/ })

describe('AnswerText', () => {
  it('turns only markers from 1 to the number of sources into buttons, like the server', () => {
    render(<AnswerText text="Zero [0], one [1], two [2], three [3]." available={2} />)
    expect(citeButtons().map((b) => b.textContent)).toEqual(['1', '2'])
    expect(screen.getByText(/Zero \[0\], one/)).toBeInTheDocument()
    expect(screen.getByText(/, three \[3\]\./)).toBeInTheDocument()
  })

  it('keeps [0] as text when the number of sources is unknown', () => {
    render(<AnswerText text="See [0] and [7]." />)
    expect(citeButtons().map((b) => b.textContent)).toEqual(['7'])
    expect(screen.getByText(/See \[0\] and/)).toBeInTheDocument()
  })

  it('turns a grouped marker into one button per source', () => {
    const onCite = vi.fn()
    render(<AnswerText text="Both sources [1, 2] agree." available={2} onCite={onCite} />)
    expect(citeButtons().map((b) => b.textContent)).toEqual(['1', '2'])
  })

  it('keeps out-of-range numbers in a group as text', () => {
    render(<AnswerText text="See [1, 5]." available={2} />)
    expect(citeButtons().map((b) => b.textContent)).toEqual(['1'])
    expect(screen.getByText(/5/)).toBeInTheDocument()
  })

  it('keeps a fully out-of-range group as literal text', () => {
    render(<AnswerText text="See [0, 9]." available={2} />)
    expect(citeButtons()).toHaveLength(0)
    expect(screen.getByText(/See \[0, 9\]\./)).toBeInTheDocument()
  })

  it('reports the clicked source number', async () => {
    const onCite = vi.fn()
    render(<AnswerText text="Budget is 1,000 EUR [2]." available={2} onCite={onCite} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Show source 2' }))
    expect(onCite).toHaveBeenCalledWith(2)
  })
})
