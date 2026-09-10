import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { AuthProvider } from '@/providers/AuthProvider'
import { AddJobPage } from '@/pages/AddJobPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage'
import { JobDetailPage } from '@/pages/JobDetailPage'
import { JobsPage } from '@/pages/JobsPage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { RegisterPage } from '@/pages/RegisterPage'
import { ResetPasswordPage } from '@/pages/ResetPasswordPage'
import { ResumeDetailPage } from '@/pages/ResumeDetailPage'
import { ResumePage } from '@/pages/ResumePage'
import { SavedJobsPage } from '@/pages/SavedJobsPage'
import { VerifyEmailPage } from '@/pages/VerifyEmailPage'
import { ApiError } from '@/services/apiClient'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // The default refetch-on-focus makes every tab switch fire requests,
      // which is noise during development and a real cost against rate-limited
      // AI endpoints later (NFR-8).
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry a client error: a 401, 403, 404 or 422 will fail
        // identically every time, and retrying a 429 makes the problem worse.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 2
      },
    },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {/* AuthProvider sits inside the router so it can use navigation, and
            outside the routes so session state survives navigation. */}
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            {/* Public: these are reached from a link in an email, often on a
                different device where no session exists. */}
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/verify-email" element={<VerifyEmailPage />} />

            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/resume" element={<ResumePage />} />
                <Route path="/resume/:resumeId" element={<ResumeDetailPage />} />
                {/* /jobs/new before /jobs/:jobId — otherwise the parameter
                    route matches "new" and the detail page looks up a job
                    whose id is the word new. */}
                {/* Match ranking is a sort mode on /jobs, not a page of its
                    own. Redirected rather than deleted so a bookmark or a
                    shared link still lands on the ranking it named. */}
                <Route
                  path="/recommendations"
                  element={<Navigate to="/jobs?sort=match" replace />}
                />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/jobs/new" element={<AddJobPage />} />
                <Route path="/jobs/:jobId" element={<JobDetailPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                {/* Top level, not /jobs/saved: a path under /jobs would
                    have to be declared before /jobs/:jobId or the
                    parameter route swallows it, and relying on
                    declaration order for correctness is the trap the
                    comment above already describes. */}
                <Route path="/saved-jobs" element={<SavedJobsPage />} />
              </Route>
            </Route>

            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
