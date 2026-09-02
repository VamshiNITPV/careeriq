import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '@/providers/AuthProvider'
import { ApiError } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { clearTokens } from '@/services/tokenStorage'
import type { AuthResponse } from '@/types/auth'
import { LoginPage } from './LoginPage'

const authResponse: AuthResponse = {
  user: {
    id: '01a06172-a77b-7ef5-86aa-a6079081db56',
    email: 'priya@example.com',
    role: 'USER',
    auth_provider: 'LOCAL',
    is_active: true,
    email_verified_at: null,
    last_login_at: null,
    created_at: '2026-09-02T10:00:00Z',
  },
  tokens: {
    access_token: 'access',
    refresh_token: 'refresh',
    token_type: 'bearer',
    expires_in: 1800,
  },
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<h1>Dashboard</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    clearTokens()
    vi.restoreAllMocks()
  })

  it('renders the form with accessible labels', () => {
    renderLogin()

    // Queried by label, not by CSS class or test id: if this passes, a screen
    // reader user can also identify the field.
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('uses a password input so the value is masked', () => {
    renderLogin()
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('type', 'password')
  })

  it('submits credentials and navigates to the dashboard', async () => {
    const user = userEvent.setup()
    const login = vi.spyOn(authService, 'login').mockResolvedValue(authResponse)
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse-9')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith({
        email: 'priya@example.com',
        password: 'correct-horse-9',
      })
    })
    expect(await screen.findByRole('heading', { name: /dashboard/i })).toBeInTheDocument()
  })

  it('shows the server message when credentials are rejected', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'login').mockRejectedValue(
      new ApiError(401, 'AUTHENTICATION_FAILED', 'Invalid credentials.', {}, 'corr-9'),
    )
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong-password-1')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    // role=alert so the failure is announced, not just drawn.
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Invalid credentials.')
    expect(alert).toHaveTextContent('corr-9')
  })

  it('does not echo the password into the error message', async () => {
    const user = userEvent.setup()
    // Simulates a server that carelessly reflected the submitted input back.
    // The UI must not surface it: error text is the one place a password can
    // end up copied into a bug report or a screenshot.
    vi.spyOn(authService, 'login').mockRejectedValue(
      new ApiError(422, 'VALIDATION_ERROR', 'Invalid input.', {
        fields: [{ field: 'password', message: 'too weak', type: 'value_error' }],
      }),
    )
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.type(screen.getByLabelText(/password/i), 'my-secret-password-1')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).not.toContain('my-secret-password-1')
    // The field-level message still renders, so the user knows what to fix.
    expect(screen.getByText('too weak')).toBeInTheDocument()
  })

  it('disables the button while the request is in flight', async () => {
    const user = userEvent.setup()
    let resolve: ((value: AuthResponse) => void) | undefined
    vi.spyOn(authService, 'login').mockReturnValue(
      new Promise<AuthResponse>((r) => {
        resolve = r
      }),
    )
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), 'priya@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse-9')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    // Prevents a double-submit creating two sessions.
    const button = screen.getByRole('button', { name: /signing in/i })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')

    resolve?.(authResponse)
  })

  it('offers a route to registration', () => {
    renderLogin()
    expect(screen.getByRole('link', { name: /create one/i })).toHaveAttribute('href', '/register')
  })
})
