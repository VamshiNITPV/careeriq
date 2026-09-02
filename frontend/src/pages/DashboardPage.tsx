import { useAuth } from '@/hooks/useAuth'
import { Alert } from '@/components/ui/Alert'

/**
 * Dashboard shell.
 *
 * The tiles show placeholder values with an explicit "not yet available" state
 * rather than invented numbers. A mock 87% that later becomes a real 87% is
 * indistinguishable from a working feature, which makes it impossible to tell
 * what is actually finished — and it is the same fabrication problem ADR-012
 * exists to prevent, applied to the UI.
 */

interface StatTileProps {
  label: string
  value: string
  caption: string
  available: boolean
}

function StatTile({ label, value, caption, available }: StatTileProps) {
  return (
    <div className="rounded-lg bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <p className="text-sm font-medium text-slate-600">{label}</p>
      <p
        className={
          available ? 'mt-2 text-3xl font-bold text-slate-900' : 'mt-2 text-3xl font-bold text-slate-300'
        }
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{caption}</p>
    </div>
  )
}

export function DashboardPage() {
  const { user } = useAuth()

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-600">Signed in as {user?.email}</p>
      </div>

      <Alert tone="info" title="Phase 3 of 12">
        Authentication and the application shell are in place. Resume intelligence, job matching and
        interview practice arrive in later phases — the tiles below are placeholders until then.
      </Alert>

      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">
          Overview
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Resume score" value="—" caption="Available in Phase 4" available={false} />
          <StatTile label="Career match" value="—" caption="Available in Phase 6" available={false} />
          <StatTile label="Applications" value="0" caption="Tracking starts in Phase 8" available />
          <StatTile
            label="Interview readiness"
            value="—"
            caption="Available in Phase 9"
            available={false}
          />
        </div>
      </section>

      <section aria-labelledby="next-heading" className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <h2 id="next-heading" className="text-base font-semibold text-slate-900">
          What works right now
        </h2>
        <ul className="mt-3 space-y-2 text-sm text-slate-600">
          <li>• Registration and sign-in, with rotating refresh tokens and reuse detection</li>
          <li>• Session restored automatically on reload, without storing an access token</li>
          <li>• Protected routes that return you here after signing in</li>
        </ul>
      </section>
    </div>
  )
}
