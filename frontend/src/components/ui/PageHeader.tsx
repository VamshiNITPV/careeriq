import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

/**
 * The title block every page opens with.
 *
 * The same `h1` class string was written out in ten pages, so "what a page
 * title looks like" had no address and the two pages that differed did so by
 * accident rather than on purpose.
 *
 * `text-2xl sm:text-3xl` rather than a flat `text-2xl`: the old size sat close
 * enough to the section headings beneath it that the page had no clear top.
 * Growing it only at `sm` keeps phones from spending a third of the first
 * screen on a heading.
 */
export function PageHeader({
  title,
  description,
  action,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  /** A primary action for the page, right-aligned beside the title. */
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-x-4 gap-y-3', className)}>
      <div className="min-w-0">
        {/* `break-words` unconditionally: one page titles itself with a job
            title, which can be a long unbroken string, and it needed this
            locally before. Harmless everywhere else. */}
        <h1 className="text-2xl font-bold tracking-tight break-words text-slate-900 sm:text-3xl">
          {title}
        </h1>
        {description !== undefined && (
          <p className="mt-1.5 max-w-2xl text-sm text-slate-600">{description}</p>
        )}
      </div>
      {action !== undefined && <div className="shrink-0">{action}</div>}
    </div>
  )
}
