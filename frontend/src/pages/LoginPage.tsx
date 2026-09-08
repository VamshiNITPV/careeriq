import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import type { SignedOutReason } from '@/hooks/authContext'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/services/apiClient'
import { ErrorCode } from '@/types/api'

interface LocationState {
  from?: { pathname: string }
  reason?: SignedOutReason
}

export function LoginPage() {
  const { login, status, signedOutReason } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Where the user was headed before the guard redirected them here.
  const state = location.state as LocationState | null
  const from = state?.from?.pathname ?? '/dashboard'

  /*
    Why they are here, if it is worth saying. Route state first: its lifetime is
    exactly the one wanted — it survives the redirect and dies on reload, so the
    notice does not haunt the page. The context is the fallback for someone
    already sitting on /login, where there is no <Navigate> and so no state.

    No number in the message. The window is a constant on both sides, and
    "60 minutes" becomes a lie the day either changes.
  */
  const wasSignedOutForIdling = (state?.reason ?? signedOutReason) === 'idle'

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await login({ email, password })
      navigate(from, { replace: true })
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, ErrorCode.InternalError, 'Something went wrong. Please try again.'),
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
      <div className="mx-auto w-full max-w-sm">
        <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
          Sign in to CareerIQ
        </h1>

        {wasSignedOutForIdling && (
          <Alert tone="info" className="mt-6">
            You were signed out after a period of inactivity. Please sign in again.
          </Alert>
        )}

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-8 space-y-5" noValidate>
          {error && (
            <Alert tone="error" correlationId={error.correlationId}>
              {/* The backend returns the same message for a wrong password and
                  an unknown email, so this cannot be made more specific without
                  turning the form into an account-existence oracle. */}
              {error.message}
            </Alert>
          )}

          <Input
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={error?.fieldError('email')}
          />

          <Input
            label="Password"
            type="password"
            name="password"
            // "current-password" tells password managers to fill, not generate.
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error?.fieldError('password')}
          />

          <div className="text-right">
            <Link
              to="/forgot-password"
              className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
            >
              Forgot password?
            </Link>
          </div>

          <Button type="submit" isLoading={isSubmitting} className="w-full">
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          No account?{' '}
          <Link to="/register" className="font-semibold text-indigo-600 hover:text-indigo-500">
            Create one
          </Link>
        </p>
      </div>
    </div>
  )
}
