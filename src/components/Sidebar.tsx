import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { usePageLoader } from '../context/PageLoaderContext'

type NavItem = {
  label: string
  to: string
}

type NavGroup = {
  title: string
  items: NavItem[]
}

const groups: NavGroup[] = [
  {
    title: 'OPERATIONS',
    items: [
      { label: 'Live Trains', to: '/operations/live-trains' },
      { label: 'Stations', to: '/operations/stations' },
      { label: 'Network', to: '/operations/network' },
    ],
  },
  {
    title: 'INTELLIGENCE',
    items: [
      { label: 'Simulator', to: '/intelligence/simulator' },
      { label: 'Performance', to: '/intelligence/performance' },
    ],
  },
]

const linkBase =
  'block rounded-md px-3 py-1.5 text-sm transition-colors'
const linkInactive = 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
const linkActive = 'bg-slate-800 text-white'

function navLinkClass({ isActive }: { isActive: boolean }) {
  return `${linkBase} ${isActive ? linkActive : linkInactive}`
}

type SidebarProps = {
  /** Whether the off-canvas drawer is open on small screens (ignored at lg+, where it's always visible). */
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const { user, signOut } = useAuth()
  const { triggerLoader } = usePageLoader()
  const navigate = useNavigate()

  const handleSignOut = async () => {
    onClose()
    triggerLoader('Signing Out…', 'Terminating operator terminal session', 400)
    await signOut()
    navigate('/login')
  }

  return (
    <>
      {/* Backdrop: only rendered/interactive on small screens while the drawer is open */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-svh w-72 max-w-[85vw] shrink-0 flex-col overflow-y-auto border-r border-slate-800 bg-slate-950 px-4 py-5 transition-transform duration-200 ease-out sm:w-64 lg:sticky lg:top-0 lg:z-auto lg:w-64 lg:max-w-none lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between gap-2 px-1 pb-4">
          <div className="flex items-center gap-2">
            <img src="/logo.png" alt="TrackWave" className="h-8 w-8 rounded-full object-cover" />
            <span className="text-lg font-semibold tracking-wide text-white">TrackWave</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-800 hover:text-white lg:hidden"
            aria-label="Close menu"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <hr className="border-slate-800" />

        <nav className="mt-4 flex flex-1 flex-col gap-5 overflow-y-auto">
          <NavLink to="/" end className={navLinkClass} onClick={onClose}>
            Overview
          </NavLink>

          {groups.map((group) => (
            <div key={group.title}>
              <div className="px-3 pb-1.5 text-xs font-semibold tracking-wider text-slate-500">
                {group.title}
              </div>
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <NavLink key={item.to} to={item.to} className={navLinkClass} onClick={onClose}>
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <hr className="border-slate-800" />
        <div className="mt-4">
          <div className="px-3 pb-1.5 text-xs font-semibold tracking-wider text-slate-500">
            SYSTEM
          </div>
          <NavLink to="/settings" className={navLinkClass} onClick={onClose}>
            Settings
          </NavLink>
        </div>

      {/* Operator Session / Auth Section */}
      <div className="mt-4 pt-3 border-t border-slate-800">
        {user ? (
          <div className="rounded-lg border border-slate-800/80 bg-slate-900/60 p-2.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-cyan-500 font-semibold text-xs text-white shadow-sm">
                {user.user_metadata?.full_name
                  ? (user.user_metadata.full_name as string)
                      .split(' ')
                      .map((n: string) => n[0])
                      .join('')
                      .toUpperCase()
                      .slice(0, 2)
                  : user.email?.slice(0, 2).toUpperCase() || 'OP'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="truncate text-xs font-semibold text-slate-200">
                  {user.user_metadata?.full_name || 'Railway Operator'}
                </p>
                <p className="truncate text-[10px] text-slate-400">
                  {user.email}
                </p>
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between pt-1.5 border-t border-slate-800/60 text-[11px]">
              <span className="inline-flex items-center gap-1 text-emerald-400 font-mono text-[10px]">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                ONLINE
              </span>
              <button
                onClick={handleSignOut}
                className="text-slate-400 hover:text-rose-400 transition-colors cursor-pointer"
                title="Sign out of operations terminal"
              >
                Sign Out
              </button>
            </div>
          </div>
        ) : (
          <NavLink
            to="/login"
            onClick={onClose}
            className="flex items-center justify-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs font-medium text-indigo-300 hover:bg-indigo-500/20 transition-colors"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
            </svg>
            Sign In / Register
          </NavLink>
        )}
      </div>
      </aside>
    </>
  )
}
