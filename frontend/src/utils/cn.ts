/**
 * Join class names, dropping falsy values.
 *
 * Deliberately not clsx + tailwind-merge: two dependencies to save nine lines,
 * and nothing here yet needs conflicting-class resolution. Revisit if variant
 * composition starts producing real conflicts.
 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}
