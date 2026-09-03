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
    expect(await screen.findByLabelText('Full name')).toBeInTheDocument()
    expect(screen.getByLabelText('Headline')).toBeInTheDocument()
    expect(screen.getByLabelText('Target roles')).toBeInTheDocument()
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

    const name = screen.getByLabelText('Full name')
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

    await screen.findByLabelText('Full name')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('corr-42')
  })

  it('sends the full preference set, not a partial one', async () => {
    // The endpoint replaces wholesale, so omitting a key would silently clear it.
    const user = userEvent.setup()
    vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
    const replace = vi
      .spyOn(profileService, 'replacePreferences')
      .mockResolvedValue(profileFixture())
    renderApp()

    const roles = await screen.findByLabelText('Target roles')
    await user.type(roles, 'Backend Engineer, ML Engineer')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[1]!)

    await waitFor(() => expect(replace).toHaveBeenCalled())
    const sent = replace.mock.calls[0]![0]
    expect(sent.target_roles).toEqual(['Backend Engineer', 'ML Engineer'])
    expect(sent).toHaveProperty('preferred_work_modes')
    expect(sent).toHaveProperty('open_to_relocation')
  })

  describe('pickers', () => {
    it('adds no button named "Save"', async () => {
      // Two tests above index getAllByRole('button', { name: 'Save' })
      // positionally. Asserting the count here turns a baffling failure in
      // those into an obvious one here.
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      renderApp()

      await screen.findByLabelText('Full name')
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
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
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
      const user = userEvent.setup()
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture())
      renderApp()

      const locations = await screen.findByLabelText('Preferred locations')
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
      vi.spyOn(profileService, 'get').mockResolvedValue(profileFixture())
      const replace = vi
        .spyOn(profileService, 'replacePreferences')
        .mockResolvedValue(profileFixture())
      renderApp()

      const locations = await screen.findByLabelText('Preferred locations')
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
