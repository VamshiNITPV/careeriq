import { useEffect, useRef, type ReactNode } from 'react'
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
  destructive = false,
  isBusy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)

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
      aria-labelledby="confirm-title"
    >
      <div className="p-6">
        <h2 id="confirm-title" className="text-base font-semibold text-slate-900">
          {title}
        </h2>
        <div className="mt-2 text-sm text-slate-600">{children}</div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={isBusy}>
            {cancelLabel}
          </Button>
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
