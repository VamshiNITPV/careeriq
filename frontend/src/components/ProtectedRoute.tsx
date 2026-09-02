import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Spinner } from './ui/Spinner'

/**
 * Gate for authenticated routes.
 *
 * This is a UX control, not a security boundary. Anyone can edit the bundle and
 * render whatever they like; what actually protects data is the API rejecting
 * unauthenticated requests (ADR-014). Treating a client-side guard as security
 * is how "hidden" admin panels leak.
 */
export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    // Distinct from unauthenticated. On a hard refresh we hold a refresh token
    // but no user yet; redirecting here would bounce a signed-in user to the
    // login screen every time they reload.
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="size-8 text-indigo-600" label="Checking your session" />
      </div>
    )
  }

  if (status === 'unauthenticated') {
    // `state.from` lets the login page send the user back where they were
    // headed. `replace` keeps the guarded URL out of history, so Back after
    // signing in does not land on a redirect loop.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
