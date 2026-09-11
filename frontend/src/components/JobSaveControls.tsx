import type { JobApplicationState } from '@/hooks/useJobApplication'
import { cn } from '@/utils/cn'

/**
 * Save a job, and record whether you applied to it.
 *
 * A controlled component: every decision lives in `useJobApplication`, so the
 * job card, the two copies on the detail page and the profile rows all behave
 * identically — and the detail page's two copies stay in step because they read
 * one hook.
 */

interface JobSaveControlsProps {
  state: JobApplicationState
  /** Goes into the button's accessible name — twenty cards of "Save this job"
   *  are indistinguishable to anyone arrowing through them. */
  jobTitle: string
  /** `icon` drops the checkbox: a list row has no space for it. */
  variant?: 'full' | 'icon'
  className?: string
}

function BookmarkIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-5"
      aria-hidden="true"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 4h12v16l-6-4-6 4V4z" />
    </svg>
  )
}

export function JobSaveControls({
  state,
  jobTitle,
  variant = 'full',
  className,
}: JobSaveControlsProps) {
  const { isSaved, isApplied } = state

  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-2', className)}>
      {variant === 'full' && (
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={isApplied}
            onChange={(e) => state.setApplied(e.target.checked)}
            className="size-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
          />
          {/* First person, past tense. A bare "Applied" reads like a button
              that might submit something — and nothing here applies on the
              user's behalf; this only records what they say they did. */}
          I have applied
        </label>
      )}

      {variant === 'icon' && isApplied && (
        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
          Applied
        </span>
      )}

      <button
        type="button"
        onClick={state.toggleSaved}
        // The name changes with state rather than carrying aria-pressed:
        // aria-pressed promises a plain on/off, but this control's *effect*
        // changes — on an applied job it opens a confirmation instead.
        aria-label={isSaved ? `Remove ${jobTitle} from saved` : `Save ${jobTitle}`}
        className={cn(
          // `size-10` on phones — the most-tapped control in the app was a 28px
          // target (a `size-5` icon in `p-1`), which clears the 24px WCAG 2.5.8
          // minimum but is small for a thumb on a dense list of cards. The icon
          // is unchanged; only the hit area grows. `-m-1` keeps the larger box
          // from pushing the card's header row taller, and it shrinks back at
          // `sm` where pointers are precise and the row is tight.
          'inline-flex size-10 shrink-0 items-center justify-center rounded -m-1',
          'sm:m-0 sm:size-auto sm:p-1',
          'focus-visible:ring-2 focus-visible:ring-indigo-600 focus-visible:outline-none',
          isSaved ? 'text-slate-900' : 'text-slate-400 hover:text-slate-600',
        )}
      >
        <BookmarkIcon filled={isSaved} />
      </button>

      {variant === 'icon' && state.error !== null && (
        <span role="alert" className="text-xs text-red-700">
          Couldn&apos;t save.
        </span>
      )}
    </div>
  )
}
