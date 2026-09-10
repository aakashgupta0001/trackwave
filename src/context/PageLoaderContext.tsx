import { createContext, useContext, useState, useEffect, useRef, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import PageLoader from '../components/PageLoader'

type PageLoaderContextType = {
  /** Manually trigger the page loader for button clicks or asynchronous operations */
  triggerLoader: (message?: string, subtext?: string, durationMs?: number) => void
  isLoading: boolean
  currentMessage: string
  currentSubtext: string
}

const PageLoaderContext = createContext<PageLoaderContextType>({
  triggerLoader: () => {},
  isLoading: false,
  currentMessage: 'Loading Railway Telemetry…',
  currentSubtext: 'Aggregating live signals, digital twin state & ETA predictions',
})

export function usePageLoader() {
  return useContext(PageLoaderContext)
}

function getPageMessage(pathname: string, search: string): { message: string; subtext: string } {
  const trainParam = new URLSearchParams(search).get('train')
  if (trainParam) {
    return {
      message: `Loading Train ${trainParam} Telemetry…`,
      subtext: 'Fetching real-time GPS coordinates, delay, and ML residual predictions',
    }
  }

  const stationParam = new URLSearchParams(search).get('station')
  if (stationParam) {
    return {
      message: `Loading Station ${stationParam} Operational Board…`,
      subtext: 'Aggregating active arrivals, departures, and track conflicts',
    }
  }

  switch (pathname) {
    case '/':
      return {
        message: 'Loading Network Overview…',
        subtext: 'Aggregating fleet status, network conflict scores, and active alerts',
      }
    case '/operations/live-trains':
      return {
        message: 'Loading Real-Time Trains & AI Predictions…',
        subtext: 'Streaming live telemetry from RailRadar and digital twin predictions',
      }
    case '/operations/stations':
      return {
        message: 'Loading Station Operations & Departure Boards…',
        subtext: 'Querying station schedules, live board updates, and track occupancies',
      }
    case '/operations/network':
      return {
        message: 'Loading Network Delay Propagation & Intelligence…',
        subtext: 'Computing secondary cascade risk and network congestion hotspots',
      }
    case '/intelligence/simulator':
      return {
        message: 'Loading Interactive Railway Simulator…',
        subtext: 'Initializing scenario runner, track injects, and dispatch models',
      }
    case '/intelligence/performance':
      return {
        message: 'Loading Prediction Model Analytics & MLOps…',
        subtext: 'Evaluating residual accuracy, data drift metrics, and retraining jobs',
      }
    case '/settings':
      return {
        message: 'Loading System Health & Provider Configuration…',
        subtext: 'Probing live data providers, database pools, and Redis streams',
      }
    default:
      return {
        message: 'Loading Railway Telemetry…',
        subtext: 'Syncing with TrackWave platform digital twin',
      }
  }
}

export function PageLoaderProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [initialVisit, setInitialVisit] = useState(true)
  const [isNavigating, setIsNavigating] = useState(false)
  const [loaderMessage, setLoaderMessage] = useState('Loading Railway Telemetry…')
  const [loaderSubtext, setLoaderSubtext] = useState('Aggregating live signals, digital twin state & ETA predictions')
  const prevPathRef = useRef(location.pathname + location.search)
  const timerRef = useRef<any>(null)

  // 1. Initial Page Visit / Refresh: Show splash loader with user logo
  useEffect(() => {
    const splashTimer = setTimeout(() => {
      setInitialVisit(false)
    }, 750)
    return () => clearTimeout(splashTimer)
  }, [])

  // 2. Navigation / Route Change / Button visit: Trigger page loader
  useEffect(() => {
    const currentPath = location.pathname + location.search
    if (prevPathRef.current !== currentPath) {
      prevPathRef.current = currentPath

      if (!initialVisit) {
        const { message, subtext } = getPageMessage(location.pathname, location.search)
        setLoaderMessage(message)
        setLoaderSubtext(subtext)
        setIsNavigating(true)

        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => {
          setIsNavigating(false)
        }, 380)
      }
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [location.pathname, location.search, initialVisit])

  // 3. Manual trigger function for buttons
  const triggerLoader = (
    message = 'Processing Request…',
    subtext = 'Updating live railway data models',
    durationMs = 400
  ) => {
    setLoaderMessage(message)
    setLoaderSubtext(subtext)
    setIsNavigating(true)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      setIsNavigating(false)
    }, durationMs)
  }

  return (
    <PageLoaderContext.Provider
      value={{
        triggerLoader,
        isLoading: isNavigating || initialVisit,
        currentMessage: loaderMessage,
        currentSubtext: loaderSubtext,
      }}
    >
      {/* Fullscreen Initial Visit Splash with User Logo */}
      {initialVisit && (
        <PageLoader
          fullScreen
          logoUrl="/logo.png"
          message="TrackWave Intelligence"
          subtext="Initializing Railway Digital Twin & Syncing Live Indian Railways Feed…"
        />
      )}

      {/* Top Progress Bar during navigation */}
      {isNavigating && (
        <div className="fixed top-0 left-0 right-0 z-50 h-1 bg-slate-900/40">
          <div className="h-full bg-gradient-to-r from-emerald-400 via-indigo-500 to-cyan-400 animate-pulse shadow-md shadow-indigo-500/50" />
        </div>
      )}

      {children}
    </PageLoaderContext.Provider>
  )
}
