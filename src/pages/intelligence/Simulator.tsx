import { useState } from 'react'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import {
  getTrainEta,
  getTrainNetworkImpact,
  getLiveTrainState,
  formatIST,
} from '../../lib/api'
import type { EtaStation } from '../../lib/api'
import { useWebSocketFeed } from '../../lib/websocket'
import type { WebSocketMessage } from '../../lib/websocket'

export default function Simulator() {
  const [selectedTrain, setSelectedTrain] = useState('12002')
  const [simDelay, setSimDelay] = useState(0)
  const [simStep, setSimStep] = useState(0)
  const [logMessages, setLogMessages] = useState<Array<{ time: string; text: string; tone: string }>>([
    {
      time: new Date().toISOString(),
      text: 'Simulator initialized in deterministic demo mode. Select a scenario step below.',
      tone: 'neutral',
    },
  ])

  const eta = useFetch(() => getTrainEta(selectedTrain), [selectedTrain, simStep])
  const liveState = useFetch(() => getLiveTrainState(selectedTrain), [selectedTrain, simStep])
  const impact = useFetch(() => getTrainNetworkImpact(selectedTrain), [selectedTrain, simStep])

  // Live WebSocket feed for this train and network updates
  const { connectionState } = useWebSocketFeed(`/ws/trains/${selectedTrain}`, (msg: WebSocketMessage) => {
    const text = `[WebSocket] ${msg.event_type || msg.type}: train ${msg.train_number || selectedTrain} updated`
    setLogMessages((prev) => [{ time: msg.timestamp, text, tone: 'good' }, ...prev.slice(0, 19)])
  })

  function addLog(text: string, tone: string = 'neutral') {
    setLogMessages((prev) => [{ time: new Date().toISOString(), text, tone }, ...prev.slice(0, 19)])
  }

  function handleInjectDelay(delayMinutes: number, desc: string) {
    setSimDelay(delayMinutes)
    setSimStep((s) => s + 1)
    addLog(
      `Scenario Step: Injected ${delayMinutes > 0 ? `+${delayMinutes}m` : '0m'} delay (${desc}) → recalculating baseline + ML residual.`,
      delayMinutes >= 15 ? 'bad' : delayMinutes > 0 ? 'warn' : 'good'
    )
  }

  function handleReset() {
    setSimDelay(0)
    setSimStep(0)
    addLog('Simulation reset to origin on-time baseline state.', 'neutral')
  }

  const loading = eta.loading || liveState.loading || impact.loading
  const error = eta.error || liveState.error

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Interactive Railway Scenario Simulator"
          description="Test and observe how train delays trigger deterministic baseline adjustments, ML residuals, uncertainty intervals, and network cascade analysis."
        />
        <div className="flex flex-wrap items-center gap-2">
          <Badge label="MODE: SIMULATED / DEMO" tone="neutral" />
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
            {connectionState === 'CONNECTED' ? 'STREAM CONNECTED' : connectionState}
          </span>
        </div>
      </div>

      {/* Scenario Control Panel */}
      <div className="rounded-xl border border-slate-800 bg-slate-950 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-850 pb-4">
          <div>
            <h3 className="text-sm font-semibold text-white">Scenario Injection Controls</h3>
            <p className="text-xs text-slate-400">
              Inject real-time operational disturbances to observe immediate model and network cascade responses.
            </p>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <span className="text-xs text-slate-400">Target Train:</span>
            <select
              value={selectedTrain}
              onChange={(e) => setSelectedTrain(e.target.value)}
              className="w-full min-w-0 max-w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white focus:outline-none sm:w-auto"
            >
              <option value="12002">12002 · Bhopal Shatabdi (NDLS → AGC → VGLB)</option>
              <option value="12951">12951 · Mumbai Rajdhani (BCT → AGC → NDLS)</option>
              <option value="12615">12615 · Grand Trunk Express (MAS → AGC → NDLS)</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-xs font-medium text-slate-400">Preset Disturbances:</span>
          <button
            onClick={() => handleInjectDelay(0, 'Train running on time')}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              simDelay === 0
                ? 'border-emerald-600 bg-emerald-950/80 text-emerald-300'
                : 'border-slate-800 bg-slate-900 text-slate-300 hover:bg-slate-800'
            }`}
          >
            T0: On-Time (+0m)
          </button>
          <button
            onClick={() => handleInjectDelay(5, 'Speed restriction on track')}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              simDelay === 5
                ? 'border-amber-600 bg-amber-950/80 text-amber-300'
                : 'border-slate-800 bg-slate-900 text-slate-300 hover:bg-slate-800'
            }`}
          >
            T1: Minor Slowdown (+5m)
          </button>
          <button
            onClick={() => handleInjectDelay(10, 'Signal clearance congestion')}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              simDelay === 10
                ? 'border-amber-600 bg-amber-950/80 text-amber-300'
                : 'border-slate-800 bg-slate-900 text-slate-300 hover:bg-slate-800'
            }`}
          >
            T2: Congestion (+10m)
          </button>
          <button
            onClick={() => handleInjectDelay(18, 'Major section delay jump (Triggers Network Cascade)')}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
              simDelay === 18
                ? 'border-red-600 bg-red-950/80 text-red-300'
                : 'border-slate-800 bg-slate-900 text-slate-300 hover:bg-slate-800'
            }`}
          >
            T3: Severe Delay (+18m)
          </button>
          <button
            onClick={handleReset}
            className="ml-auto rounded-lg border border-slate-700 bg-slate-850 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700"
          >
            Reset
          </button>
        </div>
      </div>

      <DataState loading={loading} error={error}>
        {/* Real-time Response Cards */}
        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {/* Telemetry & State */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Current Simulated State
            </h4>
            <div className="mt-3 space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Position</span>
                <span className="font-mono text-slate-200">
                  {liveState.data?.section_code ?? liveState.data?.station_code ?? 'NDLS'}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Injected Delay</span>
                <span className="font-mono font-semibold text-amber-400">+{simDelay} min</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Speed</span>
                <span className="font-mono text-slate-200">
                  {liveState.data?.speed_kmph ?? 85} km/h
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Data Source</span>
                <Badge label="SIMULATOR" tone="neutral" />
              </div>
            </div>
          </div>

          {/* AI ETA & Uncertainty */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Next Station ETA & Uncertainty
            </h4>
            {eta.data?.stations && eta.data.stations.length > 0 ? (
              <div className="mt-3 space-y-2">
                {(() => {
                  const nextSt: EtaStation = eta.data.stations[0]
                  return (
                    <>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">Station</span>
                        <span className="font-semibold text-white">
                          {nextSt.station_code} ({nextSt.station_name})
                        </span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">Baseline ETA</span>
                        <span className="font-mono text-slate-300">
                          {formatIST(nextSt.baseline_eta)}
                        </span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">ML Residual</span>
                        <span className="font-mono text-emerald-400">
                          {nextSt.predicted_residual_minutes !== undefined && nextSt.predicted_residual_minutes !== null
                            ? `${nextSt.predicted_residual_minutes > 0 ? '+' : ''}${nextSt.predicted_residual_minutes.toFixed(1)}m`
                            : '—'}
                        </span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">Final ETA</span>
                        <span className="font-mono font-bold text-white">
                          {formatIST(nextSt.final_eta ?? nextSt.baseline_eta)}
                        </span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-slate-400">Confidence</span>
                        <span className="font-mono text-xs text-emerald-300">
                          {nextSt.confidence?.score ?? 95}% ({nextSt.confidence?.level ?? 'HIGH'})
                        </span>
                      </div>
                    </>
                  )
                })()}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">No upcoming stations.</p>
            )}
          </div>

          {/* Network Impact */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Network Cascade Impact
            </h4>
            <div className="mt-3 space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Impact Score</span>
                <span className="font-mono font-bold text-white">
                  {impact.data?.network_impact_score ?? Math.min(100, simDelay * 4)} / 100
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Severity</span>
                <Badge
                  label={impact.data?.severity ?? (simDelay >= 15 ? 'CRITICAL' : simDelay >= 8 ? 'MEDIUM' : 'LOW')}
                  tone={simDelay >= 15 ? 'bad' : simDelay >= 8 ? 'warn' : 'neutral'}
                />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Affected Trains</span>
                <span className="font-mono text-slate-200">
                  {impact.data?.total_affected_trains ?? (simDelay >= 15 ? 3 : simDelay >= 8 ? 1 : 0)} trains
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Active Conflicts</span>
                <span className="font-mono text-slate-200">
                  {impact.data?.active_conflicts?.length ?? (simDelay >= 15 ? 2 : 0)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Live Simulation Event Log */}
        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-5">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Live Pipeline Stream Event Log
            </h4>
            <span className="text-[10px] text-slate-500 font-mono">Last 20 events</span>
          </div>

          <div className="space-y-1.5 font-mono text-xs max-h-48 overflow-y-auto">
            {logMessages.map((entry, idx) => (
              <div
                key={idx}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-900 bg-slate-900/40 px-3 py-1.5 text-slate-300"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      entry.tone === 'bad'
                        ? 'bg-red-400'
                        : entry.tone === 'warn'
                        ? 'bg-amber-400'
                        : entry.tone === 'good'
                        ? 'bg-emerald-400'
                        : 'bg-slate-400'
                    }`}
                  />
                  <span>{entry.text}</span>
                </div>
                <span className="text-[10px] text-slate-500">{formatIST(entry.time)}</span>
              </div>
            ))}
          </div>
        </div>
      </DataState>
    </>
  )
}