import { describe, expect, it } from 'vitest'
import { backLabelFor } from './backTo'

describe('backLabelFor', () => {
  it('names the page the link returns to', () => {
    expect(backLabelFor('/saved-jobs')).toBe('Back to saved jobs')
    expect(backLabelFor('/dashboard')).toBe('Back to dashboard')
    expect(backLabelFor('/jobs')).toBe('Back to jobs')
  })

  it('ignores the query string', () => {
    // `/jobs?q=python&offset=20` is still the job list. The filters are part of
    // where the link goes, never part of what it is called.
    expect(backLabelFor('/jobs?q=python&offset=20')).toBe('Back to jobs')
    expect(backLabelFor('/jobs?sort=match')).toBe('Back to jobs')
    expect(backLabelFor('/saved-jobs?anything=1')).toBe('Back to saved jobs')
  })

  it('falls back rather than failing on a path it does not know', () => {
    /*
     * `backTo` is read from history state, which any script on the page can
     * write, so this receives arbitrary strings. It has to return something
     * sensible for all of them — the *destination* is validated separately in
     * JobDetailPage, and that is where a hostile value is actually stopped.
     */
    expect(backLabelFor('/somewhere-new')).toBe('Back to jobs')
    expect(backLabelFor('')).toBe('Back to jobs')
    expect(backLabelFor('?only-a-query')).toBe('Back to jobs')
  })

  it('does not match a page that merely starts with the same letters', () => {
    /*
     * A bare `startsWith` would call this the dashboard, because the string
     * does begin with '/dashboard'. Nothing routes there today — the point is
     * that adding such a page later must not silently inherit the label.
     */
    expect(backLabelFor('/dashboards-of-my-team')).toBe('Back to jobs')
    expect(backLabelFor('/saved-jobs-archive')).toBe('Back to jobs')
  })

  it('matches a child path of a known page', () => {
    expect(backLabelFor('/dashboard/summary')).toBe('Back to dashboard')
  })
})
