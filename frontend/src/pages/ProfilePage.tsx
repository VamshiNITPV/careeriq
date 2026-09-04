import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type RefObject,
} from 'react'
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
  formRef,
}: {
  title: string
  description: string
  children: ReactNode
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  isSaving: boolean
  saved: boolean
  error: ApiError | null
  /** So a blocked submit can move focus to the first invalid control. */
  formRef?: RefObject<HTMLFormElement | null>
}) {
  return (
    <form
      ref={formRef}
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

/**
 * Required-field rules, deliberately stricter than the API.
 *
 * ProfilePersonalUpdate defaults every field and treats "" as an intentional
 * clear; PreferencesReplace only enforces the currency/salary pair. So the
 * server would happily store a profile with no name and no target roles — and
 * that profile is useless to job matching, which is the entire point of the
 * section. The asterisk is the frontend saying so.
 *
 * Every rule is trim-based, mirroring the server's own `_blank_to_none` and
 * `_clean_list`, so the client never blocks something the server would have
 * accepted as non-empty.
 *
 * Each message repeats the field's format guidance, because Input, Combobox and
 * MultiCombobox all suppress `hint` whenever `error` is set — so "Comma
 * separated, e.g. …" disappears at exactly the moment the user needs it.
 */
function fullNameError(value: string): string | undefined {
  return value.trim() === '' ? 'Enter your full name.' : undefined
}

function targetRolesError(value: string): string | undefined {
  return toList(value).length === 0
    ? 'Add at least one target role, separated by commas.'
    : undefined
}

function preferredLocationsError(value: readonly string[]): string | undefined {
  return value.length === 0
    ? 'Add at least one preferred location. Remote and Anywhere count.'
    : undefined
}

/**
 * Mirrors `_currency_required_with_salary` in backend/app/schemas/profile.py —
 * in that direction only.
 *
 * A currency with no salary is legal server-side and is a real thing to want
 * ("pay me in INR, no floor stated"), so enforcing the reverse here would be
 * the frontend inventing a constraint the API does not have.
 */
function currencyError(currency: string, minSalary: string): string | undefined {
  if (minSalary.trim() === '') return undefined
  return currency.trim() === '' ? 'Choose the currency for your minimum salary.' : undefined
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
  /**
   * How many times Save has been pressed on this section.
   *
   * Zero means "say nothing": a profile the user has not filled in yet is
   * invalid by construction, and greeting them with red messages before they
   * type a character is hostile. From the first press onwards the messages are
   * live, so one clears the moment its field becomes valid.
   *
   * Deliberately not reset after a successful save — a later edit that empties
   * a required field should get feedback immediately, without another press.
   */
  const [personalAttempts, setPersonalAttempts] = useState(0)
  const personalFormRef = useRef<HTMLFormElement>(null)

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
  const [prefsAttempts, setPrefsAttempts] = useState(0)
  const prefsFormRef = useRef<HTMLFormElement>(null)

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

  /**
   * Ungated on purpose — the submit guards below need the true answer on the
   * very first click, while the attempt counters are still 0. Gating happens at
   * the point of display, in the JSX.
   *
   * Derived rather than stored, matching localPasswordError in
   * ResetPasswordPage. A stored error would need a clearing policy, and would
   * go stale: typing spaces into a name would blind-clear a message that is
   * still true.
   */
  const fullNameProblem = fullNameError(personal.full_name ?? '')
  const targetRolesProblem = targetRolesError(targetRoles)
  const locationsProblem = preferredLocationsError(preferredLocations)
  const currencyProblem = currencyError(currency, minSalary)

  const personalInvalid = fullNameProblem !== undefined
  const prefsInvalid =
    targetRolesProblem !== undefined ||
    locationsProblem !== undefined ||
    currencyProblem !== undefined

  /**
   * Move focus to the first field that failed.
   *
   * Without this a blocked submit is silent to anyone not looking at the
   * screen: focus stays on Save, the inline message is not a live region, and
   * an aria-invalid flip is not announced.
   *
   * In an effect rather than in the handler because on the first blocked submit
   * the error markup does not exist yet when the handler runs. Keyed on the
   * attempt counter so it fires once per press, not on every keystroke
   * afterwards.
   */
  useEffect(() => {
    if (personalAttempts === 0 || !personalInvalid) return
    personalFormRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    // Only the counter: re-running when the validity changes would steal focus
    // mid-typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personalAttempts])

  useEffect(() => {
    if (prefsAttempts === 0 || !prefsInvalid) return
    prefsFormRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefsAttempts])

  async function savePersonal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Cleared above the guard: a stale server Alert or a "Saved" chip from an
    // earlier attempt must not sit above the fresh inline messages, giving two
    // contradictory accounts of the same click.
    setPersonalError(null)
    setPersonalSaved(false)
    setPersonalAttempts((n) => n + 1)

    // Above setSavingPersonal(true): Button disables itself while isLoading, so
    // entering that state for a request which never fires would blink the
    // button disabled for nothing.
    if (personalInvalid) return

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
    setPrefsAttempts((n) => n + 1)

    if (prefsInvalid) return

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
        formRef={personalFormRef}
        isSaving={savingPersonal}
        saved={personalSaved}
        error={personalError}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Full name"
            autoComplete="name"
            required
            error={personalAttempts > 0 ? fullNameProblem : undefined}
            {...field('full_name')}
          />
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
        formRef={prefsFormRef}
        isSaving={savingPrefs}
        saved={prefsSaved}
        error={prefsError}
      >
        <Input
          label="Target roles"
          required
          hint="Comma separated, e.g. Backend Engineer, ML Engineer"
          value={targetRoles}
          onChange={(e) => setTargetRoles(e.target.value)}
          error={prefsAttempts > 0 ? targetRolesProblem : undefined}
        />
        <MultiCombobox
          label="Preferred locations"
          options={LOCATION_OPTIONS}
          value={preferredLocations}
          onChange={setPreferredLocations}
          allowCustom
          // Mirrors MAX_LIST_ITEMS in backend/app/schemas/profile.py.
          max={20}
          required
          hint="Search cities, or type your own. Remote and Anywhere are on the list."
          error={prefsAttempts > 0 ? locationsProblem : undefined}
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
            // Conditional, mirroring _currency_required_with_salary: with no
            // salary this field really is optional, and an asterisk there would
            // be a promise the form does not keep. Typing a salary popping a red
            // * onto its neighbour also explains the coupling better than a
            // sentence can.
            required={minSalary.trim() !== ''}
            hint="Required if you set a minimum salary."
            error={prefsAttempts > 0 ? currencyProblem : undefined}
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
