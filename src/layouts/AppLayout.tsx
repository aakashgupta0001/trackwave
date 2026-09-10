import { Suspense, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import PageLoader from '../components/PageLoader'
import { usePageLoader } from '../context/PageLoaderContext'

function MainContent() {
  const { isLoading, currentMessage, currentSubtext } = usePageLoader()

  return (
    <main className="relative min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
      {isLoading ? (
        <div className="flex h-full min-h-[60vh] items-center justify-center">
          <PageLoader
            message={currentMessage}
            subtext={currentSubtext}
          />
        </div>
      ) : (
        <Suspense fallback={<PageLoader message="Loading Page…" subtext="Initializing railway digital twin module…" />}>
          <Outlet />
        </Suspense>
      )}
    </main>
  )
}

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()

  // Close the mobile drawer on every route change (covers navigation triggered
  // outside a Sidebar NavLink click, e.g. programmatic redirects).
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  return (
    <div className="flex min-h-svh bg-slate-900 text-slate-100">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar: hamburger + brand, hidden at lg+ where the sidebar is always visible */}
        <header className="flex items-center gap-3 border-b border-slate-800 bg-slate-950 px-4 py-3 lg:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-1.5 text-slate-300 hover:bg-slate-800 hover:text-white"
            aria-label="Open menu"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <img src="/logo.png" alt="TrackWave" className="h-6 w-6 rounded-full object-cover" />
          <span className="text-sm font-semibold tracking-wide text-white">TrackWave</span>
        </header>

        <MainContent />
      </div>
    </div>
  )
}
