/**
 * The browse list's filters and page, read from and written to the URL.
 *
 * `/jobs?q=python&work_mode=REMOTE&offset=20` describes the list completely, so
 * leaving the page and coming back restores it — which is the whole reason this
 * moved out of `useState`. A refresh survives it too, and a filtered list
 * becomes a link that can be bookmarked or sent to someone.
 *
 * Pure, and deliberately outside React: the parsing is the part most worth
 * testing and the part least worth rendering a page to test. It is also the one
 * place the five parameter names are written down.
 *
 * **Everything is validated on read, because a URL is user input.** Anyone can
 * type `?work_mode=BANANA`, and it must not reach the API — FastAPI answers 422
 * for a value outside the enum, so an unvalidated read turns a mangled URL into
 * a broken page.
 */

import { EXPERIENCE_YEAR_OPTIONS, POSTED_WITHIN_OPTIONS } from '@/types/job'
import {
  EMPLOYMENT_TYPES,
  WORK_MODES,
  type EmploymentType,
  type WorkMode,
} from '@/types/profile'

/** One page of the browse list. */
export const PAGE_SIZE = 20

/**
 * Deep enough that nobody reaches it by paging, shallow enough that
 * `?offset=99999999` cannot ask the database to count its way there.
 */
const MAX_OFFSET = 10_000

/**
 * The five filters, named as the API names them.
 *
 * An array with the type derived from it, rather than the other way round, so
 * "clear every filter" can iterate the list instead of restating it — a sixth
 * filter added here is then cleared without anyone remembering to.
 */
export const JOB_FILTER_KEYS = [
  'q',
  'work_mode',
  'employment_type',
  'years_experience',
  'posted_within_days',
  'min_score',
  'exclude_applied',
] as const

export type JobFilterKey = (typeof JOB_FILTER_KEYS)[number]

/**
 * How the list is ordered. `sort` is **not** in `JOB_FILTER_KEYS`.
 *
 * It is not a filter: it narrows nothing, and "Clear all filters" must not throw
 * someone out of match mode as a side effect of clearing a work-mode dropdown.
 */
export const SORT_OPTIONS = [
  { value: 'recent', label: 'Newest first' },
  { value: 'match', label: 'Best match for me' },
] as const

export type JobSort = (typeof SORT_OPTIONS)[number]['value']

/** The `min_score` choices, as scores a reader can reason about. */
export const MIN_SCORE_OPTIONS = [
  { value: '50', label: '50 and above' },
  { value: '60', label: '60 and above' },
  { value: '70', label: '70 and above' },
] as const

export interface JobListParams {
  q: string
  workMode: WorkMode | ''
  employmentType: EmploymentType | ''
  /**
   * '' is "Any"; otherwise '0'…'10'. Still the option *string*, not a number,
   * because `Number('0')` is falsy and every check written on the converted
   * value would silently drop the "0+ years" filter.
   */
  yearsValue: string
  /** '' is "Any time"; otherwise '7' | '14' | '30'. */
  postedWithin: string
  /** 'recent' unless the URL says otherwise. */
  sort: JobSort
  /**
   * '' is "Any score"; otherwise '50' | '60' | '70'. A string for the same
   * reason `yearsValue` is one.
   *
   * Only meaningful under `sort=match` — the API answers 422 if it arrives
   * without it, so `requestFilters` drops it in browse mode rather than letting
   * a stale URL break the page.
   */
  minScore: string
  /**
   * Whether to leave out jobs already applied to. Defaults to **true**, matching
   * the API, so the common request omits it entirely.
   */
  excludeApplied: boolean
  /** At least 0, and always a multiple of `PAGE_SIZE`. */
  offset: number
}

/**
 * The option whose value this is, or '' if the URL made it up.
 *
 * `.find()` rather than `.includes()` or an index: under
 * `noUncheckedIndexedAccess` an index yields `T | undefined`, and `.includes()`
 * narrows nothing — both routes end in a cast. Reading the matched option's own
 * `value` gets the narrowed type for free, and works unchanged for the lists
 * typed `{ value: WorkMode }[]` and the ones inferred `{ value: string }[]`.
 */
function readOption<T extends string>(
  raw: string | null,
  options: readonly { value: T; label: string }[],
): T | '' {
  if (raw === null) return ''
  return options.find((option) => option.value === raw)?.value ?? ''
}

/** Everything the browse list needs, with anything the URL invented removed. */
export function readJobListParams(params: URLSearchParams): JobListParams {
  const raw = Number(params.get('offset') ?? '')
  const offset =
    Number.isInteger(raw) && raw > 0 && raw <= MAX_OFFSET
      ? // Snapped to a page boundary. An off-grid `?offset=37` would otherwise
        // stay off-grid forever: Previous only ever subtracts PAGE_SIZE, so
        // the pager could never land back on a real page.
        Math.floor(raw / PAGE_SIZE) * PAGE_SIZE
      : 0

  return {
    // Trimmed here, so `?q=%20%20` is no filter at all rather than one the page
    // reports as active and the request then drops.
    q: (params.get('q') ?? '').trim(),
    workMode: readOption(params.get('work_mode'), WORK_MODES),
    employmentType: readOption(params.get('employment_type'), EMPLOYMENT_TYPES),
    yearsValue: readOption(params.get('years_experience'), EXPERIENCE_YEAR_OPTIONS),
    postedWithin: readOption(params.get('posted_within_days'), POSTED_WITHIN_OPTIONS),
    // `|| 'recent'` rather than a bare read: `?sort=banana` must fall back to the
    // default ordering, not send an invented value the API answers 422 to.
    sort: readOption(params.get('sort'), SORT_OPTIONS) || 'recent',
    minScore: readOption(params.get('min_score'), MIN_SCORE_OPTIONS),
    // Absent means on, so only the literal string 'false' turns it off. Anything
    // else in the URL leaves the safer default in place.
    excludeApplied: params.get('exclude_applied') !== 'false',
    offset,
  }
}

/**
 * The parameters to actually send, given the mode.
 *
 * `min_score` and `exclude_applied` mean nothing to a date-sorted list, and the
 * API rejects `min_score` without `sort=match` rather than ignoring it — so a
 * URL carrying a stale `?min_score=60` after switching back to Newest first
 * would 422 the page. Dropped here rather than guarded at each call site.
 */
export function requestFilters(params: JobListParams): {
  q: string
  work_mode: string
  employment_type: string
  years_experience: string
  posted_within_days: string
  sort?: JobSort
  min_score?: string
  exclude_applied?: string
} {
  const base = {
    q: params.q,
    work_mode: params.workMode,
    employment_type: params.employmentType,
    years_experience: params.yearsValue,
    posted_within_days: params.postedWithin,
  }
  if (params.sort !== 'match') return base
  return {
    ...base,
    sort: 'match',
    ...(params.minScore !== '' ? { min_score: params.minScore } : {}),
    // Sent only when false: true is the API's default, and omitting it keeps the
    // common request short and its URL readable in a log.
    ...(params.excludeApplied ? {} : { exclude_applied: 'false' }),
  }
}

/**
 * Set filters, out of however many the caller counts.
 *
 * Compared against '' rather than tested for truthiness, for the reason
 * `yearsValue` gives above: '0' is a real filter and `Number('0')` is falsy.
 * Miss it and "0+ years" counts as nothing.
 *
 * Both counters below take the validated params, never raw `URLSearchParams`.
 * `?work_mode=BANANA` is not a filter, and counting query-string keys would
 * advertise one that was never sent — the same lie the empty state refuses to
 * tell.
 */
function countSet(values: readonly string[]): number {
  return values.filter((value) => value !== '').length
}

/**
 * How many filters are set, the search term included.
 *
 * This is "is the list narrowed at all?" — it decides whether the empty state
 * offers to add a job or to widen the search, and whether there is anything for
 * "Clear all filters" to do.
 *
 * **Two deliberate exclusions.** `sort` is not counted because it narrows
 * nothing; a reader who switched to match order has not filtered anything and
 * would be puzzled by "1 filter" over untouched dropdowns. `excludeApplied` is
 * not counted because it *defaults to on* — counting it would open every fresh
 * page reading "Filters 1", and its off state is the less-filtered one, so
 * counting only the non-default would be stranger still.
 */
export function countActiveJobFilters({
  q,
  workMode,
  employmentType,
  yearsValue,
  postedWithin,
  minScore,
}: JobListParams): number {
  return countSet([q, workMode, employmentType, yearsValue, postedWithin, minScore])
}

/**
 * How many filters are set *behind the Filters button* — the search term
 * excluded, because it is not behind it.
 *
 * Search is its own control in its own place on the page. A badge that counted
 * it would promise something the panel does not contain: type "python" and the
 * button would read "Filters 1" over four untouched dropdowns.
 */
export function countPanelFilters({
  workMode,
  employmentType,
  yearsValue,
  postedWithin,
  minScore,
}: JobListParams): number {
  return countSet([workMode, employmentType, yearsValue, postedWithin, minScore])
}

/**
 * Set or clear one filter, and drop the page with it.
 *
 * **Page one is reset here, at the write.** It used to be an effect watching the
 * filters, which cannot survive the move to the URL: an effect also fires on
 * mount, so arriving back at `/jobs?offset=20` would wipe the very offset the
 * URL was restoring.
 */
export function setJobListFilter(
  previous: URLSearchParams,
  key: JobFilterKey,
  value: string,
): URLSearchParams {
  // Copied, never mutated: React Router memoises the object it hands us.
  const next = new URLSearchParams(previous)
  // Deleted rather than set to '', so page one of an unfiltered list is a bare
  // `/jobs` — one canonical URL per view, instead of a bar that slowly fills
  // with `?work_mode=&years_experience=` as filters are cleared.
  if (value === '') next.delete(key)
  else next.set(key, value)
  next.delete('offset')
  return next
}

/**
 * Drop every filter, and the page with them.
 *
 * One write, not five calls to `setJobListFilter` — that would be five
 * navigations, five history entries and five refetches for one tap.
 *
 * The page goes for the same reason it goes on any single filter change:
 * clearing filters while on page three would otherwise show an empty page three
 * of a list that now has one page.
 *
 * **The caller must reset the search box in the same handler.** The input is
 * controlled by local state that the URL does not own, and its debounce writes
 * whatever it still holds — so clearing the URL alone gets `?q=python` written
 * straight back 300ms later.
 */
export function clearJobListFilters(previous: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(previous)
  for (const key of JOB_FILTER_KEYS) next.delete(key)
  next.delete('offset')
  return next
}

/**
 * Change the ordering, and drop the page with it.
 *
 * Separate from `setJobListFilter` because `sort` is not a filter key — putting
 * it in `JOB_FILTER_KEYS` to reuse this function would make "Clear all filters"
 * silently return the reader to date order, which is not what that button says.
 *
 * The page resets for the same reason a filter change resets it: page three of a
 * date-ordered list has no counterpart in a match-ordered one, so keeping the
 * offset would land on an unrelated screenful.
 *
 * Switching **away** from match also drops `min_score`. The API answers 422 to
 * `min_score` without `sort=match`, and leaving it in the URL would arm a broken
 * request for anyone who later shares or reloads that address.
 */
export function setJobListSort(previous: URLSearchParams, sort: JobSort): URLSearchParams {
  const next = new URLSearchParams(previous)
  if (sort === 'recent') {
    next.delete('sort')
    next.delete('min_score')
    next.delete('exclude_applied')
  } else {
    next.set('sort', sort)
  }
  next.delete('offset')
  return next
}

export function setJobListOffset(
  previous: URLSearchParams,
  offset: number,
): URLSearchParams {
  const next = new URLSearchParams(previous)
  if (offset <= 0) next.delete('offset')
  else next.set('offset', String(offset))
  return next
}
