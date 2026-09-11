import { useEffect, useId, useRef, type ReactNode } from 'react'
import { cn } from '@/utils/cn'
import { Button } from './Button'

/**
 * Modal confirmation for an action that cannot be undone.
 *
 * Built on the native `<dialog>` element rather than a div: the browser then
 * provides the focus trap, Escape-to-close, inert background and correct
 * accessibility semantics for free. Hand-rolled modals almost always get the
 * focus trap wrong, which strands keyboard and screen reader users behind a
 * dialog they cannot reach.
 */

interface ConfirmDialogProps {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /**
   * A third way out, between cancelling and going through with it.
   *
   * Optional, and worth having when the *reason* an action is destructive has a
   * remedy: offering it here beats making the reader cancel, go and do the
   * remedy themselves, and come back. Rendered between Cancel and the confirm
   * button, so the destructive one stays last.
   */
  secondaryAction?: { label: string; onClick: () => void }
  destructive?: boolean
  isBusy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  secondaryAction,
  destructive = false,
  isBusy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  /*
   * Per-instance, because this id was hardcoded as "confirm-title" and every
   * JobCard renders one of these: a 20-job list put twenty identical ids in the
   * document. `aria-labelledby` resolves to the *first* match, so an open dialog
   * on the seventeenth card was announced with the first card's title — telling
   * a screen reader user they were about to act on the wrong job. Every other
   * id-bearing component here already uses useId().
   */
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (dialog === null) return

    // showModal() is what activates the focus trap and backdrop; setting the
    // `open` attribute directly renders the dialog non-modally and loses both.
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      // Fires on Escape as well as close(), so dismissing with the keyboard
      // keeps React state in step with the DOM.
      onClose={onCancel}
      // Clicking the backdrop targets the dialog itself; a click inside targets
      // a child. Comparing the target is what distinguishes the two.
      onClick={(event) => {
        if (event.target === ref.current && !isBusy) onCancel()
      }}
      // `m-auto` is load-bearing, not decoration. A modal <dialog> is centred
      // by the browser's own `margin: auto`, and Tailwind's preflight resets
      // margin to 0 on every element — which silently pins the dialog to the
      // top of the viewport. Restoring it is what puts the modal back in the
      // middle.
      //
      // The width and max-height keep it inside small viewports rather than
      // overflowing off-screen where the buttons cannot be reached.
      className={cn(
        'm-auto w-[calc(100%-2rem)] max-w-md rounded-lg p-0 shadow-xl',
        'max-h-[85vh] overflow-auto',
        'backdrop:bg-slate-900/40 backdrop:backdrop-blur-[1px]',
      )}
      aria-labelledby={titleId}
    >
      {/*
        `p-4 sm:p-6` — at a 320px viewport the dialog is 288px wide, and `p-6`
        spent 48px of that on padding.
      */}
      <div className="p-4 sm:p-6">
        {/*
          `break-words` because the title is caller-supplied and is sometimes a
          raw filename: `Delete "Parshuram_Bardawal_Resume_2026.pdf"?` is a
          single unbreakable token far wider than the dialog, which turned the
          modal into a horizontal scroller with the title running under its edge.
        */}
        <h2 id={titleId} className="text-base font-semibold break-words text-slate-900">
          {title}
        </h2>
        <div className="mt-2 text-sm text-slate-600">{children}</div>

        {/*
          `flex-wrap` so a longer confirmLabel stacks rather than overflowing.
          `justify-end` still holds once wrapped.
        */}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={isBusy}>
            {cancelLabel}
          </Button>
          {secondaryAction !== undefined && (
            <Button
              variant="secondary"
              size="sm"
              onClick={secondaryAction.onClick}
              disabled={isBusy}
            >
              {secondaryAction.label}
            </Button>
          )}
          <Button
            variant={destructive ? 'danger' : 'primary'}
            size="sm"
            isLoading={isBusy}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  )
}
