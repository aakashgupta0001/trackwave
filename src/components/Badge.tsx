type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

const toneClasses: Record<BadgeTone, string> = {
  neutral: 'bg-slate-800 text-slate-300',
  good: 'bg-emerald-900/50 text-emerald-300',
  warn: 'bg-amber-900/50 text-amber-300',
  bad: 'bg-red-900/50 text-red-300',
  info: 'bg-sky-900/50 text-sky-300',
}

export default function Badge({ label, tone = 'neutral' }: { label: string; tone?: BadgeTone }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}>
      {label}
    </span>
  )
}

/** Tone for the provider-layer data_status: LIVE | STALE | UNAVAILABLE | SIMULATED. */
export function dataStatusTone(status: string): BadgeTone {
  switch (status) {
    case 'LIVE':
      return 'good'
    case 'SIMULATED':
      return 'info'
    case 'STALE':
      return 'warn'
    case 'UNAVAILABLE':
      return 'bad'
    default:
      return 'neutral'
  }
}

/** Tone for the station-board status: ON_TIME | DELAYED | NO_RECENT_DATA. */
export function boardStatusTone(status: string): BadgeTone {
  switch (status) {
    case 'ON_TIME':
      return 'good'
    case 'DELAYED':
      return 'warn'
    case 'NO_RECENT_DATA':
      return 'neutral'
    default:
      return 'neutral'
  }
}
