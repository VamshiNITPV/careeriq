import { describe, expect, it } from 'vitest'
import {
  clearJobListFilters,
  countActiveJobFilters,
  JOB_FILTER_KEYS,
  PAGE_SIZE,
  readJobListParams,
  setJobListFilter,
  setJobListOffset,
} from './jobListParams'

const read = (search: string) => readJobListParams(new URLSearchParams(search))

describe('readJobListParams', () => {
  it('reads a full URL', () => {
    expect(read('q=python&work_mode=REMOTE&employment_type=FULL_TIME&offset=20')).toEqual({
      q: 'python',
      workMode: 'REMOTE',
      employmentType: 'FULL_TIME',
      yearsValue: '',
      postedWithin: '',
      offset: 20,
    })
  })

  it('reads an empty URL as no filters and page one', () => {
    expect(read('')).toEqual({
      q: '',
      workMode: '',
      employmentType: '',
      yearsValue: '',
      postedWithin: '',
      offset: 0,
    })
  })

  describe('values the URL made up', () => {
    /**
     * The URL is user input, and the API is strict: FastAPI answers 422 for a
     * value outside its enum, so an unvalidated read would turn a typo in the
     * address bar into a broken page.
     */

    it('drops an invented option', () => {
      const params = read('work_mode=BANANA&employment_type=NONSENSE')

      expect(params.workMode).toBe('')
      expect(params.employmentType).toBe('')
    })

    it('drops an out-of-range number', () => {
      expect(read('years_experience=99').yearsValue).toBe('')
      expect(read('posted_within_days=999').postedWithin).toBe('')
    })

    it('drops a value of the wrong case', () => {
      // The backend enum is case-sensitive, so this must be rejected here
      // rather than sent and refused.
      expect(read('work_mode=remote').workMode).toBe('')
      expect(read('employment_type=full_time').employmentType).toBe('')
    })
  })

  it('keeps "0+ years", which is a real filter', () => {
    // The zero trap: Number('0') is falsy, so anything that converts early
    // silently drops this one.
    expect(read('years_experience=0').yearsValue).toBe('0')
  })

  it('trims the search term', () => {
    // Otherwise "?q=%20%20" is a filter the page reports as active and the
    // request then drops — an empty list with no visible cause.
    expect(read('q=%20%20python%20%20').q).toBe('python')
    expect(read('q=%20%20').q).toBe('')
  })

  describe('offset', () => {
    it('falls back to page one for anything that is not a page', () => {
      for (const search of ['', 'offset=', 'offset=abc', 'offset=-5', 'offset=1.5']) {
        expect(read(search).offset).toBe(0)
      }
    })

    it('refuses an offset deep enough to be a denial of service', () => {
      expect(read('offset=99999999').offset).toBe(0)
    })

    it('snaps an off-grid offset onto a page boundary', () => {
      // Previous only ever subtracts PAGE_SIZE, so an off-grid offset would
      // otherwise stay off-grid forever and the pager could never land on a
      // real page.
      expect(read('offset=37').offset).toBe(20)
      expect(read(`offset=${PAGE_SIZE}`).offset).toBe(PAGE_SIZE)
    })
  })
})

describe('countActiveJobFilters', () => {
  it('counts nothing for a bare URL', () => {
    expect(countActiveJobFilters(read(''))).toBe(0)
  })

  it('counts every filter', () => {
    const all = read(
      'q=python&work_mode=REMOTE&employment_type=FULL_TIME' +
        '&years_experience=5&posted_within_days=7',
    )

    expect(countActiveJobFilters(all)).toBe(5)
  })

  it('counts "0+ years", which is a real filter', () => {
    // The zero trap again, and this is now a third site that has to get it
    // right: a truthiness check would show "Filters" with no count while a
    // filter was quietly narrowing the list.
    expect(countActiveJobFilters(read('years_experience=0'))).toBe(1)
  })

  it('does not count a value the URL made up', () => {
    // It counts the validated params, not query-string keys — otherwise the
    // badge advertises a filter that was never sent to the API.
    expect(countActiveJobFilters(read('work_mode=BANANA&years_experience=99'))).toBe(0)
  })

  it('does not count the page', () => {
    expect(countActiveJobFilters(read('offset=20'))).toBe(0)
  })
})

describe('setJobListFilter', () => {
  it('sets a filter and drops the page with it', () => {
    // The rule that used to be an effect watching the filters. It moved here
    // because an effect also fires on mount, and would wipe the offset a
    // Back-navigation was restoring.
    const next = setJobListFilter(new URLSearchParams('offset=40'), 'work_mode', 'REMOTE')

    expect(next.get('work_mode')).toBe('REMOTE')
    expect(next.has('offset')).toBe(false)
  })

  it('deletes the key rather than leaving it blank', () => {
    // A blank still reads as "no filter", so the request would stay correct
    // while the address bar slowly filled with ?work_mode=&years_experience=.
    const next = setJobListFilter(new URLSearchParams('work_mode=REMOTE'), 'work_mode', '')

    expect(next.has('work_mode')).toBe(false)
    expect(next.toString()).toBe('')
  })

  it('leaves the params it was given alone', () => {
    // React Router memoises the object it hands the caller; mutating it would
    // change the current location's params underneath the render.
    const previous = new URLSearchParams('q=python')
    setJobListFilter(previous, 'q', 'java')

    expect(previous.get('q')).toBe('python')
  })
})

describe('clearJobListFilters', () => {
  it('drops every filter and the page', () => {
    const next = clearJobListFilters(
      new URLSearchParams(
        'q=python&work_mode=REMOTE&employment_type=FULL_TIME' +
          '&years_experience=5&posted_within_days=7&offset=40',
      ),
    )

    // toString rather than five has() calls: this is the one place that must
    // leave nothing behind, and an assertion listing the keys would pass while
    // missing a sixth one added later.
    expect(next.toString()).toBe('')
  })

  it('clears whatever JOB_FILTER_KEYS says a filter is', () => {
    // The reason the keys are an array with the type derived from it. Add a
    // sixth filter and it is cleared without anyone remembering to.
    const all = new URLSearchParams(JOB_FILTER_KEYS.map((key) => [key, 'x']))

    expect(clearJobListFilters(all).toString()).toBe('')
  })

  it('leaves the params it was given alone', () => {
    const previous = new URLSearchParams('q=python')
    clearJobListFilters(previous)

    expect(previous.get('q')).toBe('python')
  })
})

describe('setJobListOffset', () => {
  it('sets a page', () => {
    expect(setJobListOffset(new URLSearchParams('q=python'), 20).get('offset')).toBe('20')
  })

  it('drops the key for page one, so an unfiltered list is a bare /jobs', () => {
    const next = setJobListOffset(new URLSearchParams('offset=20'), 0)

    expect(next.has('offset')).toBe(false)
  })

  it('keeps the filters', () => {
    expect(setJobListOffset(new URLSearchParams('q=python'), 20).get('q')).toBe('python')
  })
})
