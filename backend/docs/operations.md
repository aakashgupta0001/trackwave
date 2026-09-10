# RAILCAST Operations & Production Runbook

This guide covers operational administration, observability, backup/recovery, and failure troubleshooting for the RAILCAST platform backend.

---

## 1. System Startup & Shutdown

### Development Startup
```powershell
# In D:\RAILCAST\backend with virtual environment activated:
$env:PYTHONPATH="."
$env:ENVIRONMENT="development"
$env:RAILCAST_MODE="DEMO"

# Start the API server
python -m uvicorn app.main:app --reload --port 8000

# Start the continuous prediction worker (in a separate terminal)
python -m app.streaming.worker
```

### Production Docker Compose Startup
```bash
docker compose up -d
docker compose ps
```

### Graceful Shutdown
The application handles `SIGTERM` and `SIGINT` signals cleanly. During shutdown:
1. Active WebSocket connections receive close frames.
2. Background ingestion and streaming consumers finish in-flight records and acknowledge them in Redis.
3. Redis client connection pools close (`aclose()`).
4. SQLAlchemy async database engine disposes of active pool connections (`engine.dispose()`).

---

## 2. Health, Readiness & Liveness Probes

RAILCAST exposes three standardized health endpoints:

### Liveness Probe
- **Endpoint**: `GET /api/v1/system/liveness`
- **Purpose**: Fast process heartbeat for container orchestrators (Docker/Kubernetes).
- **Behavior**: Instantaneous response with zero network or database I/O. Always returns 200 OK while the Python event loop is functioning.

### Readiness Probe
- **Endpoint**: `GET /api/v1/system/readiness`
- **Purpose**: Validates whether the instance can accept incoming user requests.
- **Rules**:
  - PostgreSQL connectivity is strictly **required**. If the database is unreachable, returns `503 Service Unavailable`.
  - Redis, ML models, and external railway providers are **not required**; if any of these are down, the system continues serving cached states and deterministic baseline ETAs.

### Comprehensive Component Health
- **Endpoint**: `GET /api/v1/system/health`
- **Response Shape**:
```json
{
  "status": "HEALTHY",
  "timestamp": "2026-03-10T10:00:00Z",
  "components": {
    "database": "UP",
    "redis": "UP",
    "streaming": "UP",
    "model": "UP",
    "provider": "UP",
    "network": "UP"
  },
  "details": {
    "active_model_version": "xgb-residual-v1",
    "environment": "production",
    "mode": "PRODUCTION",
    "worker_status": "RUNNING",
    "streaming_enabled": true
  }
}
```
Possible overall statuses: `HEALTHY`, `DEGRADED`, `UNAVAILABLE`.

---

## 3. Telemetry Data Quality Monitoring

RAILCAST tracks telemetry quality on every ingested event and provides a composite 0–100 Data Quality Score:
- **Endpoint**: `GET /api/v1/system/data-quality`

### Quality Dimensions (25 points each)
1. **Completeness**: Evaluates presence of coordinates, instantaneous speed, and delay minutes.
2. **Freshness**: Ratio of events arriving within 120 seconds of generation.
3. **Validity**: Verifies coordinates lie within legitimate geospatial bounds ($[-90, 90]$ latitude, $[-180, 180]$ longitude) and speeds are non-negative.
4. **Consistency**: Penalizes duplicate events and out-of-order telemetry arrivals.

### Quality Ratings
- $\ge 80$: `HIGH`
- $50 - 79$: `MEDIUM`
- $< 50$: `LOW` (Triggers `DATA_QUALITY_LOW` operational alert)

---

## 4. Failure Degradation Matrix

RAILCAST is engineered so that failure of any single component never takes down the entire system:

| Failure Scenario | Immediate System Behavior | User Impact | Operational Remediation |
|---|---|---|---|
| **Redis Server Down** | Connection timeouts fail fast (200ms). Caches bypass to PostgreSQL/engine. Streaming degrades. | Slight increase in response latency. Real-time updates poll via REST. | Restart Redis (`docker compose restart redis`). Check logs. |
| **PostgreSQL Down** | Readiness probe fails (`503`). Persistent write operations rejected. | Read-only cache hits may serve; write operations fail safely. | Check DB disk space, connection limits, and restart PostgreSQL. |
| **ML Model Unavailable** | Engine automatically falls back to deterministic Baseline ETA (`prediction_mode=BASELINE_FALLBACK`). | ETAs served with timetable/distance baseline without ML correction. | Inspect `models/eta_residual/`. Check `GET /api/v1/system/models`. |
| **SHAP / Explanations Fail** | Prediction succeeds normally; explanation marked `available=false, reason="EXPLANATION_UNAVAILABLE"`. | ETAs still displayed; feature contribution breakdown hidden. | Check CPU load; TreeSHAP falls back gracefully. |
| **External Provider Outage** | `ProviderManager` trips cooldown (60s), falls back to secondary provider or Simulator. | Live status marked `STALE` or `SIMULATED`. No cascading crash. | Inspect `GET /api/v1/system/providers/metrics`. Verify provider API keys. |
| **Streaming Worker Poison Pill**| Malformed message is logged as error, acknowledged (ACK), and bypassed. | Pipeline does not stall; bad message does not crash consumer loop. | Review poison pill payload in error logs. |
| **Network Analysis Exception** | Train ETA completes normally; network impact defaults to score 0. | Train ETA works; cascade graph is skipped for that single tick. | Verify section topology and timetable inputs. |

---

## 5. PostgreSQL Database Backup & Recovery

### Automated Backup (`pg_dump`)
Run regular cron backups of the production database:
```bash
# Backup command
pg_dump -U railcast -d railcast -F c -b -v -f /backups/railcast_$(date +%Y%m%d_%H%M%S).dump

# Compressed text dump alternative
pg_dump -U railcast -d railcast | gzip > /backups/railcast_$(date +%Y%m%d_%H%M%S).sql.gz
```

### Database Restoration (`pg_restore`)
To restore from a custom-format dump:
```bash
# Terminate existing connections and restore
pg_restore -U railcast -d railcast -v --clean --if-exists /backups/railcast_backup_file.dump
```

---

## 6. Administrative Security & Audit Logging

### API Key Authentication
Administrative endpoints (`/models/{version}/promote`, `/models/rollback`, `/audit-log`) are protected by header `X-Admin-API-Key`.
- Set `ADMIN_API_KEY="your-secure-key"` in `.env`.
- In `production` mode, requests without a matching `X-Admin-API-Key` return `401 Unauthorized`.

### Audit Log Inspection
View all administrative mutations, promotions, and rollbacks:
```bash
curl -H "X-Admin-API-Key: $ADMIN_API_KEY" http://localhost:8000/api/v1/system/audit-log
```

---

## 7. Metrics & Prometheus Scraping

- **Human-readable Overview**: `GET /api/v1/system/metrics`
- **Prometheus Exporter**: `GET /metrics`

Scrape configuration for `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'railcast'
    scrape_interval: 15s
    static_configs:
      - targets: ['backend:8000']
```
