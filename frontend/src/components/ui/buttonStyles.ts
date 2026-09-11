import { cn } from '@/utils/cn'

/**
 * Button styling, separated from the component.
 *
 * A plain .ts module for the same reason comboboxCore.ts is one: exporting a
 * non-component function from a .tsx file breaks fast refresh, and the lint
 * rule says so.
 *
 * This exists because a link that navigates must be an `<a>`, not a `<button>`
 * with an onClick — middle-click, open-in-new-tab and "copy link address" all
 * depend on it. A `<Link>` can wear these classes without Button growing an
 * `as` prop and the generic typing that comes with it.
 */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

export const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-indigo-600 text-white hover:bg-indigo-500 focus-visible:outline-indigo-600 disabled:bg-indigo-300',
  secondary:
    'bg-white text-slate-900 ring-1 ring-slate-300 ring-inset hover:bg-slate-50 focus-visible:outline-slate-600',
  ghost: 'text-slate-700 hover:bg-slate-100 focus-visible:outline-slate-600',
  danger:
    'bg-red-600 text-white hover:bg-red-500 focus-visible:outline-red-600 disabled:bg-red-300',
}

/**
 * `sm` and `md` carry a phone-only height floor.
 *
 * `sm` computed to 32px and `md` to 36px, and `sm` is the default for nearly
 * every row action in the app — Edit, Remove, Re-extract, the pagers, the
 * confirmation dialog's buttons. That is a comfortable mouse target and a poor
 * thumb one, and it applied to destructive actions among others.
 *
 * Expressed as a floor that relaxes at `sm:` rather than as new padding, so the
 * desktop appearance is unchanged and ~15 call sites need no edit. `min-h`
 * rather than larger `py` keeps the label centred without moving the text.
 */
export const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'min-h-10 px-2.5 py-1.5 text-sm sm:min-h-0',
  md: 'min-h-10 px-3.5 py-2 text-sm sm:min-h-0',
  lg: 'px-4 py-2.5 text-base',
}

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-md font-semibold shadow-sm ' +
  'transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ' +
  'disabled:cursor-not-allowed disabled:opacity-70'

export function buttonClass(
  // `| undefined` on each: under exactOptionalPropertyTypes a caller forwarding
  // its own optional prop passes `string | undefined` explicitly, which a bare
  // `className?: string` rejects.
  options: {
    variant?: ButtonVariant | undefined
    size?: ButtonSize | undefined
    className?: string | undefined
  } = {},
) {
  const { variant = 'primary', size = 'md', className } = options
  return cn(BASE, BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className)
}
