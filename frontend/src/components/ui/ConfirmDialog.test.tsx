import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

/**
 * Most of what makes this component correct — that it is centred, that its
 * buttons stay reachable, that long titles wrap — is layout, and jsdom has no
 * layout engine, so none of it is assertable here.
 *
 * The label wiring is the exception. `aria-labelledby` is a document-wide id
 * lookup, and duplicate ids are a real, checkable defect.
 */

beforeAll(() => {
  // jsdom implements <dialog> but not showModal/close.
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true
  })
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false
  })
})

function renderTwo() {
  return render(
    <>
      <ConfirmDialog open title="Delete résumé A?" onConfirm={() => {}} onCancel={() => {}}>
        This cannot be undone.
      </ConfirmDialog>
      <ConfirmDialog open title="Delete résumé B?" onConfirm={() => {}} onCancel={() => {}}>
        This cannot be undone.
      </ConfirmDialog>
    </>,
  )
}

describe('ConfirmDialog', () => {
  it('gives each dialog its own title id', () => {
    /*
     * The id used to be the hardcoded string "confirm-title". Every JobCard
     * renders one of these, so a twenty-job list put twenty identical ids in the
     * document — and `aria-labelledby` resolves to the *first* match. Opening the
     * dialog on the seventeenth card announced the first card's title, telling a
     * screen reader user they were about to act on a different job.
     */
    renderTwo()

    const ids = screen
      .getAllByRole('heading', { level: 2 })
      .map((heading) => heading.getAttribute('id'))

    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
    expect(ids.every((id) => id !== null && id !== '')).toBe(true)
  })

  it('points each dialog at its own title, not at the first one on the page', () => {
    // The property that actually matters. The ids above could differ and still
    // be wired to the wrong heading.
    renderTwo()

    for (const title of ['Delete résumé A?', 'Delete résumé B?']) {
      // getByRole resolves the accessible name through aria-labelledby, so this
      // fails if a dialog borrows the other's heading.
      expect(screen.getByRole('dialog', { name: title })).toBeInTheDocument()
    }
  })

  it('offers a third way out only when one is given', async () => {
    /*
     * The escape hatch for a destructive action whose harm has a remedy — used
     * by "forget that you applied" to offer keeping the job bookmarked instead.
     * Absent by default, so the two existing dialogs are unaffected.
     */
    const user = userEvent.setup()
    const keep = vi.fn()

    const { unmount } = render(
      <ConfirmDialog open title="Forget it?" onConfirm={() => {}} onCancel={() => {}}>
        Body.
      </ConfirmDialog>,
    )
    expect(screen.queryByRole('button', { name: 'Keep it saved' })).not.toBeInTheDocument()
    unmount()

    render(
      <ConfirmDialog
        open
        title="Forget it?"
        secondaryAction={{ label: 'Keep it saved', onClick: keep }}
        onConfirm={() => {}}
        onCancel={() => {}}
      >
        Body.
      </ConfirmDialog>,
    )

    await user.click(screen.getByRole('button', { name: 'Keep it saved' }))
    expect(keep).toHaveBeenCalledOnce()
  })
})
