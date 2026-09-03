import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Spinner } from './Spinner'
import { buttonClass, type ButtonSize, type ButtonVariant } from './buttonStyles'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  isLoading?: boolean
  children: ReactNode
}

export function Button({
  variant = 'primary',
  size = 'md',
  isLoading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      // Explicit: a <button> inside a <form> defaults to type="submit", so an
      // unrelated button silently submits the form when clicked.
      type="button"
      // Disabled while loading so a double click cannot fire the request twice.
      disabled={disabled === true || isLoading}
      // aria-busy tells assistive technology the control is working; the
      // spinner alone conveys nothing to a screen reader.
      aria-busy={isLoading}
      className={buttonClass({ variant, size, className })}
      {...props}
    >
      {isLoading && <Spinner className="size-4" />}
      {children}
    </button>
  )
}
