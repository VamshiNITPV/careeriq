import { useId, type SelectHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'

/**
 * A native select, styled to match Input.
 *
 * Not the Combobox: that exists for lists long enough to need searching —
 * 249 countries, 155 currencies. A filter with four options needs a native
 * control, which brings the platform's own keyboard handling, mobile picker
 * and accessibility for free.
 */

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'children'> {
  label: string
  options: readonly { value: string; label: string }[]
  /** Shown as the first entry, mapping to the empty value. */
  placeholder?: string
  error?: string | undefined
  hint?: string | undefined
}

export function Select({
  label,
  options,
  placeholder,
  error,
  hint,
  className,
  required,
  ...props
}: SelectProps) {
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

      <select
        id={id}
        required={required}
        aria-invalid={error !== undefined}
        aria-describedby={
          cn(error !== undefined && errorId, hint !== undefined && hintId) || undefined
        }
        className={cn(
          'mt-1.5 block w-full rounded-md border-0 bg-white px-3 py-2 text-slate-900 shadow-sm',
          'ring-1 ring-inset focus:ring-2 focus:ring-inset focus:outline-none',
          'disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500',
          error !== undefined
            ? 'ring-red-400 focus:ring-red-600'
            : 'ring-slate-300 focus:ring-indigo-600',
          className,
        )}
        {...props}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

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
