import { describe, expect, it } from 'vitest'
import { avatarColourFor, displayNameFor, firstNameFor, initialsFor } from './initials'

describe('initialsFor', () => {
  it('uses first and last of a full name', () => {
    expect(initialsFor('Priya Sharma', 'x@y.com')).toBe('PS')
  })

  it('skips middle names', () => {
    // "Priya Kumari Sharma" reads as PS, not PK.
    expect(initialsFor('Priya Kumari Sharma', 'x@y.com')).toBe('PS')
  })

  it('handles a single name', () => {
    expect(initialsFor('Priya', 'x@y.com')).toBe('P')
  })

  it('falls back to a structured email local part', () => {
    expect(initialsFor(null, 'priya.sharma@example.com')).toBe('PS')
    expect(initialsFor(null, 'priya_sharma@example.com')).toBe('PS')
    expect(initialsFor(null, 'priya-sharma@example.com')).toBe('PS')
  })

  it('falls back to one letter for an unstructured email', () => {
    expect(initialsFor(null, 'priyasharma@example.com')).toBe('P')
  })

  it('treats a whitespace-only name as absent', () => {
    expect(initialsFor('   ', 'priya@example.com')).toBe('P')
  })

  it('never returns an empty string', () => {
    // The avatar would otherwise render as a blank circle.
    expect(initialsFor(null, '')).toBe('?')
  })
})

describe('displayNameFor', () => {
  it('prefers the name', () => {
    expect(displayNameFor('Priya Sharma', 'x@y.com')).toBe('Priya Sharma')
  })

  it('falls back to the email local part', () => {
    expect(displayNameFor(null, 'priya@example.com')).toBe('priya')
  })
})

describe('firstNameFor', () => {
  it('takes the first token', () => {
    expect(firstNameFor('Priya Sharma', 'x@y.com')).toBe('Priya')
  })

  it('falls back to the email, then to a generic greeting', () => {
    expect(firstNameFor(null, 'priya@example.com')).toBe('priya')
    expect(firstNameFor(null, '')).toBe('there')
  })
})

describe('avatarColourFor', () => {
  it('is stable for the same seed', () => {
    // The avatar changing colour between renders would look like a bug.
    expect(avatarColourFor('abc')).toBe(avatarColourFor('abc'))
  })

  it('returns a literal class, never an interpolated one', () => {
    // Tailwind v4 scans source text for class names and emits no CSS for
    // `bg-${x}-600`, so an interpolated class renders with no background.
    expect(avatarColourFor('abc')).toMatch(/^bg-[a-z]+-600$/)
  })
})
