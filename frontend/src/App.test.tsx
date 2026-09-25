import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'

describe('App (demo mode)', () => {
  beforeEach(() => localStorage.clear())

  it('answers a question with citations and highlighted snippets, then keeps history', async () => {
    const user = userEvent.setup()
    render(<App />)
    expect(screen.getByText(/Demo project \/ Демо-проект/)).toBeInTheDocument()
    expect(await screen.findByText('Lumenfold Labs Employee Handbook')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Ask a question'), 'What is the learning budget?{Enter}')

    await waitFor(() => expect(screen.getByText(/Sources \(\d\)/)).toBeInTheDocument())
    await waitFor(() => expect(screen.queryByLabelText('Stop generating')).not.toBeInTheDocument(), {
      timeout: 5000,
    })
    expect(screen.getAllByText(/1,000 EUR/).length).toBeGreaterThan(0)
    expect(document.querySelectorAll('mark').length).toBeGreaterThan(0)

    const cite = screen.getAllByRole('button', { name: /Show source 1/ })[0]!
    await user.click(cite)

    const history = screen.getByRole('heading', { name: 'History' }).parentElement!
    expect(within(history).getAllByText('What is the learning budget?').length).toBeGreaterThan(0)
  })
})
