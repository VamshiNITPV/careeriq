import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Spinner } from '@/components/ui/Spinner'
import { authService } from '@/services/authService'
import { resumeService, skillService } from '@/services/resumeService'
import { firstNameFor } from '@/utils/initials'
import { cn } from '@/utils/cn'

/**
 * Dashboard.
 *
 * Shows real counts where the data exists and an explicit "not yet" where it
 * does not. Plausible placeholder numbers are worse than blanks: a mock 87%
 * that later becomes a real 87% is indistinguishable from a working feature, so
 * nobody can tell what is actually finished — the same fabrication problem
 * ADR-012 guards against, applied to the UI.
 */

interface Stat {
  label: string
  value: string
  caption: string
  available: boolean
}

function StatCard({ stat }: { stat: Stat }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition-shadow hover:shadow-sm">
      <p className="text-sm font-medium text-slate-600">{stat.label}</p>
      <p
        className={cn(
          'mt-2 text-3xl font-bold tabular-nums',
          stat.available ? 'text-slate-900' : 'text-slate-300',
        )}
      >
        {stat.value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{stat.caption}</p>
    </div>
  )
}

function VerifyEmailNotice() {
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  async function resend() {
    setState('sending')
    try {
      await authService.resendVerification()
      setState('sent')
    } catch {
      setState('failed')
    }
  }

  return (
    // Deliberately quiet. Verification confirms an address; it gates nothing
    // (ADR-017), so a full-width warning block overstates it and becomes the
    // loudest thing on the page. A dismissible one-liner says the same thing
    // without shouting.
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm">
      <span className="text-slate-600">
        {state === 'sent'
          ? 'Confirmation sent — check your inbox.'
          : state === 'failed'
            ? 'Could not send that just now.'
            : 'Your email address is not confirmed yet.'}
      </span>
      {state !== 'sent' && (
        <button
          type="button"
          onClick={() => void resend()}
          disabled={state === 'sending'}
          className="font-medium text-indigo-600 underline-offset-2 hover:underline disabled:opacity-60"
        >
          {state === 'sending' ? 'Sending…' : 'Resend'}
        </button>
      )}
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="ml-auto rounded px-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
      >
        ×
      </button>
    </div>
  )
}

function NextStep({ hasResume, skillCount }: { hasResume: boolean; skillCount: number }) {
  const [title, body, cta, href]: [string, string, string, string] = hasResume
    ? [
        'Your profile is building',
        `${skillCount} skills are on your profile. Review them, add anything the parser missed, or upload a newer resume.`,
        'Review skills',
        '/resume',
      ]
    : [
        'Start with your resume',
        'Upload a PDF or DOCX and CareerIQ will pull out your skills automatically. It takes a few seconds.',
        'Upload resume',
        '/resume',
      ]

  return (
    <section className="overflow-hidden rounded-xl bg-gradient-to-br from-indigo-600 to-indigo-700 text-white">
      <div className="flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
        <div className="max-w-xl">
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-indigo-100">{body}</p>
        </div>
        <Link
          to={href}
          className="inline-flex shrink-0 items-center justify-center rounded-md bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 shadow-sm transition-colors hover:bg-indigo-50"
        >
          {cta}
        </Link>
      </div>
    </section>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

const ROADMAP = [
  { phase: 'Resume intelligence', status: 'done' },
  { phase: 'Job matching & ranking', status: 'next' },
  { phase: 'Skill gaps & learning paths', status: 'later' },
  { phase: 'Application tracking', status: 'later' },
  { phase: 'AI mock interviews', status: 'later' },
] as const

export function DashboardPage() {
  const { user, profile } = useAuth()
  const [resumeCount, setResumeCount] = useState(0)
  const [skillCount, setSkillCount] = useState(0)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    // Tolerant of failure: a dashboard that renders nothing because one count
    // could not be fetched is worse than one showing zeros.
    const [resumes, skills] = await Promise.all([
      resumeService.list().catch(() => []),
      skillService.mySkills().catch(() => []),
    ])
    setResumeCount(resumes.length)
    setSkillCount(skills.length)
  }, [])

  useEffect(() => {
    void load().finally(() => setLoaded(true))
  }, [load])

  const stats: Stat[] = [
    {
      label: 'Resumes',
      value: String(resumeCount),
      caption: resumeCount === 0 ? 'None uploaded yet' : 'Stored and parsed',
      available: true,
    },
    {
      label: 'Skills',
      value: String(skillCount),
      caption: skillCount === 0 ? 'Upload a resume to populate' : 'On your profile',
      available: true,
    },
    { label: 'Job matches', value: '—', caption: 'Arrives with job matching', available: false },
    {
      label: 'Applications',
      value: '—',
      caption: 'Arrives with application tracking',
      available: false,
    },
  ]

  // Prefers the profile name, so editing it on /profile changes the greeting
  // here immediately — both read the same context value.
  const firstName = firstNameFor(profile?.full_name, user?.email ?? '')

  if (!loaded) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="size-8 text-indigo-600" label="Loading your dashboard" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Welcome back, {firstName}
        </h1>
        <p className="mt-1 text-sm text-slate-600">Here is where your profile stands.</p>
      </div>

      {user !== null && user.email_verified_at === null && <VerifyEmailNotice />}

      <NextStep hasResume={resumeCount > 0} skillCount={skillCount} />

      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">
          Overview
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <StatCard key={stat.label} stat={stat} />
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="What works today">
          <ul className="space-y-2.5 text-sm text-slate-600">
            {[
              'Upload a PDF or DOCX and get your skills extracted',
              'Skills suggested from your experience, with the evidence quoted',
              'Correct or add anything by hand — corrections are never overwritten',
              'Secure sign-in with rotating tokens and password recovery',
            ].map((item) => (
              <li key={item} className="flex gap-2.5">
                <span className="mt-0.5 text-emerald-600" aria-hidden="true">
                  ✓
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Coming next">
          <ol className="space-y-3">
            {ROADMAP.map((item) => (
              <li key={item.phase} className="flex items-center gap-3 text-sm">
                <span
                  className={cn(
                    'inline-block size-2 shrink-0 rounded-full',
                    item.status === 'done'
                      ? 'bg-emerald-500'
                      : item.status === 'next'
                        ? 'bg-indigo-500'
                        : 'bg-slate-300',
                  )}
                  aria-hidden="true"
                />
                <span
                  className={cn(
                    item.status === 'later' ? 'text-slate-400' : 'text-slate-700',
                    item.status === 'next' && 'font-medium',
                  )}
                >
                  {item.phase}
                </span>
                {item.status === 'done' && (
                  <span className="ml-auto text-xs text-emerald-600">Ready</span>
                )}
                {item.status === 'next' && (
                  <span className="ml-auto text-xs text-indigo-600">In progress</span>
                )}
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </div>
  )
}
