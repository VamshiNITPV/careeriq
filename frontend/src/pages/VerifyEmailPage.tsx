import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Spinner } from '@/components/ui/Spinner'
import { useAuth } from '@/hooks/useAuth'
import { authService } from '@/services/authService'

type State = 'verifying' | 'verified' | 'failed' | 'missing-token'

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const { user, setUser } = useAuth()
  const token = searchParams.get('token')
  const [state, setState] = useState<State>(token === null ? 'missing-token' : 'verifying')

  // StrictMode runs effects twice in development. Verification tokens are
  // single-use, so the second call would consume nothing and report failure on
  // a link that actually worked. This guard makes the effect run once.
  const attempted = useRef(false)

  useEffect(() => {
    if (token === null || attempted.current) return
    attempted.current = true

    authService
      .verifyEmail(token)
      .then((updated) => {
        // Apply the fresh user, so the "confirm your email" notice disappears
        // immediately instead of surviving until a hard reload.
        //
        // The id guard is not optional: this route is public and the request
        // is unauthenticated, so a verification link opened on a shared device
        // may belong to somebody other than whoever is signed in here.
        // Applying it unconditionally would swap the signed-in identity.
        if (user !== null && user.id === updated.id) setUser(updated)
        setState('verified')
      })
      .catch(() => setState('failed'))
  }, [token, user, setUser])

  return (
    <div className="flex min-h-screen flex-col justify-center bg-slate-50 px-6 py-12">
      <div className="mx-auto w-full max-w-sm text-center">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Email confirmation</h1>

        <div className="mt-6">
          {state === 'verifying' && (
            <div className="flex flex-col items-center gap-3">
              <Spinner className="size-8 text-indigo-600" label="Confirming your email" />
              <p className="text-sm text-slate-600">Confirming your email…</p>
            </div>
          )}

          {state === 'verified' && (
            <Alert tone="success">Your email address is confirmed. Thank you.</Alert>
          )}

          {state === 'failed' && (
            <Alert tone="error">
              This link is invalid or has expired. Sign in and request a new confirmation email
              from your account.
            </Alert>
          )}

          {state === 'missing-token' && (
            <Alert tone="error">
              This link is missing its token. Email clients sometimes split long links — try
              copying the whole link from the email.
            </Alert>
          )}
        </div>

        <p className="mt-6 text-sm">
          <Link to="/login" className="font-semibold text-indigo-600 hover:text-indigo-500">
            Continue to sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
