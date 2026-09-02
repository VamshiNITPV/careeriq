import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ApiError } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { MIN_PASSWORD_LENGTH } from '@/types/auth'

function localPasswordError(password: string): string | undefined {
  if (password.length === 0) return undefined
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  if (!/[a-zA-Z]/.test(password)) return 'Include at least one letter.'
  if (!/\d/.test(password)) return 'Include at least one digit.'
  return undefined
}

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  // A link opened without a token is a truncated or mangled email link. Say so,
  // rather than showing a form that cannot possibly succeed.
  if (token === null) {
    return (
      <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
        <div className="mx-auto w-full max-w-sm">
          <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
            Link incomplete
          </h1>
          <Alert tone="error" className="mt-6">
            This reset link is missing its token. Email clients sometimes split long links —
            try copying the whole link from the email, or request a new one.
          </Alert>
          <p className="mt-6 text-center text-sm">
            <Link
              to="/forgot-password"
              className="font-semibold text-indigo-600 hover:text-indigo-500"
            >
              Request a new link
            </Link>
          </p>
        </div>
      </div>
    )
  }

  const passwordHint = localPasswordError(password)
  const mismatch = confirm.length > 0 && confirm !== password
  const canSubmit = password !== '' && confirm === password && passwordHint === undefined

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      await authService.resetPassword(token as string, password)
      setDone(true)
      // Send them to sign in with the new password. The server revoked every
      // session, so there is nothing to resume.
      setTimeout(() => void navigate('/login', { replace: true }), 2500)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, 'INTERNAL_ERROR', 'Something went wrong. Please try again.'),
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  if (done) {
    return (
      <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
        <div className="mx-auto w-full max-w-sm">
          <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
            Password updated
          </h1>
          <Alert tone="success" className="mt-6">
            You have been signed out of all devices. Redirecting you to sign in…
          </Alert>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
      <div className="mx-auto w-full max-w-sm">
        <h1 className="text-center text-2xl font-bold tracking-tight text-slate-900">
          Choose a new password
        </h1>

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-8 space-y-5" noValidate>
          {error && (
            <Alert tone="error" correlationId={error.correlationId}>
              {error.status === 401 ? (
                <>
                  This link has expired or was already used.{' '}
                  <Link to="/forgot-password" className="font-semibold underline">
                    Request a new one
                  </Link>
                  .
                </>
              ) : (
                error.message
              )}
            </Alert>
          )}

          <Input
            label="New password"
            type="password"
            name="new_password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={passwordHint ?? error?.fieldError('new_password')}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters, with a letter and a digit.`}
          />

          <Input
            label="Confirm new password"
            type="password"
            name="confirm_password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={mismatch ? 'Passwords do not match.' : undefined}
          />

          <Button type="submit" isLoading={isSubmitting} disabled={!canSubmit} className="w-full">
            {isSubmitting ? 'Updating…' : 'Update password'}
          </Button>
        </form>
      </div>
    </div>
  )
}
