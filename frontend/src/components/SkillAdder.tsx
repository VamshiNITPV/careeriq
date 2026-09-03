import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ApiError } from '@/services/apiClient'
import { skillService } from '@/services/resumeService'
import type { Skill } from '@/types/resume'

/**
 * Type-ahead for adding a skill by hand.
 *
 * Falls back to creating the skill when the taxonomy does not know it. No
 * taxonomy is ever complete, and a search box that can only offer what already
 * exists tells users their real skill "does not exist" — a dead end with no
 * way forward.
 */

const DEBOUNCE_MS = 250

export function SkillAdder({ onAdded }: { onAdded: () => void }) {
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Skill[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    const trimmed = query.trim()
    if (timer.current !== null) window.clearTimeout(timer.current)

    if (trimmed.length < 2) {
      setMatches([])
      return
    }

    // Debounced: a request per keystroke would fire a dozen for one word and
    // arrive out of order.
    setIsSearching(true)
    timer.current = window.setTimeout(() => {
      skillService
        .search(trimmed)
        .then(setMatches)
        .catch(() => setMatches([]))
        .finally(() => setIsSearching(false))
    }, DEBOUNCE_MS)

    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    }
  }, [query])

  async function add(action: () => Promise<unknown>) {
    setError(null)
    setIsAdding(true)
    try {
      await action()
      setQuery('')
      setMatches([])
      onAdded()
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.status === 409
            ? 'That skill is already on your profile.'
            : caught.message
          : 'Could not add that skill.',
      )
    } finally {
      setIsAdding(false)
    }
  }

  const trimmed = query.trim()
  // Only offer creation when nothing matches exactly, so a typo does not become
  // a near-duplicate of a skill that already exists.
  const exactMatch = matches.some((m) => m.name.toLowerCase() === trimmed.toLowerCase())
  const canCreate = trimmed.length >= 2 && !isSearching && !exactMatch

  return (
    <div>
      <label htmlFor="skill-search" className="block text-sm font-medium text-slate-900">
        Add a skill
      </label>
      <p className="mt-1 text-sm text-slate-600">
        Anything the parser missed. Start typing to search, or add your own.
      </p>

      <div className="mt-2 flex gap-2">
        <input
          id="skill-search"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Bun, Svelte, Figma"
          autoComplete="off"
          aria-describedby={error !== null ? 'skill-add-error' : undefined}
          className="block w-full rounded-md border-0 px-3 py-2 text-slate-900 shadow-sm ring-1 ring-slate-300 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 focus:ring-inset focus:outline-none"
        />
      </div>

      {error !== null && (
        <p id="skill-add-error" className="mt-2 text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {trimmed.length >= 2 && (
        <div className="mt-2 space-y-1">
          {matches.map((skill) => (
            <button
              key={skill.id}
              type="button"
              disabled={isAdding}
              onClick={() => void add(() => skillService.add(skill.id))}
              className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-slate-100 disabled:opacity-50"
            >
              <span className="font-medium text-slate-900">{skill.name}</span>
              {skill.category !== null && (
                <span className="text-xs text-slate-500">{skill.category}</span>
              )}
            </button>
          ))}

          {canCreate && (
            <Button
              variant="secondary"
              size="sm"
              isLoading={isAdding}
              className="w-full justify-start"
              onClick={() => void add(() => skillService.addByName(trimmed))}
            >
              Add “{trimmed}” as a new skill
            </Button>
          )}

          {isSearching && matches.length === 0 && (
            <p className="px-3 py-2 text-sm text-slate-500">Searching…</p>
          )}
        </div>
      )}
    </div>
  )
}
