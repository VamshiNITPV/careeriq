import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/services/apiClient'
import { ErrorCode } from '@/types/api'

interface LocationState {
  from?: { pathname: string }
}

export function LoginPage() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Where the user was headed before the guard redirected them here.
  const from = (location.state as LocationState | null)?.from?.pathname ?? '/dashboard'

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
