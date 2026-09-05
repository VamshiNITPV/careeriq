/**
 * Turn a stored URL into something safe to put in an `href`.
 *
 * Stored job links are not trustworthy. They were accepted for years with only
 * a length check, so a row can hold anything at all — and the corpus is shared,
 * so one user's value renders on everyone's screen. Validation now happens at
 * the API boundary too, but that does nothing for rows written before it.
 *
 * Parsing alone is NOT a guard: `new URL('javascript:alert(1)')` succeeds. The
 * protocol allow-list below is the line that matters.
 */

export interface ExternalLink {
  /** Safe for an href: parsed, and guaranteed http or https. */
  href: string
  /** Where it goes, for showing beside the link: "greenhouse.io/acme/jobs/…" */
  label: string
}

/** Long enough to recognise a host and a path, short enough not to wrap. */
const MAX_LABEL = 28

export function externalLink(
  raw: string | null,
  options: { assumeHttps?: boolean | undefined } = {},
): ExternalLink | null {
  if (raw === null) return null
  const trimmed = raw.trim()
  if (trimmed === '') return null

  // Mirrors normalize_url in backend/app/schemas/urls.py, including the
  // case-insensitive test. The two must agree: this decides whether the form's
  // Save button is enabled, and the server decides whether the save succeeds.
  const candidate =
    options.assumeHttps === true && !/^https?:\/\//i.test(trimmed)
      ? `https://${trimmed}`
      : trimmed

  let url: URL
  try {
    url = new URL(candidate)
  } catch {
    return null
  }

  // The allow-list, not a denylist of known-bad schemes: anything not http(s)
  // is refused, so a scheme nobody thought of is refused too.
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null

  const host = url.hostname.replace(/^www\./i, '')
  const path = url.pathname === '/' ? '' : url.pathname
  const full = `${host}${path}`

  return {
    // The parsed form, never the raw string — so what is rendered is what was
    // actually validated.
    href: url.toString(),
    label: full.length <= MAX_LABEL ? full : `${full.slice(0, MAX_LABEL - 1)}…`,
  }
}
