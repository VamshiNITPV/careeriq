import type { ElementType, ReactNode } from 'react'
import { cardClass, type CardTone } from '@/components/ui/cardStyles'

/**
 * A surface. The default panel everything sits on.
 *
 * `as` because half the call sites are a `<section>` that owns a heading and
 * wants `aria-labelledby`, and rendering those as a `<div>` would drop them out
 * of the document outline. The styling lives in `cardStyles.ts`, which anything
 * can wear without going through this component.
 */
export function Card({
  as: Tag = 'div',
  tone,
  interactive,
  padded,
  className,
  children,
  ...rest
}: {
  as?: ElementType
  tone?: CardTone
  interactive?: boolean
  /** Off for a card whose own children own the padding — a divided list. */
  padded?: boolean
  className?: string
  children: ReactNode
} & Record<string, unknown>) {
  return (
    <Tag {...rest} className={cardClass({ tone, interactive, padded, className })}>
      {children}
    </Tag>
  )
}
