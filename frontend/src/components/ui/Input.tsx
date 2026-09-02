import { useId, type InputHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string
  error?: string | undefined
  hint?: string | undefined
}

export function Input({ label, error, hint, className, required, ...props }: InputProps) {
  // useId gives a stable, collision-free id across server and client, so the
  // label's htmlFor always matches even with two of the same field on a page.
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-900">
        {label}
        {required === true && (
          <span className="ml-0.5 text-red-600" aria-hidden="true">
            *
          </span>
        )}
      </label>

      <input
        id={id}
        required={required}
        // Announces the invalid state to screen readers, not just visually.
        aria-invalid={error !== undefined}
        // Points assistive technology at the error or hint text. Without it the
        // message is visible but never read out.
        aria-describedby={cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined}
        className={cn(
          'mt-1.5 block w-full rounded-md border-0 px-3 py-2 text-slate-900 shadow-sm',
          'ring-1 ring-inset placeholder:text-slate-400',
          'focus:ring-2 focus:ring-inset focus:outline-none',
          'disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500',
          error !== undefined
            ? 'ring-red-400 focus:ring-red-600'
            : 'ring-slate-300 focus:ring-indigo-600',
          className,
        )}
        {...props}
      />

      {hint !== undefined && error === undefined && (
        <p id={hintId} className="mt-1.5 text-sm text-slate-500">
          {hint}
        </p>
      )}
      {error !== undefined && (
        <p id={errorId} className="mt-1.5 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  )
}
