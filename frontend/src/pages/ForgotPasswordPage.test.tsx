import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { ForgotPasswordPage } from './ForgotPasswordPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )
}

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('submits the address and shows confirmation', async () => {
    const user = userEvent.setup()
    const forgot = vi
      .spyOn(authService, 'forgotPassword')
      .mockResolvedValue({ message: 'ok' })
    renderPage()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))

    expect(forgot).toHaveBeenCalledWith('priya@example.com')
    expect(await screen.findByRole('heading', { name: /check your email/i })).toBeInTheDocument()
  })

  it('phrases the confirmation conditionally', async () => {
    // The wording must not assert that an email WAS sent to this address.
    // Doing so would confirm the account exists — exactly the leak the
    // endpoint's identical-response design prevents.
    const user = userEvent.setup()
    vi.spyOn(authService, 'forgotPassword').mockResolvedValue({ message: 'ok' })
    renderPage()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))

    const notice = await screen.findByRole('status')
    expect(notice).toHaveTextContent(/if an account exists/i)
  })

  it('shows the same confirmation for an address with no account', async () => {
    const user = userEvent.setup()
    // The server returns 200 either way; the UI must not diverge.
    vi.spyOn(authService, 'forgotPassword').mockResolvedValue({ message: 'ok' })
    renderPage()

    await user.type(screen.getByLabelText(/email/i), 'nobody@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))

    expect(await screen.findByRole('heading', { name: /check your email/i })).toBeInTheDocument()
  })

  it('surfaces a server error without claiming success', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'forgotPassword').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.'),
    )
    renderPage()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.click(screen.getByRole('button', { name: /send reset link/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server.')
    expect(screen.queryByRole('heading', { name: /check your email/i })).not.toBeInTheDocument()
  })

  it('links back to sign in', () => {
    renderPage()
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login')
  })
})
