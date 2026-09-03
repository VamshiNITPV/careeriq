import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { CareerProfile } from '@/components/career/CareerProfile'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Combobox } from '@/components/ui/Combobox'
import { Input } from '@/components/ui/Input'
import { MultiCombobox } from '@/components/ui/MultiCombobox'
import { Spinner } from '@/components/ui/Spinner'
import { Textarea } from '@/components/ui/Textarea'
import { COUNTRY_OPTIONS } from '@/data/countries'
import { CURRENCY_OPTIONS, PINNED_CURRENCIES } from '@/data/currencies'
import { LOCATION_OPTIONS } from '@/data/locations'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/services/apiClient'
import { profileService } from '@/services/profileService'
import {
  EMPLOYMENT_TYPES,
  WORK_MODES,
  type EmploymentType,
  type Profile,
  type ProfilePersonalUpdate,
  type WorkMode,
} from '@/types/profile'
import { avatarColourFor, displayNameFor, initialsFor } from '@/utils/initials'
import { cn } from '@/utils/cn'

/**
 * Profile page.
 *
 * Two independently-saveable sections, matching the two endpoints. Each Save is
 * atomic on its own, which avoids the partial-failure state a single button
 * would create ("your details saved but your preferences didn't").
 *
 * Form state is local, seeded once. It is deliberately NOT derived from the
 * profile in context: with two sections, re-seeding when the *other* one saves
 * would clobber whatever the user is currently typing.
 */

function Section({
  title,
  description,
  children,
  onSubmit,
  isSaving,
  saved,
  error,
}: {
  title: string
  description: string
  children: ReactNode
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  isSaving: boolean
  saved: boolean
  error: ApiError | null
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-slate-200 bg-white p-6"
      noValidate
    >
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-sm text-slate-600">{description}</p>

      {error && (
        <Alert tone="error" className="mt-4" correlationId={error.correlationId}>
          {error.fieldErrors.length > 0
            ? error.fieldErrors.map((f) => `${f.field}: ${f.message}`).join('; ')
            : error.message}
        </Alert>
      )}

      <div className="mt-5 space-y-4">{children}</div>

      <div className="mt-6 flex items-center gap-3">
        <Button type="submit" isLoading={isSaving}>
          Save
        </Button>
        {saved && !isSaving && (
          <span role="status" className="text-sm text-emerald-600">
            Saved
          </span>
        )}
      </div>
    </form>
  )
}

/**
 * Comma-separated text ↔ string[]. Keeps a free-text list editable as text.
 *
 * Still used by target_roles, which stays a plain text field — roles are open
 * vocabulary with no useful list to pick from, unlike locations.
 */
function toList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function CheckboxGroup<T extends string>({
  legend,
  options,
  selected,
  onChange,
}: {
  legend: string
  options: { value: T; label: string }[]
  selected: T[]
  onChange: (next: T[]) => void
}) {
  return (
    <fieldset>
      <legend className="text-sm font-medium text-slate-900">{legend}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => {
          const checked = selected.includes(option.value)
          return (
            <label
              key={option.value}
              className={cn(
                'cursor-pointer rounded-full border px-3 py-1.5 text-sm transition-colors',
                checked
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                  : 'border-slate-300 text-slate-600 hover:bg-slate-50',
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                onChange={() =>
                  onChange(
                    checked
                      ? selected.filter((v) => v !== option.value)
                      : [...selected, option.value],
                  )
                }
              />
              {option.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

export function ProfilePage() {
  const { user, setProfile } = useAuth()

  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Personal section
  const [personal, setPersonal] = useState<ProfilePersonalUpdate>({})
  const [savingPersonal, setSavingPersonal] = useState(false)
  const [personalSaved, setPersonalSaved] = useState(false)
  const [personalError, setPersonalError] = useState<ApiError | null>(null)

  // Preferences section
  const [targetRoles, setTargetRoles] = useState('')
  const [preferredLocations, setPreferredLocations] = useState<string[]>([])
  const [workModes, setWorkModes] = useState<WorkMode[]>([])
  const [employmentTypes, setEmploymentTypes] = useState<EmploymentType[]>([])
  const [minSalary, setMinSalary] = useState('')
  const [currency, setCurrency] = useState('')
  const [relocate, setRelocate] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)
  const [prefsSaved, setPrefsSaved] = useState(false)
  const [prefsError, setPrefsError] = useState<ApiError | null>(null)

  /**
   * Seeding is split per section so that saving one never re-seeds the other.
   * Each Save returns the whole profile, and re-seeding wholesale would discard
   * whatever the user had already typed into the section they did not save.
   */
  const seedPersonal = useCallback((profile: Profile) => {
    setPersonal({
      full_name: profile.full_name ?? '',
      headline: profile.headline ?? '',
      location: profile.location ?? '',
      country_code: profile.country_code ?? '',
      phone: profile.phone ?? '',
      summary: profile.summary ?? '',
      linkedin_url: profile.linkedin_url ?? '',
      github_url: profile.github_url ?? '',
      portfolio_url: profile.portfolio_url ?? '',
    })
  }, [])

  const seedPreferences = useCallback((profile: Profile) => {
    setTargetRoles(profile.target_roles.join(', '))
    // Verbatim, with no canonicalisation. A stored "Bangalore" stays
    // "Bangalore": rewriting it to "Bengaluru" here would make an untouched
    // form save a changed array, and _preference_snapshot compares
    // case-sensitively, so that would invalidate the user's cached rankings for
    // no reason.
    setPreferredLocations(profile.preferred_locations)
    setWorkModes(profile.preferred_work_modes)
    setEmploymentTypes(profile.preferred_employment_types)
    setMinSalary(profile.min_salary_expectation ?? '')
    setCurrency(profile.salary_currency ?? '')
    setRelocate(profile.open_to_relocation)
  }, [])

  useEffect(() => {
    profileService
      .get()
      .then((profile) => {
        seedPersonal(profile)
        seedPreferences(profile)
        setProfile(profile)
      })
      .catch(() => setLoadError('Could not load your profile.'))
      .finally(() => setLoaded(true))
    // setProfile is stable; seeding must happen once, not on every context change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedPersonal, seedPreferences])

  function field(key: keyof ProfilePersonalUpdate) {
    return {
      value: personal[key] ?? '',
      onChange: (e: { target: { value: string } }) =>
        setPersonal((prev) => ({ ...prev, [key]: e.target.value })),
    }
  }

  async function savePersonal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPersonalError(null)
    setPersonalSaved(false)
    setSavingPersonal(true)
    try {
      // The response is the full profile, so pushing it into context updates
      // the header initials in the same commit — no refetch.
      const updated = await profileService.updatePersonal(personal)
      setProfile(updated)
      seedPersonal(updated)
      setPersonalSaved(true)
    } catch (caught) {
      setPersonalError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, 'INTERNAL_ERROR', 'Could not save your details.'),
      )
    } finally {
      setSavingPersonal(false)
    }
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPrefsError(null)
    setPrefsSaved(false)
    setSavingPrefs(true)
    try {
      const updated = await profileService.replacePreferences({
        target_roles: toList(targetRoles),
        preferred_locations: preferredLocations,
        preferred_work_modes: workModes,
        preferred_employment_types: employmentTypes,
        min_salary_expectation: minSalary.trim() || null,
        salary_currency: currency.trim() || null,
        open_to_relocation: relocate,
      })
      setProfile(updated)
      // Re-seed from the response so the chips reflect what the server actually
      // stored. _clean_list strips and dedupes; without this any divergence
      // would sit on screen looking saved until the next reload.
      seedPreferences(updated)
      setPrefsSaved(true)
    } catch (caught) {
      setPrefsError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, 'INTERNAL_ERROR', 'Could not save your preferences.'),
      )
    } finally {
      setSavingPrefs(false)
    }
  }

  if (!loaded) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="size-8 text-indigo-600" label="Loading your profile" />
      </div>
    )
  }

  const name = displayNameFor(personal.full_name, user?.email ?? '')

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <span
          className={cn(
            'grid size-14 shrink-0 place-items-center rounded-full text-lg font-semibold text-white',
            avatarColourFor(user?.id ?? ''),
          )}
          aria-hidden="true"
        >
          {initialsFor(personal.full_name, user?.email ?? '')}
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold tracking-tight text-slate-900">{name}</h1>
          <p className="truncate text-sm text-slate-600">{user?.email}</p>
        </div>
      </div>

      {loadError !== null && <Alert tone="error">{loadError}</Alert>}

      <Alert tone="info">
        Details found in your resume fill in any field you have left blank. Anything you type
        here is never overwritten by a later upload.
      </Alert>

      <Section
        title="Your details"
        description="How you appear across CareerIQ."
        onSubmit={(e) => void savePersonal(e)}
        isSaving={savingPersonal}
        saved={personalSaved}
        error={personalError}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" autoComplete="name" {...field('full_name')} />
          <Input
            label="Headline"
            hint="e.g. Backend Engineer"
            {...field('headline')}
          />
          <Input label="Location" autoComplete="address-level2" {...field('location')} />
          {/*
            Not field('country_code'): that helper returns an event-shaped
            onChange, and making the picker emit { target: { value } } to fit it
            would be the tail wagging the dog.
          */}
          <Combobox
            label="Country"
            options={COUNTRY_OPTIONS}
            value={personal.country_code ?? ''}
            onChange={(next) => setPersonal((prev) => ({ ...prev, country_code: next }))}
            placeholder="Search countries"
          />
          <Input label="Phone" type="tel" autoComplete="tel" {...field('phone')} />
        </div>

        <Textarea label="Summary" rows={4} {...field('summary')} />

        <div className="grid gap-4 sm:grid-cols-3">
          <Input label="LinkedIn" placeholder="linkedin.com/in/you" {...field('linkedin_url')} />
          <Input label="GitHub" placeholder="github.com/you" {...field('github_url')} />
          <Input label="Portfolio" placeholder="you.dev" {...field('portfolio_url')} />
        </div>
      </Section>

      <Section
        title="Career preferences"
        description="What you are looking for. These will drive job matching."
        onSubmit={(e) => void savePreferences(e)}
        isSaving={savingPrefs}
        saved={prefsSaved}
        error={prefsError}
      >
        <Input
          label="Target roles"
          hint="Comma separated, e.g. Backend Engineer, ML Engineer"
          value={targetRoles}
          onChange={(e) => setTargetRoles(e.target.value)}
        />
        <MultiCombobox
          label="Preferred locations"
          options={LOCATION_OPTIONS}
          value={preferredLocations}
          onChange={setPreferredLocations}
          allowCustom
          // Mirrors MAX_LIST_ITEMS in backend/app/schemas/profile.py.
          max={20}
          hint="Search cities, or type your own. Remote and Anywhere are on the list."
          placeholder="Search locations"
        />

        <CheckboxGroup
          legend="Work mode"
          options={WORK_MODES}
          selected={workModes}
          onChange={setWorkModes}
        />
        <CheckboxGroup
          legend="Employment type"
          options={EMPLOYMENT_TYPES}
          selected={employmentTypes}
          onChange={setEmploymentTypes}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Minimum salary"
            inputMode="decimal"
            value={minSalary}
            onChange={(e) => setMinSalary(e.target.value)}
          />
          <Combobox
            label="Currency"
            options={CURRENCY_OPTIONS}
            pinnedValues={PINNED_CURRENCIES}
            pinnedLabel="Common"
            restLabel="All currencies"
            value={currency}
            onChange={setCurrency}
            // Required alongside a salary: an unlabelled number is useless to
            // the matching engine, and the API rejects one without the other.
            hint="Required if you set a minimum salary."
            placeholder="Search currencies"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={relocate}
            onChange={(e) => setRelocate(e.target.checked)}
            className="size-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
          />
          Open to relocation
        </label>
      </Section>

      {/*
        Below the two saved sections, not inside them: each entry saves on its
        own, so folding these into a form with one Save button would imply an
        atomicity that does not exist.
      */}
      <CareerProfile />
    </div>
  )
}
