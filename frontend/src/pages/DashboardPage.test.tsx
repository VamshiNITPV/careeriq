import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobService } from '@/services/jobService'
import { resumeService, skillService } from '@/services/resumeService'
import type { JobListResponse } from '@/types/job'
import { DashboardPage } from './DashboardPage'

/**
 * The "Job matches" tile, which counted the wrong thing.
 *
 * It read `recommendations().considered` — the size of the *recall set*, the
 * ~200 postings stage one hands to the scorer. That answers "how many jobs did
 * we look at", while the label says "Job matches", so it showed 200 on a corpus
 * where a handful actually scored well. These tests exist so it cannot drift
 * back to counting everything.
 */

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ user: { email: 'a@example.com' }, profile: null }),
}))

function listResponse(total: number, extra: Partial<JobListResponse> = {}): JobListResponse {
  return {
    items: [],
    total,
    limit: 1,
    offset: 0,
    availability: 'READY',
    ranking_version: 'v1-hand-tuned',
    ...extra,
  }
}

const renderDashboard = () =>
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )

/**
 * The tile's card, once the dashboard has finished loading.
 *
 * Async because the page shows a spinner until every count settles, so a
 * synchronous query runs against the loading state and finds nothing.
 */
const matchTile = async () =>
  within((await screen.findByText('Job matches')).closest('div')!)

describe('the Job matches tile', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(resumeService, 'list').mockResolvedValue([])
    vi.spyOn(skillService, 'mySkills').mockResolvedValue([])
    // The panel below fetches its own rows and is not the subject here.
    vi.spyOn(jobService, 'recommendations').mockRejectedValue(new Error('not under test'))
  })

  it('counts only jobs scoring at or above the threshold', async () => {
    const list = vi.spyOn(jobService, 'list').mockResolvedValue(listResponse(7))

    renderDashboard()

    expect((await matchTile()).getByText('7')).toBeInTheDocument()
    // The count has to come from a *ranked* request with the floor applied —
    // asking without `min_score` would return the whole recall set again.
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'match', min_score: 50 }),
    )
  })

  it('names the threshold in the caption', async () => {
    // "Ranked against your resume" described the old number. A caption that no
    // longer matches the figure above it is worse than no caption.
    vi.spyOn(jobService, 'list').mockResolvedValue(listResponse(7))

    renderDashboard()

    expect((await matchTile()).getByText(/50 or above/)).toBeInTheDocument()
  })

  it('blames the missing resume rather than the scores', async () => {
    /*
     * Both render 0, and only one of them is something the reader can act on.
     * "Nothing scored 50 or above" when no resume has been uploaded is both
     * false and a dead end.
     */
    vi.spyOn(jobService, 'list').mockResolvedValue(
      listResponse(0, { availability: 'NO_RESUME' }),
    )

    renderDashboard()

    expect((await matchTile()).getByText(/Upload a resume/)).toBeInTheDocument()
  })

  it('says nothing scored well enough when a resume is there', async () => {
    vi.spyOn(jobService, 'list').mockResolvedValue(listResponse(0))

    renderDashboard()

    expect((await matchTile()).getByText(/Nothing scoring 50 or above/)).toBeInTheDocument()
  })

  it('shows zero rather than breaking when the count cannot be fetched', async () => {
    // A dashboard that renders nothing because one tile failed is worse than
    // one showing a zero — the other three tiles are still worth reading.
    vi.spyOn(jobService, 'list').mockRejectedValue(new Error('offline'))

    renderDashboard()

    expect((await matchTile()).getByText('0')).toBeInTheDocument()
  })
})
