export type PageLoaderProps = {
  /** Main loading title/message */
  message?: string
  /** Secondary status or operational context message */
  subtext?: string
  /** Whether the loader fills the entire viewport or fits within its container */
  fullScreen?: boolean
  /** Visual design variant: 'radar' | 'track' | 'minimal' */
  variant?: 'radar' | 'track' | 'minimal'
  /** URL to the logo image (defaults to /logo.png) */
  logoUrl?: string
  /** Additional CSS class names */
  className?: string
}

export default function PageLoader({
  message = 'Loading Railway Telemetry…',
  subtext = 'Aggregating live signals, digital twin state & ETA predictions',
  fullScreen = false,
  variant = 'radar',
  logoUrl = '/logo.png',
  className = '',
}: PageLoaderProps) {
  const containerClasses = fullScreen
    ? 'fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/95 backdrop-blur-md p-6'
    : 'flex min-h-[300px] w-full flex-col items-center justify-center rounded-xl border border-slate-850 bg-slate-950/80 p-8 text-center'

  return (
    <div className={`${containerClasses} ${className}`}>
      {/* Visual Animation with User Logo */}
      {variant === 'radar' && (
        <div className={`relative mb-6 flex ${fullScreen ? 'h-64 w-64' : 'h-48 w-48'} items-center justify-center`}>
          {/* Outer Pulsing Radar Wave */}
          <div className="absolute inset-0 animate-ping rounded-full border border-indigo-500/30 opacity-40" />

          {/* Concentric Scanner Rings */}
          <div className="absolute inset-1 rounded-full border border-slate-800/90" />
          <div className="absolute inset-5 rounded-full border border-slate-800/80" />
          <div className="absolute inset-10 rounded-full border border-indigo-900/50" />

          {/* Rotating Radar Sweep Gradient */}
          <div className="absolute inset-0 animate-spin" style={{ animationDuration: '2.8s' }}>
            <div className="h-1/2 w-1/2 rounded-tl-full bg-gradient-to-br from-indigo-500/35 to-transparent" />
          </div>

          {/* Operational Signal Indicator Nodes */}
          <span className="absolute top-4 right-8 h-3 w-3 animate-pulse rounded-full bg-emerald-400 shadow-md shadow-emerald-400" />
          <span
            className="absolute bottom-5 left-7 h-2.5 w-2.5 animate-pulse rounded-full bg-amber-400 shadow-md shadow-amber-400"
            style={{ animationDelay: '0.4s' }}
          />
          <span
            className="absolute top-1/2 -left-2 h-2.5 w-2.5 animate-pulse rounded-full bg-cyan-400 shadow-md shadow-cyan-400"
            style={{ animationDelay: '0.8s' }}
          />

          {/* Center Brand Logo with Extra Large Sizing & Glowing Halo */}
          <div className="relative flex items-center justify-center">
            <div className="absolute -inset-4 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 via-emerald-500 to-cyan-500 opacity-80 blur-xl" />
            <img
              src={logoUrl}
              alt="TrackWave Logo"
              className={`${
                fullScreen ? 'h-40 w-40' : 'h-32 w-32'
              } relative rounded-full border-4 border-indigo-400/90 bg-slate-950 object-cover shadow-2xl ring-6 ring-indigo-500/30 transition-transform duration-300 hover:scale-105`}
            />
          </div>
        </div>
      )}

      {variant === 'track' && (
        <div className="relative mb-6 flex flex-col items-center justify-center">
          {/* Logo with prominent glowing frame */}
          <div className="relative mb-4">
            <div className="absolute -inset-3 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-emerald-500 opacity-80 blur-lg" />
            <img
              src={logoUrl}
              alt="TrackWave Logo"
              className="relative h-28 w-28 rounded-full border-4 border-slate-700 bg-slate-950 object-cover shadow-2xl"
            />
          </div>

          {/* Railway Track Representation */}
          <div className="relative h-4 w-64">
            <div className="absolute top-0 h-0.5 w-full bg-slate-700" />
            <div className="absolute bottom-0 h-0.5 w-full bg-slate-700" />
            <div className="absolute inset-0 flex justify-between px-2">
              {[...Array(13)].map((_, i) => (
                <div key={i} className="h-full w-0.5 bg-slate-800" />
              ))}
            </div>
            <div className="absolute top-1/2 -mt-1 h-3 w-10 -translate-y-1/2 rounded bg-gradient-to-r from-emerald-400 to-indigo-500 shadow-md shadow-emerald-400 animate-pulse" />
          </div>
        </div>
      )}

      {variant === 'minimal' && (
        <div className="relative mb-4 flex items-center justify-center">
          <div className="absolute -inset-3 animate-spin rounded-full border-3 border-indigo-500 border-t-transparent" />
          <img
            src={logoUrl}
            alt="TrackWave Logo"
            className="relative h-20 w-20 rounded-full border-2 border-slate-800 bg-slate-950 object-cover shadow-xl ring-2 ring-indigo-500/40"
          />
        </div>
      )}

      {/* Brand & Loading Status */}
      {fullScreen && (
        <span className="mb-2 font-mono text-sm font-semibold tracking-widest text-indigo-400 uppercase">
          TrackWave Platform
        </span>
      )}

      <h3 className={`${fullScreen ? 'text-xl sm:text-2xl' : 'text-base sm:text-lg'} font-semibold tracking-wide text-white`}>
        {message}
      </h3>

      {subtext && (
        <p className="mt-2 max-w-md text-xs sm:text-sm text-slate-400">
          {subtext}
        </p>
      )}

      {/* Real-time Indicator Dots */}
      <div className="mt-5 flex items-center gap-1.5">
        <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
        <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" style={{ animationDelay: '0.2s' }} />
        <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" style={{ animationDelay: '0.4s' }} />
        <span className="ml-2 font-mono text-xs tracking-wider text-slate-400 uppercase font-medium">
          LIVE NETWORK STREAM
        </span>
      </div>
    </div>
  )
}
