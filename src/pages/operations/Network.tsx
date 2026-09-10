import { useState } from 'react'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import {
  getNetworkOverview,
  listNetworkConflicts,
  listNetworkHotspots,
  getNetworkTimeline,
  formatIST,
} from '../../lib/api'
import type { Severity, NetworkConflict } from '../../lib/api'
import { useWebSocketFeed } from '../../lib/websocket'
import type { WebSocketMessage } from '../../lib/websocket'

function severityTone(sev: Severity): 'bad' | 'warn' | 'neutral' | 'good' {
  switch (sev) {
    case 'CRITICAL':
      return 'bad'
    case 'HIGH':
      return 'bad'
    case 'MEDIUM':
      return 'warn'
    case 'LOW':
    default:
      return 'neutral'
  }
}

export default function Network() {
  const [severityFilter, setSeverityFilter] = useState<Severity | undefined>(undefined)
  const [refreshKey, setRefreshKey] = useState(0)

  const overview = useFetch(() => getNetworkOverview(), [refreshKey])
  const conflicts = useFetch(
    () => listNetworkConflicts({ page_size: 20, severity: severityFilter }),
    [severityFilter, refreshKey]
  )
  const hotspots = useFetch(() => listNetworkHotspots(), [refreshKey])
  const timeline = useFetch(() => getNetworkTimeline(30), [refreshKey])

  const [liveEventNotice, setLiveEventNotice] = useState<string | null>(null)

  // Real-time WebSocket feed for network updates
  const { connectionState } = useWebSocketFeed('/ws/network', (msg: WebSocketMessage) => {
    if (msg.event_type === 'network_alert' || msg.event_type === 'congestion_risk') {
      setLiveEventNotice(`Live event received: ${msg.data.title || msg.event_type} at ${formatIST(msg.timestamp)}`)
      setRefreshKey((k) => k + 1)
    }
  })

  const loading = overview.loading || conflicts.loading || hotspots.loading
  const error = overview.error || conflicts.error || hotspots.error

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Network Intelligence & Delay Cascades"
          description="Analytical propagation model, shared-section conflict detection, and congestion hotspots."
        />
        <span
          className={`inline-flex items-center gap-1.5 self-start rounded-full px-2.5 py-1 text-xs font-medium ${
            connectionState === 'CONNECTED'
              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
              : 'bg-slate-850 text-slate-400 border border-slate-700'
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              connectionState === 'CONNECTED' ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
            }`}
          />
          {connectionState === 'CONNECTED' ? 'NETWORK STREAM ACTIVE' : connectionState}
        </span>
      </div>

      {liveEventNotice && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-amber-800 bg-amber-950/60 p-3 text-xs text-amber-200">
          <span>{liveEventNotice}</span>
          <button onClick={() => setLiveEventNotice(null)} className="text-amber-400 hover:underline">
            Dismiss
          </button>
        </div>
      )}

      <DataState loading={loading} error={error}>
        {/* Network Metrics Overview */}
        {overview.data && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
              <div className="text-xs uppercase tracking-wider text-slate-500">Network Impact Score</div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-white">
                  {overview.data.network_impact_score}
                </span>
                <span className="text-xs text-slate-500">/ 100</span>
                <Badge
                  label={overview.data.severity}
                  tone={severityTone(overview.data.severity)}
                />
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
              <div className="text-xs uppercase tracking-wider text-slate-500">Affected Trains</div>
              <div className="mt-1 text-2xl font-semibold text-white">
                {overview.data.affected_trains}
                <span className="ml-2 text-xs font-normal text-slate-500">
                  of {overview.data.total_trains_monitored} monitored
                </span>
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
              <div className="text-xs uppercase tracking-wider text-slate-500">Affected Stations</div>
              <div className="mt-1 text-2xl font-semibold text-white">
                {overview.data.affected_stations}
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
              <div className="text-xs uppercase tracking-wider text-slate-500">Active Conflicts</div>
              <div className="mt-1 text-2xl font-semibold text-white">
                {overview.data.active_conflicts}
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
              <div className="text-xs uppercase tracking-wider text-slate-500">Congestion Hotspots</div>
              <div className="mt-1 text-2xl font-semibold text-white">
                {overview.data.hotspots.length}
              </div>
            </div>
          </div>
        )}

        {/* Shared-Section Conflicts */}
        <div className="mt-6 rounded-lg border border-slate-800 bg-slate-950 p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">Shared-Section Conflicts</h3>
              <p className="text-xs text-slate-500">
                Overlapping section occupancies and headway violations predicted by the propagation engine.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-slate-500">Filter:</span>
              {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSeverityFilter(sev === 'ALL' ? undefined : (sev as Severity))}
                  className={`rounded px-2 py-1 font-medium transition-colors ${
                    (sev === 'ALL' && severityFilter === undefined) || severityFilter === sev
                      ? 'bg-slate-800 text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="px-3 py-2 font-medium">Section</th>
                  <th className="px-3 py-2 font-medium">Train A</th>
                  <th className="px-3 py-2 font-medium">Train B</th>
                  <th className="px-3 py-2 font-medium">Conflict Type</th>
                  <th className="px-3 py-2 font-medium">Est. Overlap</th>
                  <th className="px-3 py-2 font-medium">Severity</th>
                  <th className="px-3 py-2 font-medium">Predicted At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {conflicts.data?.items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-slate-500">
                      No predicted conflicts matching current filters.
                    </td>
                  </tr>
                ) : (
                  conflicts.data?.items.map((cnf: NetworkConflict, idx: number) => (
                    <tr key={`${cnf.train_a}-${cnf.train_b}-${cnf.section_code}-${idx}`} className="hover:bg-slate-900/50">
                      <td className="px-3 py-2.5 font-mono font-medium text-slate-200">
                        {cnf.section_code ?? '—'}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-300">{cnf.train_a}</td>
                      <td className="px-3 py-2.5 font-mono text-slate-300">{cnf.train_b}</td>
                      <td className="px-3 py-2.5 text-slate-300">
                        {cnf.conflict_type.replace(/_/g, ' ')}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-amber-400">
                        {cnf.estimated_overlap_minutes != null ? `${cnf.estimated_overlap_minutes.toFixed(0)} min` : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge label={cnf.severity} tone={severityTone(cnf.severity)} />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-500">
                        {cnf.predicted_at ? formatIST(cnf.predicted_at) : '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Hotspots and Propagation Timeline */}
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Congestion Hotspots */}
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-200">Predicted Congestion Hotspots</h3>
            {hotspots.data?.length === 0 ? (
              <p className="text-xs text-slate-500">No congestion hotspots detected.</p>
            ) : (
              <div className="space-y-2">
                {hotspots.data?.map((hp, idx) => (
                  <div
                    key={`${hp.entity_type}-${hp.entity_code}-${idx}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-850 bg-slate-900/60 p-3 text-xs"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white">{hp.entity_name}</span>
                        <span className="font-mono text-[10px] text-slate-500">({hp.entity_code})</span>
                        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                          {hp.entity_type}
                        </span>
                      </div>
                      <div className="mt-1 text-slate-400">
                        {hp.affected_trains} affected trains · {hp.conflict_count} conflicts · impact score {hp.impact_score}/100
                      </div>
                    </div>
                    <Badge label={hp.severity} tone={severityTone(hp.severity)} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Forward-Looking Timeline */}
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-200">Forward Propagation Horizon</h3>
            {timeline.data?.length === 0 ? (
              <p className="text-xs text-slate-500">No timeline buckets available.</p>
            ) : (
              <div className="space-y-2">
                {timeline.data?.map((tb, idx) => (
                  <div
                    key={idx}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-850 bg-slate-900/60 p-3 text-xs"
                  >
                    <div>
                      <div className="font-mono text-xs text-slate-300">
                        {formatIST(tb.timestamp, { hour: '2-digit', minute: '2-digit' })}
                      </div>
                      <div className="mt-0.5 text-[11px] text-slate-500">
                        {tb.conflicts} conflicts · {tb.affected_trains} affected trains
                      </div>
                    </div>
                    <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300">
                      {tb.network_impact_score}/100
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </DataState>
    </>
  )
}