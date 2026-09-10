import { Fragment, useState } from 'react'
import PageHeader from '../../components/PageHeader'
import DataState from '../../components/DataState'
import Badge from '../../components/Badge'
import { useFetch } from '../../lib/useFetch'
import {
  listModels,
  getDataQuality,
  getDriftAnalysis,
  getModelMetrics,
  formatIST,
  DATA_QUALITY_DIMENSION_MAX,
} from '../../lib/api'
import type { ModelMetadata } from '../../lib/api'

function ModelMetricsDetail({ modelVersion }: { modelVersion: string }) {
  const { data, loading, error } = useFetch(() => getModelMetrics(modelVersion), [modelVersion])

  return (
    <tr className="bg-slate-900/40">
      <td colSpan={7} className="px-3 py-3">
        <DataState loading={loading} error={error}>
          {data && (
            <div className="flex flex-wrap gap-6 text-xs">
              <span>ML RMSE: <strong className="font-mono text-slate-200">{data.ml_rmse !== null ? `${data.ml_rmse.toFixed(2)} min` : '—'}</strong></span>
              <span>Median abs. error: <strong className="font-mono text-slate-200">{data.median_absolute_error !== null ? `${data.median_absolute_error.toFixed(2)} min` : '—'}</strong></span>
              <span>P90 abs. error: <strong className="font-mono text-slate-200">{data.p90_absolute_error !== null ? `${data.p90_absolute_error.toFixed(2)} min` : '—'}</strong></span>
              <span>Mean error bias: <strong className="font-mono text-slate-200">{data.mean_error_bias !== null ? data.mean_error_bias.toFixed(2) : '—'}</strong></span>
              <span>Samples evaluated: <strong className="font-mono text-slate-200">{data.total_samples}</strong></span>
              <span>
                Uncertainty coverage: <strong className="font-mono text-slate-200">
                  {data.uncertainty_coverage_percent !== null ? `${data.uncertainty_coverage_percent.toFixed(1)}%` : '—'}
                </strong> (target {data.uncertainty_target_percent}%)
              </span>
              {data.by_horizon.length > 0 && (
                <div className="w-full">
                  <div className="mb-1 text-slate-500">By horizon</div>
                  <div className="flex flex-wrap gap-3">
                    {data.by_horizon.map((h) => (
                      <span key={h.horizon_bucket} className="rounded border border-slate-800 px-2 py-1 font-mono">
                        {h.horizon_bucket}: {h.ml_mae !== null ? `${h.ml_mae.toFixed(2)}m MAE` : '—'} (n={h.sample_count})
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DataState>
      </td>
    </tr>
  )
}

export default function Performance() {
  const models = useFetch(() => listModels(), [])
  const dataQuality = useFetch(() => getDataQuality(), [])
  const drift = useFetch(() => getDriftAnalysis(), [])
  const [expandedModel, setExpandedModel] = useState<string | null>(null)

  const loading = models.loading || dataQuality.loading || drift.loading
  const error = models.error || dataQuality.error || drift.error

  const activeModel = models.data?.models.find((m) => m.model_version === models.data?.active_model)

  return (
    <>
      <PageHeader
        title="Model Performance & Platform Quality"
        description="Active model metrics, prediction quality gates, telemetry data quality scores, and statistical drift monitoring."
      />

      <DataState loading={loading} error={error}>
        {/* Active Production Model Hero */}
        {activeModel && (
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-6">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-850 pb-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-bold text-white font-mono">{activeModel.model_version}</h2>
                  <Badge label="ACTIVE PRODUCTION" tone="good" />
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Dataset: {activeModel.dataset_version} · Schema: {activeModel.feature_schema_version} · Trained: {formatIST(activeModel.training_timestamp)}
                </p>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold text-emerald-400">
                  {activeModel.improvement_percent !== null ? `+${activeModel.improvement_percent.toFixed(1)}%` : '—'}
                </span>
                <span className="text-xs text-slate-400">vs Baseline ETA</span>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-4">
                <div className="text-xs uppercase tracking-wider text-slate-500">Candidate ML MAE</div>
                <div className="mt-1 text-2xl font-semibold text-white font-mono">
                  {activeModel.test_mae !== null ? `${activeModel.test_mae.toFixed(2)}m` : '—'}
                </div>
              </div>
              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-4">
                <div className="text-xs uppercase tracking-wider text-slate-500">Baseline Engine MAE</div>
                <div className="mt-1 text-2xl font-semibold text-white font-mono">
                  {activeModel.baseline_mae !== null ? `${activeModel.baseline_mae.toFixed(2)}m` : '—'}
                </div>
              </div>
              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-4">
                <div className="text-xs uppercase tracking-wider text-slate-500">Uncertainty Level</div>
                <div className="mt-1 text-2xl font-semibold text-white font-mono">
                  {activeModel.uncertainty_level !== null ? `${(activeModel.uncertainty_level * 100).toFixed(0)}%` : '80%'}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Residual Quantiles</div>
              </div>
              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-4">
                <div className="text-xs uppercase tracking-wider text-slate-500">Drift Status</div>
                <div className="mt-1 text-2xl font-semibold text-white">
                  {drift.data ? (drift.data.data_drift_detected || drift.data.model_drift_detected ? 'DRIFT DETECTED' : 'STABLE') : '—'}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">PSI & KS 2-Sample</div>
              </div>
            </div>
          </div>
        )}

        {/* Telemetry Data Quality Score */}
        {dataQuality.data && (
          <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-850 pb-3">
              <div>
                <h3 className="text-base font-semibold text-white">Telemetry Data Quality Score</h3>
                <p className="text-xs text-slate-400">
                  Evaluates completeness, freshness, validity, and consistency of incoming train events (0-100).
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <div className="text-2xl font-bold font-mono text-white">
                    {dataQuality.data.score.toFixed(1)} <span className="text-xs font-normal text-slate-500">/ 100</span>
                  </div>
                </div>
                <Badge
                  label={dataQuality.data.rating}
                  tone={dataQuality.data.rating === 'HIGH' ? 'good' : dataQuality.data.rating === 'MEDIUM' ? 'warn' : 'bad'}
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Completeness</span>
                  <span className="font-mono font-medium text-slate-200">
                    {dataQuality.data.completeness.score.toFixed(1)} / {DATA_QUALITY_DIMENSION_MAX}
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-emerald-500"
                    style={{ width: `${(dataQuality.data.completeness.score / DATA_QUALITY_DIMENSION_MAX) * 100}%` }}
                  />
                </div>
              </div>

              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Freshness</span>
                  <span className="font-mono font-medium text-slate-200">
                    {dataQuality.data.freshness.score.toFixed(1)} / {DATA_QUALITY_DIMENSION_MAX}
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-emerald-500"
                    style={{ width: `${(dataQuality.data.freshness.score / DATA_QUALITY_DIMENSION_MAX) * 100}%` }}
                  />
                </div>
              </div>

              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Validity</span>
                  <span className="font-mono font-medium text-slate-200">
                    {dataQuality.data.validity.score.toFixed(1)} / {DATA_QUALITY_DIMENSION_MAX}
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-emerald-500"
                    style={{ width: `${(dataQuality.data.validity.score / DATA_QUALITY_DIMENSION_MAX) * 100}%` }}
                  />
                </div>
              </div>

              <div className="rounded-lg border border-slate-850 bg-slate-900/60 p-3">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Consistency</span>
                  <span className="font-mono font-medium text-slate-200">
                    {dataQuality.data.consistency.score.toFixed(1)} / {DATA_QUALITY_DIMENSION_MAX}
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-emerald-500"
                    style={{ width: `${(dataQuality.data.consistency.score / DATA_QUALITY_DIMENSION_MAX) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Ingestion Issue Counts */}
            <div className="mt-4 flex flex-wrap gap-4 text-xs text-slate-400 border-t border-slate-850 pt-3">
              <span>Missing coords: <strong className="text-slate-200 font-mono">{dataQuality.data.metrics.missing_coordinates}</strong></span>
              <span>Missing speed: <strong className="text-slate-200 font-mono">{dataQuality.data.metrics.missing_speed}</strong></span>
              <span>Stale events: <strong className="text-slate-200 font-mono">{dataQuality.data.metrics.stale_events}</strong></span>
              <span>Duplicates filtered: <strong className="text-slate-200 font-mono">{dataQuality.data.metrics.duplicate_events}</strong></span>
              <span>Out-of-order handled: <strong className="text-slate-200 font-mono">{dataQuality.data.metrics.out_of_order_events}</strong></span>
            </div>
          </div>
        )}

        {/* Model Registry Catalog */}
        <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-6">
          <h3 className="mb-3 text-base font-semibold text-white">Model Registry & Lifecycle Catalog</h3>
          <p className="mb-3 text-xs text-slate-500">Click a row for detailed evaluation metrics.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="px-3 py-2 font-medium">Model Version</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Dataset Version</th>
                  <th className="px-3 py-2 font-medium">Test MAE</th>
                  <th className="px-3 py-2 font-medium">Baseline MAE</th>
                  <th className="px-3 py-2 font-medium">Improvement</th>
                  <th className="px-3 py-2 font-medium">Trained At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {models.data?.models.map((m: ModelMetadata) => (
                  <Fragment key={m.model_version}>
                    <tr
                      className="cursor-pointer hover:bg-slate-900/50"
                      onClick={() => setExpandedModel((v) => (v === m.model_version ? null : m.model_version))}
                    >
                      <td className="px-3 py-2.5 font-mono font-medium text-slate-200">
                        {m.model_version}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge
                          label={m.status}
                          tone={m.status === 'PRODUCTION' ? 'good' : m.status === 'VALIDATED' ? 'neutral' : 'warn'}
                        />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-400">{m.dataset_version}</td>
                      <td className="px-3 py-2.5 font-mono text-slate-200">
                        {m.test_mae !== null ? `${m.test_mae.toFixed(2)} min` : '—'}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-400">
                        {m.baseline_mae !== null ? `${m.baseline_mae.toFixed(2)} min` : '—'}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-emerald-400">
                        {m.improvement_percent !== null ? `+${m.improvement_percent.toFixed(2)}%` : '—'}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-slate-500">
                        {formatIST(m.training_timestamp)}
                      </td>
                    </tr>
                    {expandedModel === m.model_version && <ModelMetricsDetail modelVersion={m.model_version} />}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </DataState>
    </>
  )
}