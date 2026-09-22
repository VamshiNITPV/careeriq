import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { UserMenu } from '@/components/layout/UserMenu'
import { useHoverIntent } from '@/components/ui/hoverIntent'
import { usePopoverDismiss } from '@/components/ui/popoverDismiss'
import { cn } from '@/utils/cn'

/**
 * Four, not five. "Resume" was here *and* in the account menu as "Your resume",
 * and a navbar is the wrong place to keep the duplicate: it is the one surface
 * where every extra item costs width at exactly the sizes that have none.
 *
 * The route and the page are untouched. Only the link moved out.
 */
const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/applications', label: 'Applications' },
  { to: '/skill-gaps', label: 'Skills' },
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

  /*
   * Hover opens the disclosure on a machine with a real pointer.
   *
   * Handlers go on the button *and* the panel, sharing one hook, because the
   * two are not inside a common wrapper — the button sits in the header row and
   * the panel is a full-width bar beneath it. Entering either cancels the
   * pending close; leaving either schedules one. Restructuring the header to
   * put a single wrapper around them would be a larger change than this earns.
   *
   * Worth saying plainly: below `sm` is phone territory, where nothing can
   * hover, so this fires only when a laptop window has been narrowed. It is
   * cheap and consistent with the account menu rather than significant.
   */
  const navHover = useHoverIntent({
    onOpen: () => setMenuOpen(true),
    onClose: () => setMenuOpen(false),
  })

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

          {/*
            One wrapper around the button and its panel, which is what lets the
            panel anchor to the button instead of spanning the header.

            It also collapses the hover wiring to a single pair of handlers.
            They used to sit on the button *and* the panel, because the two had
            no common parent; now the panel is a descendant, so moving from one
            into the other fires no `pointerleave` at all and only the 8px gap
            leans on the close delay — the same arrangement DropdownMenu uses.
          */}
          <div
            className="relative sm:hidden"
            onPointerEnter={navHover.onPointerEnter}
            onPointerLeave={navHover.onPointerLeave}
          >
            {/* Sits immediately after the logo, where a hamburger is expected.
                aria-expanded and aria-controls are what tell a screen reader
                this button owns a collapsible region and whether it is open;
                without them it announces as an unlabelled button that appears
                to do nothing. */}
            <button
              ref={triggerRef}
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              // `size-10` on the hit area: this was 36px, and it is the only
              // route to navigation on a phone. The icon is unchanged.
              className="inline-flex size-10 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            >
              <MenuIcon open={menuOpen} />
            </button>

            {/*
              A panel anchored under the button, not a bar across the header.

              Full width made four short labels sit alone on four full-width
              rows, which read as a page rather than a menu. `w-56` is the
              width: "Applications" is the longest label at roughly 85px, and
              224px clears it with room to spare while staying a step narrower
              than the account menu's `w-60` beside it — the two read as the
              same family without being the same size.

              `max-w-[calc(100vw-2rem)]` for the same reason DropdownMenu
              carries it: on a very narrow phone a fixed width would push past
              the viewport and take the horizontal scrollbar with it.

              Kept mounted and toggled with `hidden` so the links stay in the
              accessibility tree in a predictable place, and so the collapse is
              one attribute change rather than a remount.
            */}
            <div
              id="mobile-nav"
              hidden={!menuOpen}
              className={cn(
                'absolute top-full left-0 z-30 mt-2 w-56 max-w-[calc(100vw-2rem)]',
                'rounded-lg border border-slate-200 bg-white p-2 shadow-lg',
              )}
            >
              {/* Navigation only. The account details and Sign out live in the
                  avatar menu, which is visible at every breakpoint, so
                  duplicating them here would be two places to keep in step. */}
              <nav aria-label="Main" className="space-y-1">
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
          </div>

          {/* Desktop navigation, from `sm` rather than `md`. Four links, the
              logo and the avatar measure roughly 545px together, so 640px clears
              them — which makes the disclosure below genuinely phone-shaped
              instead of something a half-width laptop window also gets. */}
          <nav aria-label="Main" className="hidden gap-1 sm:flex">
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

      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  )
}
