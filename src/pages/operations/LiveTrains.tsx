import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge, { dataStatusTone } from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import {
  listTrains,
  getTrain,
  getLiveTrainState,
  getLiveTrainRoute,
  getTrainEta,
  getTrainExplanation,
  formatIST,
} from '../../lib/api'
import type { EtaStation, LiveTrainRouteStop } from '../../lib/api'
import { useWebSocketFeed } from '../../lib/websocket'
import type { WebSocketMessage } from '../../lib/websocket'
import { usePageLoader } from '../../context/PageLoaderContext'

function formatTime(iso: string | null | undefined): string {
  return formatIST(iso, { hour: '2-digit', minute: '2-digit' })
}

function TrainList({ selected, onSelect }: { selected: string | null; onSelect: (trainNumber: string) => void }) {
  const [search, setSearch] = useState('')
  const { data, loading, error } = useFetch(
    () => listTrains({ page_size: 50, search: search || undefined }),
    [search],
  )

  return (
    <div className="flex w-full flex-col gap-3 lg:w-80 lg:shrink-0">
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search train number or name…"
        className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-slate-600 focus:outline-none"
      />
      <DataState loading={loading} error={error} empty={data?.items.length === 0} emptyMessage="No trains match.">
        <div className="flex max-h-80 flex-col gap-1 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 lg:max-h-none">
          {data?.items.map((train) => (
            <button
              key={train.train_number}
              onClick={() => onSelect(train.train_number)}
              className={`flex flex-col gap-0.5 border-b border-slate-900 px-3 py-2 text-left last:border-b-0 hover:bg-slate-900 ${
                selected === train.train_number ? 'bg-slate-900' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-medium text-white">
                  {train.train_number} · {train.train_name}
                </span>
                {train.active && (
                  <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" title="Active Feed" />
                )}
              </div>
              <span className="truncate text-xs text-slate-500">
                {train.source_station_code} → {train.destination_station_code} · {train.train_type}
              </span>
            </button>
          ))}
        </div>
      </DataState>
    </div>
  )
}

function ExplanationModal({
  trainNumber,
  stationCode,
  stationName,
  onClose,
}: {
  trainNumber: string
  stationCode: string
  stationName: string
  onClose: () => void
}) {
  const { data, loading, error } = useFetch(
    () => getTrainExplanation(trainNumber, stationCode),
    [trainNumber, stationCode]
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
      <div className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-950 p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white">Prediction Explainability</h3>
            <p className="text-xs text-slate-400">
              Train {trainNumber} → {stationCode} ({stationName})
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            ✕
          </button>
        </div>

        <div className="mt-4 max-h-[70vh] overflow-y-auto pr-1">
          <DataState loading={loading} error={error}>
            {data && (
              <div className="space-y-5">
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    Deterministic Baseline Factors
                  </h4>
                  <div className="mt-2 space-y-1.5">
                    {data.baseline_factors.map((bf, idx) => (
                      <div
                        key={idx}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-850 bg-slate-900/60 px-3 py-2 text-xs"
                      >
                        <span className="font-medium text-slate-200">{bf.display_name}</span>
                        <span className="text-slate-400">
                          {bf.effect} {bf.value !== null && bf.value !== undefined ? `(${bf.value}m)` : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Machine Learning Feature Contributions (TreeSHAP)
                    </h4>
                    <span className="text-[10px] text-slate-500">
                      Model: {data.model_version ?? 'xgb-residual'}
                    </span>
                  </div>

                  {!data.available ? (
                    <div className="mt-2 rounded-md border border-slate-850 bg-slate-900/40 p-3 text-xs text-slate-400">
                      ML Explanation unavailable ({data.reason ?? 'Fallback to baseline'}).
                    </div>
                  ) : (
                    <div className="mt-2 space-y-1.5">
                      {data.ml_factors.map((mf, idx) => (
                        <div
                          key={idx}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-850 bg-slate-900/60 px-3 py-2 text-xs"
                        >
                          <span className="font-medium text-slate-200">{mf.display_name}</span>
                          <div className="flex items-center gap-2">
                            <span
                              className={`font-mono font-medium ${
                                mf.direction === 'LATER' ? 'text-amber-400' : 'text-emerald-400'
                              }`}
                            >
                              {mf.direction === 'LATER' ? '+' : '-'}
                              {Math.abs(mf.contribution_minutes).toFixed(2)} min
                            </span>
                            <Badge
                              label={mf.direction}
                              tone={mf.direction === 'LATER' ? 'warn' : 'good'}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </DataState>
        </div>
      </div>
    </div>
  )
}

function TrainDetailPanel({ trainNumber }: { trainNumber: string }) {
  const { triggerLoader } = usePageLoader()
  const [activeTab, setActiveTab] = useState<'predictions' | 'route'>('predictions')
  const detail = useFetch(() => getTrain(trainNumber), [trainNumber])
  const liveState = useFetch(() => getLiveTrainState(trainNumber), [trainNumber])
  const liveRoute = useFetch(() => getLiveTrainRoute(trainNumber), [trainNumber])
  const eta = useFetch(() => getTrainEta(trainNumber), [trainNumber])
  const [selectedStation, setSelectedStation] = useState<{ code: string; name: string } | null>(null)
  const [liveOverride, setLiveOverride] = useState<any>(null)

  // Real-time WebSocket feed for this train
  const { connectionState } = useWebSocketFeed(`/ws/trains/${trainNumber}`, (msg: WebSocketMessage) => {
    if (msg.event_type === 'train_state' || msg.type === 'TRAIN_STATE_UPDATE') {
      setLiveOverride((prev: any) => ({
        ...liveState.data,
        ...prev,
        ...msg.data,
        // Preserve rich metadata, data_source and status if websocket message omitted them
        metadata: liveState.data?.metadata ?? prev?.metadata,
        data_source: msg.data?.data_source ?? liveState.data?.data_source ?? 'RAILRADAR',
        data_status: msg.data?.data_status ?? liveState.data?.data_status ?? 'LIVE',
      }))
    }
  })

  // Reset override when switching trains
  useEffect(() => {
    setLiveOverride(null)
  }, [trainNumber])

  const curState = liveOverride || liveState.data

  return (
    <div className="flex flex-1 flex-col gap-6">
      {selectedStation && (
        <ExplanationModal
          trainNumber={trainNumber}
          stationCode={selectedStation.code}
          stationName={selectedStation.name}
          onClose={() => setSelectedStation(null)}
        />
      )}

      {/* Train Identification Header */}
      <DataState loading={detail.loading} error={detail.error}>
        {detail.data && (
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-xl font-bold text-white">
                    {detail.data.train_number}
                  </h2>
                  <span className="text-slate-500">·</span>
                  <span className="text-lg font-semibold text-slate-100">
                    {curState?.metadata?.train_name || detail.data.train_name}
                  </span>
                  {curState?.data_source === 'RAILRADAR' && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-700/60 bg-emerald-950/80 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                      LIVE RAILRADAR
                    </span>
                  )}
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      connectionState === 'CONNECTED'
                        ? 'border border-emerald-800 bg-emerald-950 text-emerald-300'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        connectionState === 'CONNECTED' ? 'animate-pulse bg-emerald-400' : 'bg-slate-500'
                      }`}
                    />
                    {connectionState === 'CONNECTED' ? 'STREAM CONNECTED' : connectionState}
                  </span>
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  {detail.data.source_station_name} ({detail.data.source_station_code}) →{' '}
                  {detail.data.destination_station_name} ({detail.data.destination_station_code})
                  {detail.data.zone ? ` · ${detail.data.zone}` : ''}
                  {detail.data.train_type ? ` · ${detail.data.train_type}` : ''}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge label={detail.data.active ? 'ACTIVE SERVICE' : 'INACTIVE'} tone={detail.data.active ? 'good' : 'neutral'} />
              </div>
            </div>

            {/* Original vs Live Comparison Grid */}
            <div className="mt-4 grid grid-cols-1 gap-3 border-t border-slate-850 pt-3 text-xs md:grid-cols-2">
              <div className="rounded-md border border-slate-850/80 bg-slate-900/40 p-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Scheduled Baseline (Original Twin)
                </span>
                <div className="mt-1.5 space-y-1 text-slate-300">
                  <div>
                    <span className="text-slate-500">Scheduled Name:</span>{' '}
                    <span className="font-medium text-slate-200">{detail.data.train_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Scheduled Route:</span>{' '}
                    <span>{detail.data.source_station_code} → {detail.data.destination_station_code}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Twin Stations:</span>{' '}
                    <span>{detail.data.route_summary?.total_stations ?? '—'} stations · {detail.data.route_summary?.total_distance_km?.toFixed(0) ?? '—'} km</span>
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-emerald-950/60 bg-emerald-950/20 p-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                  Live Provider Telemetry ({curState?.data_source ?? 'RAILRADAR'})
                </span>
                <div className="mt-1.5 space-y-1 text-slate-300">
                  <div>
                    <span className="text-slate-500">Live Official Name:</span>{' '}
                    <span className="font-medium text-emerald-200">{curState?.metadata?.train_name ?? detail.data.train_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Tracking Mode:</span>{' '}
                    <span className="capitalize text-slate-200">{curState?.metadata?.tracking_mode ?? 'Real-time GPS'}</span>
                    {' · '}
                    <span className="text-slate-500">Status:</span>{' '}
                    <span className="font-semibold uppercase text-emerald-400">{curState?.metadata?.status ?? 'RUNNING'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Data Freshness:</span>{' '}
                    <span className="text-slate-300">
                      {curState?.data_age_seconds !== undefined && curState?.data_age_seconds !== null
                        ? `${curState.data_age_seconds.toFixed(1)}s ago`
                        : 'Real-time'}
                    </span>
                    {curState?.timestamp && (
                      <span className="text-slate-500"> ({formatIST(curState.timestamp)})</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </DataState>

      {/* Live Telemetry & Position */}
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-300">Live Telemetry & Position</h3>
          <div className="flex items-center gap-2">
            <Badge label={curState?.data_status ?? 'LIVE'} tone={dataStatusTone(curState?.data_status ?? 'LIVE')} />
            <Badge label={curState?.data_source ?? 'RAILRADAR'} tone="neutral" />
          </div>
        </div>

        <DataState loading={liveState.loading && !liveOverride} error={liveState.error}>
          {curState && (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-slate-500">Current Station / Section</dt>
                    <dd className="mt-0.5 font-mono text-sm font-semibold text-white">
                      {curState.metadata?.current_location?.stationName
                        ? `${curState.metadata.current_location.stationName} (${curState.station_code ?? curState.metadata.current_location.stationCode})`
                        : curState.section_code ?? curState.station_code ?? curState.current_station_code ?? '—'}
                    </dd>
                    {curState.metadata?.current_location?.status && (
                      <span className="text-[11px] capitalize text-emerald-400">
                        ● {curState.metadata.current_location.status}
                      </span>
                    )}
                  </div>

                  <div>
                    <dt className="text-xs text-slate-500">Current Delay</dt>
                    <dd className="mt-0.5 font-mono text-sm font-semibold">
                      {curState.delay_minutes !== undefined && curState.delay_minutes !== null ? (
                        curState.delay_minutes > 0 ? (
                          <span className="text-amber-400">+{Math.round(curState.delay_minutes)} min</span>
                        ) : curState.delay_minutes === 0 ? (
                          <span className="text-emerald-400">Right on time (0m)</span>
                        ) : (
                          <span className="text-emerald-400">{Math.round(curState.delay_minutes)} min (early)</span>
                        )
                      ) : (
                        <span className="text-slate-400">0 min</span>
                      )}
                    </dd>
                    <span className="text-[11px] text-slate-500">Real-time telemetry</span>
                  </div>

                  <div>
                    <dt className="text-xs text-slate-500">Speed</dt>
                    <dd className="mt-0.5 font-mono text-sm font-semibold text-white">
                      {curState.speed_kmph !== undefined && curState.speed_kmph !== null
                        ? `${curState.speed_kmph} km/h`
                        : curState.speed_kmh !== undefined
                        ? `${curState.speed_kmh} km/h`
                        : '0 km/h'}
                    </dd>
                    <span className="text-[11px] text-slate-500">GPS Tracked</span>
                  </div>

                  <div>
                    <dt className="text-xs text-slate-500">Live GPS Coordinates</dt>
                    <dd className="mt-0.5 font-mono text-xs text-slate-300">
                      {curState.position?.latitude ?? curState.current_lat ?? '—'},{' '}
                      {curState.position?.longitude ?? curState.current_lng ?? '—'}
                    </dd>
                    <span className="text-[11px] text-slate-500">WGS84 Coordinates</span>
                  </div>
                </dl>

                {/* Previous and Next Halt Details from RailRadar */}
                {(curState.metadata?.previous_halt || curState.metadata?.next_halt || curState.metadata?.current_location) && (
                  <div className="mt-4 grid grid-cols-1 gap-3 border-t border-slate-850 pt-3 sm:grid-cols-3 text-xs">
                    <div className="rounded border border-slate-850 bg-slate-900/30 p-2.5">
                      <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500">Previous Scheduled Halt</span>
                      <div className="mt-1 font-medium text-slate-200">
                        {curState.metadata?.previous_halt?.stationName ?? '—'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {curState.metadata?.previous_halt?.stationCode ? `Code: ${curState.metadata.previous_halt.stationCode}` : ''}
                        {curState.metadata?.previous_halt?.distance ? ` · ${curState.metadata.previous_halt.distance} km` : ''}
                      </div>
                    </div>

                    <div className="rounded border border-slate-850 bg-slate-900/30 p-2.5">
                      <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500">Current Segment Progress</span>
                      <div className="mt-1 font-medium text-slate-200">
                        {curState.metadata?.current_location?.distanceFromOriginKm
                          ? `${curState.metadata.current_location.distanceFromOriginKm} km from origin`
                          : 'In Transit'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {curState.metadata?.current_location?.distanceFromLastStationKm
                          ? `${curState.metadata.current_location.distanceFromLastStationKm} km from last station`
                          : ''}
                      </div>
                    </div>

                    <div className="rounded border border-slate-850 bg-slate-900/30 p-2.5">
                      <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500">Next Scheduled Halt</span>
                      <div className="mt-1 font-medium text-slate-200">
                        {curState.metadata?.next_halt?.stationName ?? '—'}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {curState.metadata?.next_halt?.stationCode ? `Code: ${curState.metadata.next_halt.stationCode}` : ''}
                        {curState.metadata?.next_halt?.distance ? ` · ${curState.metadata.next_halt.distance} km` : ''}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </DataState>
      </div>

      {/* Tabs Switcher: AI Predictions vs Full RailRadar Live Route */}
      <div>
        <div className="flex overflow-x-auto border-b border-slate-800">
          <button
            onClick={() => {
              setActiveTab('predictions')
              triggerLoader('Loading AI Predictions & Uncertainty…', 'Evaluating baseline physics, XGBoost residual & 80% quantiles', 220)
            }}
            className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
              activeTab === 'predictions'
                ? 'border-indigo-500 text-white'
                : 'border-transparent text-slate-400 hover:border-slate-700 hover:text-slate-200'
            }`}
          >
            AI Predictions & Uncertainty
            {eta.data?.stations && (
              <span className="ml-2 rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">
                {eta.data.stations.length} Stops
              </span>
            )}
          </button>
          <button
            onClick={() => {
              setActiveTab('route')
              triggerLoader('Loading RailRadar Live Route…', 'Streaming official timetable and all 94 stops', 220)
            }}
            className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
              activeTab === 'route'
                ? 'border-indigo-500 text-white'
                : 'border-transparent text-slate-400 hover:border-slate-700 hover:text-slate-200'
            }`}
          >
            Full RailRadar Live Route
            {liveRoute.data?.stations && (
              <span className="ml-2 rounded-full border border-emerald-800/60 bg-emerald-950 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                {liveRoute.data.stations.length} Stops
              </span>
            )}
          </button>
        </div>

        {activeTab === 'predictions' ? (
          <div className="mt-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-slate-400">
                Baseline ETA + XGBoost Residual + 80% Quantile Uncertainty Intervals + TreeSHAP explainability.
              </span>
              {eta.data?.model_version && (
                <span className="text-xs text-slate-400">Model: {eta.data.model_version}</span>
              )}
            </div>

            <DataState loading={eta.loading} error={eta.error} empty={eta.data?.stations.length === 0} emptyMessage="No upcoming stations.">
              {eta.data && (
                <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-500">
                        <th className="px-4 py-3 font-medium">Station</th>
                        <th className="px-4 py-3 font-medium">Scheduled</th>
                        <th className="px-4 py-3 font-medium">Baseline ETA</th>
                        <th className="px-4 py-3 font-medium">ML Residual</th>
                        <th className="px-4 py-3 font-medium">Final ETA</th>
                        <th className="px-4 py-3 font-medium">80% Uncertainty Band</th>
                        <th className="px-4 py-3 font-medium">Confidence</th>
                        <th className="px-4 py-3 font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-900">
                      {eta.data.stations.map((st: EtaStation) => (
                        <tr key={st.sequence_number} className="hover:bg-slate-900/50">
                          <td className="px-4 py-2.5 font-medium text-slate-100">
                            {st.station_code} · {st.station_name}
                          </td>
                          <td className="px-4 py-2.5 text-slate-400">{formatTime(st.scheduled_arrival)}</td>
                          <td className="px-4 py-2.5 font-mono text-slate-300">{formatTime(st.baseline_eta)}</td>
                          <td className="px-4 py-2.5 font-mono">
                            {st.predicted_residual_minutes !== null && st.predicted_residual_minutes !== undefined ? (
                              <span className={st.predicted_residual_minutes > 0 ? 'text-amber-400' : 'text-emerald-400'}>
                                {st.predicted_residual_minutes > 0 ? '+' : ''}
                                {st.predicted_residual_minutes.toFixed(1)}m
                              </span>
                            ) : (
                              <span className="text-slate-500">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 font-mono font-semibold text-white">
                            {formatTime(st.final_eta ?? st.baseline_eta)}
                          </td>
                          <td className="px-4 py-2.5 font-mono text-[11px] text-slate-400">
                            {st.uncertainty?.lower_eta && st.uncertainty?.upper_eta ? (
                              <span>
                                [{formatTime(st.uncertainty.lower_eta)} .. {formatTime(st.uncertainty.upper_eta)}]
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            {st.confidence ? (
                              <span
                                className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${
                                  st.confidence.level === 'HIGH'
                                    ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                                    : st.confidence.level === 'MEDIUM'
                                    ? 'bg-amber-950 text-amber-300 border border-amber-800'
                                    : 'bg-red-950 text-red-300 border border-red-800'
                                }`}
                              >
                                {st.confidence.score}% ({st.confidence.level})
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <button
                              onClick={() => setSelectedStation({ code: st.station_code, name: st.station_name })}
                              className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-200 hover:bg-slate-700"
                            >
                              Explain
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </DataState>
          </div>
        ) : (
          <div className="mt-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-slate-400">
                Live official timetable and stop-by-stop schedule streamed from RailRadar API.
              </span>
              {liveRoute.data && (
                <span className="text-xs text-slate-500">
                  Source: <span className="text-slate-300">{liveRoute.data.data_source ?? 'RAILRADAR'}</span> · Status:{' '}
                  <span className="text-emerald-400">{liveRoute.data.data_status}</span>
                </span>
              )}
            </div>

            <DataState
              loading={liveRoute.loading}
              error={liveRoute.error}
              empty={liveRoute.data?.stations?.length === 0}
              emptyMessage="No route schedule available for this train."
            >
              {liveRoute.data && (
                <div className="max-h-[500px] overflow-y-auto rounded-lg border border-slate-800 bg-slate-950">
                  <table className="w-full text-left text-xs">
                    <thead className="sticky top-0 bg-slate-950 border-b border-slate-800 text-slate-500">
                      <tr>
                        <th className="px-4 py-3 font-medium">#</th>
                        <th className="px-4 py-3 font-medium">Station</th>
                        <th className="px-4 py-3 font-medium">Scheduled Arrival</th>
                        <th className="px-4 py-3 font-medium">Scheduled Departure</th>
                        <th className="px-4 py-3 font-medium">Distance</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-900">
                      {liveRoute.data.stations.map((stop: LiveTrainRouteStop) => {
                        const isCurrentStation =
                          curState?.station_code === stop.station_code ||
                          curState?.metadata?.current_location?.stationCode === stop.station_code

                        return (
                          <tr
                            key={stop.sequence_number}
                            className={`hover:bg-slate-900/50 ${
                              isCurrentStation ? 'bg-indigo-950/40 font-medium' : ''
                            }`}
                          >
                            <td className="px-4 py-2.5 font-mono text-slate-400">
                              {stop.sequence_number}
                            </td>
                            <td className="px-4 py-2.5 text-slate-100">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-white">{stop.station_code}</span>
                                <span className="text-slate-400">{stop.station_name ?? '—'}</span>
                                {isCurrentStation && (
                                  <span className="inline-flex items-center gap-1 rounded bg-emerald-950 border border-emerald-800 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                                    CURRENT / NEAR
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-4 py-2.5 font-mono text-slate-300">
                              {stop.arrival_time ?? 'Origin (Starts)'}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-slate-300">
                              {stop.departure_time ?? 'Terminates'}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-slate-400">
                              {stop.distance_km !== null ? `${stop.distance_km.toFixed(1)} km` : '—'}
                            </td>
                            <td className="px-4 py-2.5">
                              {isCurrentStation ? (
                                <span className="text-emerald-400 font-medium text-[11px]">
                                  {curState?.metadata?.current_location?.status?.toUpperCase() ?? 'ACTIVE'}
                                </span>
                              ) : (
                                <span className="text-slate-500 text-[11px]">Scheduled</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </DataState>
          </div>
        )}
      </div>
    </div>
  )
}

export default function LiveTrains() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selected = searchParams.get('train')

  function selectTrain(trainNumber: string) {
    setSearchParams({ train: trainNumber })
  }

  return (
    <>
      <PageHeader
        title="Live Trains & AI Prediction"
        description="Real-time telemetry, continuous baseline + ML residual ETAs, uncertainty bands, and SHAP explainability."
      />
      <div className="flex flex-col gap-6 lg:flex-row">
        <TrainList selected={selected} onSelect={selectTrain} />
        {selected ? (
          <TrainDetailPanel trainNumber={selected} />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-slate-800 bg-slate-950 p-6 text-sm text-slate-400">
            Select a train to inspect its live position, ETA, uncertainty intervals, and explanations.
          </div>
        )}
      </div>
    </>
  )
}