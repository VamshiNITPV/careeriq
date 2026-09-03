/**
 * Avatar initials and display name.
 *
 * Pure functions rather than context values, so they can be tested without
 * mounting a provider.
 */

/** Two letters at most, from a name if there is one, otherwise the email. */
export function initialsFor(fullName: string | null | undefined, email: string): string {
  const name = fullName?.trim()

  if (name) {
    const tokens = name.split(/\s+/).filter(Boolean)
    if (tokens.length === 1) return tokens[0]!.charAt(0).toUpperCase()
    // First and last, not first and second — "Priya Kumari Sharma" reads as PS.
    return (tokens[0]!.charAt(0) + tokens[tokens.length - 1]!.charAt(0)).toUpperCase()
  }

  const local = email.split('@')[0] ?? ''
  if (!local) return '?'

  // "priya.sharma" and "priya_sharma" carry the same two-part structure as a
  // name, so use it when it is there.
  const parts = local.split(/[._-]+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0]!.charAt(0) + parts[1]!.charAt(0)).toUpperCase()
  }
  return local.charAt(0).toUpperCase() || '?'
}

/** What to call the user in the interface. */
export function displayNameFor(
  fullName: string | null | undefined,
  email: string,
): string {
  return fullName?.trim() || (email.split('@')[0] ?? email)
}

/** First name only, for a greeting. */
export function firstNameFor(fullName: string | null | undefined, email: string): string {
  const name = fullName?.trim()
  if (name) return name.split(/\s+/)[0] ?? name
  // `||` not `??`: splitting an empty email yields "", which is not null and
  // would slip through a nullish check to render "Welcome back, ".
  return email.split('@')[0] || 'there'
}

/**
 * A stable colour per user.
 *
 * Full literal class strings, never `bg-${x}-600`: Tailwind v4 scans source
 * text for class names and generates no CSS at all for an interpolated one, so
 * the avatar would render with no background.
 */
const AVATAR_COLOURS = [
  'bg-indigo-600',
  'bg-emerald-600',
  'bg-rose-600',
  'bg-amber-600',
  'bg-sky-600',
  'bg-violet-600',
  'bg-teal-600',
] as const

export function avatarColourFor(seed: string): string {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0
  }
  return AVATAR_COLOURS[Math.abs(hash) % AVATAR_COLOURS.length]!
}
