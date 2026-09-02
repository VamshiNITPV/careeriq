import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ApiError } from '@/services/apiClient'
import { authService } from '@/services/authService'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await authService.forgotPassword(email)
      setSubmitted(true)
    } catch (caught) {
      // Only a malformed address or an unreachable server can land here — the
      // endpoint returns 200 whether or not the account exists.
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, 'INTERNAL_ERROR', 'Something went wrong. Please try again.'),
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
        <div className="mx-auto w-full max-w-sm">
          <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
            Check your email
          </h1>
          <Alert tone="success" className="mt-6">
            {/* Deliberately conditional. Confirming that a link was sent to this
                specific address would reveal that an account exists — the exact
                leak the endpoint is built to avoid. */}
            If an account exists for <strong>{email}</strong>, a reset link is on its way. The
            link expires in 30 minutes and can be used once.
          </Alert>
          <p className="mt-6 text-center text-sm text-slate-600">
            <Link to="/login" className="font-semibold text-indigo-600 hover:text-indigo-500">
              Back to sign in
            </Link>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
      <div className="mx-auto w-full max-w-sm">
        <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
          Reset your password
        </h1>
        <p className="mt-2 text-center text-sm text-slate-600">
          Enter your email and we&apos;ll send you a link to choose a new password.
        </p>

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-8 space-y-5" noValidate>
          {error && (
            <Alert tone="error" correlationId={error.correlationId}>
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

          <Button type="submit" isLoading={isSubmitting} className="w-full">
            {isSubmitting ? 'Sending…' : 'Send reset link'}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          Remembered it?{' '}
          <Link to="/login" className="font-semibold text-indigo-600 hover:text-indigo-500">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
