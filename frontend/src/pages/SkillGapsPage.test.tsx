import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { skillGapService } from '@/services/skillGapService'
import type { SkillGap, SkillGapsResponse } from '@/types/skillGap'

import { SkillGapsPage } from './SkillGapsPage'

function gap(overrides: Partial<SkillGap> = {}): SkillGap {
  return {
    skill_id: 's1',
    name: 'Apache Spark',
    category: 'tool',
    status: 'MISSING',
    severity: 'HIGH',
    frequency: '0.5400',
    job_count: 12,
    ...overrides,
  }
}

function response(overrides: Partial<SkillGapsResponse> = {}): SkillGapsResponse {
  return {
    items: [gap()],
    target_jobs: 68,
    target_roles: ['Data Engineer'],
    job_id: null,
    availability: 'READY',
    ...overrides,
  }
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <SkillGapsPage />
    </MemoryRouter>,
  )

describe('SkillGapsPage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('separates what to learn from what is already covered', async () => {
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(
      response({
        items: [
          gap({ skill_id: 's1', name: 'Apache Spark', status: 'MISSING' }),
          gap({ skill_id: 's2', name: 'Python', status: 'STRONG', severity: 'CRITICAL' }),
        ],
      }),
    )

    renderPage()

    const learn = (await screen.findByRole('heading', { name: 'Learn these next' }))
      .parentElement!
    expect(within(learn).getByText('Apache Spark')).toBeInTheDocument()
    expect(within(learn).queryByText('Python')).not.toBeInTheDocument()

    const covered = screen.getByRole('heading', { name: 'Already covered' }).parentElement!
    expect(within(covered).getByText('Python')).toBeInTheDocument()
  })

  it('shows how many jobs the report was built from', async () => {
    /*
     * The denominator is part of the claim. The same list computed from four
     * postings would mean far less, and a reader who cannot see how many jobs it
     * came from has no way to judge how much to trust it.
     */
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(response({ target_jobs: 68 }))

    renderPage()

    expect(await screen.findByText(/68/)).toBeInTheDocument()
    expect(screen.getByText(/Data Engineer/)).toBeInTheDocument()
  })

  it('states the share of target jobs rather than a raw fraction', async () => {
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(response())

    renderPage()

    // Rounded for reading: two decimal places would imply a precision that 68
    // postings cannot carry.
    expect(await screen.findByText(/54% of target jobs/)).toBeInTheDocument()
  })

  it('does not put a severity on a skill you already have', async () => {
    // "CRITICAL" beside something the reader has would read as an alarm about
    // nothing.
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(
      response({ items: [gap({ name: 'Python', status: 'STRONG', severity: 'CRITICAL' })] }),
    )

    renderPage()

    await screen.findByText('Python')
    expect(screen.queryByText('critical')).not.toBeInTheDocument()
  })

  it('asks for target roles rather than showing an empty list', async () => {
    /*
     * An unexplained empty list reads as "you have no gaps" — congratulation for
     * a completeness nobody measured.
     */
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(
      response({ items: [], target_jobs: 0, target_roles: [], availability: 'NO_TARGET' }),
    )

    renderPage()

    expect(await screen.findByRole('link', { name: 'Set your target roles' })).toHaveAttribute(
      'href',
      '/profile',
    )
  })

  it('names the roles it tried when nothing matched', async () => {
    // So the reader can tell whether the problem is their wording or an empty
    // corpus — two different fixes.
    vi.spyOn(skillGapService, 'gaps').mockResolvedValue(
      response({
        items: [],
        target_jobs: 0,
        target_roles: ['Underwater Basket Weaver'],
        availability: 'NO_JOBS',
      }),
    )

    renderPage()

    expect(await screen.findByText(/Underwater Basket Weaver/)).toBeInTheDocument()
  })

  it('says a failure is ours rather than implying you have no gaps', async () => {
    const gaps = vi.spyOn(skillGapService, 'gaps').mockRejectedValue(new Error('offline'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(/problem on our side/i)

    gaps.mockResolvedValue(response())
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Apache Spark')).toBeInTheDocument()
  })
})
