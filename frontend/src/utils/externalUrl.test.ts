import { describe, expect, it } from 'vitest'
import { externalLink } from './externalUrl'

describe('externalLink', () => {
  it('passes through an ordinary posting link', () => {
    const link = externalLink('https://boards.greenhouse.io/acme/jobs/4821')

    expect(link?.href).toBe('https://boards.greenhouse.io/acme/jobs/4821')
    expect(link?.label).toBe('boards.greenhouse.io/acme/j…')
  })

  it('keeps http, rather than rewriting the scheme', () => {
    // Some postings are genuinely http. Upgrading it would be inventing.
    expect(externalLink('http://jobs.example.com/1')?.href).toBe('http://jobs.example.com/1')
  })

  it.each([
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
  ])('refuses %s', (raw) => {
    // new URL() parses every one of these happily — the protocol allow-list is
    // the only thing standing between a stored value and an href.
    expect(externalLink(raw)).toBeNull()
  })

  it('refuses a javascript: link even when a scheme would be assumed', () => {
    // The prepend must not rescue it: "javascript:alert(1)" already has a
    // scheme by the regex, so it goes to new URL() as-is and is caught by the
    // allow-list.
    expect(externalLink('javascript:alert(1)', { assumeHttps: true })).toBeNull()
  })

  it.each([null, '', '   ', 'not a url at all'])('has nothing to show for %s', (raw) => {
    expect(externalLink(raw)).toBeNull()
  })

  it('assumes https only when there is no scheme', () => {
    expect(externalLink('careers.acme.com/jobs/1', { assumeHttps: true })?.href).toBe(
      'https://careers.acme.com/jobs/1',
    )
    expect(externalLink('http://careers.acme.com/1', { assumeHttps: true })?.href).toBe(
      'http://careers.acme.com/1',
    )
  })

  it('recognises an existing scheme whatever its case', () => {
    // Otherwise a second scheme is glued on front and the link goes nowhere —
    // the same bug the backend normaliser had.
    expect(externalLink('HTTPS://Acme.example/apply', { assumeHttps: true })?.href).toBe(
      'https://acme.example/apply',
    )
  })

  it('leaves a scheme-less value alone when not asked to assume one', () => {
    expect(externalLink('careers.acme.com/jobs/1')).toBeNull()
  })

  it('drops www. and a bare slash from the label', () => {
    expect(externalLink('https://www.acme.com/')?.label).toBe('acme.com')
  })
})
