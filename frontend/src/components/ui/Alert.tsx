import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

type Tone = 'error' | 'warning' | 'success' | 'info'

const TONES: Record<Tone, string> = {
  error: 'bg-red-50 text-red-800 ring-red-200',
  warning: 'bg-amber-50 text-amber-900 ring-amber-200',
  success: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  info: 'bg-slate-50 text-slate-700 ring-slate-200',
}

interface AlertProps {
  tone?: Tone
  title?: string
  children: ReactNode
  /** Correlation id from a failed request, shown so a user can quote it. */
  correlationId?: string | undefined
  className?: string
}

export function Alert({ tone = 'info', title, children, correlationId, className }: AlertProps) {
  return (
    <div
      // "alert" interrupts a screen reader immediately, which is right for a
      // failure the user must act on but rude for a passive notice.
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-md px-4 py-3 text-sm ring-1 ring-inset', TONES[tone], className)}
    >
      {title !== undefined && <p className="font-semibold">{title}</p>}
      <div className={cn(title !== undefined && 'mt-1')}>{children}</div>
      {correlationId !== undefined && (
        // Surfaced deliberately: it is the value that ties this failure to a
        // specific server log entry, turning "it broke" into a findable request.
        <p className="mt-2 font-mono text-xs opacity-70">Reference: {correlationId}</p>
      )}
    </div>
  )
}
