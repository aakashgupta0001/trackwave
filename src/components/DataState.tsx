import type { ReactNode } from 'react'
import PageLoader from './PageLoader'

type DataStateProps = {
  loading: boolean
  error: string | undefined
  empty?: boolean
  emptyMessage?: string
  loadingMessage?: string
  loadingSubtext?: string
  loadingVariant?: 'radar' | 'track' | 'minimal'
  children: ReactNode
}

export default function DataState({
  loading,
  error,
  empty,
  emptyMessage,
  loadingMessage,
  loadingSubtext,
  loadingVariant,
  children,
}: DataStateProps) {
  if (loading) {
    return (
      <PageLoader
        message={loadingMessage ?? 'Loading Railway Telemetry…'}
        subtext={loadingSubtext}
        variant={loadingVariant ?? 'radar'}
      />
    )
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-6 text-sm text-red-300">
        Could not load data: {error}
      </div>
    )
  }
  if (empty) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950 p-6 text-sm text-slate-400">
        {emptyMessage ?? 'Nothing to show.'}
      </div>
    )
  }
  return <>{children}</>
}
