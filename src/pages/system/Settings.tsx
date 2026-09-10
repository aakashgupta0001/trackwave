import { useState } from 'react'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import {
  getProvidersStatus,
  getSystemHealth,
  getSystemReadiness,
  getSystemLiveness,
  getSystemMetrics,
  getProviderMetrics,
  getStreamingMetrics,
  getStreamingStatus,
  getAuditLog,
  promoteModel,
  rollbackModel,
  formatIST,
  ApiError,
} from '../../lib/api'
import type { AuditLogEntry } from '../../lib/api'

function formatTimestamp(iso: string | null): string {
  return formatIST(iso)
}

function HealthCard() {
  const { data, loading, error } = useFetch(() => getSystemHealth(), [])

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-300">Deep System Health & Dependencies</h3>
      <DataState loading={loading} error={error}>
        {data && (
          <div className="flex flex-wrap items-center gap-6 rounded-lg border border-slate-800 bg-slate-950 p-5">
            <Badge label={data.status} tone={data.status === 'HEALTHY' ? 'good' : 'warn'} />
            <div className="text-xs">
              <span className="text-slate-500">PostgreSQL: </span>
              <span className={data.components?.database === 'UP' ? 'text-emerald-300 font-mono font-semibold' : 'text-red-300 font-mono font-semibold'}>
                {data.components?.database ?? 'UNKNOWN'}
              </span>
            </div>
            <div className="text-xs">
              <span className="text-slate-500">Redis: </span>
              <span className={data.components?.redis === 'UP' ? 'text-emerald-300 font-mono font-semibold' : 'text-amber-300 font-mono font-semibold'}>
                {data.components?.redis ?? 'UNKNOWN'}
              </span>
            </div>
            <div className="text-xs">
              <span className="text-slate-500">ML Model: </span>
              <span className={data.components?.model === 'UP' ? 'text-emerald-300 font-mono font-semibold' : 'text-amber-300 font-mono font-semibold'}>
                {data.components?.model ?? 'UNKNOWN'} ({data.details?.active_model_version ?? 'xgb-residual-v1'})
              </span>
            </div>
            <div className="text-xs">
              <span className="text-slate-500">Streaming: </span>
              <span className={data.components?.streaming === 'UP' ? 'text-emerald-300 font-mono font-semibold' : 'text-amber-300 font-mono font-semibold'}>
                {data.components?.streaming ?? 'UNKNOWN'}
              </span>
            </div>
            <div className="text-xs">
              <span className="text-slate-500">Network Engine: </span>
              <span className={data.components?.network === 'UP' ? 'text-emerald-300 font-mono font-semibold' : 'text-amber-300 font-mono font-semibold'}>
                {data.components?.network ?? 'UNKNOWN'}
              </span>
            </div>
            <div className="text-xs text-slate-500 font-mono">mode: {data.details?.mode ?? 'DEMO'}</div>
          </div>
        )}
      </DataState>
    </div>
  )
}

function DiagnosticsCard() {
  const readiness = useFetch(() => getSystemReadiness(), [])
  const liveness = useFetch(() => getSystemLiveness(), [])
  const metrics = useFetch(() => getSystemMetrics(), [])
  const providerMetrics = useFetch(() => getProviderMetrics(), [])
  const streamingMetrics = useFetch(() => getStreamingMetrics(), [])
  const streamingStatus = useFetch(() => getStreamingStatus(), [])

  const loading =
    readiness.loading || liveness.loading || metrics.loading || providerMetrics.loading || streamingMetrics.loading || streamingStatus.loading
  const error = readiness.error || liveness.error || metrics.error || providerMetrics.error || streamingMetrics.error || streamingStatus.error

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-300">Platform Diagnostics</h3>
      <DataState loading={loading} error={error}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-semibold text-white">Readiness / Liveness</span>
              <div className="flex gap-1.5">
                <Badge label={readiness.data?.ready ? 'READY' : 'NOT READY'} tone={readiness.data?.ready ? 'good' : 'bad'} />
                <Badge label={liveness.data?.alive ? 'ALIVE' : 'DEAD'} tone={liveness.data?.alive ? 'good' : 'bad'} />
              </div>
            </div>
            {readiness.data && (
              <dl className="mt-3 flex flex-col gap-1.5 text-xs">
                {Object.entries(readiness.data.checks).map(([check, ok]) => (
                  <div key={check} className="flex justify-between">
                    <dt className="text-slate-500">{check}</dt>
                    <dd className={ok ? 'text-emerald-300' : 'text-red-300'}>{ok ? 'ok' : 'failing'}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
            <span className="text-sm font-semibold text-white">Streaming</span>
            {streamingMetrics.data && (
              <dl className="mt-3 flex flex-col gap-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-slate-500">Worker status</dt>
                  <dd className="text-slate-300">{streamingMetrics.data.worker_status}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Events ingested</dt>
                  <dd className="font-mono text-slate-300">{streamingMetrics.data.events_ingested_total}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Predictions calculated</dt>
                  <dd className="font-mono text-slate-300">{streamingMetrics.data.predictions_calculated_total}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Network recalcs</dt>
                  <dd className="font-mono text-slate-300">{streamingMetrics.data.network_recalcs_total}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Streaming enabled</dt>
                  <dd className="text-slate-300">{String(streamingStatus.data?.streaming_enabled ?? '—')}</dd>
                </div>
              </dl>
            )}
          </div>

          {providerMetrics.data && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 sm:col-span-2">
              <span className="text-sm font-semibold text-white">Provider Latency & Health</span>
              <div className="mt-3 flex flex-col gap-2 text-xs">
                {Object.entries(providerMetrics.data.providers).map(([name, stats]) => (
                  <pre
                    key={name}
                    className="overflow-x-auto rounded border border-slate-850 bg-slate-900/60 p-2 font-mono text-slate-300"
                  >
                    {name}: {JSON.stringify(stats)}
                  </pre>
                ))}
              </div>
            </div>
          )}

          {metrics.data && (
            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 sm:col-span-2">
              <span className="text-sm font-semibold text-white">System Metrics Overview</span>
              <pre className="mt-3 overflow-x-auto text-xs text-slate-300">{JSON.stringify(metrics.data, null, 2)}</pre>
            </div>
          )}
        </div>
      </DataState>
    </div>
  )
}

function MlopsAdminPanel() {
  const [adminKey, setAdminKey] = useState('')
  const [auditLog, setAuditLog] = useState<AuditLogEntry[] | null>(null)
  const [auditError, setAuditError] = useState<string | undefined>(undefined)
  const [auditLoading, setAuditLoading] = useState(false)
  const [actionMessage, setActionMessage] = useState<string | undefined>(undefined)
  const [promoteVersion, setPromoteVersion] = useState('')
  const [rollbackVersion, setRollbackVersion] = useState('')

  async function loadAuditLog() {
    setAuditLoading(true)
    setAuditError(undefined)
    try {
      setAuditLog(await getAuditLog(adminKey))
    } catch (err) {
      setAuditError(err instanceof ApiError ? err.message : 'Could not reach the backend.')
    } finally {
      setAuditLoading(false)
    }
  }

  async function handlePromote() {
    if (!promoteVersion) return
    if (!confirm(`Promote model "${promoteVersion}" to PRODUCTION?`)) return
    try {
      const result = await promoteModel(promoteVersion, adminKey)
      setActionMessage(result.message)
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Could not reach the backend.')
    }
  }

  async function handleRollback() {
    if (!rollbackVersion) return
    if (!confirm(`Roll back the production model pointer to "${rollbackVersion}"?`)) return
    try {
      const result = await rollbackModel(rollbackVersion, adminKey)
      setActionMessage(result.message)
    } catch (err) {
      setActionMessage(err instanceof ApiError ? err.message : 'Could not reach the backend.')
    }
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-300">MLOps Admin</h3>
      <p className="mb-3 text-xs text-slate-500">
        Sensitive mutations (model promotion, rollback, audit log) require an admin API key — unset in local
        development. Nothing here is called automatically.
      </p>
      <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          X-Admin-API-Key
          <input
            type="password"
            value={adminKey}
            onChange={(e) => setAdminKey(e.target.value)}
            placeholder="leave blank in local development"
            className="rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-slate-600 focus:outline-none"
          />
        </label>

        {actionMessage && <p className="mt-3 text-xs text-sky-300">{actionMessage}</p>}

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-slate-300">Promote model to production</span>
            <div className="flex gap-2">
              <input
                type="text"
                value={promoteVersion}
                onChange={(e) => setPromoteVersion(e.target.value)}
                placeholder="model version"
                className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-slate-600 focus:outline-none"
              />
              <button
                onClick={handlePromote}
                className="shrink-0 rounded-md border border-emerald-800 bg-emerald-950 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-900"
              >
                Promote
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-slate-300">Rollback production pointer</span>
            <div className="flex gap-2">
              <input
                type="text"
                value={rollbackVersion}
                onChange={(e) => setRollbackVersion(e.target.value)}
                placeholder="target version"
                className="w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-slate-600 focus:outline-none"
              />
              <button
                onClick={handleRollback}
                className="shrink-0 rounded-md border border-amber-800 bg-amber-950 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-900"
              >
                Rollback
              </button>
            </div>
          </div>
        </div>

        <div className="mt-4 border-t border-slate-850 pt-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300">Audit log</span>
            <button
              onClick={loadAuditLog}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800"
            >
              Load
            </button>
          </div>
          <DataState loading={auditLoading} error={auditError} empty={auditLog?.length === 0} emptyMessage="No audit events recorded.">
            {auditLog && (
              <div className="mt-2 flex flex-col gap-1.5 text-xs">
                {auditLog.map((entry) => (
                  <div key={entry.id} className="flex flex-wrap items-center gap-2 rounded border border-slate-850 bg-slate-900/60 px-2 py-1.5">
                    <span className="font-mono text-slate-300">{entry.action}</span>
                    <span className="text-slate-500">by {entry.actor}</span>
                    <span className="text-slate-500">{formatIST(entry.timestamp)}</span>
                    {entry.previous_value && <span className="text-slate-500">{entry.previous_value} → {entry.new_value}</span>}
                    {entry.reason && <span className="text-slate-400">({entry.reason})</span>}
                  </div>
                ))}
              </div>
            )}
          </DataState>
        </div>
      </div>
    </div>
  )
}

export default function Settings() {
  const { data, loading, error } = useFetch(() => getProvidersStatus(), [])

  return (
    <>
      <PageHeader
        title="Settings"
        description="System health and live-data provider configuration."
      />
      <div className="flex flex-col gap-6">
        <HealthCard />
        <DiagnosticsCard />

        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-300">Live data providers</h3>
          <p className="mb-3 text-xs text-slate-500">
            NTES has no documented public API and RailRadar requires real credentials — both
            honestly report unavailable until configured. The simulator wraps TrackWave's own
            sample data and is always clearly labeled as simulated, never presented as live.
          </p>
          <DataState loading={loading} error={error}>
            {data && (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                {data.providers.map((provider) => (
                  <div key={provider.provider} className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-white">{provider.provider}</span>
                      <Badge label={provider.available ? 'AVAILABLE' : 'UNAVAILABLE'} tone={provider.available ? 'good' : 'bad'} />
                    </div>
                    <dl className="mt-3 flex flex-col gap-1.5 text-xs">
                      <div className="flex justify-between">
                        <dt className="text-slate-500">Type</dt>
                        <dd className="text-slate-300">{provider.provider_type}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-slate-500">Enabled</dt>
                        <dd className="text-slate-300">{provider.enabled ? 'yes' : 'no'}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-slate-500">Configured</dt>
                        <dd className="text-slate-300">{provider.configured ? 'yes' : 'no'}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-slate-500">Last success</dt>
                        <dd className="text-slate-300">{formatTimestamp(provider.last_success)}</dd>
                      </div>
                      {provider.error && <div className="mt-1 text-amber-300">{provider.error}</div>}
                    </dl>
                  </div>
                ))}
              </div>
            )}
          </DataState>
        </div>

        <MlopsAdminPanel />
      </div>
    </>
  )
}
