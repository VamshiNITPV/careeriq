import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { UserMenu } from '@/components/layout/UserMenu'
import { usePopoverDismiss } from '@/components/ui/popoverDismiss'
import { cn } from '@/utils/cn'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/resume', label: 'Resume' },
  { to: '/jobs', label: 'Jobs' },
] as const

function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg
      className="size-5"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      aria-hidden="true"
    >
      {open ? (
        <path d="M6 6l12 12M18 6L6 18" />
      ) : (
        <>
          <path d="M4 7h16" />
          <path d="M4 12h16" />
          <path d="M4 17h16" />
        </>
      )}
    </svg>
  )
}

export function AppLayout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  /*
   * Close on an outside tap and on navigation, via the shared hook rather than
   * the hand-rolled route effect this used to carry.
   *
   * The missing piece was outside-tap dismissal: on a phone the panel covers the
   * page, and tapping the content behind it did nothing — the only way out was
   * to find the hamburger again. DropdownMenu.tsx names this layout by name as
   * the inferior precedent it was extracted away from, so this is that debt
   * being paid rather than a new idea.
   *
   * The ref goes on the element wrapping *both* the trigger and the panel, so
   * one containment check covers both and the opening tap is not also read as an
   * outside tap.
   */
  const shellRef = usePopoverDismiss<HTMLDivElement>({
    open: menuOpen,
    onOutsidePointer: () => setMenuOpen(false),
    onRouteChange: () => setMenuOpen(false),
  })

  // Escape closes it. A menu that can only be dismissed by hitting the exact
  // toggle button again is a trap for keyboard users. Focus goes back to the
  // trigger, because hiding the panel would otherwise drop it on <body> and
  // reset tab order to the top of the document.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setMenuOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'rounded-md px-3 py-2 text-sm font-medium transition-colors',
      isActive
        ? 'bg-indigo-50 text-indigo-700'
        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
    )

  return (
    <div className="min-h-screen bg-slate-50">
      <header
        ref={shellRef}
        className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur"
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <NavLink
            to="/dashboard"
            className="flex items-center gap-2 text-lg font-bold tracking-tight text-indigo-600"
          >
            <span
              className="grid size-8 place-items-center rounded-lg bg-indigo-600 text-sm text-white"
              aria-hidden="true"
            >
              CQ
            </span>
            CareerIQ
          </NavLink>

          {/* Sits immediately after the logo, where a hamburger is expected.
              aria-expanded and aria-controls are what tell a screen reader this
              button owns a collapsible region and whether it is open; without
              them it announces as an unlabelled button that appears to do
              nothing. */}
          <button
            ref={triggerRef}
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            // `size-10` on the hit area: this was 36px, and it is the only route
            // to navigation on a phone. The icon is unchanged.
            className="inline-flex size-10 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 hover:text-slate-900 md:hidden"
          >
            <MenuIcon open={menuOpen} />
          </button>

          {/* Desktop navigation. */}
          <nav aria-label="Main" className="hidden gap-1 md:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={navLinkClass}>
                {item.label}
              </NavLink>
            ))}
          </nav>

          {/* No `md:` visibility class on the avatar — it is now the only
              sign-out path at every width, and hiding it on mobile would strand
              the user. */}
          <div className="ml-auto flex items-center">
            <UserMenu />
          </div>
        </div>

        {/* Mobile panel. Kept mounted and toggled with `hidden` so the links
            stay in the accessibility tree in a predictable place, and so the
            collapse is a single attribute change rather than a remount. */}
        <div
          id="mobile-nav"
          hidden={!menuOpen}
          className="border-t border-slate-200 bg-white md:hidden"
        >
          {/* Navigation only. The account details and Sign out moved into the
              avatar menu, which is visible at every breakpoint, so duplicating
              them here would be two places to keep in step. */}
          <nav aria-label="Main" className="space-y-1 px-4 py-3 sm:px-6">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => cn(navLinkClass({ isActive }), 'block')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  )
}
