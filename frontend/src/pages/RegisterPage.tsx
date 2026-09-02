import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/services/apiClient'
import { ErrorCode } from '@/types/api'
import { MIN_PASSWORD_LENGTH } from '@/types/auth'

/**
 * Mirrors the server's password policy so the user gets feedback before a round
 * trip. The server rule is authoritative — this is convenience, not validation,
 * and the two must be kept in step (backend/app/schemas/auth.py).
 */
function localPasswordError(password: string): string | undefined {
  if (password.length === 0) return undefined
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  if (!/[a-zA-Z]/.test(password)) return 'Include at least one letter.'
  if (!/\d/.test(password)) return 'Include at least one digit.'
  return undefined
}

export function RegisterPage() {
  const { register, status } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (status === 'authenticated') return <Navigate to="/dashboard" replace />

  const passwordHint = localPasswordError(password)
  const canSubmit = email !== '' && password !== '' && passwordHint === undefined

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await register({
        email,
        password,
        // Omit rather than send an empty string: the field is optional and
        // "" would be stored as a real, blank name.
        ...(fullName.trim() !== '' ? { full_name: fullName.trim() } : {}),
      })
      navigate('/dashboard', { replace: true })
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
          Create your account
        </h1>

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-8 space-y-5" noValidate>
          {error && (
            <Alert tone="error" correlationId={error.correlationId}>
              {error.code === ErrorCode.RegistrationFailed
                ? // The server will not say whether the email is taken, to avoid
                  // confirming which addresses have accounts (US-1.1 AC3). This
                  // wording nudges the user without making that claim either.
                  'We could not create that account. If you already have one, try signing in instead.'
                : error.message}
            </Alert>
          )}

          <Input
            label="Full name"
            name="full_name"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            hint="Optional"
          />

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
            // "new-password" prompts password managers to offer a generated one.
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={passwordHint ?? error?.fieldError('password')}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters, with a letter and a digit.`}
          />

          <Button type="submit" isLoading={isSubmitting} disabled={!canSubmit} className="w-full">
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          Already registered?{' '}
          <Link to="/login" className="font-semibold text-indigo-600 hover:text-indigo-500">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
