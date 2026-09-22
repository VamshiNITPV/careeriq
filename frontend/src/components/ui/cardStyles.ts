import { cn } from '@/utils/cn'

/**
 * The app's surfaces, in one place.
 *
 * A plain `.ts` module for the reason `buttonStyles.ts` gives: exporting a
 * non-component function from a `.tsx` file breaks fast refresh, and the lint
 * rule says so. It also lets a `<section>`, a `<form>` or a `<li>` wear the
 * surface without `Card` growing an `as` prop.
 *
 * ## Why this exists at all
 *
 * The string `rounded-xl border border-slate-200 bg-white p-4 sm:p-6` was
 * written out by hand in **twelve files**. Nothing was wrong with any one copy;
 * the problem was that "what a panel looks like" had no address, so changing it
 * meant finding twelve places and the app drifted every time somebody added a
 * thirteenth.
 *
 * ## A ring, not a border
 *
 * `ring-1 ring-slate-900/5` replaced `border border-slate-200`, and it is the
 * change that does most of the work. A translucent ring sits *on* the surface
 * instead of drawing a hard grey line around it — the difference between a
 * layered sheet and an outlined box. It also occupies no space in the box
 * model, where a border adds a pixel on each side, so swapping one for the
 * other shifts nothing.
 */

export type CardTone = 'plain' | 'inset' | 'dashed'

const SURFACE = 'rounded-card bg-white ring-1 ring-slate-900/5 shadow-card'

const TONES: Record<CardTone, string> = {
  plain: SURFACE,
  /**
   * A panel *inside* a panel — a stat tile, a nested summary.
   *
   * Recessed rather than raised. Two stacked shadows read as clutter, and the
   * thing inside a card is not floating above it.
   */
  inset: 'rounded-xl bg-slate-50 ring-1 ring-slate-900/5',
  /** An empty state. Dashed says "something belongs here and does not yet". */
  dashed: 'rounded-card border border-dashed border-slate-300 bg-white',
}

export const CARD_PADDING = 'p-5 sm:p-7'

/**
 * Interactive surfaces only.
 *
 * Deliberately **not** applied by default. A card that lifts under the cursor
 * and then does nothing when clicked is a promise the interface does not keep,
 * and the app has far more static panels than clickable ones.
 */
const INTERACTIVE = 'transition-shadow duration-150 hover:shadow-card-hover'

export function cardClass(
  // `| undefined` on each, as `buttonStyles.ts` explains: under
  // exactOptionalPropertyTypes a caller forwarding its own optional prop passes
  // `string | undefined` explicitly, which a bare `className?: string` rejects.
  options: {
    tone?: CardTone | undefined
    interactive?: boolean | undefined
    padded?: boolean | undefined
    className?: string | undefined
  } = {},
) {
  const { tone = 'plain', interactive = false, padded = true, className } = options
  return cn(
    TONES[tone],
    padded && CARD_PADDING,
    interactive && INTERACTIVE,
    className,
  )
}

/**
 * The shared pill shape, without its colour.
 *
 * Written twice already — `SkillGapsPage` had it first and `ApplicationBoard`
 * matched it — and a third copy is where they start to drift. Callers supply
 * the tone, which is the part that carries meaning and genuinely differs.
 */
export const PILL_SHAPE =
  'inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ' +
  'ring-1 ring-inset'
