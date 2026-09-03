import { useId, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'

/**
 * Multi-line input.
 *
 * A sibling of Input rather than an `as` prop on it: the two share the label
 * and description wiring but nothing else, and overloading one component with
 * a rendering switch makes both harder to read.
 */

interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: string
  error?: string | undefined
  hint?: string | undefined
}

export function Textarea({ label, error, hint, className, required, ...props }: TextareaProps) {
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

      <textarea
        id={id}
        required={required}
        aria-invalid={error !== undefined}
        aria-describedby={
          cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined
        }
        className={cn(
          'mt-1.5 block w-full rounded-md border-0 px-3 py-2 text-slate-900 shadow-sm',
          'ring-1 ring-inset placeholder:text-slate-400',
          'focus:ring-2 focus:ring-inset focus:outline-none',
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
