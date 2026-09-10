import { useState } from 'react'
import { Link } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import DataState from '../components/DataState'
import Badge from '../components/Badge'
import { useFetch } from '../lib/useFetch'
import {
  listTrains,
  listStations,
  getProvidersStatus,
  getNetworkOverview,
  getOperationalAlerts,
  getSystemHealth,
  formatIST,
} from '../lib/api'
import type { OperationalAlert } from '../lib/api'
import { useWebSocketFeed } from '../lib/websocket'
import type { WebSocketMessage } from '../lib/websocket'

function StatCard({
  label,
  value,
  subtext,
  to,
}: {
  label: string
  value: string
  subtext?: string
  to?: string
}) {
  const content = (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-5 transition-colors hover:border-slate-700">
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-white">{value}</span>
        {subtext && <span className="text-xs text-slate-400">{subtext}</span>}
      </div>
    </div>
  )
  return to ? <Link to={to}>{content}</Link> : content
}

export default function Overview() {
  const trains = useFetch(() => listTrains({ page_size: 1 }), [])
  const activeTrains = useFetch(() => listTrains({ page_size: 1, active: true }), [])
  const stations = useFetch(() => listStations({ page_size: 1 }), [])
  const providers = useFetch(() => getProvidersStatus(), [])
  const network = useFetch(() => getNetworkOverview(), [])
  const health = useFetch(() => getSystemHealth(), [])
  const alertsFetch = useFetch(() => getOperationalAlerts(), [])

  const [liveAlerts, setLiveAlerts] = useState<OperationalAlert[]>([])

  // Live WebSocket for network alerts
  const { connectionState } = useWebSocketFeed('/ws/network', (msg: WebSocketMessage) => {
    if (msg.event_type === 'network_alert' || msg.type === 'ALERT_CREATED') {
      const newAlert: OperationalAlert = {
        fingerprint: String(Date.now()),
        alert_type: msg.data.alert_type ?? 'STREAM_ALERT',
        severity: msg.data.severity ?? 'WARNING',
        title: msg.data.title ?? 'Real-Time Network Alert',
        description: msg.data.description ?? JSON.stringify(msg.data),
        source: 'WebSocket',
        timestamp: new Date().toISOString(),
      }
      setLiveAlerts((prev) => [newAlert, ...prev.slice(0, 9)])
    }
  })

  const combinedAlerts = [...liveAlerts, ...(alertsFetch.data || [])]

  const loading =
    trains.loading ||
    activeTrains.loading ||
    stations.loading ||
    providers.loading ||
    network.loading ||
    health.loading
  const error =
    trains.error ||
    activeTrains.error ||
    stations.error ||
    providers.error ||
    network.error ||
    health.error

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Network Operations Overview"
          description="Real-time situational awareness, train status, network propagation risk, and active alerts."
        />
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
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
      </div>

      <DataState loading={loading} error={error}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Total Active Trains"
            value={String(activeTrains.data?.total ?? 0)}
            subtext={`of ${trains.data?.total ?? 0} registered`}
            to="/operations/live-trains"
          />
          <StatCard
            label="Delayed Trains"
            value={String(network.data?.delayed_trains ?? 0)}
            subtext={`impact score: ${network.data?.network_impact_score ?? 0}/100`}
            to="/operations/network"
          />
          <StatCard
            label="Active Conflicts"
            value={String(network.data?.active_conflicts ?? 0)}
            subtext={`${network.data?.hotspots.length ?? 0} hotspots`}
            to="/operations/network"
          />
          <StatCard
            label="System Health"
            value={health.data?.status ?? 'HEALTHY'}
            subtext={`v${health.data?.version ?? '0.1.0'}`}
            to="/settings"
          />
        </div>

        {/* Operational Alerts */}
        <div className="mt-6 rounded-lg border border-slate-800 bg-slate-950 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-200">Active Operational & Predictive Alerts</h3>
            <span className="text-xs text-slate-400">{combinedAlerts.length} active</span>
          </div>

          {combinedAlerts.length === 0 ? (
            <p className="text-xs text-slate-500">No active alerts. Network is operating normally.</p>
          ) : (
            <div className="space-y-2">
              {combinedAlerts.slice(0, 5).map((alt, idx) => (
                <div
                  key={alt.fingerprint || idx}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-850 bg-slate-900/60 px-3.5 py-2.5 text-xs"
                >
                  <div className="flex flex-wrap items-center gap-2.5">
                    <Badge
                      label={alt.severity}
                      tone={alt.severity === 'CRITICAL' ? 'bad' : alt.severity === 'WARNING' ? 'warn' : 'neutral'}
                    />
                    <span className="font-medium text-slate-200">{alt.title || alt.alert_type}</span>
                    <span className="text-slate-400">{alt.description}</span>
                  </div>
                  <span className="font-mono text-[11px] text-slate-500">
                    {formatIST(alt.timestamp)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Data Providers and Live Ingestion */}
        <div className="mt-6 rounded-lg border border-slate-800 bg-slate-950 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-300">Data Providers & Live Ingestion</h3>
            {providers.data?.providers.some((p) => p.provider === 'RAILRADAR' && p.available) ? (
              <Badge label="MODE: LIVE (RAILRADAR)" tone="good" />
            ) : (
              <Badge label="MODE: DEMO / SIMULATED" tone="neutral" />
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {providers.data?.providers.map((provider) => (
              <Badge
                key={provider.provider}
                label={`${provider.provider}: ${provider.available ? 'AVAILABLE' : 'UNAVAILABLE'}`}
                tone={provider.available ? 'good' : 'bad'}
              />
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            {providers.data?.providers.some((p) => p.provider === 'RAILRADAR' && p.available) ? (
              <>
                <strong className="text-emerald-400">Live Connection Active:</strong> Primary train telemetry and live movements are streaming live from Indian Railways via the RailRadar API (<code className="text-slate-300">api.railradar.in</code>). The deterministic railway simulator stands by as an automatic zero-downtime fallback.
              </>
            ) : (
              <>
                <strong>Honesty Disclaimer:</strong> Live train telemetry and station arrival events currently run on TrackWave's deterministic railway simulator. Adapters for NTES and RailRadar are cleanly abstracted and ready for pluggable live feeds.
              </>
            )}
          </p>
        </div>
      </DataState>
    </>
  )
}