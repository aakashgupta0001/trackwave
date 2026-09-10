// Typed client for the TrackWave backend. Types mirror the Pydantic response schemas in
// backend/app/schemas/*.py and backend/app/providers/models.py exactly — keep them in
// sync if those change.

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

// De-dupes identical concurrent GET requests into a single in-flight promise. This
// matters in practice: React 19 StrictMode double-invokes effects in dev, and without
// this, two slow-to-answer endpoints (see app/providers/manager.py) each doubling up
// can pile up enough simultaneous connections to make things worse, not just wasteful.
const inFlightRequests = new Map<string, Promise<unknown>>()

async function apiFetch<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
    }
  }
  const key = url.toString()

  const existing = inFlightRequests.get(key)
  if (existing) return existing as Promise<T>

  const promise = (async () => {
    try {
      const response = await fetch(key)
      if (!response.ok) {
        let detail = response.statusText
        try {
          const body = (await response.json()) as { detail?: string }
          if (body.detail) detail = body.detail
        } catch {
          // response body wasn't JSON — fall back to statusText
        }
        throw new ApiError(response.status, detail)
      }
      return (await response.json()) as T
    } finally {
      inFlightRequests.delete(key)
    }
  })()

  inFlightRequests.set(key, promise)
  return promise
}

// Non-GET (or header-bearing) requests bypass the GET de-dupe cache above.
async function apiRequest<T>(
  path: string,
  init: { method: 'GET' | 'POST'; adminKey?: string; body?: unknown; params?: Record<string, string | number | boolean | undefined> }
): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`)
  if (init.params) {
    for (const [key, value] of Object.entries(init.params)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
    }
  }

  const headers: Record<string, string> = {}
  if (init.adminKey) headers['X-Admin-API-Key'] = init.adminKey
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(url.toString(), {
    method: init.method,
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

// --- shared -----------------------------------------------------------------------

export type Page<T> = {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export type TrainType = 'RAJDHANI' | 'SHATABDI' | 'SUPERFAST' | 'EXPRESS'
export type TrainPriority = 'HIGH' | 'NORMAL'
export type StationType = 'TERMINAL' | 'MAJOR' | 'JUNCTION' | 'REGULAR' | 'HALT'
export type EventType =
  | 'POSITION_UPDATE'
  | 'ARRIVAL'
  | 'DEPARTURE'
  | 'SIGNAL_HALT'
  | 'UNSCHEDULED_STOP'
  | 'SPEED_RESTRICTION'
  | 'CONGESTION'
  | 'MAINTENANCE_BLOCK'
  | 'WEATHER_DISRUPTION'
export type EventSource = 'SIMULATOR' | 'GPS' | 'RTIS' | 'NTES' | 'RAILRADAR' | 'MANUAL' | 'SYSTEM'
export type DataStatus = 'LIVE' | 'STALE' | 'UNAVAILABLE' | 'SIMULATED'
export type ProviderName = 'NTES' | 'RAILRADAR' | 'SIMULATOR'
export type PredictionMode = 'ML' | 'BASELINE' | 'BASELINE_FALLBACK'

// --- trains ---------------------------------------------------------------------------

export type TrainListItem = {
  train_number: string
  train_name: string
  train_type: TrainType
  source_station_code: string
  source_station_name: string
  destination_station_code: string
  destination_station_name: string
  zone: string
  priority: TrainPriority
  active: boolean
}

export type TrainRouteSummary = {
  total_stations: number
  total_distance_km: number | null
  origin_departure_time: string | null
  destination_arrival_time: string | null
  destination_arrival_day_offset: number | null
}

export type TrainDetail = TrainListItem & {
  created_at: string
  updated_at: string
  route_summary: TrainRouteSummary | null
}

export type TrainRouteItem = {
  sequence_number: number
  station_code: string
  station_name: string
  arrival_time: string | null
  departure_time: string | null
  day_offset: number
  halt_minutes: number
  distance_from_source_km: number
  section_code: string | null
}

export type TrainRouteResponse = {
  train_number: string
  train_name: string
  source: string
  destination: string
  route: TrainRouteItem[]
}

export type TrainUpcomingResponse = {
  train_number: string
  train_name: string
  has_known_state: boolean
  as_of: string | null
  current_station_code: string | null
  current_section_code: string | null
  current_delay_minutes: number | null
  upcoming: TrainRouteItem[]
}

export type TrainStateResponse = {
  train_number: string
  timestamp: string
  latitude: number | null
  longitude: number | null
  speed_kmph: number | null
  station_code: string | null
  section_code: string | null
  delay_minutes: number
  event_type: EventType
  event_source: EventSource
  metadata: Record<string, unknown> | null
  data_freshness_seconds: number
}

export type TrainEventResponse = {
  id: number
  timestamp: string
  event_type: EventType
  event_source: EventSource
  station_code: string | null
  section_code: string | null
  delay_minutes: number
  speed_kmph: number | null
  latitude: number | null
  longitude: number | null
  metadata: Record<string, unknown> | null
}

export function listTrains(params: {
  page?: number
  page_size?: number
  search?: string
  train_type?: TrainType
  zone?: string
  active?: boolean
}) {
  return apiFetch<Page<TrainListItem>>('/trains', params)
}

export function getTrain(trainNumber: string) {
  return apiFetch<TrainDetail>(`/trains/${encodeURIComponent(trainNumber)}`)
}

export function getTrainRoute(trainNumber: string) {
  return apiFetch<TrainRouteResponse>(`/trains/${encodeURIComponent(trainNumber)}/route`)
}

export function getTrainUpcoming(trainNumber: string) {
  return apiFetch<TrainUpcomingResponse>(`/trains/${encodeURIComponent(trainNumber)}/upcoming`)
}

export function getTrainState(trainNumber: string) {
  return apiFetch<TrainStateResponse>(`/trains/${encodeURIComponent(trainNumber)}/state`)
}

export function listTrainEvents(trainNumber: string, params: { page?: number; page_size?: number } = {}) {
  return apiFetch<Page<TrainEventResponse>>(`/trains/${encodeURIComponent(trainNumber)}/events`, params)
}

// --- stations -----------------------------------------------------------------------

export type StationListItem = {
  station_code: string
  station_name: string
  zone: string
  state: string | null
  station_type: StationType
}

export type StationDetail = {
  station_code: string
  station_name: string
  latitude: number
  longitude: number
  zone: string
  division: string | null
  state: string | null
  station_type: StationType
}

export type BoardStatus = 'ON_TIME' | 'DELAYED' | 'NO_RECENT_DATA'

export type StationBoardItem = {
  train_number: string
  train_name: string
  source_station_code: string
  destination_station_code: string
  scheduled_arrival: string | null
  scheduled_departure: string | null
  latest_known_delay_minutes: number | null
  latest_event_timestamp: string | null
  status: BoardStatus
}

export type StationBoardResponse = {
  station_code: string
  station_name: string
  generated_at: string
  board: StationBoardItem[]
}

export type StationTrainItem = {
  train_number: string
  train_name: string
  source_station_code: string
  destination_station_code: string
  sequence_number: number
  scheduled_arrival: string | null
  scheduled_departure: string | null
  halt_minutes: number
}

export function listStations(params: {
  page?: number
  page_size?: number
  search?: string
  zone?: string
  state?: string
  station_type?: StationType
}) {
  return apiFetch<Page<StationListItem>>('/stations', params)
}

export function getStation(stationCode: string) {
  return apiFetch<StationDetail>(`/stations/${encodeURIComponent(stationCode)}`)
}

export function getStationBoard(stationCode: string) {
  return apiFetch<StationBoardResponse>(`/stations/${encodeURIComponent(stationCode)}/board`)
}

export function listStationTrains(stationCode: string, params: { page?: number; page_size?: number } = {}) {
  return apiFetch<Page<StationTrainItem>>(`/stations/${encodeURIComponent(stationCode)}/trains`, params)
}

// --- live -----------------------------------------------------------------------------

export type LiveTrainStateResponse = {
  train_number: string
  position: { latitude: number | null; longitude: number | null } | null
  speed_kmph: number | null
  station_code: string | null
  section_code: string | null
  delay_minutes: number | null
  event_type: EventType | null
  timestamp: string | null
  data_source: ProviderName | null
  data_status: DataStatus
  retrieved_at: string | null
  data_age_seconds: number | null
  error: string | null
  metadata?: {
    train_name?: string | null
    tracking_mode?: string | null
    status?: string | null
    is_live?: boolean
    previous_halt?: { stationCode: string; stationName: string; sequence?: number; distance?: number } | null
    next_halt?: { stationCode: string; stationName: string; sequence?: number; distance?: number } | null
    current_location?: {
      stationCode: string
      stationName: string
      status: string
      isHalt?: boolean
      distanceFromOriginKm?: number
      delayMinutes?: number
    } | null
  } | null
}

export function getLiveTrainState(trainNumber: string) {
  return apiFetch<LiveTrainStateResponse>(`/live/trains/${encodeURIComponent(trainNumber)}`)
}

export type LiveTrainRouteStop = {
  sequence_number: number
  station_code: string
  station_name: string | null
  arrival_time: string | null
  departure_time: string | null
  distance_km: number | null
}

export type LiveTrainRouteResponse = {
  train_number: string
  source: string | null
  destination: string | null
  stations: LiveTrainRouteStop[]
  data_source: ProviderName | null
  data_status: DataStatus
  retrieved_at: string | null
  error: string | null
}

export function getLiveTrainRoute(trainNumber: string) {
  return apiFetch<LiveTrainRouteResponse>(`/live/trains/${encodeURIComponent(trainNumber)}/route`)
}

export type LiveStationBoardEntry = {
  train_number: string
  train_name: string | null
  scheduled_arrival: string | null
  scheduled_departure: string | null
  delay_minutes: number | null
  status: string | null
}

export type LiveStationBoardResponse = {
  station_code: string
  trains: LiveStationBoardEntry[]
  data_source: ProviderName | null
  data_status: DataStatus
  retrieved_at: string | null
  error: string | null
}

export function getLiveStationBoard(stationCode: string) {
  return apiFetch<LiveStationBoardResponse>(`/live/stations/${encodeURIComponent(stationCode)}`)
}

// --- providers --------------------------------------------------------------------------

export type ProviderStatus = {
  provider: ProviderName
  enabled: boolean
  available: boolean
  last_success: string | null
  last_failure: string | null
  latency_ms: number | null
  error: string | null
  configured: boolean
  provider_type: string
}

export function getProvidersStatus() {
  return apiFetch<{ providers: ProviderStatus[] }>('/providers/status')
}

export function getProviderStatus(provider: ProviderName) {
  return apiFetch<ProviderStatus>(`/providers/${encodeURIComponent(provider)}/status`)
}

// --- eta (baseline + ML residual, Phase 5, 6, 7) ---------------------------------------

export type UncertaintyInterval = {
  lower_eta: string
  upper_eta: string
  interval_level: number
  interval_width_minutes: number
  source?: string | null
}

export type ConfidenceFactor = {
  factor: string
  impact: 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL'
}

export type Confidence = {
  score: number
  level: 'HIGH' | 'MEDIUM' | 'LOW'
  factors: ConfidenceFactor[]
}

export type ExplanationFactor = {
  feature: string
  display_name: string
  contribution_minutes: number
  direction: 'LATER' | 'EARLIER'
}

export type Explanation = {
  available: boolean
  reason?: string | null
  top_factors: ExplanationFactor[]
}

export type EtaStation = {
  station_code: string
  station_name: string
  sequence_number: number
  scheduled_arrival: string | null
  scheduled_eta?: string | null
  baseline_eta: string | null
  delay_minutes: number
  remaining_distance_km: number
  prediction_mode: PredictionMode
  predicted_residual_minutes?: number | null
  ml_residual_minutes?: number | null
  predicted_residual_raw?: number | null
  residual_clipped?: boolean
  final_eta?: string | null
  final_delay_minutes?: number | null
  lower_bound?: string | null
  upper_bound?: string | null
  confidence_score?: number | null
  confidence_level?: string | null
  uncertainty?: UncertaintyInterval | null
  confidence?: Confidence | null
  explanation?: Explanation | null
}

export type BaselineEtaResponse = {
  train_number: string
  train_name: string
  generated_at: string
  prediction_timestamp?: string | null
  journey_date: string
  prediction_mode: PredictionMode
  model_version?: string | null
  data_source: string | null
  data_status: DataStatus
  provider_status?: string | null
  status?: string | null
  current_position: {
    kind: string
    position_source: string
    station_code: string | null
    section_code: string | null
    last_known_station_code: string | null
    next_station_code: string | null
  }
  remaining_distance_km: number
  stations: EtaStation[]
}

export type SingleStationEtaResponse = {
  train_number: string
  station_code: string
  station_name: string
  scheduled_arrival: string | null
  scheduled_eta?: string | null
  baseline_eta: string | null
  delay_minutes: number
  predicted_residual_minutes?: number | null
  ml_residual_minutes?: number | null
  predicted_residual_raw?: number | null
  residual_clipped: boolean
  final_eta: string | null
  final_delay_minutes?: number | null
  remaining_distance_km: number
  prediction_mode: PredictionMode
  model_version?: string | null
  data_source?: string | null
  data_status: DataStatus
  provider_status?: string | null
  status?: string | null
  prediction_timestamp?: string | null
  lower_bound?: string | null
  upper_bound?: string | null
  confidence_score?: number | null
  confidence_level?: string | null
  uncertainty?: UncertaintyInterval | null
  confidence?: Confidence | null
  explanation?: Explanation | null
}

export type BaselineFactor = {
  factor: string
  display_name: string
  effect: string
  value?: number | null
}

export type FullExplanationResponse = {
  train_number: string
  station_code: string
  prediction_mode: PredictionMode
  model_version?: string | null
  prediction_timestamp?: string | null
  final_eta?: string | null
  predicted_residual_minutes?: number | null
  available: boolean
  reason?: string | null
  baseline_factors: BaselineFactor[]
  ml_factors: ExplanationFactor[]
}

export function getTrainEta(trainNumber: string, mode?: 'final' | 'baseline') {
  return apiFetch<BaselineEtaResponse>(`/eta/${encodeURIComponent(trainNumber)}`, { mode })
}

export function getStationEta(trainNumber: string, stationCode: string, mode?: 'final' | 'baseline') {
  return apiFetch<SingleStationEtaResponse>(
    `/eta/${encodeURIComponent(trainNumber)}/${encodeURIComponent(stationCode)}`,
    { mode }
  )
}

export function getTrainExplanation(trainNumber: string, stationCode: string) {
  return apiFetch<FullExplanationResponse>(
    `/eta/${encodeURIComponent(trainNumber)}/${encodeURIComponent(stationCode)}/explanation`
  )
}

// --- network intelligence (Phase 8) --------------------------------------------------

export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type NetworkOverviewResponse = {
  journey_date: string
  total_active_trains: number
  total_delayed_trains: number
  total_affected_trains: number
  total_affected_stations: number
  total_affected_sections: number
  active_conflicts_count: number
  congestion_hotspots_count: number
  overall_network_impact_score: number
  overall_severity: Severity
  generated_at: string
}

export type TrainImpactResponse = {
  train_number: string
  journey_date: string
  current_delay_minutes: number
  network_impact_score: number
  severity: Severity
  directly_affected_trains: number
  knock_on_affected_trains: number
  total_affected_trains: number
  affected_stations: string[]
  affected_sections: string[]
  active_conflicts: NetworkConflict[]
  generated_at: string
}

export type NetworkConflict = {
  id: string
  section_code: string
  train_a: string
  train_b: string
  conflict_type: string
  severity: Severity
  estimated_delay_minutes: number
  detected_at: string
  resolved: boolean
  description?: string | null
}

export type NetworkHotspot = {
  identifier: string
  kind: 'STATION' | 'SECTION'
  code: string
  name: string
  converging_trains_count: number
  total_delay_minutes: number
  average_delay_minutes: number
  congestion_risk: Severity
}

export type AffectedTrain = {
  train_number: string
  train_name: string
  primary_delay_minutes: number
  estimated_delay_minutes: number
  impact_severity: Severity
  causing_train_number: string | null
  conflict_section_code: string | null
}

export type TimelineBucket = {
  start_time: string
  end_time: string
  predicted_conflicts_count: number
  maximum_severity: Severity
  affected_trains_count: number
}

export function getNetworkOverview(journeyDate?: string) {
  return apiFetch<NetworkOverviewResponse>('/network/overview', { journey_date: journeyDate })
}

export function getTrainNetworkImpact(trainNumber: string, journeyDate?: string) {
  return apiFetch<TrainImpactResponse>(`/network/trains/${encodeURIComponent(trainNumber)}/impact`, { journey_date: journeyDate })
}

export function listNetworkConflicts(params: { page?: number; page_size?: number; severity?: Severity; section_code?: string; train_number?: string } = {}) {
  return apiFetch<Page<NetworkConflict>>('/network/conflicts', params)
}

export function listNetworkHotspots(journeyDate?: string) {
  return apiFetch<NetworkHotspot[]>('/network/hotspots', { journey_date: journeyDate })
}

export function listAffectedTrains(params: { page?: number; page_size?: number; severity?: Severity; min_impact_score?: number } = {}) {
  return apiFetch<Page<AffectedTrain>>('/network/affected-trains', params)
}

export function getNetworkTimeline(bucketMinutes: number = 30) {
  return apiFetch<TimelineBucket[]>('/network/timeline', { bucket_minutes: bucketMinutes })
}

// --- system monitoring & mlops (Phase 10) --------------------------------------------

export type SystemHealthResponse = {
  status: 'HEALTHY' | 'DEGRADED' | 'UNAVAILABLE'
  timestamp: string
  version?: string
  components: Record<string, string>
  details?: {
    active_model_version?: string | null
    environment?: string
    mode?: string
    worker_status?: string
    streaming_enabled?: boolean
    [key: string]: unknown
  }
}

// Each dimension is scored out of a fixed 25 points (they sum to the 0-100 overall score);
// the backend (app/monitoring/schemas.py DataQualityDimension) doesn't echo that max back.
export const DATA_QUALITY_DIMENSION_MAX = 25

export type DataQualityDimension = {
  score: number
  status: string
  description?: string
}

export type DataQualityResponse = {
  score: number
  rating: 'HIGH' | 'MEDIUM' | 'LOW'
  timestamp: string
  completeness: DataQualityDimension
  freshness: DataQualityDimension
  validity: DataQualityDimension
  consistency: DataQualityDimension
  metrics: {
    events_evaluated_total: number
    missing_coordinates: number
    invalid_coordinates: number
    missing_speed: number
    missing_delay: number
    stale_events: number
    duplicate_events: number
    out_of_order_events: number
    unknown_train: number
    unknown_station: number
    unknown_section: number
    provider_failures: number
  }
}

export type FeatureDrift = {
  feature_name: string
  psi_score: number
  ks_statistic: number
  ks_p_value: number
  drift_detected: boolean
}

export type ModelDriftResult = {
  active_model_version: string
  reference_mae: number
  recent_mae: number
  degradation_percent: number
  sample_count: number
  drift_detected: boolean
}

export type DriftAnalysisResponse = {
  data_drift_detected: boolean
  model_drift_detected: boolean
  window_days: number
  data_drift_threshold: number
  model_drift_threshold: number
  feature_drifts: FeatureDrift[]
  model_drift: ModelDriftResult | null
  checked_at: string
}

export type OperationalAlert = {
  fingerprint: string
  alert_type: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  title: string
  description: string
  source: string
  timestamp: string
  details?: Record<string, unknown>
}

export type ModelMetadata = {
  model_version: string
  status: 'CANDIDATE' | 'VALIDATED' | 'PRODUCTION' | 'REJECTED' | 'ARCHIVED'
  training_timestamp: string
  dataset_version: string
  feature_schema_version: string
  test_mae: number | null
  baseline_mae: number | null
  improvement_percent: number | null
  uncertainty_level: number | null
  artifact_path: string
}

export type ModelCatalogResponse = {
  active_model: string | null
  staged_model: string | null
  models: ModelMetadata[]
}

export function getSystemHealth() {
  return apiFetch<SystemHealthResponse>('/system/health')
}

export type ReadinessResponse = {
  ready: boolean
  timestamp: string
  checks: Record<string, boolean>
}

export function getSystemReadiness() {
  return apiFetch<ReadinessResponse>('/system/readiness')
}

export type LivenessResponse = {
  alive: boolean
  timestamp: string
}

export function getSystemLiveness() {
  return apiFetch<LivenessResponse>('/system/liveness')
}

export function getSystemMetrics() {
  return apiFetch<Record<string, unknown>>('/system/metrics')
}

export type ProviderMetricsResponse = {
  providers: Record<string, Record<string, unknown>>
  timestamp: string
}

export function getProviderMetrics() {
  return apiFetch<ProviderMetricsResponse>('/system/providers/metrics')
}

export type StreamingMetricsResponse = {
  events_ingested_total: number
  events_debounced_total: number
  predictions_calculated_total: number
  network_recalcs_total: number
  events_out_of_order_total: number
  events_duplicate_total: number
  stream_lag: number
  latency_percentiles_ms: Record<string, number>
  worker_status: string
  last_event_time: string | null
  last_prediction_time: string | null
}

export function getStreamingMetrics() {
  return apiFetch<StreamingMetricsResponse>('/system/streaming/metrics')
}

export function getStreamingStatus() {
  return apiFetch<Record<string, unknown>>('/system/streaming/status')
}

export function getDataQuality() {
  return apiFetch<DataQualityResponse>('/system/data-quality')
}

export function getDriftAnalysis() {
  return apiFetch<DriftAnalysisResponse>('/system/drift')
}

export function getOperationalAlerts() {
  return apiFetch<OperationalAlert[]>('/system/alerts')
}

export function listModels() {
  return apiFetch<ModelCatalogResponse>('/system/models')
}

export type HorizonMetric = {
  horizon_bucket: string
  sample_count: number
  scheduled_mae: number | null
  baseline_mae: number | null
  ml_mae: number | null
  improvement_percent: number | null
}

export type GroupMetric = {
  group_type: string
  group_value: string
  sample_count: number
  baseline_mae: number | null
  ml_mae: number | null
}

export type ModelEvaluationResponse = {
  model_version: string
  total_samples: number
  scheduled_mae: number | null
  baseline_mae: number | null
  ml_mae: number | null
  ml_rmse: number | null
  median_absolute_error: number | null
  p90_absolute_error: number | null
  mean_error_bias: number | null
  improvement_vs_baseline_percent: number | null
  by_horizon: HorizonMetric[]
  by_train_type: GroupMetric[]
  by_data_source: GroupMetric[]
  uncertainty_coverage_percent: number | null
  uncertainty_target_percent: number
  uncertainty_avg_width_minutes: number | null
  confidence_calibration: Record<string, unknown>
  evaluation_timestamp: string
}

export function getModelMetrics(modelVersion: string) {
  return apiFetch<ModelEvaluationResponse>(`/system/models/${encodeURIComponent(modelVersion)}/metrics`)
}

// --- MLOps admin actions (require an X-Admin-API-Key; unset in local development) -----

export type AuditLogEntry = {
  id: string
  action: string
  actor: string
  timestamp: string
  previous_value: string | null
  new_value: string | null
  reason: string | null
}

export function getAuditLog(adminKey: string, limit: number = 50) {
  return apiRequest<AuditLogEntry[]>('/system/audit-log', { method: 'GET', adminKey, params: { limit } })
}

export type PromoteModelResult = {
  status: string
  model_version: string
  previous_active: string | null
  message: string
}

export function promoteModel(modelVersion: string, adminKey: string, opts: { force?: boolean; reason?: string } = {}) {
  return apiRequest<PromoteModelResult>(`/system/models/${encodeURIComponent(modelVersion)}/promote`, {
    method: 'POST',
    adminKey,
    params: { force: opts.force, reason: opts.reason },
  })
}

export type RollbackModelResult = {
  status: string
  active_model_version: string
  previous_active: string | null
  message: string
}

export function rollbackModel(targetVersion: string, adminKey: string, reason?: string) {
  return apiRequest<RollbackModelResult>('/system/models/rollback', {
    method: 'POST',
    adminKey,
    body: { target_version: targetVersion, reason },
  })
}

// --- health (unversioned root endpoint) -----------------------------------------------

const ROOT_BASE_URL = API_BASE_URL.replace(/\/api\/v1$/, '')

export type HealthResponse = {
  status: 'ok' | 'degraded'
  service: string
  version: string
  environment: string
  timestamp: string
  dependencies: { database: 'up' | 'down'; redis: 'up' | 'down' }
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${ROOT_BASE_URL}/health`)
  if (!response.ok) throw new ApiError(response.status, response.statusText)
  return (await response.json()) as HealthResponse
}

// --- timezone helper (Indian Standard Time Asia/Kolkata) ------------------------------

export function formatIST(dateStr: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return '—'
  const defaultOpts: Intl.DateTimeFormatOptions = {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    ...options,
  }
  return new Intl.DateTimeFormat('en-IN', defaultOpts).format(date)
}

export function formatISTDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date)
}

