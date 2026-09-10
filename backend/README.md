# RAILCAST Backend

Real-Time AI-Powered ETA & Railway Network Intelligence Platform — backend service.

Built so far:
- **Phase 1** — FastAPI application skeleton, configuration, database/cache connectivity,
  Alembic migrations, Docker setup, and a health endpoint.
- **Phase 2** — the railway digital twin: `Station`, `RailwaySection`, `Train`, `TrainRoute`,
  `TrainEvent`, `Prediction`, `Alert` models; Pydantic schemas; a thin repository/service layer;
  an idempotent seed script populating a small realistic Delhi → Mumbai network.
- **Phase 3** — the read-only Train State and Station APIs under `/api/v1/trains` and
  `/api/v1/stations`: paginated listings with search/filters, route/upcoming-route/latest-state/
  event-history endpoints for trains, and detail/board/trains-at-station endpoints for stations.
- **Phase 4** — a real-railway-data provider abstraction (`app/providers/`): NTES and RailRadar
  adapters (both honestly `UNAVAILABLE` without real access — see "Data providers" below), a
  Simulator adapter wrapping RAILCAST's own sample data, a `ProviderManager` handling
  primary/fallback selection, timeouts, per-provider cooldown, and Redis caching, an ingestion
  service turning provider data into `TrainEvent` rows, an opt-in background polling worker, and
  `/api/v1/live/*` + `/api/v1/providers/*` endpoints.
- **Phase 5** — the deterministic, railway-aware Baseline ETA Engine (`app/services/
  baseline_eta_service.py` + `position_resolver.py`), the `/api/v1/eta/*` endpoints, Redis
  caching of computed ETAs, and persistence of `Prediction` rows — see
  "Baseline ETA engine (Phase 5)" below.
- **Phase 6** — the ML residual ETA model (`app/ml/`): XGBoost learns
  `residual = actual arrival − baseline ETA` from engineered railway features; a fusion
  service produces `final_eta = baseline_eta + clamped residual` on the `/api/v1/eta/*`
  endpoints, with a filesystem model registry, chronological-split evaluation, honest
  baseline-vs-ML comparison, and guaranteed baseline fallback — see
  "ML residual ETA model (Phase 6)" below.
- **Phase 7** — ETA uncertainty, confidence, and explainability (`app/ml/uncertainty.py`,
  `app/ml/explain.py`, `app/services/confidence_service.py`, `app/services/baseline_explain.py`):
  residual-quantile prediction intervals, deterministic 0–100 confidence scoring with
  factor breakdown, exact TreeSHAP ML explainability, deterministic baseline explanations,
  and dedicated explanation endpoints (`/api/v1/eta/{train}/{station}/explanation`) — see
  "ETA uncertainty, confidence & explainability (Phase 7)" below.
- **Phase 8** — network intelligence and delay-propagation prediction (`app/network/`): a
  bounded railway graph over the existing Station/RailwaySection/TrainRoute tables, shared-
  section conflict detection, a deterministic (swappable) propagation model, RAILCAST's own
  0–100 impact scoring, hotspot detection, predictive (deduplicated) alerts, and
  `/api/v1/network/*` endpoints — see "Network intelligence (Phase 8)" below. Everything here
  is a PREDICTED/ESTIMATED analytical output, never a signalling or dispatching decision.
- **Phase 9** — real-time streaming and continuous prediction pipeline (`app/streaming/`):
  event-driven continuous prediction using Redis Streams (`railcast:train-events`,
  `railcast:prediction-updates`), background consumer workers (`railcast-prediction-workers`),
  deterministic event fingerprint deduplication, out-of-order event handling, prediction
  debouncing (5.0s window), conditional network cascade analysis triggers, streaming metrics
  and latency tracking, and push-based WebSockets (`/ws/trains/*`, `/ws/stations/*`,
  `/ws/network`, `/ws/updates`) — see "Real-Time Streaming & Continuous Prediction Pipeline (Phase 9)" below.
- **Phase 10** — productionization, monitoring, retraining & MLOps (`app/monitoring/`, `app/api/middleware/`,
  `scripts/retrain_eta_model.py`, `docs/`): system health, Kubernetes liveness/readiness probes,
  composite 0–100 Data Quality Score engine, statistical feature data drift (PSI/KS-test) and model degradation drift,
  Prometheus metrics exporter (`/metrics`), reproducible model retraining pipeline with dataset & schema versioning,
  strict Quality Gate validation, active model pointer management (`active_model.json`), safe promotion and rollback,
  admin authentication & persistent JSONL audit logging, rate limiting, correlation IDs, multi-stage Docker build,
  and GitHub Actions CI/CD pipeline — see "Productionization, Monitoring, Retraining & MLOps (Phase 10)" below.
- **Phase 11** — full system integration, frontend integration & end-to-end validation (`src/`, `tests/test_system_integration.py`,
  `scripts/run_demo.py`, `scripts/benchmark_system.py`, `docs/benchmark_report.md`, `docs/architecture.md`):
  unification of the complete backend pipeline (Phases 1–10) with the React 19 + Tailwind CSS frontend; standardized
  API response contracts with backward-compatible synonyms (`scheduled_eta`, `baseline_eta`, `ml_residual_minutes`,
  `final_eta`, `lower_bound`, `upper_bound`, `confidence_score`, `confidence_level`, `status`, `provider_status`, `data_age_seconds`);
  real-time WebSocket integration with auto-reconnect (`useWebSocketFeed`); deterministic end-to-end demo scenario
  (`python -m scripts.run_demo`); full system integration and chaos/failure mode tests (7/7 passing); 100/500-train performance
  benchmarking; and security audit.

## Status honesty

This backend currently runs on **sample/seed data and a simulator** (the simulator itself
arrives in a later phase). It does **not** connect to any official live NTES/RTIS railway
feed, and none of the station distances/running times/timetables below are official Indian
Railways data — they're realistic-looking prototype values for demonstration. Adapters for
real data sources (`NTESAdapter`, `RTISAdapter`, `WeatherAdapter`) are planned as pluggable
integrations once such access is available.

## Architecture (target — built incrementally)

```
Current Train State + Schedule + History + Network + Operations + Weather
                                    |
                                    v
                          Baseline ETA Engine  →  baseline_eta
                                    |
                                    v
                          Feature Engineering
                                    |
                                    v
                          ML Residual Model  →  predicted_correction
                                    |
                                    v
                          ETA Fusion Engine
                                    |
                                    v
              final_eta = baseline_eta + predicted_correction
                     (+ uncertainty + explanation)
                                    |
                    ┌───────────────┼───────────────┐
              Passenger API    Station API     Control Room API
```

`final_eta` always falls back to `baseline_eta` alone if the ML model is unavailable —
the ML layer is a correction on top of a deterministic engine, never a single point of failure.

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.x (async) · PostgreSQL · Alembic · Redis ·
pytest/httpx for testing · Docker Compose for local orchestration.

(scikit-learn / XGBoost / SHAP / MLflow / pandas are added to `requirements.txt` starting the
ML phases — see the commented section at the bottom of that file.)

## Project structure

```
backend/
    app/
        main.py                FastAPI app, CORS, error handling
        core/
            config.py           Settings (env vars / .env)
            logging.py           Structured (JSON) logging setup
        api/routes/
            health.py            GET /health
            trains.py             GET /api/v1/trains/* (Phase 3)
            stations.py            GET /api/v1/stations/* (Phase 3)
        models/                  SQLAlchemy 2.x ORM models (the digital twin)
            enums.py              Shared enum types (StationType, EventType, ...)
            station.py, section.py, train.py, route.py,
            train_event.py, prediction.py, alert.py
        schemas/
            common.py              Generic Page[T] pagination envelope (Phase 3)
            station.py, train.py, route.py, train_event.py, section.py, alert.py, prediction.py
                                    Each holds both the Phase 2 internal Create/Read schemas
                                    and the Phase 3 frontend-facing response schemas — see
                                    the "API-facing response schemas" comment block in each file.
        repositories/            Thin query layer — no business logic
            station_repository.py, section_repository.py, train_repository.py,
            route_repository.py, event_repository.py
        services/                Business-logic layer above repositories
            station_service.py, train_service.py, exceptions.py
        db/
            base.py                Declarative Base for ORM models
            session.py               Async engine/session + connectivity check
        cache/
            redis.py                  Async Redis client + connectivity check
    tests/
        test_health.py
        test_db_models.py           Model/constraint tests (rollback-isolated)
        test_seed_integrity.py       Seed idempotency + railway-graph validity
        test_api_trains.py           Train API tests (Phase 3)
        test_api_stations.py          Station API tests (Phase 3)
    alembic/                       Migration environment (wired to app settings)
    scripts/
        seed.py                    Idempotent sample-data seed script
    data/{raw,processed,sample}/    Datasets (later phases)
    notebooks/                     Exploration (later phases)
    Dockerfile
    docker-compose.yml
    requirements.txt
    .env.example
```

## Setup

### Option A — Docker Compose (recommended, brings up Postgres + Redis + API together)

```bash
cd backend
cp .env.example .env
docker compose up --build
```

This starts three services: `backend` (FastAPI on `:8000`), `postgres` (`:5432`), `redis` (`:6379`).

### Option B — Local Python environment

Requires a local PostgreSQL and Redis (or point `.env` at ones you already have running).

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
cp .env.example .env           # edit DATABASE_URL / REDIS_URL if needed

uvicorn app.main:app --reload
```

## Environment variables

See [.env.example](.env.example). Key ones for Phase 1:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (used by both the app and Alembic, via `psycopg` 3) |
| `REDIS_URL` | Redis connection string |
| `ENVIRONMENT` | `development` / `production` |
| `LOG_LEVEL` | Python logging level |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API (the Vite dev server by default) |
| `BASELINE_MIN_SPEED_KMPH` / `BASELINE_MAX_SPEED_KMPH` / `BASELINE_FALLBACK_SPEED_KMPH` | Plausible-speed clamps and last-resort speed for the baseline ETA engine (Phase 5) |
| `BASELINE_MAX_RECOVERY_PERCENT` / `BASELINE_MAX_RECOVERY_MINUTES_PER_SECTION` | Conservative per-section delay-recovery caps (Phase 5) |
| `BASELINE_CACHE_TTL_SECONDS` / `BASELINE_STALE_STATE_MINUTES` | ETA cache TTL; event age beyond which data is reported `STALE` (Phase 5) |
| `ML_MODEL_ENABLED` | Master switch for the Phase 6 residual model (false → pure baseline) |
| `ML_MODEL_DIR` / `ML_MODEL_VERSION` | Registry root / active model version (empty = latest trained) |
| `ML_RESIDUAL_MINUTES_MIN` / `ML_RESIDUAL_MINUTES_MAX` | Safety clamp applied to every ML residual |
| `ML_CACHE_TTL_SECONDS` | Redis TTL for fused ETA responses |
| `ML_DATASET_PATH`, `ML_SYNTHETIC_DAYS`, `ML_SYNTHETIC_SEED` | Dataset generation defaults (Phase 6) |
| `ML_XGB_MAX_DEPTH`, `ML_XGB_LEARNING_RATE`, `ML_XGB_N_ESTIMATORS`, … | XGBoost hyperparameters |
| `ML_SPLIT_TRAIN` / `ML_SPLIT_VALIDATION` | Chronological split ratios (remainder = test) |
| `ML_MODEL_PATH`, `MLFLOW_TRACKING_URI` | Reserved for later ML phases |

## Database setup & migrations (Alembic)

`alembic/env.py` reads `DATABASE_URL` from the same `Settings` object the app uses and
targets `Base.metadata` (via `app/models/__init__.py`, which imports every model so they
register on the shared registry), so migrations, autogenerate, and the running app never
drift apart.

```bash
# create the database + role once (see docker-compose.yml for the Docker-provided ones,
# or create them yourself against a local PostgreSQL instance):
#   CREATE ROLE railcast WITH LOGIN PASSWORD 'railcast';
#   CREATE DATABASE railcast OWNER railcast;

alembic upgrade head          # apply all migrations
alembic downgrade -1          # roll back one revision (verified clean in this phase)
alembic upgrade head          # re-apply — round-trips without corruption

# once models change in a later phase:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Seed data

```bash
python -m scripts.seed
```

Populates a small, realistic **New Delhi → Mumbai CSMT** trunk line (via Mathura, Agra,
Gwalior, Jhansi, Bhopal, Itarsi, Nagpur), plus a **Jhansi → Bina → Bhopal** branch offered
as an alternative to the direct Jhansi–Bhopal section — so the network has a genuine fork,
not just a single line. See `scripts/seed.py` for the full station/section/train tables and
inline documentation of every value.

The script is **idempotent**: stations/sections are looked up by their unique code and
trains by their unique number before insert, so running it repeatedly never creates
duplicates. Sample `TrainEvent` rows are only inserted the first time (skipped if any
`train_events` row already exists) — they're illustrative point-in-time data, not something
that needs re-seeding on every run.

Seeded (see "Sample data" below for the full breakdown): **10 stations**, **10 railway
sections**, **7 trains**, **35 train-route entries**, **6 train events**. No `Prediction` or
`Alert` rows are seeded — Phase 2 only defines their storage shape; nothing computes them yet.

## Running tests

```bash
pytest -v
```

- `test_health.py` — no database required; the health endpoint degrades gracefully.
- `test_db_models.py` — model creation, unique/check constraints, relationships. Uses a
  per-test savepoint that's rolled back afterward, so these tests never touch seed data and
  are safe to run against a database you're also using for manual exploration.
- `test_seed_integrity.py` — runs the real seed script (committing, since it's testing the
  seed script's actual persisted behavior) and verifies: running it twice produces identical
  row counts (idempotency), the expected sample rows exist, and — critically — that every
  consecutive station pair in every seeded train's route is backed by a real `RailwaySection`.
  That last check matters because the future baseline ETA engine walks this exact graph.
- `test_api_trains.py` / `test_api_stations.py` — exercise every Phase 3 endpoint over HTTP
  (via `httpx.AsyncClient` against the real ASGI app) using the reseeded sample network:
  listing/pagination/search/filters, 404s, route ordering, upcoming-route position logic,
  latest-state selection, event pagination/filtering, station board, and the data-integrity
  checks that upcoming stations never include already-passed ones and that a station's
  `/trains` listing round-trips correctly through each train's own `/route`.

All DB-dependent test modules skip (rather than fail) with a clear message if PostgreSQL
isn't reachable, via a `require_db` fixture wrapping `check_database_connection()`. The API
test modules additionally depend on a `seeded_client` (HTTP) or `seeded_session` (direct
`AsyncSession`) fixture that runs the (idempotent) seed script before the test, so they work
against a freshly created database too.

- `test_providers.py` — provider interface, NTES, RailRadar (mocked HTTP), and
  `ProviderManager` (fallback, cooldown, timeout, the no-silent-simulator-fallback safety
  rule) — none of this needs a database, and it never calls a real external service.
- `test_provider_simulator.py`, `test_ingestion.py`, `test_api_live.py` — the Simulator
  adapter, TrainEvent ingestion (including duplicate protection), and the `/live`/`/providers`
  APIs against the real reseeded sample network.

## API documentation

With the server running, interactive docs are available at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI schema: `http://localhost:8000/openapi.json`

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Basic service info |
| GET | `/health` | Liveness probe; reports database/Redis connectivity without failing the request |
| GET | `/api/v1/trains` | Paginated train list — `search`, `train_type`, `zone`, `active` filters |
| GET | `/api/v1/trains/{train_number}` | Train detail + route summary |
| GET | `/api/v1/trains/{train_number}/route` | Full scheduled route, ordered by `sequence_number` |
| GET | `/api/v1/trains/{train_number}/upcoming` | Remaining stops based on the train's latest known position |
| GET | `/api/v1/trains/{train_number}/state` | Latest known operational state (404 if no event yet) |
| GET | `/api/v1/trains/{train_number}/events` | Paginated event history — `event_type`, `from_timestamp`, `to_timestamp` filters |
| GET | `/api/v1/stations` | Paginated station list — `search`, `zone`, `state`, `station_type` filters |
| GET | `/api/v1/stations/{station_code}` | Station detail |
| GET | `/api/v1/stations/{station_code}/board` | Trains scheduled here + their latest known status (not an ETA board) |
| GET | `/api/v1/stations/{station_code}/trains` | Paginated trains stopping here, via `TrainRoute` |
| GET | `/api/v1/live/trains/{train_number}` | Live/simulated position + delay from the configured provider (see "Data providers") |
| GET | `/api/v1/live/trains/{train_number}/route` | Route as reported by the provider (not RAILCAST's own schedule) |
| GET | `/api/v1/live/stations/{station_code}` | Live operational board from the provider |
| GET | `/api/v1/providers/status` | Status of every configured provider (NTES, RailRadar, Simulator) |
| GET | `/api/v1/providers/{provider}/status` | Detailed health for one provider |
| GET | `/api/v1/eta/{train_number}` | ETA for every upcoming station: baseline + ML residual fusion (Phase 6), or pure baseline with `?mode=baseline` |
| GET | `/api/v1/eta/{train_number}/{station_code}` | ETA for one specific upcoming station (same fusion semantics) |
| GET | `/api/v1/network/overview` | Network-wide predicted impact: delayed/affected trains, conflicts, hotspots, overall score |
| GET | `/api/v1/network/trains/{train_number}/impact` | Predicted network impact of one train's current delay |
| GET | `/api/v1/network/affected-trains` | Paginated trains potentially affected by delay propagation — `severity`, `min_impact_score` filters |
| GET | `/api/v1/network/conflicts` | Paginated predicted shared-section conflicts — `severity`, `conflict_type`, `section_code`, `train_number` filters |
| GET | `/api/v1/network/hotspots` | Stations/sections where predicted impacts converge |
| GET | `/api/v1/network/timeline` | Time-bucketed predicted network impact across the analysis horizon |

Health example:

```json
{
  "status": "ok",
  "service": "RAILCAST",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-09-09T18:18:15.328306Z",
  "dependencies": { "database": "up", "redis": "up" }
}
```

`status` is `"degraded"` (still HTTP 200) if either dependency is unreachable, so the
endpoint itself never flaps for orchestrator health checks.

## API examples

All list endpoints share one pagination envelope:

```json
{ "items": [...], "page": 1, "page_size": 20, "total": 7, "total_pages": 1 }
```

**`GET /api/v1/trains?search=Rajdhani`**
```json
{
  "items": [{
    "train_number": "12951",
    "train_name": "Mumbai Rajdhani Express",
    "train_type": "RAJDHANI",
    "source_station_code": "NDLS", "source_station_name": "New Delhi",
    "destination_station_code": "CSMT", "destination_station_name": "Mumbai CSMT",
    "zone": "NR", "priority": "HIGH", "active": true
  }],
  "page": 1, "page_size": 20, "total": 1, "total_pages": 1
}
```

**`GET /api/v1/trains/12951`**
```json
{
  "train_number": "12951", "train_name": "Mumbai Rajdhani Express", "train_type": "RAJDHANI",
  "source_station_code": "NDLS", "source_station_name": "New Delhi",
  "destination_station_code": "CSMT", "destination_station_name": "Mumbai CSMT",
  "zone": "NR", "priority": "HIGH", "active": true,
  "created_at": "2026-09-09T18:20:00Z", "updated_at": "2026-09-09T18:20:00Z",
  "route_summary": {
    "total_stations": 9, "total_distance_km": 1882.0,
    "origin_departure_time": "16:25:00",
    "destination_arrival_time": "15:25:00", "destination_arrival_day_offset": 1
  }
}
```

**`GET /api/v1/trains/12951/route`** (excerpt)
```json
{
  "train_number": "12951", "train_name": "Mumbai Rajdhani Express",
  "source": "NDLS", "destination": "CSMT",
  "route": [
    { "sequence_number": 1, "station_code": "NDLS", "station_name": "New Delhi",
      "arrival_time": null, "departure_time": "16:25:00", "day_offset": 0,
      "halt_minutes": 0, "distance_from_source_km": 0.0, "section_code": null },
    { "sequence_number": 2, "station_code": "MTJ", "station_name": "Mathura Junction",
      "arrival_time": "18:00:00", "departure_time": "18:05:00", "day_offset": 0,
      "halt_minutes": 5, "distance_from_source_km": 141.0, "section_code": "NDLS-MTJ" }
  ]
}
```

**`GET /api/v1/trains/11077/upcoming`** — latest event is a SPEED_RESTRICTION in section
`GWL-JHS`, so the train is treated as already past GWL, heading to JHS:
```json
{
  "train_number": "11077", "train_name": "Jhelum Superfast Express",
  "has_known_state": true, "as_of": "2026-09-09T18:40:00Z",
  "current_station_code": null, "current_section_code": "GWL-JHS", "current_delay_minutes": 8,
  "upcoming": [
    { "sequence_number": 3, "station_code": "JHS", "station_name": "Jhansi Junction", "...": "..." },
    { "sequence_number": 4, "station_code": "BPL", "...": "..." },
    { "sequence_number": 5, "station_code": "ET", "...": "..." }
  ]
}
```

**`GET /api/v1/trains/12951/state`**
```json
{
  "train_number": "12951", "timestamp": "2026-09-09T19:00:00Z",
  "latitude": null, "longitude": null, "speed_kmph": 0.0,
  "station_code": null, "section_code": "AGC-GWL", "delay_minutes": 15,
  "event_type": "SIGNAL_HALT", "event_source": "SIMULATOR",
  "metadata": { "reason": "awaiting platform clearance" },
  "data_freshness_seconds": 342.7
}
```

**`GET /api/v1/trains/12951/events?page_size=2`**
```json
{
  "items": [
    { "id": 3, "timestamp": "2026-09-09T19:00:00Z", "event_type": "SIGNAL_HALT",
      "event_source": "SIMULATOR", "station_code": null, "section_code": "AGC-GWL",
      "delay_minutes": 15, "speed_kmph": 0.0, "latitude": null, "longitude": null,
      "metadata": { "reason": "awaiting platform clearance" } },
    { "id": 2, "timestamp": "2026-09-09T17:30:00Z", "event_type": "POSITION_UPDATE",
      "event_source": "SIMULATOR", "station_code": null, "section_code": "MTJ-AGC",
      "delay_minutes": 12, "speed_kmph": 95.0, "latitude": 27.3, "longitude": 77.85,
      "metadata": null }
  ],
  "page": 1, "page_size": 2, "total": 3, "total_pages": 2
}
```

**`GET /api/v1/stations?search=Delhi`**
```json
{
  "items": [{ "station_code": "NDLS", "station_name": "New Delhi", "zone": "NR",
              "state": "Delhi", "station_type": "TERMINAL" }],
  "page": 1, "page_size": 20, "total": 1, "total_pages": 1
}
```

**`GET /api/v1/stations/NDLS`**
```json
{
  "station_code": "NDLS", "station_name": "New Delhi",
  "latitude": 28.6432, "longitude": 77.2196,
  "zone": "NR", "division": "Delhi", "state": "Delhi", "station_type": "TERMINAL"
}
```

**`GET /api/v1/stations/BPL/board`** — note the `NO_RECENT_DATA` entry: train 12294
originates at BPL but has no seeded event yet, so its state is honestly reported as unknown
rather than fabricated:
```json
{
  "station_code": "BPL", "station_name": "Bhopal Junction", "generated_at": "2026-09-09T19:05:00Z",
  "board": [
    { "train_number": "12294", "train_name": "Sanghamitra Superfast Express",
      "source_station_code": "BPL", "destination_station_code": "CSMT",
      "scheduled_arrival": null, "scheduled_departure": "11:30:00",
      "latest_known_delay_minutes": null, "latest_event_timestamp": null,
      "status": "NO_RECENT_DATA" },
    { "train_number": "12951", "train_name": "Mumbai Rajdhani Express",
      "source_station_code": "NDLS", "destination_station_code": "CSMT",
      "scheduled_arrival": "01:00:00", "scheduled_departure": "01:05:00",
      "latest_known_delay_minutes": 15, "latest_event_timestamp": "2026-09-09T19:00:00Z",
      "status": "DELAYED" }
  ]
}
```

**`GET /api/v1/stations/BPL/trains`**
```json
{
  "items": [{ "train_number": "12951", "train_name": "Mumbai Rajdhani Express",
              "source_station_code": "NDLS", "destination_station_code": "CSMT",
              "sequence_number": 6, "scheduled_arrival": "01:00:00",
              "scheduled_departure": "01:05:00", "halt_minutes": 5 }],
  "page": 1, "page_size": 20, "total": 5, "total_pages": 1
}
```

Errors follow FastAPI's standard shape: `{"detail": "Train 99999 not found"}` (404),
or a 422 with field-level detail for invalid query params (e.g. `page_size` over 100).

**`GET /api/v1/live/trains/12951`** — with the default config (`PRIMARY_DATA_PROVIDER=SIMULATOR`),
this reads the same seeded `TrainEvent` data as `/api/v1/trains/12951/state`, but through the
provider abstraction, explicitly labeled:
```json
{
  "train_number": "12951",
  "position": { "latitude": null, "longitude": null },
  "speed_kmph": 0.0,
  "station_code": null,
  "section_code": "AGC-GWL",
  "delay_minutes": 15,
  "event_type": "SIGNAL_HALT",
  "timestamp": "2026-09-09T19:00:00Z",
  "data_source": "SIMULATOR",
  "data_status": "SIMULATED",
  "retrieved_at": "2026-09-10T09:15:00Z",
  "data_age_seconds": 62.3
}
```

**`GET /api/v1/providers/status`** — the honest default state without any real provider
credentials configured:
```json
{
  "providers": [
    { "provider": "NTES", "enabled": false, "available": false, "configured": false,
      "provider_type": "REAL", "error": "NTES_ENABLED is false", "...": "..." },
    { "provider": "RAILRADAR", "enabled": false, "available": false, "configured": false,
      "provider_type": "REAL", "error": "RAILRADAR_ENABLED is false", "...": "..." },
    { "provider": "SIMULATOR", "enabled": true, "available": true, "configured": true,
      "provider_type": "SIMULATOR", "error": null, "...": "..." }
  ]
}
```

## Database entities & relationships

```
Station
 ├── sections_from / sections_to     (RailwaySection.from_station / to_station)
 ├── trains_originating / trains_terminating   (Train.source_station / destination_station)
 ├── route_entries                   (TrainRoute.station)
 ├── events                          (TrainEvent.station, nullable FK)
 ├── predictions                     (Prediction.station)
 └── alerts                          (Alert.station, nullable FK)

Train
 ├── source_station / destination_station
 ├── routes         (TrainRoute, cascade delete — the route IS the train's schedule)
 ├── events         (TrainEvent, cascade delete)
 ├── predictions    (Prediction, cascade delete)
 └── alerts         (Alert, cascade delete, nullable FK)

RailwaySection
 ├── from_station / to_station
 ├── routes    (TrainRoute.section, nullable — the origin stop has none)
 ├── events    (TrainEvent.section, nullable FK)
 └── alerts    (Alert.section, nullable FK)
```

`Train`'s children (`routes`, `events`, `predictions`, `alerts`) cascade-delete with the
train, both at the ORM level and via `ON DELETE CASCADE` — a train's data lifecycle is
owned by the train record. `Station` and `RailwaySection` are reference data: nothing
cascades from them, so deleting one is blocked while anything still points to it.

## Database design decisions

**Integer primary keys, not UUIDs.** Simpler joins, smaller indexes, and there's no
multi-writer/offline-generation scenario here that would need UUIDs' collision-free
properties. Applied consistently across every table.

**`TrainRoute.scheduled_arrival` / `scheduled_departure` are clock `Time` values, not
`datetime`s — plus a `day_offset` integer.** A `TrainRoute` row is a *template*: "this train
stops here at 08:40, every time it runs" — not "this train stopped here on 9 March 2026."
Baking a calendar date into the schedule would conflate the recurring timetable with one
specific day's run. `day_offset` (days elapsed since the train's origin departure) exists
because journeys spanning past midnight need to distinguish 08:10 on day 0 from 08:10 on
day 1 — e.g. the Mumbai Rajdhani's Nagpur→Mumbai leg. Actual dated occurrences belong to
`TrainEvent` (real observed timestamps) and `Prediction` (real predicted/actual timestamps),
which is exactly where the future baseline ETA engine will combine a `TrainRoute` template
with "today's date" to get a concrete scheduled time.

**`event_metadata` / `alert_metadata`, not `metadata`.** SQLAlchemy's `DeclarativeBase`
reserves the `metadata` attribute for the ORM's own table registry, so a column literally
named `metadata` can't be a same-named Python attribute. The database column is still named
`metadata` (matches the spec); only the ORM-side Python attribute is renamed. The Pydantic
schemas paper over this with a validation/serialization alias, so the API surface still reads
and writes a `metadata` key — the rename is purely an ORM implementation detail.

**Enums are `VARCHAR` + `CHECK` constraint, not native PostgreSQL `ENUM` types**
(`SAEnum(..., native_enum=False)`). Native PG enums require an `ALTER TYPE` migration dance
to add new values later; a `CHECK` constraint is a normal column constraint a future Alembic
migration can drop and recreate like any other. Given `EventType`/`AlertType`/etc. are likely
to grow as later phases add real operational scenarios, this trades a small amount of storage
efficiency for much cheaper schema evolution.

**Cascade deletes from `Train`, not from `Station`/`RailwaySection`.** A train "owns" its
route/events/predictions/alerts — deleting a train should not leave orphaned rows. Deleting a
*station* or *section*, on the other hand, is a rare reference-data correction that should be
blocked (default `NO ACTION`) while any train/event/route still references it, not silently
cascade into deleting unrelated trains' history.

## Sample data

Seeded network (`scripts/seed.py`) — 10 stations along a Delhi → Mumbai trunk line with one
branch:

```
NDLS (New Delhi, TERMINAL)
  │
MTJ (Mathura Jn) — AGC (Agra Cantt) — GWL (Gwalior) — JHS (Jhansi Jn)
                                                          │
                                              ┌───────────┴───────────┐
                                         JHS-BPL (direct)        JHS-BINA-BPL (branch)
                                              │                         │
                                              └───────────┬─────────────┘
                                                         BPL (Bhopal Jn)
                                                            │
                                                  ET (Itarsi Jn) — NGP (Nagpur)
                                                            │
                                                   CSMT (Mumbai CSMT, TERMINAL)
```

7 trains of varying type/priority/route length running over it: `12951` Mumbai Rajdhani
Express (RAJDHANI, NDLS→CSMT, full line), `12002` Bhopal Shatabdi Express (SHATABDI,
NDLS→BPL), `12615` Grand Trunk Superfast Express (SUPERFAST, NDLS→NGP, via the Bina branch),
`11077` Jhelum Superfast Express (SUPERFAST, AGC→ET), `14217` Prayagraj Express (EXPRESS,
NDLS→AGC), `12138` Punjab Mail (EXPRESS, NGP→CSMT), `12294` Sanghamitra Superfast Express
(SUPERFAST, BPL→CSMT) — 35 route entries total. Plus 6 sample `TrainEvent` rows (a
DEPARTURE, POSITION_UPDATE, SIGNAL_HALT, ARRIVAL, CONGESTION, and SPEED_RESTRICTION),
all tagged `event_source: SIMULATOR`.

## API design decisions (Phase 3)

**"Upcoming" is derived from the latest `TrainEvent`, not predicted.** `/upcoming` walks the
train's static route and returns whatever comes after its last known position — an event at a
station means that station is passed (upcoming = later stops only); an event *in* a section
means the train is heading toward that section's destination station (upcoming = that station
onward). No timing math, no ETA — purely "where does the known data put us on the timetable."
If there's no event yet, or the event references a station/section not on this train's route
(bad data), it falls back to returning the full route rather than guessing.

**Station board status (`ON_TIME`/`DELAYED`/`NO_RECENT_DATA`) is a label, not a forecast.**
It's `DELAYED` iff the train's latest known `delay_minutes > 0`, `NO_RECENT_DATA` iff no event
exists yet for that train at all — never fabricated. It deliberately has no "on time within N
minutes" grace band or trend logic; that kind of judgment call belongs to the alert-generation
phase, not a read-only board endpoint.

**`get_latest_for_trains` uses `SELECT DISTINCT ON (train_id) ... ORDER BY train_id,
timestamp DESC, id DESC` (one query) rather than one `get_latest_for_train` call per train.**
The station board needs "latest event" for every train stopping there at once; doing that as
N sequential queries would be an N+1 pattern that gets worse as more trains share a station.
This is the one place Phase 3 reaches for a non-obvious query shape — everywhere else stays
plain `SELECT ... LIMIT`.

**Every `ORDER BY timestamp DESC` is `ORDER BY timestamp DESC, id DESC`.** Two events can
share a timestamp (simulated data, or two systems reporting at the same instant); `id DESC` as
a tiebreaker makes "latest event" and event-history ordering deterministic instead of
depending on incidental row-storage order.

## Data providers (Phase 4)

RAILCAST talks to real or simulated railway data through one abstraction (`app/providers/`)
so the rest of the system — the ingestion service, the live APIs — never knows or cares
which provider actually answered:

```
NTESProvider ──┐
RailRadarProvider ─┼──▶ ProviderManager ──▶ LiveResult (data + data_status + actual_provider)
SimulatorProvider ─┘         │
                              ├─▶ Redis (cache, protects providers from repeated calls)
                              └─▶ ingestion_service ──▶ TrainEvent (PostgreSQL) ──▶ Phase 3 APIs
```

### Supported providers

| Provider | Status in this build | What it would take to go live |
|---|---|---|
| **NTES** | Always `UNAVAILABLE` | Indian Railways has no documented public developer API for NTES. This adapter (`app/providers/ntes.py`) implements the full interface but never fabricates a connection — see its module docstring. |
| **RailRadar** | `UNAVAILABLE` unless configured | A third-party service, not an official Railways API. The HTTP plumbing (auth, timeout, retry/backoff, response validation) is real and production-shaped, but the request paths/response parsing in `app/providers/railradar.py` are a best-effort scaffold — this repo has no verified access to RailRadar's actual documentation. Set `RAILRADAR_ENABLED=true`, `RAILRADAR_API_KEY`, and `RAILRADAR_BASE_URL` to enable it; it never guesses at a default URL. |
| **Simulator** | `AVAILABLE` / `SIMULATED` by default | Wraps RAILCAST's own Phase 2 sample data (seeded `TrainEvent`/`TrainRoute` rows) behind the same interface a real feed would use. Always explicitly tagged `data_source: SIMULATOR`, `data_status: SIMULATED` — never presented as live. |

### Configuration

```bash
PRIMARY_DATA_PROVIDER=SIMULATOR   # which provider to try first
FALLBACK_DATA_PROVIDER=           # empty = no fallback (see "Fallback behavior" below)

NTES_ENABLED=false
RAILRADAR_ENABLED=false
SIMULATOR_ENABLED=true

RAILRADAR_API_KEY=                # never commit a real key
RAILRADAR_BASE_URL=                # never commit a real URL

PROVIDER_TIMEOUT_SECONDS=10
PROVIDER_CACHE_TTL_SECONDS=30      # how long a cached result counts as "fresh"
PROVIDER_COOLDOWN_SECONDS=60       # how long a failed provider is skipped afterward

LIVE_INGESTION_ENABLED=false       # background polling is opt-in
LIVE_INGESTION_INTERVAL_SECONDS=30
```

To enable the simulator (the default, needs nothing else): leave `SIMULATOR_ENABLED=true`
and `PRIMARY_DATA_PROVIDER=SIMULATOR` — it works out of the box against seeded data.

To configure RailRadar: set `RAILRADAR_ENABLED=true` plus `RAILRADAR_API_KEY` and
`RAILRADAR_BASE_URL` in your own untracked `.env`. Until you have real API documentation
for RailRadar, expect `/api/v1/providers/RAILRADAR/status` to show `available: false` even
when "configured" — `available` requires a proven successful call, not just credentials
(see "API design decisions" below).

NTES has no enablement path in this build — see the table above.

### LIVE vs STALE vs UNAVAILABLE vs SIMULATED

Every live-data response carries a `data_status`:

| Status | Meaning |
|---|---|
| `LIVE` | A real provider (NTES/RailRadar) answered successfully, within its cache freshness window. |
| `SIMULATED` | The Simulator answered — always, regardless of freshness. Never confused with `LIVE`. |
| `STALE` | A fresh provider call failed, but a previously cached result (past its freshness window, within its hard cache expiry) was returned instead of nothing. |
| `UNAVAILABLE` | No provider — primary, or the explicitly configured fallback — could produce data, and nothing usable was cached. `data` is `null`. |

`retrieved_at` and `data_age_seconds` accompany every response so a consumer can judge
freshness itself rather than trusting the label alone.

### Fallback behavior

`ProviderManager` tries `PRIMARY_DATA_PROVIDER`, and only if that fails, tries
`FALLBACK_DATA_PROVIDER` — **but only if it's explicitly set**. If `FALLBACK_DATA_PROVIDER`
is empty (the default), a primary failure goes straight to `UNAVAILABLE`. The manager never
silently substitutes the simulator (or any other provider) as an implicit fallback — see
`test_manager_all_unavailable_never_silently_uses_simulator` in `tests/test_providers.py`.
This is deliberate: a production deployment must never accidentally present simulated train
positions as real ones. `requested_provider` and `actual_provider` are both always reported,
so a caller can tell when a fallback actually happened.

### How ingestion works

`app/services/ingestion_service.py` converts a provider's normalized `TrainState` into a
`TrainEvent` row — reusing the exact model/table Phase 2 already defined, not a second one.
It resolves the train/station/section by their RAILCAST codes, and is idempotent: a
duplicate `(train, provider, timestamp)` triple returns the existing row instead of
inserting a copy — see `find_duplicate` in `event_repository.py`.

An optional background worker (`app/workers/ingestion_worker.py`) polls every active train
through `ProviderManager` on a configurable interval and ingests the results. It's a
deliberately minimal async loop — a placeholder that can later be swapped for
Celery/APScheduler/Redis Streams without changing `ingestion_service` or `ProviderManager`.
It only starts if `LIVE_INGESTION_ENABLED=true` (wired into `app/main.py`'s lifespan); the
API is fully functional with it off, including every `/live/*` endpoint (which fetch
on-demand through the same `ProviderManager`, independent of the background worker).

## API design decisions (Phase 4)

**`available` requires a proven successful call, not just configuration.** For NTES/RailRadar,
`ProviderStatus.available` only becomes `true` after that adapter's most recent attempt
succeeded — `enabled=true` plus valid-looking credentials isn't proof of connectivity. The
Simulator is the one exception: it has no external network dependency (only the database,
already covered by `/health`), so it's `available` whenever `SIMULATOR_ENABLED=true`.

**A 404 vs. `data_status: UNAVAILABLE` mean different things.** `/live/trains/{train_number}`
first checks whether the train exists in RAILCAST's own digital twin (Phase 2) — if not, a
404, exactly like the Phase 3 endpoints. If the train *does* exist but no configured provider
currently has data for it, that's a normal 200 with `data_status: UNAVAILABLE` — a real
resource with temporarily-unknown live state, not a client error.

**Two-tier cache freshness, not a single Redis TTL.** Each cache entry is written with a
Redis TTL of `4 × PROVIDER_CACHE_TTL_SECONDS` (the hard expiry), but only treated as fresh
(`LIVE`/`SIMULATED`) within `PROVIDER_CACHE_TTL_SECONDS` of retrieval. Past that softer
window, a fresh provider call is attempted; if it also fails, the old entry is still
returned rather than discarded — just relabeled `STALE`. This is what makes `STALE` mean
something distinct from "cache miss, ask the provider again."

**RailRadar's failure modes are split by whether they indicate a health problem.**
`ProviderTimeoutError`/`ProviderUnavailableError` trip that provider's cooldown (module 12);
`ProviderNotFoundError` (train/station genuinely has no data there) and `ProviderDataError`
(response couldn't be normalized) don't — a single train the provider doesn't know about
shouldn't take the whole provider offline for everyone else's requests.

## Baseline ETA engine (Phase 5)

`GET /api/v1/eta/{train_number}` computes a deterministic, railway-aware ETA for every
upcoming station (destination included) — **not** an ML prediction and not a naive
`scheduled_arrival + current_delay`. The pipeline:

```
Latest Train State (TrainEvent)
        ↓
Position Resolver (app/services/position_resolver.py)
        ├── at a station            → journey resumes after that station
        ├── departed a station      → full next section (progress unknown)
        ├── inside a known section  → remaining distance (GPS-projected fraction if GPS exists)
        ├── GPS only                → nearest route station / section heuristic (approximate)
        └── no event                → whole route, delay 0, data_status UNAVAILABLE
        ↓
Remaining Route Resolver
        ↓
Section Travel-Time Estimator  (expected speed hierarchy below)
        ↓
Station Halt Estimator         (scheduled halt_minutes; swappable for dwell prediction later)
        ↓
Delay / Recovery Logic         (CONFIGURED_BASELINE_RECOVERY, conservative and capped)
        ↓
BASELINE ETA per station
```

**Expected-speed hierarchy per section** (all speeds clamped to
`[BASELINE_MIN_SPEED_KMPH, BASELINE_MAX_SPEED_KMPH]`):

1. operational/current speed — current leg only, only when actually moving
2. section average running time (`RailwaySection.average_running_minutes`)
3. scheduled running time (`RailwaySection.scheduled_running_minutes`)
4. section speed limit (`RailwaySection.speed_limit_kmph`)
5. configured fallback (`BASELINE_FALLBACK_SPEED_KMPH`)

**Distance hierarchy**: `RailwaySection.distance_km` → route
`distance_from_origin_km` deltas → haversine × detour factor, always labelled
`GEOGRAPHIC_APPROXIMATION` in the response's calculation details (straight-line distance
is never presented as railway distance).

**Delay propagation & recovery**: the current delay evolves per remaining section:
`delay ← max(0, delay + (estimated − scheduled running time) − recovery)`, where
recovery is `min(delay × BASELINE_MAX_RECOVERY_PERCENT/100,
BASELINE_MAX_RECOVERY_MINUTES_PER_SECTION)` — deliberately conservative; a train never
snaps back to schedule. This is RAILCAST model configuration, not an Indian Railways
operating rule.

**Fallbacks**: stations without a timetable anchor get a
`prediction_mode = BASELINE_FALLBACK` ETA reconstructed from cumulative travel-time
estimates (halts included). Insufficient data never crashes the API — it degrades and
says so.

**Response contract** (per station): `scheduled_arrival` is the untouched timetable
value, `baseline_eta` is the estimate, `delay_minutes = baseline − scheduled`, and
`calculation_details` carries position/distance/speed/delay/recovery provenance for
future explainability (RailExplain). Responses carry `data_source` and `data_status`
(`LIVE` / `SIMULATED` / `STALE` / `UNAVAILABLE` — a stale event still computes, honestly
labelled).

**Caching**: computed ETAs are cached in Redis under
`railcast:baseline_eta:{train_number}:{latest_event_timestamp}` with a short TTL — a new
train state produces a new key, so an old ETA is never served for a changed state.
Without Redis the engine simply recomputes.

**Persistence**: fresh computations are stored as `Prediction` rows
(`prediction_mode=BASELINE`/`BASELINE_FALLBACK`, `ml_correction_minutes=null`,
`model_version=baseline-v1`), one current row per (train, station, mode).

**Final ETA is NOT computed here.** Later phases add
`FINAL ETA = BASELINE ETA + ML PREDICTED RESIDUAL`; this engine stays fully independent
of XGBoost/ML so the ML layer remains a pure correction on top of it.

## ML residual ETA model (Phase 6)

The ML layer NEVER produces an absolute ETA. It learns only the correction the baseline
doesn't capture:

```
FINAL ETA = BASELINE ETA + ML PREDICTED RESIDUAL   (residual clamped to configured bounds)
```

**Target definition.** For every observation:
`residual_minutes = actual_arrival − baseline_eta` (positive = arrived later than the
baseline predicted). Actual arrivals are labels only — never features.

**Leakage prevention (mandatory).** Features use only information known at the
prediction timestamp. `build_feature_row` additionally refuses any history event newer
than the prediction time (defence in depth), and a regression test injects a T+1 record
and asserts the T features don't move. The chronological split (below) prevents future
periods from leaking into training.

**Feature groups** (`app/ml/features.py`; identical code path for training and
inference): delay (current, trend), position (GPS, speed), route (remaining distance/
sections/stations, progress %, distance to next stop), schedule (leg scheduled/average
running, speed limit, halt, baseline delay, baseline minutes-ahead), calendar
(hour/day-of-week/month), categoricals (train type, priority, zone, station, section —
vocabulary-encoded, saved with the model, unseen values map to UNKNOWN). Missing values
→ NaN, handled natively by XGBoost.

**Data.** With no real history yet, `python -m scripts.build_ml_dataset` generates a
**clearly-labelled SYNTHETIC** dataset (Parquet at `ML_DATASET_PATH`, git-ignored): N
days of simulated journeys over the real sample network, with a ground-truth latency
process (rush-hour, Monday, train-type effects + noise) the baseline can't explain. The
same baseline engine and feature builder produce every row, so training and inference
distributions match. Synthetic metrics are never presented as real-world performance.
The HISTORICAL path activates once ≥500 stored predictions have known actual arrivals.

**Training** (`python -m scripts.train_eta_model`): chronological split at journey-day
level (70/15/15, configurable) → XGBoost regression (Booster API, conservative
hyperparameters from config, fixed seed) → validation + held-out-test evaluation →
registry save. Never trained at request time.

**Evaluation.** MAE, RMSE, median absolute error, bias — plus the mandatory comparison
on the held-out test period:

| Model | MAE (current SYNTHETIC test set) |
|---|---|
| Scheduled ETA | ~10.0 min |
| Baseline ETA | ~7.0 min |
| ML Residual ETA | ~6.8 min |

Improvement is signed and reported honestly (~3.5% on the current synthetic set — the
noise floor limits it); if ML is ever worse than baseline, the report says so and the
runtime fallback covers it. Gain-based feature importance is included in the training
report (SHAP is a later phase).

**Model artifact & registry** (`app/ml/registry.py`):
`{ML_MODEL_DIR}/eta_residual/{version}/` holds `model.json` (booster),
`feature_schema.json` (feature columns + categorical vocabularies),
`metadata.json` (version, dataset source/size, split, test metrics, comparison,
training timestamp, hyperparameters). Current version: `xgb-residual-v1`. MLflow is not
required.

**Inference / fusion** (`app/services/eta_fusion_service.py`): per request — baseline
ETA → features → predict residual → **clamp** (`ML_RESIDUAL_MINUTES_MIN/MAX`, clipping
recorded per station via `predicted_residual_raw` / `residual_clipped`) → `final_eta` →
cached in Redis (`railcast:eta:{train}:{state_timestamp}:{model_version}`) → persisted
as `Prediction` rows (`prediction_mode=ML_RESIDUAL`, `ml_correction_minutes`, `final_eta`).
When an observed ARRIVAL is ingested, stored predictions get `actual_arrival` and
`error_minutes` backfilled (outcome-only updates — never during inference).

**Fallback (mandatory).** Backend starts and serves valid ETAs with NO model present:
`prediction_mode=BASELINE_FALLBACK`, `model_version=null`, `final_eta=baseline_eta`.
Any ML failure (disabled, missing, corrupt, feature problems, runtime error) lands in
the same clean fallback — an invented ML value is never returned.

**API response semantics** — four distinct, never-overwritten values per station:
`scheduled_arrival` (timetable), `baseline_eta` (Phase 5 estimate),
`predicted_residual_minutes` (clamped ML correction), `final_eta` (fused), plus
`delay_minutes` / `final_delay_minutes`. `?mode=baseline` returns the pure Phase 5
deterministic estimate.

## ETA Uncertainty, Confidence & Explainability (Phase 7)

Phase 7 evolves RAILCAST from answering purely *"When will the train arrive?"* to:
- *"How confident are we?"* (transparent 0–100 quality score + level)
- *"What is the likely ETA range?"* (residual-error prediction intervals)
- *"Why is the ETA changing?"* (deterministic baseline explanations + exact TreeSHAP ML factors)

```
              BASELINE ETA
                    +
             ML RESIDUAL
                    │
                    ▼
               FINAL ETA
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    Confidence   Uncertainty   Explanation
        │           │           │
        └───────────┼───────────┘
                    ▼
              RAILCAST ETA API
```

### 1. ETA Uncertainty & Prediction Intervals

Uncertainty is **never** an arbitrary fixed ±10 minute interval. It is derived empirically from
the active ML residual model's held-out evaluation residuals:

- **Method**: signed residual quantiles (e.g., nominal 80% interval $\rightarrow$ $P_{10}$ and $P_{90}$ of $actual - baseline$).
- **Asymmetric bounds**:
  $$\text{lower\_eta} = \text{final\_eta} + \text{residual\_p10}$$
  $$\text{upper\_eta} = \text{final\_eta} + \text{residual\_p90}$$
  Delays typically skew positive (e.g., $P_{10} = -5.0$ min, $P_{90} = +13.0$ min), so upper bound expansion is wider than lower bound contraction.
- **Conditional grouping**: quantiles are grouped by prediction horizon buckets (`UNCERTAINTY_HORIZON_BUCKET_MINUTES=60`). When a bucket has fewer than `UNCERTAINTY_MIN_GROUP_SIZE` samples, it safely falls back to global residual quantiles (`source="GLOBAL_QUANTILES"`).
- **Calibration metrics**: stored directly in model metadata:
  - `coverage`: percentage of held-out actual arrivals falling inside $[\text{lower\_eta}, \text{upper\_eta}]$.
  - `average_interval_width_minutes`: mean width of the interval across the test set.
- **Wording discipline**: Always referred to as an *"80% prediction interval"* whose empirical coverage is measured — **never** "80% accurate".

### 2. Prediction Confidence Score & Level

A deterministic, transparent 0–100 quality score:
- **Base score**: 60.0
- **Data Quality**:
  - `LIVE_DATA_FRESHNESS`: +20 for age $\le 120$s, decays linearly to 0 by 360s; -15 for `STALE`; -30 for `UNAVAILABLE`.
  - `POSITION_KNOWN`: +10 if station/section/GPS position is known, -10 if unknown.
  - `KNOWN_RAILWAY_SECTION`: +10 if railway-section metadata exists, -10 if approximated.
- **Model Quality**:
  - `ML_MODEL_AVAILABLE`: +10 if fused with active model, -5 in baseline fallback mode.
  - `HISTORICAL_SUPPORT`: scales linearly from -10 (0 historical rows) to +10 (500+ rows).
- **Prediction Horizon**:
  - `PREDICTION_HORIZON`: +10 for horizon $\le 30$ min, -10 for horizon $\ge 120$ min, linear degradation in between.
- **Score Mapping**:
  - $80 - 100 \rightarrow$ `HIGH`
  - $50 - 79 \rightarrow$ `MEDIUM`
  - $0 - 49 \rightarrow$ `LOW`

> [!IMPORTANT]
> **Difference between confidence and probability**:
> Confidence score represents **confidence in the quality of the prediction inputs and model applicability** (data freshness, model availability, section fidelity). It is **NOT** the probability that the train will arrive on time.

### 3. Explainability (TreeSHAP & Baseline Factors)

The platform distinguishes two independent explanation layers:
1. **Deterministic Baseline Factors** (`app/services/baseline_explain.py`):
   - Provenance from the deterministic engine arithmetic:
     - `CURRENT_DELAY` (`LATER` / `NEUTRAL`)
     - `DELAY_RECOVERY` (`EARLIER`)
     - `SECTION_RUNNING_TIME` (`NEUTRAL`)
     - `STATION_HALT` (`NEUTRAL`)
     - `SECTION_DATA` (`NEUTRAL`)
   - Requires no ML and runs even in baseline-only mode.
2. **Exact TreeSHAP ML Factors** (`app/ml/explain.py`):
   - Uses native XGBoost TreeSHAP (`pred_contribs=True`) — exact Shapley contributions computed in $<1$ ms per station.
   - Top-K factors sorted by absolute contribution magnitude (`TOP_K_EXPLANATIONS=5`).
   - Direction mapping: positive contribution $\rightarrow$ `LATER`, negative contribution $\rightarrow$ `EARLIER`.
   - Deterministic translation layer mapping raw columns to passenger-friendly concepts (e.g. `current_delay_minutes` $\rightarrow$ "Current delay", `speed_kmph` $\rightarrow$ "Current speed", `leg_average_minus_scheduled_minutes` $\rightarrow$ "Section historical delay"). No LLM is used.

### 4. Endpoints & Response Structure

- `GET /api/v1/eta/{train_number}`:
  Every station includes `uncertainty`, `confidence`, and `explanation` blocks.
- `GET /api/v1/eta/{train_number}/{station_code}`:
  Single-station query with the same uncertainty, confidence, and explanation fields.
- `GET /api/v1/eta/{train_number}/{station_code}/explanation`:
  Full explanation endpoint returning `baseline_factors` and `ml_factors`:
  ```json
  {
    "train_number": "12951",
    "station_code": "GWL",
    "prediction_mode": "ML_RESIDUAL",
    "model_version": "xgb-residual-v1",
    "prediction_timestamp": "2026-09-10T09:30:00Z",
    "final_eta": "2026-09-10T11:15:30Z",
    "predicted_residual_minutes": 4.5,
    "available": true,
    "reason": null,
    "baseline_factors": [
      {
        "factor": "CURRENT_DELAY",
        "display_name": "Current train delay",
        "effect": "LATER",
        "value": 12.0
      },
      {
        "factor": "DELAY_RECOVERY",
        "display_name": "Expected delay recovery",
        "effect": "EARLIER",
        "value": 2.0
      }
    ],
    "ml_factors": [
      {
        "feature": "current_delay_minutes",
        "display_name": "Current delay",
        "contribution_minutes": 4.8,
        "direction": "LATER"
      },
      {
        "feature": "speed_kmph",
        "display_name": "Current speed",
        "contribution_minutes": -0.9,
        "direction": "EARLIER"
      }
    ]
  }
  ```

### 5. Fallback & Safety Guarantees

- If the ML model is disabled or unavailable:
  - `prediction_mode`: `BASELINE_FALLBACK`
  - `final_eta = baseline_eta`
  - `explanation.available`: `false`, `reason`: `"ML_MODEL_UNAVAILABLE"`
  - `baseline_factors` remain fully available and informative.
  - The API **never crashes** and **never returns fabricated explanations**.
- Explanations are cached in Redis under state-versioned keys:
  `railcast:explanation:{train_number}:{station_code}:{state_timestamp}:{model_version}` with TTL 60 seconds.

### 6. Claim Restrictions & Limitations

- **No Probability Claims**: Score 87 means high confidence in prediction inputs/model, NOT an 87% chance of arriving on time.
- **No Coverage Guarantees**: An 80% nominal prediction interval does not guarantee 80% coverage in dynamic environments; empirical coverage is reported separately based on held-out test data.
- **No Causal Claims**: SHAP indicates model feature attribution, not physical or causal relationships in the railway network.

## Network intelligence (Phase 8)

Phases 1-7 answer "when will this train arrive?" Phase 8 (`app/network/`) answers "what
happens to the network if this train is delayed?" — a predictive decision-support layer,
**not** a replacement for signalling, interlocking, block occupancy control, platform
allocation, or any real railway dispatching system. Every number here is labelled
`PREDICTED`/`ESTIMATED`; nothing is a confirmed operational fact or a command.

### 1. Architecture

```
        TRAIN DELAY (latest TrainEvent.delay_minutes)
                      │
                      ▼
     RailwayGraphService — bounded candidate discovery
   (graph.py: which OTHER active trains share a section
      with this train's upcoming route — never a full
              table scan of trains/routes)
                      │
                      ▼
      resolver.py — section occupancy windows
  source train: reuses the Phase 5/6/7 final ETA per
  station (no second ETA model). candidates: static
  schedule + their own latest known delay (shifted).
                      │
                      ▼
   conflict.py — shared-section + temporal overlap
     SHARED_SECTION_OVERLAP / INSUFFICIENT_SEPARATION
                      │
                      ▼
  propagation.py — DeterministicPropagationModel
   estimated_delay = source_delay × overlap_factor
                       × decay^depth
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
   Affected Trains  Stations    Sections
    (BFS, up to NETWORK_MAX_PROPAGATION_DEPTH hops)
          │           │           │
          └───────────┼───────────┘
                      ▼
        scoring.py — 0-100 impact score + severity
                      │
          ┌───────────┼───────────┐
          ▼                       ▼
   Predictive Alert          /api/v1/network/*
   (deduplicated, only
    above NETWORK_ALERT_
    THRESHOLD)
```

No parallel/duplicate network representation exists — the graph is built directly from
the existing `Station`, `RailwaySection`, and `TrainRoute` tables (module 3) each time an
analysis runs (with a short Redis cache — see "Performance" below).

### 2. Shared-section detection & directionality

`find_shared_sections` (`app/network/conflict.py`) matches two trains' routes on
`TrainRoute.section_id` — the same directional `RailwaySection` row. Because this data
model has no separate "reverse" section row for the same physical track, a shared
`section_id` is **always** the same direction for both trains — directional confidence is
HIGH by construction, with no bidirectional ambiguity to resolve (module 35).

A shared section alone is never treated as a conflict (module 7) — only when the two
trains' *estimated occupancy windows* for that section actually overlap in time, or are
scheduled close enough that a modest delay would create one.

### 3. Temporal conflict detection

For each shared section, `overlap_minutes`/`separation_minutes` compare the source
train's window (built from its already-fused Phase 5/6/7 final ETA — see `resolver.
build_source_windows`) against the candidate's window (its static schedule, shifted by
its own currently-known delay — `resolver.build_schedule_windows`):

- Overlap > 0 → `SHARED_SECTION_OVERLAP`, severity scales with overlap magnitude.
- No overlap but separation ≤ `NETWORK_MIN_SAFE_SEPARATION_MINUTES` → `INSUFFICIENT_SEPARATION`
  (a real, lower-confidence signal: "a bit more delay and these two would overlap").
- Otherwise: no conflict at all.

**A subtlety worth documenting**: the very first upcoming section's occupancy window is
anchored to the train's *latest actual observation* (its most recent `TrainEvent.
timestamp`), not to "now" (when someone happens to call the API) — using "now" would
silently balloon the window across however long it's been since that train last reported
in, which is exactly backwards for a decision-support tool. If that event is old enough
to imply an implausible in-section duration (more than 3× the section's own scheduled
running time — realistic when demo/seed event timestamps age across real calendar days),
the window is clamped to the section's scheduled running time ending at the correctly
`journey_date`-anchored exit time, rather than trusting a stale timestamp.

### 4. Delay propagation model

`app/network/propagation.py` defines `NetworkPropagationModel` (the interface) and
`DeterministicPropagationModel` (the only implementation for now — explicitly not a GNN):

```
estimated_delay = source_delay_minutes × overlap_factor × decay^depth
```

- `overlap_factor` — 1.0 at ≥20 minutes of actual overlap (scaling down linearly below
  that), or up to 0.4× as strong for an `INSUFFICIENT_SEPARATION` case (weaker because
  it's inherently less certain — confidence is always LOW for that branch).
- `decay^depth` — depth 0 is a direct hit on an immediately-conflicting train; depth 1 is
  that train's own downstream trains, found via the same shared-section search, and so on
  up to `NETWORK_MAX_PROPAGATION_DEPTH`. Propagation stops when depth is exceeded, the
  estimate falls below `NETWORK_MIN_PROPAGATED_DELAY_MINUTES`, or there's no more overlap.

Swapping this for a learned model later (gradient boosting, a temporal GNN, ...) means
implementing the same `NetworkPropagationModel` interface and changing which instance
`app/network/impact.py` constructs — nothing about the graph, conflict detection, or API
layer would need to change (module 47).

### 5. Impact scoring & hotspots

`app/network/scoring.py`'s `train_impact_score` is a transparent, additive 0-100 score
(source delay, breadth of impact across trains/sections/stations, worst overlap, depth
reached — each capped so no single factor dominates), bucketed into LOW/MEDIUM/HIGH/
CRITICAL via configurable thresholds. `hotspot_score` scores a single station/section by
how much predicted impact converges there (affected-train count, conflict count, delay) —
independent of any one train's own score. **Both are RAILCAST's own analytical scores,
not an official railway risk classification.**

### 6. Predictive alerts & deduplication

A `HIGH_NETWORK_IMPACT` alert is only created once a train's score crosses
`NETWORK_ALERT_THRESHOLD`; `NETWORK_CONFLICT` alerts are created per HIGH/CRITICAL
conflict. Both use the existing `Alert` model (no new table) with a stable fingerprint
stored in `alert_metadata["fingerprint"]` — `{alert_type}:{train_a}:{train_b}:
{section_code}:{hour_bucket}` for conflicts, `HIGH_NETWORK_IMPACT:{train_number}:
{hour_bucket}` for the train-level alert — so re-running analysis within the same hour
never creates duplicates (module 27). The two dedup checks are independent: a train
already alerted on this hour can still get a *new* conflict alert if a genuinely new
conflict appears.

### 7. Confidence & uncertainty

Every `AffectedTrain`/`NetworkConflict` carries an `impact_confidence`/`directional_
confidence` (HIGH/MEDIUM/LOW) — never a fabricated numeric interval where the underlying
evidence doesn't support one (module 29). A low-confidence source ETA (Phase 7) naturally
produces a wider/less certain source window, which cannot manufacture a HIGH-confidence
downstream impact — confidence doesn't inflate as it propagates.

### 8. Limitations

- **Two different timing models by design**: the source train's window uses the full
  Phase 5/6/7 engine; candidate trains use their static schedule + their own latest known
  delay only (no full ETA fusion) — running the complete ML pipeline for every candidate
  in a graph walk would be prohibitively expensive for a bounded, real-time-ish analysis.
  This is a deliberate accuracy/cost trade-off, not an oversight.
- **`analysis_status: LIMITED`** is returned (never fabricated relationships) whenever
  route/section data is insufficient for a train (module 37) — e.g. no resolvable
  upcoming section.
- **Performance in this dev environment**: every `/network/*` endpoint's underlying
  analysis calls the Phase 5/6/7 ETA engine per delayed train, each of which tries a Redis
  connection with its own retry/timeout; without Redis running locally, `/network/
  overview` can take tens of seconds in this sample environment purely from repeated
  connection-timeout overhead, not from the graph algorithm itself (which is bounded and
  cheap — see "Graph performance" below). This resolves once Redis is available.
- Distances/running times/timetables remain the same prototype/sample values documented
  since Phase 2 — not official Indian Railways data.

### 9. Graph performance & bounding

- Candidate discovery (`graph.find_candidate_trains`) is always scoped to a specific,
  small set of `section_ids` — never a full scan of `trains`/`train_routes` (modules 4, 33).
- `NETWORK_MAX_TRAINS_PER_ANALYSIS` bounds both single-train and network-wide analysis;
  `NETWORK_MAX_PROPAGATION_DEPTH` bounds the BFS depth; `NETWORK_ANALYSIS_HORIZON_MINUTES`
  bounds how far forward propagation is considered (module 34).
- `get_network_snapshot` caches a full network-wide analysis result in Redis for 20
  seconds (module 32), shared by `/overview`, `/affected-trains`, `/conflicts`,
  `/hotspots`, and `/timeline` — a burst of dashboard requests triggers one graph
  analysis, not five. (With Redis unavailable, as in this dev environment, this
  gracefully degrades to recomputing every time — slower, never broken.)
- Tested against the seeded 7-train / 10-section network (see "Performance results" in
  the Phase 8 completion report) — correctness was prioritized over synthetic
  100/500-train load testing in this phase; the bounding parameters above are what keep a
  larger network from becoming a full-table-scan problem, not an unbounded BFS.

## Real-Time Streaming & Continuous Prediction Pipeline (Phase 9)

Phase 9 converts RAILCAST from a request-driven prediction engine into an asynchronous, **event-driven continuous prediction system**.

The frontend never initiates prediction calculations. When a client visits a train or station view, it connects to a push-based WebSocket or reads the latest cached state. Predictions are continually recalculated in the background as new real-time railway events land.

### 1. Architecture

```
        REAL RAILWAY PROVIDER / SIMULATOR
                        │
                        ▼
                 DATA INGESTION
                        │
                        ▼
               REDIS STREAM (Events)
             railcast:train-events
                        │
                        ▼
            PREDICTION WORKER GROUP
           railcast-prediction-workers
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
      STATE         PREDICTION       NETWORK
     UPDATER         PIPELINE        IMPACT
   (Dedup & OOO)   (Debounce 5s)   (Cascade)
        │               │               │
        └───────────────┼───────────────┘
                        │
                        ▼
            REDIS STREAM (Predictions)
           railcast:prediction-updates
                        │
                        ▼
               WEBSOCKET BROADCAST
        /ws/trains, /ws/stations, /ws/network
                        │
                        ▼
                 FRONTEND CLIENTS
```

### 2. Core Components (`app/streaming/`)

1. **`schemas.py`**: Canonical `NormalizedTrainEvent`, `StreamEventType`, SHA256 deterministic event fingerprinting, `PredictionUpdatePayload`, and `WebSocketEnvelope`.
2. **`publisher.py` (`EventPublisher`)**: Non-blocking publishing to Redis streams with fail-fast timeouts and offline degradation.
3. **`state.py` (`TrainStateUpdater`)**:
   - **Out-of-Order Handling**: If an event arrives with `timestamp < active_state.last_event_time`, it is safely recorded in the historical database (`TrainEvent`), but operational state is **never regressed**.
   - **Idempotency & Deduplication**: Fast in-memory LRU fingerprint cache prevents reprocessing identical telemetry ticks.
4. **`metrics.py` (`StreamingMetricsTracker`)**: Thread-safe observability tracking events ingested, debounced events, calculation latencies (average, p50, p95, p99 percentiles), duplicate counts, and worker status.
5. **`websocket.py` (`WebSocketConnectionManager`)**: Topic-based subscriber routing (`train:{number}`, `station:{code}`, `network`, `all`) with per-connection bounded queues (`WEBSOCKET_MAX_QUEUE_SIZE = 100`) to isolate slow consumers.
6. **`pipeline.py` (`PredictionStreamingPipeline`)**:
   - **Prediction Debouncing**: Gated by `PREDICTION_DEBOUNCE_SECONDS = 5.0` to filter high-frequency GPS ticks while still streaming map coordinates.
   - **Real-Time Recalculation**: Computes baseline ETA + ML residual with uncertainty intervals (`[lower_eta, upper_eta]`) and confidence score (`0-100`).
   - **Network Delay Cascade Triggers**: Evaluated on delay jumps ($\ge 2.0$ min), spatial jumps ($\ge 5.0$ km), or station/section milestones with rate limiting ($30$s).
7. **`consumer.py` (`StreamingConsumer`)**: Consumer group loop using Redis Streams `XREADGROUP` (`railcast-prediction-workers`) with automatic ACK on success and dead-lettering for poison pills.
8. **`worker.py`**: Standalone runnable background worker (`python -m app.streaming.worker`).

### 3. WebSocket API Contracts

- `GET /ws/trains/{train_number}`: Real-time telemetry and upcoming station predictions for a specific train.
- `GET /ws/stations/{station_code}`: Station arrivals, departures, and delay updates.
- `GET /ws/network`: Network-level delay cascade alerts, congestion hotspots, and shared-section conflicts.
- `GET /ws/updates`: Global railway network feed (all events).

#### WebSocket Message Envelope Structure
```json
{
  "topic": "train:12002",
  "event_type": "prediction_update",
  "data": {
    "train_number": "12002",
    "station_code": "AGC",
    "scheduled_arrival": "2026-03-10T08:32:00Z",
    "baseline_arrival": "2026-03-10T08:45:00Z",
    "final_eta": "2026-03-10T08:49:00Z",
    "delay_minutes": 17.0,
    "uncertainty_lower": "2026-03-10T08:35:00Z",
    "uncertainty_upper": "2026-03-10T08:50:00Z",
    "confidence_score": 100,
    "network_impact_score": 64,
    "calculation_latency_ms": 158.4,
    "is_debounced": false
  },
  "timestamp": "2026-03-10T08:30:00Z"
}
```

### 4. Observability & System Status

- `GET /api/v1/system/streaming/status`: Returns current worker status, stream queue identifiers, debounce counters, calculation latency percentiles (avg, p50, p95, p99), and active WebSocket connections.

### 5. Benchmark & Simulation Scripts

- `python -m scripts.simulate_streaming`: Replays a realistic train journey (Bhopal Shatabdi `12002`) across NDLS -> MTJ -> AGC showing departure, cruising GPS ticks, debounce filtering, signal congestion delay jump, network cascade triggers, and recovery.
- `python -m scripts.benchmark_streaming`: Load-tests the pipeline with 50 high-frequency events, verifying sub-5-second processing, out-of-order handling, and percentiles.
- `python -m scripts.seed --reset`: Resets events and predictions back to clean seed baseline.

---

## Productionization, Monitoring, Retraining & MLOps (Phase 10)

Phase 10 hardens RAILCAST into an enterprise-grade, highly available, and observable production platform with automated model lifecycle governance.

### 1. High-Level Architecture

```
                    EXTERNAL CALLERS / PROMETHEUS SCRAPERS
                                     │
                                     ▼
                      API GATEWAY / MIDDLEWARE LAYER
                     ┌──────────────────────────────┐
                     │ • Correlation ID (X-Request) │
                     │ • Rate Limiting (600 req/min)│
                     │ • Admin Key Verification     │
                     └──────────────┬───────────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                    ▼
        SYSTEM HEALTH        MONITORING & DRIFT      MLOPS LIFECYCLE
       ┌──────────────┐     ┌──────────────────┐   ┌──────────────────┐
       │ • /health    │     │ • Data Quality   │   │ • Model Catalog  │
       │ • /readiness │     │ • PSI / KS Drift │   │ • Quality Gate   │
       │ • /liveness  │     │ • Prometheus     │   │ • Safe Promotion │
       └──────────────┘     │   /metrics       │   │ • Instant Rollbk │
                            └──────────────────┘   └──────────────────┘
                                     │                       │
                                     ▼                       ▼
                              OPERATIONAL ALERTS       MODEL REGISTRY
                             (SHA-256 Deduplicated)  (active_model.json)
```

### 2. Monitoring & Health Endpoints

- `GET /api/v1/system/health`: Deep system health check reporting operational status, latency, and details for PostgreSQL, Redis, ML Model, and Data Providers.
- `GET /api/v1/system/readiness`: Kubernetes readiness probe (200 OK if PostgreSQL and Model Registry are operational; 503 if degraded).
- `GET /api/v1/system/liveness`: Kubernetes liveness probe (200 OK lightweight process check).
- `GET /metrics`: Standard Prometheus text-format metrics exporter tracking HTTP requests, database latency, streaming lag, prediction latency, and data quality scores.
- `GET /api/v1/system/data-quality`: Comprehensive telemetry data quality score (0–100) evaluating Completeness, Freshness, Validity, and Consistency across all incoming train events.
- `GET /api/v1/system/drift`: Statistical feature data drift (Population Stability Index and Kolmogorov-Smirnov 2-sample tests) and model degradation tracking.
- `GET /api/v1/system/alerts`: Active operational alerts with SHA-256 fingerprint deduplication (`DATA_QUALITY_LOW`, `PROVIDER_DOWN`, `STREAM_LAG_HIGH`, `MODEL_DRIFT`, `DATA_DRIFT`, `ETA_ERROR_HIGH`, `UNCERTAINTY_MISCALIBRATED`, `MODEL_UNAVAILABLE`).

### 3. MLOps Model Lifecycle & Safe Promotion

- `GET /api/v1/system/models`: Catalog of all registered models, their metadata, test MAE, baseline MAE, improvement %, and lifecycle status (`CANDIDATE`, `VALIDATED`, `PRODUCTION`, `REJECTED`, `ARCHIVED`).
- `GET /api/v1/system/models/{version}/metrics`: Detailed evaluation on actual arrivals, horizon breakdown (15m, 30m, 60m, 120m+), train type/source breakdowns, and uncertainty calibration.
- `POST /api/v1/system/models/{version}/promote`: Safely promotes a candidate model to `PRODUCTION` if it passes the strict Quality Gate. Updates `active_model.json` and automatically triggers hot memory reload. Requires `X-Admin-API-Key`.
- `POST /api/v1/system/models/rollback`: Reverts active production model pointer to a previous version and hot-reloads memory cache without downtime. Requires `X-Admin-API-Key`.
- `GET /api/v1/system/audit-log`: Persistent JSONL audit log of all administrative actions, model promotions, and rollbacks (`data/audit_log.jsonl`).

### 4. Quality Gate Criteria

Candidate models must satisfy all 5 criteria to achieve `VALIDATED` status and qualify for promotion:
1. **Model Exists**: Model artifacts (`booster.json`, `encoder.json`, `metadata.json`) present in registry.
2. **Beats Deterministic Baseline**: `candidate_mae < baseline_mae`.
3. **Beats Current Active Model**: `candidate_mae < active_mae` (if active model is already running).
4. **Minimum Relative Improvement**: Relative MAE improvement $\ge 2.0\%$ (`MODEL_MIN_IMPROVEMENT_PERCENT`).
5. **Sample Significance**: At least 30 held-out test arrival observations (`MIN_EVALUATION_SAMPLES`).

### 5. Retraining Pipeline CLI

Run reproducible model retraining with chronological splitting, held-out evaluation, and optional promotion:
```bash
# Train candidate model
python -m scripts.retrain_eta_model --version xgb-residual-v2

# Train and automatically promote if Quality Gate passes
python -m scripts.retrain_eta_model --version xgb-residual-v2 --promote
```

### 6. Production Hardening & Runbooks

- **Multi-Stage Dockerfile**: Secure minimal image running as non-root user `railcast` with built-in healthchecks.
- **Docker Compose**: Production composition with dependency health checks, Redis Streams worker, and auto-restart policies.
- **CI/CD Pipeline**: GitHub Actions workflow (`.github/workflows/ci.yml`) automating linting, type-checking, pytest execution (268 tests), seed verification, and Docker builds.
- **Operations Runbook**: [`docs/operations.md`](docs/operations.md) covering deployment, health inspection, incident response, failure degradation matrix, and backup/restore.
- **Model Training Runbook**: [`docs/model-training.md`](docs/model-training.md) covering reproducible training, dataset versioning, Quality Gates, and emergency rollbacks.


