import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppLayout } from '@/components/layout/AppLayout'
import { AuthProvider } from '@/providers/AuthProvider'
import { ApiError } from '@/services/apiClient'
import { authService } from '@/services/authService'
import { careerService } from '@/services/careerService'
import { profileService } from '@/services/profileService'
import { setAccessToken, setRefreshToken } from '@/services/tokenStorage'
import type { User } from '@/types/auth'
import type { Profile } from '@/types/profile'
import { ProfilePage } from './ProfilePage'

const USER: User = {
  id: '01a06172-a77b-7ef5-86aa-a6079081db56',
  email: 'priya@example.com',
  role: 'USER',
  auth_provider: 'LOCAL',
  is_active: true,
  email_verified_at: '2026-09-01T00:00:00Z',
  last_login_at: null,
  created_at: '2026-09-01T00:00:00Z',
}

function profileFixture(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 'p1',
    user_id: USER.id,
    full_name: 'Priya Sharma',
    headline: null,
    location: null,
    country_code: null,
    phone: null,
    summary: null,
    linkedin_url: null,
    github_url: null,
    portfolio_url: null,
    years_of_experience: null,
    current_experience_level: null,
    highest_education: null,
    target_roles: [],
    preferred_locations: [],
    preferred_work_modes: [],
    preferred_employment_types: [],
    min_salary_expectation: null,
    salary_currency: null,
    open_to_relocation: false,
    preferences_updated_at: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

/** The whole shell, so header and page share one provider. */
function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/profile']}>
      <AuthProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // A stored session so AuthProvider restores rather than sitting logged out.
    setAccessToken('access')
    setRefreshToken('refresh')
    vi.spyOn(authService, 'me').mockResolvedValue(USER)
    // The page also renders CareerProfile, which fetches on mount. Left
    // unmocked it fails and renders its own role="alert", which the
    // correlation-id test below — findByRole('alert'), singular — would then
    // match instead of the one it is testing.
    vi.spyOn(careerService, 'summary').mockResolvedValue({
      experiences: [],
      education: [],
      projects: [],
      certifications: [],
    })
  })

  it('renders the fields with accessible labels', async () => {
    vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
    renderApp()

    // Queried by label, not by class: passing this means a screen reader user
    // can identify the field too.
    expect(await screen.findByLabelText(/^Full name/)).toBeInTheDocument()
    expect(screen.getByLabelText('Headline')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Target roles/)).toBeInTheDocument()
  })

  it('sends only the personal fields when saving details', async () => {
    const user = userEvent.setup()
    vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
    const update = vi
      .spyOn(profileService, 'updatePersonal')
      .mockResolvedValue(profileFixture({ headline: 'Backend Engineer' }))
    renderApp()

    const headline = await screen.findByLabelText('Headline')
    await user.type(headline, 'Backend Engineer')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

    await waitFor(() => expect(update).toHaveBeenCalled())
    const sent = update.mock.calls[0]![0]
    expect(sent.headline).toBe('Backend Engineer')
    // Preference fields belong to the other endpoint entirely.
    expect(sent).not.toHaveProperty('target_roles')
  })

  it('updates the header avatar without a reload when the name changes', async () => {
    /**
     * The acceptance criterion for "edits reflect across the app".
     *
     * This is the only test that fails if the page keeps its saved value in
     * local state instead of pushing it into context — everything else would
     * still pass while the header stayed stale.
     */
    const user = userEvent.setup()
    vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture({ full_name: 'Priya Sharma' }))
    vi.spyOn(profileService, 'updatePersonal').mockResolvedValue(
      profileFixture({ full_name: 'Ananya Iyer' }),
    )
    renderApp()

    // Initials from "Priya Sharma".
    expect(await screen.findByRole('button', { name: /Priya Sharma/ })).toBeInTheDocument()

    const name = screen.getByLabelText(/^Full name/)
    await user.clear(name)
    await user.type(name, 'Ananya Iyer')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

    // The header trigger is named from the profile in context, so this only
    // passes if the save propagated out of the page.
    expect(await screen.findByRole('button', { name: /Ananya Iyer/ })).toBeInTheDocument()
  })

  it('surfaces a server error with its correlation id', async () => {
    const user = userEvent.setup()
    vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
    vi.spyOn(profileService, 'updatePersonal').mockRejectedValue(
      new ApiError(422, 'VALIDATION_ERROR', 'Invalid input.', {}, 'corr-42'),
    )
    renderApp()

    await screen.findByLabelText(/^Full name/)
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('corr-42')
  })

  it('sends the full preference set, not a partial one', async () => {
    // The endpoint replaces wholesale, so omitting a key would silently clear it.
    //
    // The location override is what makes the form valid: preferred_locations
    // is now required, and the bare fixture has an empty list, so the save
    // would be blocked before reaching the service. The default fixture is left
    // empty on purpose — seeding it would reorder the assertions in the
    // locations tests below.
    const user = userEvent.setup()
    vi.spyOn(profileService, 'get').mockResolvedValue(
      profileFixture({ preferred_locations: ['Remote'] }),
    )
    const replace = vi
      .spyOn(profileService, 'replacePreferences')
      .mockResolvedValue(profileFixture())
    renderApp()

    const roles = await screen.findByLabelText(/^Target roles/)
    await user.type(roles, 'Backend Engineer, ML Engineer')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

    await waitFor(() => expect(replace).toHaveBeenCalled())
    const sent = replace.mock.calls[0]![0]
    expect(sent.target_roles).toEqual(['Backend Engineer', 'ML Engineer'])
    expect(sent).toHaveProperty('preferred_work_modes')
    expect(sent).toHaveProperty('open_to_relocation')
  })

  describe('required fields', () => {
    /**
     * The frontend is deliberately stricter than the API here: the server
     * defaults every personal field and only enforces the currency/salary
     * pair. A profile with no name and no target roles is storable but useless
     * to job matching, and the asterisk is the interface saying so — which
     * means it has to actually prevent the save.
     */

    it('says nothing on a fresh, empty profile', async () => {
      // A new profile is invalid by construction. Greeting someone with three
      // red messages before they type a character is hostile.
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({ full_name: null, target_roles: [], preferred_locations: [] }),
      )
      renderApp()

      await screen.findByLabelText(/^Full name/)
      expect(screen.queryByText('Enter your full name.')).not.toBeInTheDocument()
      expect(
        screen.queryByText('Add at least one target role, separated by commas.'),
      ).not.toBeInTheDocument()
    })

    it('blocks the save when the name is empty', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      const update = vi.spyOn(profileService, 'updatePersonal')
      renderApp()

      const name = await screen.findByLabelText(/^Full name/)
      await user.clear(name)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

      expect(await screen.findByText('Enter your full name.')).toBeInTheDocument()
      expect(update).not.toHaveBeenCalled()
      expect(name).toHaveAttribute('aria-invalid', 'true')
    })

    it('moves focus to the field that failed', async () => {
      // Otherwise a blocked save is silent to anyone not looking at the screen:
      // focus stays on Save and nothing is announced.
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      vi.spyOn(profileService, 'updatePersonal')
      renderApp()

      const name = await screen.findByLabelText(/^Full name/)
      await user.clear(name)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

      await waitFor(() => expect(name).toHaveFocus())
    })

    it('names every empty preference from one press', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      const replace = vi.spyOn(profileService, 'replacePreferences')
      renderApp()

      await screen.findByLabelText(/^Target roles/)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      expect(
        await screen.findByText('Add at least one target role, separated by commas.'),
      ).toBeInTheDocument()
      expect(
        screen.getByText('Add at least one preferred location. Remote and Anywhere count.'),
      ).toBeInTheDocument()
      expect(replace).not.toHaveBeenCalled()
    })

    it('clears a message as soon as the field is valid, with no second press', async () => {
      // The behaviour a stored-error implementation usually gets wrong.
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      vi.spyOn(profileService, 'updatePersonal').mockResolvedValue(profileFixture())
      renderApp()

      const name = await screen.findByLabelText(/^Full name/)
      await user.clear(name)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
      await screen.findByText('Enter your full name.')

      await user.type(name, 'Priya')

      expect(screen.queryByText('Enter your full name.')).not.toBeInTheDocument()
    })

    it('keeps the message when only whitespace is typed', async () => {
      // Trim-based, mirroring the server's own _blank_to_none.
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      renderApp()

      const name = await screen.findByLabelText(/^Full name/)
      await user.clear(name)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
      await screen.findByText('Enter your full name.')

      await user.type(name, '   ')

      expect(screen.getByText('Enter your full name.')).toBeInTheDocument()
    })

    it('marks currency required only once a salary is entered', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({
          target_roles: ['Backend Engineer'],
          preferred_locations: ['Remote'],
        }),
      )
      renderApp()

      // No salary, so no asterisk — the exact-string query still matches.
      const currency = await screen.findByLabelText('Currency')
      expect(currency).not.toBeRequired()

      await user.type(screen.getByLabelText('Minimum salary'), '2400000')

      // The asterisk has appeared, so the label text has changed.
      expect(screen.getByLabelText(/^Currency/)).toBeRequired()
      expect(screen.queryByLabelText('Currency')).not.toBeInTheDocument()
    })

    it('blocks the save when a salary has no currency', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({
          target_roles: ['Backend Engineer'],
          preferred_locations: ['Remote'],
        }),
      )
      const replace = vi.spyOn(profileService, 'replacePreferences')
      renderApp()

      await user.type(await screen.findByLabelText('Minimum salary'), '2400000')
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      expect(
        await screen.findByText('Choose the currency for your minimum salary.'),
      ).toBeInTheDocument()
      expect(replace).not.toHaveBeenCalled()
    })

    it('allows a currency with no salary', async () => {
      // The rule is one-directional, matching the server: "pay me in INR, no
      // floor stated" is legitimate.
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({
          target_roles: ['Backend Engineer'],
          preferred_locations: ['Remote'],
          salary_currency: 'INR',
          min_salary_expectation: null,
        }),
      )
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture())
      renderApp()

      await screen.findByLabelText(/^Target roles/)
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      await waitFor(() => expect(replace).toHaveBeenCalled())
      expect(replace.mock.calls[0]![0].salary_currency).toBe('INR')
    })

    it('leaves optional fields unmarked', async () => {
      // The asterisk only means something while it is scarce.
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      renderApp()

      expect(await screen.findByLabelText('Headline')).not.toBeRequired()
      expect(screen.getByLabelText('Location')).not.toBeRequired()
      expect(screen.getByLabelText('Phone')).not.toBeRequired()
      expect(screen.getByLabelText('Country')).not.toBeRequired()
    })
  })

  describe('pickers', () => {
    it('adds no button named "Save"', async () => {
      // Two tests above index getAllByRole('button', { name: 'Save' })
      // positionally. Asserting the count here turns a baffling failure in
      // those into an obvious one here.
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      renderApp()

      await screen.findByLabelText(/^Full name/)
      expect(screen.getAllByRole('button', { name: 'Save' })).toHaveLength(2)
    })

    it('sends the country code, not the country name', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      const update = vi
        .spyOn(profileService, 'updatePersonal')
        .mockResolvedValue(profileFixture({ country_code: 'IN' }))
      renderApp()

      const country = await screen.findByLabelText('Country')
      await user.type(country, 'India')
      await user.keyboard('{Enter}')
      await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

      await waitFor(() => expect(update).toHaveBeenCalled())
      expect(update.mock.calls[0]![0].country_code).toBe('IN')
    })

    it('sends the currency code, not the currency name', async () => {
      const user = userEvent.setup()
      // Roles and locations seeded so the section is valid — this test is about
      // currency, not about the required-field guard.
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({
          target_roles: ['Backend Engineer'],
          preferred_locations: ['Remote'],
        }),
      )
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture({ salary_currency: 'INR' }))
      renderApp()

      const currency = await screen.findByLabelText('Currency')
      await user.type(currency, 'Indian Rupee')
      await user.keyboard('{Enter}')
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      await waitFor(() => expect(replace).toHaveBeenCalled())
      expect(replace.mock.calls[0]![0].salary_currency).toBe('INR')
    })

    it('sends preferred locations as an array', async () => {
      // The state behind this field went from a comma-separated string to
      // string[]; this is what proves the migration and that toList is no
      // longer in the path.
      //
      // Roles seeded so the guard does not block the save; locations are left
      // empty because this test fills them itself.
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({ target_roles: ['Backend Engineer'] }),
      )
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture())
      renderApp()

      const locations = await screen.findByLabelText(/^Preferred locations/)
      await user.type(locations, 'beng')
      await user.keyboard('{Enter}')
      await user.type(locations, 'remote')
      await user.keyboard('{Enter}')
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      await waitFor(() => expect(replace).toHaveBeenCalled())
      expect(replace.mock.calls[0]![0].preferred_locations).toEqual(['Bengaluru', 'Remote'])
    })

    it('sends a location that is not on the list, verbatim', async () => {
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({ target_roles: ['Backend Engineer'] }),
      )
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture())
      renderApp()

      const locations = await screen.findByLabelText(/^Preferred locations/)
      await user.type(locations, 'Whitefield')
      await user.keyboard('{Enter}')
      await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

      await waitFor(() => expect(replace).toHaveBeenCalled())
      expect(replace.mock.calls[0]![0].preferred_locations).toEqual(['Whitefield'])
    })

    it('seeds stored values without rewriting them', async () => {
      /**
       * "Bangalore" must stay "Bangalore" rather than being canonicalised to
       * "Bengaluru" on the way in. _preference_snapshot compares
       * case-sensitively, so a form that rewrites what it loads would make an
       * untouched Save invalidate the user's cached rankings.
       */
      vi.spyOn(profileService, 'get').mockResolvedValue(
        profileFixture({
          country_code: 'IN',
          salary_currency: 'INR',
          preferred_locations: ['Pune', 'Bangalore'],
        }),
      )
      renderApp()

      expect(await screen.findByLabelText('Country')).toHaveValue('India')
      expect(screen.getByLabelText('Currency')).toHaveValue('Indian Rupee')
      expect(screen.getByRole('button', { name: 'Remove Pune' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Remove Bangalore' })).toBeInTheDocument()
    })
  })
})
