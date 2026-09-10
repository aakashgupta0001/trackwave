import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge, { boardStatusTone, dataStatusTone } from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import { listStations, getStation, getStationBoard, getLiveStationBoard, formatIST } from '../../lib/api'
import { useWebSocketFeed } from '../../lib/websocket'

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  // scheduled_arrival/departure come back as plain HH:MM:SS time strings, not full ISO.
  return iso.slice(0, 5)
}

function StationList({ selected, onSelect }: { selected: string | null; onSelect: (code: string) => void }) {
  const [search, setSearch] = useState('')
  const { data, loading, error } = useFetch(
    () => listStations({ page_size: 50, search: search || undefined }),
    [search],
  )

  return (
    <div className="flex w-full flex-col gap-3 lg:w-80 lg:shrink-0">
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search station code or name…"
        className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-slate-600 focus:outline-none"
      />
      <DataState loading={loading} error={error} empty={data?.items.length === 0} emptyMessage="No stations match.">
        <div className="flex max-h-80 flex-col gap-1 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 lg:max-h-none">
          {data?.items.map((station) => (
            <button
              key={station.station_code}
              onClick={() => onSelect(station.station_code)}
              className={`flex flex-col gap-0.5 border-b border-slate-900 px-3 py-2 text-left last:border-b-0 hover:bg-slate-900 ${
                selected === station.station_code ? 'bg-slate-900' : ''
              }`}
            >
              <span className="truncate text-sm font-medium text-white">
                {station.station_code} · {station.station_name}
              </span>
              <span className="truncate text-xs text-slate-500">
                {station.zone} {station.state ? `· ${station.state}` : ''} · {station.station_type}
              </span>
            </button>
          ))}
        </div>
      </DataState>
    </div>
  )
}

function StationDetailPanel({ stationCode }: { stationCode: string }) {
  const [refreshKey, setRefreshKey] = useState(0)
  const detail = useFetch(() => getStation(stationCode), [stationCode])
  const board = useFetch(() => getStationBoard(stationCode), [stationCode, refreshKey])
  const liveBoard = useFetch(() => getLiveStationBoard(stationCode), [stationCode, refreshKey])

  const { connectionState } = useWebSocketFeed(`/ws/stations/${stationCode}`, () => {
    setRefreshKey((k) => k + 1)
  })

  return (
    <div className="flex flex-1 flex-col gap-6">
      <DataState loading={detail.loading} error={detail.error}>
        {detail.data && (
          <div className="rounded-lg border border-slate-800 bg-slate-950 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-white">
                {detail.data.station_code} · {detail.data.station_name}
              </h2>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  connectionState === 'CONNECTED'
                    ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                    : 'bg-slate-800 text-slate-400'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    connectionState === 'CONNECTED' ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'
                  }`}
                />
                {connectionState === 'CONNECTED' ? 'LIVE BOARD STREAM' : connectionState}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-400">
              {detail.data.zone} zone{detail.data.division ? ` · ${detail.data.division} division` : ''}
              {detail.data.state ? ` · ${detail.data.state}` : ''} · {detail.data.station_type}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {detail.data.latitude.toFixed(4)}, {detail.data.longitude.toFixed(4)}
            </p>
          </div>
        )}
      </DataState>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-300">
          Station board <span className="text-xs font-normal text-slate-500">(latest known info, not predicted ETAs)</span>
        </h3>
        <DataState
          loading={board.loading}
          error={board.error}
          empty={board.data?.board.length === 0}
          emptyMessage="No trains scheduled through this station."
        >
          {board.data && (
            <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                    <th className="px-4 py-2 font-medium">Train</th>
                    <th className="px-4 py-2 font-medium">Route</th>
                    <th className="px-4 py-2 font-medium">Arr.</th>
                    <th className="px-4 py-2 font-medium">Dep.</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {board.data.board.map((entry) => (
                    <tr key={entry.train_number} className="border-b border-slate-900 last:border-b-0">
                      <td className="px-4 py-2 text-slate-100">
                        {entry.train_number} · {entry.train_name}
                      </td>
                      <td className="px-4 py-2 text-slate-400">
                        {entry.source_station_code} → {entry.destination_station_code}
                      </td>
                      <td className="px-4 py-2 text-slate-400">{formatTime(entry.scheduled_arrival)}</td>
                      <td className="px-4 py-2 text-slate-400">{formatTime(entry.scheduled_departure)}</td>
                      <td className="px-4 py-2">
                        <Badge
                          label={
                            entry.status === 'DELAYED' && entry.latest_known_delay_minutes
                              ? `+${entry.latest_known_delay_minutes} min`
                              : entry.status.replaceAll('_', ' ')
                          }
                          tone={boardStatusTone(entry.status)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </div>

      <div>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-300">Live provider board</h3>
          {liveBoard.data && <Badge label={liveBoard.data.data_status} tone={dataStatusTone(liveBoard.data.data_status)} />}
        </div>
        <DataState
          loading={liveBoard.loading}
          error={liveBoard.error}
          empty={liveBoard.data?.trains.length === 0}
          emptyMessage="Live provider has no trains for this station right now."
        >
          {liveBoard.data && (
            <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950">
              {liveBoard.data.error && <p className="border-b border-slate-900 px-4 py-2 text-xs text-amber-300">{liveBoard.data.error}</p>}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                    <th className="px-4 py-2 font-medium">Train</th>
                    <th className="px-4 py-2 font-medium">Arr.</th>
                    <th className="px-4 py-2 font-medium">Dep.</th>
                    <th className="px-4 py-2 font-medium">Delay</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {liveBoard.data.trains.map((entry) => (
                    <tr key={entry.train_number} className="border-b border-slate-900 last:border-b-0">
                      <td className="px-4 py-2 text-slate-100">
                        {entry.train_number}
                        {entry.train_name ? ` · ${entry.train_name}` : ''}
                      </td>
                      <td className="px-4 py-2 text-slate-400">{formatTime(entry.scheduled_arrival)}</td>
                      <td className="px-4 py-2 text-slate-400">{formatTime(entry.scheduled_departure)}</td>
                      <td className="px-4 py-2 text-slate-400">
                        {entry.delay_minutes != null
                          ? `${entry.delay_minutes > 0 ? '+' : ''}${entry.delay_minutes} min`
                          : '—'}
                      </td>
                      <td className="px-4 py-2 text-slate-400">{entry.status ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {liveBoard.data.retrieved_at && (
                <p className="border-t border-slate-900 px-4 py-2 text-[11px] text-slate-600">
                  Retrieved {formatIST(liveBoard.data.retrieved_at)} IST
                </p>
              )}
            </div>
          )}
        </DataState>
      </div>
    </div>
  )
}

export default function Stations() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selected = searchParams.get('station')

  function selectStation(code: string) {
    setSearchParams({ station: code })
  }

  return (
    <>
      <PageHeader title="Stations" description="Station reference data and operational boards." />
      <div className="flex flex-col gap-6 lg:flex-row">
        <StationList selected={selected} onSelect={selectStation} />
        {selected ? (
          <StationDetailPanel stationCode={selected} />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-slate-800 bg-slate-950 p-6 text-sm text-slate-400">
            Select a station to see its details and board.
          </div>
        )}
      </div>
    </>
  )
}
