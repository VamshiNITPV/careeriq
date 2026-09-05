import { useState, type FormEvent } from 'react'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Input } from '@/components/ui/Input'
import { MonthPicker } from '@/components/ui/MonthPicker'
import { Select } from '@/components/ui/Select'
import { Textarea } from '@/components/ui/Textarea'
import { ApiError } from '@/services/apiClient'
import { careerService } from '@/services/careerService'
import { fromMonthInput, toMonthInput, type CareerKind } from '@/types/career'
import { cn } from '@/utils/cn'

/**
 * One editable list of career entries.
 *
 * Driven by a field spec rather than written four times. The four entity types
 * differ only in which fields they carry, and four copies of this list/edit/
 * delete logic is four places for it to drift — the same reasoning the API's
 * router factory uses.
 */

export interface FieldSpec {
  key: string
  label: string
  type: 'text' | 'textarea' | 'month' | 'checkbox' | 'select' | 'lines'
  options?: readonly { value: string; label: string }[]
  /** Rendered under the input. */
  hint?: string
  required?: boolean
  /** Half-width on wide screens. */
  half?: boolean
  /**
   * Key of a checkbox field that hides this one while it is ticked — how
   * "Ended" disappears once a role is marked current.
   *
   * A key rather than a predicate: the specs are static data read top to
   * bottom, and a function in the middle of them is harder to scan.
   */
  hiddenWhen?: string
}

/** Not applicable right now, because the checkbox it depends on is ticked. */
function isHidden(field: FieldSpec, draft: Record<string, string | boolean>): boolean {
  return field.hiddenWhen !== undefined && draft[field.hiddenWhen] === true
}

/**
 * Only what this component itself reads.
 *
 * Deliberately no `[key: string]: unknown` index signature: it would stop the
 * four concrete interfaces satisfying this constraint at all, and it would make
 * every field access in `renderSummary` `unknown` at the call site — losing the
 * type safety that is the whole reason the entities are typed.
 */
export interface CareerEntry {
  id: string
  source_version_id: string | null
  is_user_verified: boolean
}

interface CareerSectionProps<T extends CareerEntry> {
  kind: CareerKind
  title: string
  description: string
  /** What to call one of these, for buttons and the delete dialog. */
  noun: string
  items: T[]
  fields: readonly FieldSpec[]
  /** Headline and supporting line for a collapsed row. */
  renderSummary: (item: T) => { primary: string; secondary: string | null; meta: string | null }
  emptyHint: string
  onChanged: () => void
}

/** Blank values for every field, so an "add" form starts controlled. */
function emptyDraft(fields: readonly FieldSpec[]): Record<string, string | boolean> {
  return Object.fromEntries(
    fields.map((field) => [field.key, field.type === 'checkbox' ? false : '']),
  )
}

function toDraft<T extends CareerEntry>(
  item: T,
  fields: readonly FieldSpec[],
): Record<string, string | boolean> {
  // One cast, here, where the field spec is the thing driving the lookup.
  // Widening CareerEntry with an index signature instead would push `unknown`
  // into every caller.
  const record = item as unknown as Record<string, unknown>

  return Object.fromEntries(
    fields.map((field) => {
      const value = record[field.key]
      if (field.type === 'checkbox') return [field.key, value === true]
      if (field.type === 'month') return [field.key, toMonthInput((value as string | null) ?? null)]
      if (field.type === 'lines') return [field.key, ((value as string[] | null) ?? []).join('\n')]
      return [field.key, (value as string | null) ?? '']
    }),
  )
}

/** Draft back to an API payload. Blank strings become null, not "". */
function toPayload(
  draft: Record<string, string | boolean>,
  fields: readonly FieldSpec[],
): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  for (const field of fields) {
    // A hidden field is not "unchanged", it is *not applicable*: the server
    // rejects an end date on something marked ongoing, and omitting the key
    // would leave the stored one in place — exactly the CHECK violation.
    // Treating it as blank routes it through each type's own emptiness rule
    // below, so month becomes null, lines becomes [], and so on.
    const value = isHidden(field, draft) ? '' : draft[field.key]
    if (field.type === 'checkbox') {
      payload[field.key] = value === true
    } else if (field.type === 'month') {
      payload[field.key] = fromMonthInput(String(value ?? ''))
    } else if (field.type === 'lines') {
      payload[field.key] = String(value ?? '')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    } else {
      const text = String(value ?? '').trim()
      payload[field.key] = text === '' ? null : text
    }
  }
  return payload
}

export function CareerSection<T extends CareerEntry>({
  kind,
  title,
  description,
  noun,
  items,
  fields,
  renderSummary,
  emptyHint,
  onChanged,
}: CareerSectionProps<T>) {
  // Which row is open for editing, 'new' for the add form, or null.
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<T | null>(null)

  function openNew() {
    setError(null)
    setDraft(emptyDraft(fields))
    setEditing('new')
  }

  function openEdit(item: T) {
    setError(null)
    setDraft(toDraft(item, fields))
    setEditing(item.id)
  }

  function messageOf(caught: unknown): string {
    if (caught instanceof ApiError) {
      // Field errors first: "The end date cannot be before the start date" is
      // far more useful than "Invalid input".
      return caught.fieldErrors.length > 0
        ? caught.fieldErrors.map((f) => f.message).join('; ')
        : caught.message
    }
    return `Could not save that ${noun}. Please try again.`
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const payload = toPayload(draft, fields)
      if (editing === 'new') await careerService.create(kind, payload)
      else if (editing !== null) await careerService.update(kind, editing, payload)
      setEditing(null)
      onChanged()
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (pendingDelete === null) return
    setBusy(true)
    try {
      await careerService.remove(kind, pendingDelete.id)
      setPendingDelete(null)
      onChanged()
    } catch (caught) {
      setError(messageOf(caught))
      setPendingDelete(null)
    } finally {
      setBusy(false)
    }
  }

  function renderField(field: FieldSpec) {
    const value = draft[field.key]

    if (field.type === 'checkbox') {
      return (
        <label key={field.key} className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={value === true}
            onChange={(e) => setDraft((prev) => ({ ...prev, [field.key]: e.target.checked }))}
            className="size-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
          />
          {field.label}
        </label>
      )
    }

    const common = {
      label: field.label,
      value: String(value ?? ''),
      required: field.required,
      ...(field.hint !== undefined ? { hint: field.hint } : {}),
    }

    if (field.type === 'select') {
      return (
        <Select
          key={field.key}
          {...common}
          placeholder="Not stated"
          options={field.options ?? []}
          onChange={(e) => setDraft((prev) => ({ ...prev, [field.key]: e.target.value }))}
        />
      )
    }

    if (field.type === 'textarea' || field.type === 'lines') {
      return (
        <Textarea
          key={field.key}
          {...common}
          rows={field.type === 'lines' ? 5 : 3}
          onChange={(e) => setDraft((prev) => ({ ...prev, [field.key]: e.target.value }))}
        />
      )
    }

    // Its own branch rather than a `type` on Input: MonthPicker's onChange
    // emits the value, not a DOM event.
    if (field.type === 'month') {
      return (
        <MonthPicker
          key={field.key}
          {...common}
          onChange={(next) => setDraft((prev) => ({ ...prev, [field.key]: next }))}
        />
      )
    }

    return (
      <Input
        key={field.key}
        {...common}
        type="text"
        onChange={(e) => setDraft((prev) => ({ ...prev, [field.key]: e.target.value }))}
      />
    )
  }

  // Derived once, so the two filters below cannot disagree about what is shown.
  const visible = fields.filter((field) => !isHidden(field, draft))

  const form = (
    <form onSubmit={(e) => void save(e)} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        {visible
          .filter((f) => f.half === true)
          .map((f) => (
            <div key={f.key}>{renderField(f)}</div>
          ))}
      </div>
      {visible.filter((f) => f.half !== true).map(renderField)}

      <div className="flex items-center gap-3 pt-1">
        <Button type="submit" size="sm" isLoading={busy}>
          Save
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => setEditing(null)}>
          Cancel
        </Button>
      </div>
    </form>
  )

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Remove this ${noun}?`}
        confirmLabel="Remove"
        destructive
        isBusy={busy}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (!busy) setPendingDelete(null)
        }}
      >
        <p>This cannot be undone.</p>
        {/*
          `pendingDelete !== null &&` is load-bearing. Optional chaining alone
          gives `undefined !== null`, which is true, so the warning would also
          appear for an entry the user typed in themselves — where it is simply
          untrue, since nothing will bring it back.
        */}
        {pendingDelete !== null && pendingDelete.source_version_id !== null && (
          <p className="mt-2">
            {/* Said plainly, because it is surprising: a re-extract would bring
                it back, and the user would think the delete failed. */}
            This came from a resume, so re-extracting that resume will add it
            back. Edit it instead if you want a different version to stick.
          </p>
        )}
      </ConfirmDialog>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-600">{description}</p>
        </div>
        {editing !== 'new' && (
          <Button variant="secondary" size="sm" onClick={openNew}>
            Add
          </Button>
        )}
      </div>

      {error !== null && (
        <Alert tone="error" className="mt-4">
          {error}
        </Alert>
      )}

      {editing === 'new' && (
        <div className="mt-5 rounded-lg bg-slate-50 p-4">{form}</div>
      )}

      {items.length === 0 && editing !== 'new' ? (
        <p className="mt-4 text-sm text-slate-500">{emptyHint}</p>
      ) : (
        <ul className="mt-5 divide-y divide-slate-200">
          {items.map((item) => {
            const summary = renderSummary(item)
            const isOpen = editing === item.id

            return (
              <li key={item.id} className="py-4 first:pt-0 last:pb-0">
                {isOpen ? (
                  <div className="rounded-lg bg-slate-50 p-4">{form}</div>
                ) : (
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-900">{summary.primary}</p>
                      {summary.secondary !== null && (
                        <p className="text-sm text-slate-600">{summary.secondary}</p>
                      )}
                      {summary.meta !== null && (
                        <p className="mt-0.5 text-xs text-slate-500">{summary.meta}</p>
                      )}
                      {/* Where a row came from, so a parser's reading and the
                          user's own words are not presented identically. */}
                      <span
                        className={cn(
                          'mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium',
                          item.is_user_verified
                            ? 'bg-emerald-50 text-emerald-700'
                            : 'bg-slate-100 text-slate-600',
                        )}
                      >
                        {item.is_user_verified
                          ? 'Confirmed by you'
                          : 'Read from your resume'}
                      </span>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button variant="secondary" size="sm" onClick={() => openEdit(item)}>
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setPendingDelete(item)}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
