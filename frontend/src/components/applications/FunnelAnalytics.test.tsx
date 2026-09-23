import { render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { applicationService } from '@/services/applicationService'
import type { FunnelAnalyticsResponse, FunnelSegment } from '@/types/application'
import { FunnelAnalytics } from './FunnelAnalytics'

function segment(overrides: Partial<FunnelSegment> = {}): FunnelSegment {
  return {
    label: 'All applications',
    applications: 10,
    interviews: 3,
    offers: 1,
    interview_rate: 0.3,
    offer_rate: 0.1,
    low_confidence: false,
    ...overrides,
  }
}

function response(overrides: Partial<FunnelAnalyticsResponse> = {}): FunnelAnalyticsResponse {
  return {
    overall: segment(),
    by_role: [],
    by_location: [],
    by_resume: [],
    by_score_band: [],
    min_for_rate: 5,
    segments_available: ['role', 'location', 'resume_version', 'match_score_band'],
    ...overrides,
  }
}

describe('FunnelAnalytics', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('leads with the counts and their rates', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(response())

    render(<FunnelAnalytics />)

    expect(await screen.findByText('Applications sent')).toBeInTheDocument()
    expect(screen.getByText('30% of applications')).toBeInTheDocument()
    expect(screen.getByText('10% of applications')).toBeInTheDocument()
  })

  it('shows a missing rate as unknown, never as zero', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(
      response({
        overall: segment({
          applications: 2,
          interviews: 1,
          offers: 0,
          interview_rate: null,
          offer_rate: null,
          low_confidence: true,
        }),
      }),
    )

    render(<FunnelAnalytics />)

    // The distinction the whole screen turns on. Telling somebody two
    // applications in that their interview rate is 0% is both false and
    // discouraging, and it is what rendering `null` as a number would do.
    expect(await screen.findAllByText('Rate needs 5 applications')).toHaveLength(2)
    expect(screen.queryByText('0% of applications')).not.toBeInTheDocument()
    expect(screen.getByText(/Rates appear once you have 5 applications/)).toBeInTheDocument()
  })

  it('shows a real zero as a zero', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(
      response({
        overall: segment({ applications: 8, interviews: 2, offers: 0, offer_rate: 0 }),
      }),
    )

    render(<FunnelAnalytics />)

    // Eight applications and no offers is a real answer, and must not be hidden
    // behind the same caveat as "we do not know yet".
    expect(await screen.findByText('0% of applications')).toBeInTheDocument()
    expect(screen.queryByText(/Rate needs/)).not.toBeInTheDocument()
  })

  it('breaks the numbers down by role', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(
      response({
        by_role: [
          segment({ label: 'Backend Engineer', applications: 6, interviews: 3, offers: 1 }),
          segment({
            label: 'Data Engineer',
            applications: 2,
            interviews: 0,
            offers: 0,
            interview_rate: null,
            offer_rate: null,
            low_confidence: true,
          }),
        ],
      }),
    )

    render(<FunnelAnalytics />)

    const row = (await screen.findByRole('row', { name: /Backend Engineer/ })) as HTMLElement
    expect(within(row).getByText('6')).toBeInTheDocument()

    // The thin row keeps its counts and loses only its rate, so the table still
    // adds up to the total above it.
    const thin = screen.getByRole('row', { name: /Data Engineer/ })
    expect(within(thin).getByLabelText(/Not enough applications/)).toBeInTheDocument()
  })

  it('breaks the numbers down by the resume that was sent', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(
      response({
        by_resume: [segment({ label: 'v2 · asha-mehra.pdf', applications: 6 })],
        by_score_band: [
          segment({ label: '70 and above', applications: 4 }),
          segment({
            label: 'Not recorded',
            applications: 2,
            interview_rate: null,
            offer_rate: null,
            low_confidence: true,
          }),
        ],
      }),
    )

    render(<FunnelAnalytics />)

    // Named for a reader. A column of UUIDs answers no question anybody asked,
    // and "which resume worked better" is why this slice exists.
    expect(await screen.findByRole('row', { name: /asha-mehra\.pdf/ })).toBeInTheDocument()

    // "Not recorded" is a row, not an omission. Applications sent before the
    // snapshot existed are still part of the total above, and a table that
    // silently loses them reads as a bug.
    expect(screen.getByRole('row', { name: /Not recorded/ })).toBeInTheDocument()
  })

  it('renders nothing at all when nothing has been sent', async () => {
    vi.spyOn(applicationService, 'analytics').mockResolvedValue(
      response({
        overall: segment({
          applications: 0,
          interviews: 0,
          offers: 0,
          interview_rate: null,
          offer_rate: null,
          low_confidence: true,
        }),
      }),
    )

    const { container } = render(<FunnelAnalytics />)

    // The board below already explains the empty state. A row of zeroes above
    // it would say the same thing less kindly.
    await waitFor(() => expect(applicationService.analytics).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('reports a failed load rather than implying there is nothing to show', async () => {
    vi.spyOn(applicationService, 'analytics').mockRejectedValue(new Error('network'))

    render(<FunnelAnalytics />)

    expect(await screen.findByText(/couldn't work out/i)).toBeInTheDocument()
  })
})
