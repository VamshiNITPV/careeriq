import { cn } from '@/utils/cn'

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <>
      <svg
        className={cn('animate-spin text-current', className ?? 'size-5')}
        // Purely decorative: the accompanying text below carries the meaning,
        // so announcing the graphic too would just be noise.
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
      {label !== undefined && <span className="sr-only">{label}</span>}
    </>
  )
}
