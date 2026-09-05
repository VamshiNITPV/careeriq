import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/services/apiClient'
import { careerService } from '@/services/careerService'
import type {
  CareerSummary,
  EducationRecord,
  WorkExperience,
} from '@/types/career'
import { CareerProfile } from './CareerProfile'

function experience(overrides: Partial<WorkExperience> = {}): WorkExperience {
  return {
    id: 'e1',
    source_version_id: 'v1',
    extraction_confidence: '0.900',
    is_user_verified: false,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    title: 'Backend Engineer',
    company_name: 'Zenith Systems',
    location: 'Bengaluru, India',
    employment_type: 'FULL_TIME',
    work_mode: null,
    description: null,
    highlights: ['Built REST APIs in Python'],
    start_date: '2023-06-01',
    end_date: null,
    is_current: true,
    ...overrides,
  }
}

function education(overrides: Partial<EducationRecord> = {}): EducationRecord {
  return {
    id: 'd1',
    source_version_id: null,
    extraction_confidence: null,
    is_user_verified: true,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    institution: 'NIT Warangal',
    degree: 'B.Tech',
    field_of_study: 'Computer Science',
    education_level: 'BACHELORS',
    grade: '8.4',
    start_date: '2019-01-01',
    end_date: '2023-01-01',
    is_current: false,
    ...overrides,
  }
}

function summary(overrides: Partial<CareerSummary> = {}): CareerSummary {
  return {
    experiences: [experience()],
    education: [education()],
    projects: [],
    certifications: [],
    ...overrides,
  }
}

const workHistory = () =>
  screen.getByRole('heading', { name: 'Work history' }).closest('section')!

const educationSection = () =>
  screen.getByRole('heading', { name: 'Education' }).closest('section')!

/**
 * Wrapped in a Router because every date field is a MonthPicker, which closes
 * its popover on navigation and so reads the location. Same reason
 * ProfilePage.test.tsx and Combobox.test.tsx do it.
 */
const renderProfile = () =>
  render(
    <MemoryRouter>
      <CareerProfile />
    </MemoryRouter>,
  )

describe('CareerProfile', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows what was extracted', async () => {
    vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
    renderProfile()

    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('Zenith Systems')).toBeInTheDocument()
    // Month precision, never a day: the resume said "June 2023".
    expect(screen.getByText(/Jun 2023 – Present/)).toBeInTheDocument()
  })

  it('distinguishes a parser reading from the user’s own words', async () => {
    // Presenting them identically would hide that one is a guess.
    vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
    renderProfile()

    await screen.findByText('Backend Engineer')
    expect(within(workHistory()).getByText('Read from your resume')).toBeInTheDocument()
    expect(screen.getByText('Confirmed by you')).toBeInTheDocument()
  })

  it('reports a failed load instead of an empty history', async () => {
    // Telling someone their work history is empty when the request merely
    // failed is a lie they may act on by re-typing all of it.
    vi.spyOn(careerService, 'summary').mockRejectedValue(new Error('offline'))
    renderProfile()

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't load/i)
    expect(screen.queryByText(/Nothing yet/)).not.toBeInTheDocument()
  })

  it('recovers on Try again', async () => {
    const user = userEvent.setup()
    const load = vi
      .spyOn(careerService, 'summary')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(summary())
    renderProfile()

    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument()
    expect(load).toHaveBeenCalledTimes(2)
  })

  describe('editing', () => {
    it('sends only what changed', async () => {
      // Pins the PATCH contract: the API applies exclude_unset, so a field the
      // form did not touch must not arrive as null.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const update = vi.spyOn(careerService, 'update').mockResolvedValue(experience())
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getByRole('button', { name: 'Edit' }))

      const company = screen.getByLabelText('Company')
      await user.clear(company)
      await user.type(company, 'Zenith Systems Pvt Ltd')
      await user.click(within(workHistory()).getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(update).toHaveBeenCalled())
      const [kind, id, payload] = update.mock.calls[0]!
      expect(kind).toBe('experience')
      expect(id).toBe('e1')
      expect(payload.company_name).toBe('Zenith Systems Pvt Ltd')
      // Untouched fields keep their value rather than being blanked.
      expect(payload.title).toBe('Backend Engineer')
    })

    it('keeps a date at month precision through an edit', async () => {
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const update = vi.spyOn(careerService, 'update').mockResolvedValue(experience())
      renderProfile()

      await screen.findByText('Backend Engineer')
      const section = within(workHistory())
      await user.click(section.getByRole('button', { name: 'Edit' }))

      // Two segments reading MM / YYYY, because the day was never known.
      expect(section.getByRole('button', { name: 'Started month' })).toHaveTextContent('06')
      expect(section.getByRole('button', { name: 'Started year' })).toHaveTextContent('2023')

      await user.click(section.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(update).toHaveBeenCalled())
      // The day the API stores is an artefact, and it is put back on the way out.
      expect(update.mock.calls[0]![2].start_date).toBe('2023-06-01')
    })

    it('sets a date by picking a year and then a month', async () => {
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const update = vi.spyOn(careerService, 'update').mockResolvedValue(experience())
      renderProfile()

      await screen.findByText('Backend Engineer')
      const section = within(workHistory())
      await user.click(section.getByRole('button', { name: 'Edit' }))

      await user.click(section.getByRole('button', { name: 'Started year' }))
      await user.click(section.getByRole('option', { name: '2020' }))
      await user.click(section.getByRole('option', { name: 'Mar' }))
      await user.click(section.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(update).toHaveBeenCalled())
      expect(update.mock.calls[0]![2].start_date).toBe('2020-03-01')
    })

    it('turns highlights back into a list', async () => {
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const update = vi.spyOn(careerService, 'update').mockResolvedValue(experience())
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getByRole('button', { name: 'Edit' }))

      const highlights = screen.getByLabelText('Highlights')
      expect(highlights).toHaveValue('Built REST APIs in Python')
      await user.type(highlights, '\nMentored two engineers')
      await user.click(within(workHistory()).getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(update).toHaveBeenCalled())
      expect(update.mock.calls[0]![2].highlights).toEqual([
        'Built REST APIs in Python',
        'Mentored two engineers',
      ])
    })

    it('surfaces a validation message from the server', async () => {
      // "The end date cannot be before the start date" is far more useful than
      // "Invalid input".
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      vi.spyOn(careerService, 'update').mockRejectedValue(
        new ApiError(422, 'VALIDATION_ERROR', 'Invalid input.', {
          fields: [
            { field: 'end_date', message: 'The end date cannot be before the start date.' },
          ],
        }),
      )
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getByRole('button', { name: 'Edit' }))
      await user.click(within(workHistory()).getByRole('button', { name: 'Save' }))

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'The end date cannot be before the start date.',
      )
    })

    it('reloads after a successful save so the list matches the server', async () => {
      const user = userEvent.setup()
      const load = vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      vi.spyOn(careerService, 'update').mockResolvedValue(experience())
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getByRole('button', { name: 'Edit' }))
      await user.click(within(workHistory()).getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(load).toHaveBeenCalledTimes(2))
    })
  })

  describe('an ongoing entry', () => {
    it('hides the end date while the entry is current', async () => {
      // The experience fixture is is_current: true. "Ended" is not merely
      // blank, it does not apply.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      renderProfile()

      await screen.findByText('Backend Engineer')
      const section = within(workHistory())
      await user.click(section.getByRole('button', { name: 'Edit' }))

      expect(section.queryByRole('button', { name: 'Ended year' })).not.toBeInTheDocument()

      await user.click(section.getByLabelText('I still work here'))

      expect(section.getByRole('button', { name: 'Ended year' })).toBeInTheDocument()
    })

    it('sends a null end date alongside the tick', async () => {
      // Education's fixture carries a real end date, so this is the case that
      // matters: sending it beside is_current violates the CHECK constraint,
      // and the database's refusal arrives as an unreadable 500.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const update = vi.spyOn(careerService, 'update').mockResolvedValue(education())
      renderProfile()

      await screen.findByText('B.Tech')
      const section = within(educationSection())
      await user.click(section.getByRole('button', { name: 'Edit' }))
      expect(section.getByRole('button', { name: 'Finished year' })).toHaveTextContent('2023')

      await user.click(section.getByLabelText('I am still studying here'))
      await user.click(section.getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(update).toHaveBeenCalled())
      const payload = update.mock.calls[0]![2]
      expect(payload.end_date).toBeNull()
      expect(payload.is_current).toBe(true)
    })

    it('gives the date back if the tick was a misclick', async () => {
      // The draft deliberately keeps the value while the field is hidden; only
      // the payload nulls it. Clearing the draft too would break undo and buy
      // nothing.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      renderProfile()

      await screen.findByText('B.Tech')
      const section = within(educationSection())
      await user.click(section.getByRole('button', { name: 'Edit' }))

      await user.click(section.getByLabelText('I am still studying here'))
      await user.click(section.getByLabelText('I am still studying here'))

      expect(section.getByRole('button', { name: 'Finished year' })).toHaveTextContent('2023')
      expect(section.getByRole('button', { name: 'Finished month' })).toHaveTextContent('01')
    })
  })

  describe('adding', () => {
    it('creates an entry from a blank form', async () => {
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(
        summary({ experiences: [], education: [] }),
      )
      const create = vi.spyOn(careerService, 'create').mockResolvedValue(experience())
      renderProfile()

      await screen.findByRole('heading', { name: 'Work history' })
      await user.click(within(workHistory()).getByRole('button', { name: 'Add' }))
      await user.type(screen.getByLabelText(/^Job title/), 'Staff Engineer')
      await user.click(within(workHistory()).getByRole('button', { name: 'Save' }))

      await waitFor(() => expect(create).toHaveBeenCalled())
      expect(create.mock.calls[0]![0]).toBe('experience')
      expect(create.mock.calls[0]![1].title).toBe('Staff Engineer')
      // A blank optional field is null, not "" — otherwise the row shows an
      // empty company rather than none.
      expect(create.mock.calls[0]![1].company_name).toBeNull()
    })

    it('says the list is empty only once it is known to be', async () => {
      vi.spyOn(careerService, 'summary').mockResolvedValue(
        summary({ experiences: [], education: [] }),
      )
      renderProfile()

      // Scoping needs the section to exist, so wait for the load first.
      await screen.findByRole('heading', { name: 'Work history' })
      expect(within(workHistory()).getByText(/Nothing yet/)).toBeInTheDocument()
    })
  })

  describe('removing', () => {
    it('warns that a resume-derived entry comes back on re-extract', async () => {
      // Surprising otherwise: the user would think the delete failed.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getAllByRole('button', { name: 'Remove' })[0]!)

      const dialog = screen.getAllByRole('dialog')[0]!
      expect(within(dialog).getByText(/re-extracting that resume will add it back/i)).toBeInTheDocument()
    })

    it('does not warn about re-extraction for a hand-typed entry', async () => {
      // Nothing will bring it back, so saying otherwise is simply untrue.
      const user = userEvent.setup()
      vi.spyOn(careerService, 'summary').mockResolvedValue(
        summary({ experiences: [experience({ source_version_id: null })] }),
      )
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getAllByRole('button', { name: 'Remove' })[0]!)

      const dialog = screen.getAllByRole('dialog')[0]!
      expect(within(dialog).queryByText(/will add it back/i)).not.toBeInTheDocument()
    })

    it('deletes on confirm and reloads', async () => {
      const user = userEvent.setup()
      const load = vi.spyOn(careerService, 'summary').mockResolvedValue(summary())
      const remove = vi.spyOn(careerService, 'remove').mockResolvedValue({ message: 'Removed.' })
      renderProfile()

      await screen.findByText('Backend Engineer')
      await user.click(within(workHistory()).getAllByRole('button', { name: 'Remove' })[0]!)

      const dialog = screen.getAllByRole('dialog')[0]!
      await user.click(within(dialog).getByRole('button', { name: 'Remove' }))

      await waitFor(() => expect(remove).toHaveBeenCalledWith('experience', 'e1'))
      await waitFor(() => expect(load).toHaveBeenCalledTimes(2))
    })
  })
})
