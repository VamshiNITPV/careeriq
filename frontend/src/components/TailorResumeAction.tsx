import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { optimizationService } from '@/services/optimizationService'
import { resumeService } from '@/services/resumeService'

/**
 * Start tailoring a resume to this job (US-6.1).
 *
 * The entry point to the review screen. Without it the whole feature is a route
 * nobody can reach, which is how a finished backend ships as nothing at all.
 *
 * **Uses the resume that last parsed successfully.** A version whose parse
 * failed has no usable text, so asking a model to tailor it would spend a call
 * to produce suggestions grounded in nothing.
 */
export function TailorResumeAction({ jobId }: { jobId: string }) {
  const navigate = useNavigate()
  const [versionId, setVersionId] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'none'>('loading')
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    resumeService.list().then(
      (resumes) => {
        // Primary first if there is one, then anything with a usable parse.
        const usable =
          resumes.find((r) => r.is_primary && r.current_version_id) ??
          resumes.find((r) => r.current_version_id)
        if (usable?.current_version_id) {
          setVersionId(usable.current_version_id)
          setState('ready')
        } else {
          setState('none')
        }
      },
      // A resume list that fails to load is not the same as having no resume,
      // but the offer is unusable either way and saying "upload one" to
      // somebody who already has one would be wrong. Hidden instead.
      () => setState('none'),
    )
  }, [])

  function start() {
    if (versionId === null) return
    setStarting(true)
    setError(null)
    optimizationService.analyze(versionId, jobId).then(
      (started) => navigate(`/optimize/${started.analysis_id}`),
      () => {
        setStarting(false)
        setError("We couldn't start this. Please try again.")
      },
    )
  }

  if (state === 'loading') return null

  return (
    <section className="border-t border-slate-200 pt-6">
      <h2 className="text-base font-semibold text-slate-900">Tailor your resume</h2>

      {state === 'none' ? (
        <>
          <p className="mt-1 text-sm text-slate-600">
            Upload a resume first — suggestions are rewrites of what yours already says.
          </p>
          <Link to="/resume" className="mt-3 inline-block text-sm font-medium text-indigo-600 underline">
            Upload a resume
          </Link>
        </>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-600">
            {/* Says the limit up front. Someone expecting "write me a better
                resume" should learn what this does before they wait for it. */}
            We&apos;ll suggest rewrites of your existing wording to match this job. Nothing is added
            that your resume doesn&apos;t already say, and you choose each change.
          </p>
          {error && (
            <div className="mt-3">
              <Alert tone="error">{error}</Alert>
            </div>
          )}
          <Button className="mt-4" disabled={starting} onClick={start}>
            {starting ? 'Starting…' : 'Suggest changes'}
          </Button>
        </>
      )}
    </section>
  )
}
