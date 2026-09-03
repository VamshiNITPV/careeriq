import { Link } from 'react-router-dom'
import { DropdownMenu, menuItemClass } from '@/components/ui/DropdownMenu'
import { useAuth } from '@/hooks/useAuth'
import { avatarColourFor, displayNameFor, initialsFor } from '@/utils/initials'
import { cn } from '@/utils/cn'

/** The account menu in the header: avatar trigger, profile link, sign out. */
export function UserMenu() {
  const { user, profile, logout } = useAuth()

  if (user === null) return null

  const name = displayNameFor(profile?.full_name, user.email)
  const initials = initialsFor(profile?.full_name, user.email)
  const colour = avatarColourFor(user.id)

  return (
    <DropdownMenu
      align="right"
      // The name, not "Account menu" alone — with several people's screenshots
      // in a bug report it matters which account is open.
      label={`Account menu for ${name}`}
      trigger={
        <span
          className={cn(
            'grid size-9 place-items-center rounded-full text-sm font-semibold text-white',
            colour,
          )}
          // The initials are decorative; the button's aria-label already names
          // the account, and announcing "PS" as well is noise.
          aria-hidden="true"
        >
          {initials}
        </span>
      }
    >
      <div role="presentation" className="border-b border-slate-200 px-4 py-3">
        <p className="truncate text-sm font-medium text-slate-900">{name}</p>
        <p className="truncate text-xs text-slate-500">{user.email}</p>
      </div>

      <Link role="menuitem" tabIndex={-1} to="/profile" className={menuItemClass}>
        Your profile
      </Link>
      <Link role="menuitem" tabIndex={-1} to="/resume" className={menuItemClass}>
        Your resume
      </Link>

      <div className="my-1 border-t border-slate-200" role="presentation" />

      <button
        role="menuitem"
        tabIndex={-1}
        type="button"
        onClick={() => void logout()}
        className={cn(menuItemClass, 'text-red-600 hover:bg-red-50 focus:bg-red-50')}
      >
        Sign out
      </button>
    </DropdownMenu>
  )
}
