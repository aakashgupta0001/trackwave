# RAILCAST Platform Architecture & System Design Document (Phases 1–11)

**System Name:** RAILCAST — Real-Time AI-Powered ETA & Railway Network Intelligence Platform  
**Target Domain:** Indian Railways Network & Real-Time Operational Intelligence  
**Version:** 1.11.0 (Phase 11 Consolidated Architecture)  

---

## 1. Executive Architecture Overview

RAILCAST is an event-driven, hybrid deterministic-statistical intelligence platform designed to ingest raw or simulated railway telemetry, maintain real-time spatial and operational train states, compute robust ETAs with calibrated uncertainty intervals and confidence scores, evaluate network-wide delay propagation and section conflicts, and broadcast live updates to operators and passenger interfaces via WebSockets and REST APIs.

### 1.1 Architectural Principles
1. **Deterministic Foundation:** Deterministic physics-based baseline ETA is the primary invariant. The ML layer never replaces the baseline; it predicts residuals. If the ML layer degrades or fails, the system automatically falls back to baseline ETA without service interruption.
2. **Absolute Data Status Honesty:** Every data point and API response carries explicit source and status metadata (`SIMULATED`, `LIVE`, `STALE`, `UNAVAILABLE`). The system never claims simulated data is live real-world telemetry.
3. **Event-Driven Continuous Processing:** Telemetry events flow through Redis Streams (`railcast:train-events`), updating in-memory operational states and triggering debounced recalculations.
4. **Predictive vs Operational Demarcation:** All network intelligence (conflicts, propagation, hotspots) is strictly classified as predictive advisory intelligence, never as automated dispatching or safety-critical signalling decisions.

---

## 2. End-to-End System Flow Architecture

```mermaid
flowchart TD
    subgraph S1["Data Ingestion & Normalization Layer"]
        P1["NTES / RTIS Provider"] --> N1["Provider Normalizer"]
        P2["RailRadar Provider"] --> N1
        P3["Scenario Simulator (Demo)"] --> N1
        N1 --> D1["Data Status Tagging\n(SIMULATED / LIVE / STALE)"]
    end

    subgraph S2["Event Streaming & State Layer"]
        D1 --> RS1["Redis Stream: railcast:train-events"]
        RS1 --> CW1["Stream Consumer Worker\n(XREADGROUP)"]
        CW1 --> U1["TrainStateUpdater\n(Deduplication & Out-of-Order Check)"]
        U1 --> DB1[("PostgreSQL\nDigital Twin DB")]
        U1 --> AS1["In-Memory Active State"]
    end

    subgraph S3["Hybrid ETA Intelligence Engine"]
        AS1 --> B1["Phase 5: Deterministic Baseline Engine\n(Speed Hierarchy, Halts, Recovery)"]
        B1 --> ML1["Phase 6: XGBoost ML Residual Predictor\n(Feature Engineering Context)"]
        ML1 --> F1["Phase 6: ETA Fusion Layer\n(Final ETA = Baseline + Clamped Residual)"]
        F1 --> UNC1["Phase 7: Uncertainty Estimator\n(Residual Quantile Conformal Bands)"]
        UNC1 --> CONF1["Phase 7: Confidence Scorer\n(0-100 Score & Level)"]
        CONF1 --> SHAP1["Phase 7: TreeSHAP Explainability\n(Top Contributing Factors)"]
    end

    subgraph S4["Network Intelligence & Cascade Layer"]
        F1 --> TRIG1{"Delay Delta > Threshold\nor Junction Arrival?"}
        TRIG1 -- Yes --> NET1["Phase 8: Railway Graph Traversal"]
        NET1 --> CONF2["Shared-Section Headway Conflicts"]
        CONF2 --> PROP1["Cascade Propagation Engine"]
        PROP2["Hotspot Aggregator"] <-- PROP1
        PROP1 --> SCO1["Network Impact Score (0-100)"]
        SCO1 --> AL1["Predictive Network Alerts"]
    end

    subgraph S5["Dissemination & Presentation Layer"]
        F1 --> RS2["Redis Stream: railcast:prediction-updates"]
        RS2 --> WSM["WebSocket Manager\n(/ws/trains, /ws/stations, /ws/network)"]
        AL1 --> WSM
        AS1 --> WSM
        WSM --> FE["React / Vite Frontend\n(Tailwind, Lucide, WebSockets)"]
        DB1 --> REST["FastAPI REST APIs\n(/api/v1/live, /api/v1/eta, /api/v1/network)"]
        REST --> FE
    end

    subgraph S6["MLOps, Observability & Retraining"]
        DQ1["Data Quality Tracker (0-100)"] --> REST
        DR1["Feature / Model Drift Engine"] --> REST
        QG1["Quality Gate & Retraining Pipeline"] --> ML1
        PR1["Prometheus Metrics Exporter (/metrics)"]
    end
```

---

## 3. Failure Modes & Degradation Hierarchy

The RAILCAST system enforces strict graceful degradation invariants across every layer:

```mermaid
flowchart TD
    A["Raw Telemetry Ingestion"] --> B{"Data Provider Reachable?"}
    B -- Yes --> C["Normalize and Tag LIVE / SIMULATED"]
    B -- No --> D["Tag STALE / UNAVAILABLE\nServe Cached / Baseline State"]
    
    C --> E{"Redis Reachable?"}
    E -- Yes --> F["Publish to Redis Stream & Stream Workers"]
    E -- No --> G["Bypass Stream: Direct In-Memory State & DB Sync"]
    
    F --> H{"ML Model Loaded & Valid?"}
    G --> H
    H -- Yes --> I["Mode: ML_RESIDUAL\nFinal ETA = Baseline + ML Residual\nUncertainty & Confidence Full"]
    H -- No --> J["Mode: BASELINE_FALLBACK\nFinal ETA = Baseline ETA\nPredicted Residual = 0.0\nSafe Degraded Confidence"]
    
    I --> K{"Database Reachable?"}
    J --> K
    K -- Yes --> L["Readiness 200 OK\nFull Persistence"]
    K -- No --> M["Readiness 503 Service Unavailable\nLiveness 200 OK (Container Alive)"]
```

### Invariant Summary Table

| Subsystem Failure | Impact on System | Fallback Behavior | User / Client Indication |
|:---|:---|:---|:---|
| **External Data Provider Down** | Live GPS updates pause | ProviderManager fails over to secondary adapter or marks `UNAVAILABLE` | `provider_status: UNAVAILABLE`, `data_age_seconds` ticks up |
| **Redis Cache / Stream Down** | Stream buffering & caching disabled | Services fall back to direct DB sync; ETA calculations execute synchronously | Health reports `status: DEGRADED`, `components.redis: DOWN` |
| **ML Model Failure / Corrupted** | ML residual unavailable | ETA engine falls back to pure deterministic baseline engine | `prediction_mode: BASELINE_FALLBACK`, `final_eta == baseline_eta` |
| **Out-of-Order Telemetry Arrival** | Delayed or re-sent event | State updater logs and commits historical event to DB, but rejects state advancement | Current operational state preserved at newest timestamp |
| **Duplicate Event Arrival** | Redundant message | SHA-256 fingerprint deduplication discards second event in <0.01 ms | Operational state unaltered |
| **PostgreSQL Database Down** | Data mutations pause | Kubernetes readiness probe returns 503; liveness probe returns 200 | HTTP 503 Service Unavailable, frontend shows offline banner |

---

## 4. Phase-by-Phase Module Directory Structure

```
D:\RAILCAST\
├── backend/
│   ├── app/
│   │   ├── api/                    # REST API routes & middleware (Phase 3, 5, 8, 10, 11)
│   │   │   ├── middleware/         # Correlation ID & Rate Limiting
│   │   │   └── routes/             # trains, stations, live, eta, network, system, websocket
│   │   ├── cache/                  # Redis connection pool & helpers (Phase 1, 9)
│   │   ├── core/                   # Configuration & security (Phase 1, 10, 11)
│   │   ├── db/                     # SQLAlchemy async engine & migrations (Phase 1, 2)
│   │   ├── ml/                     # ML Residual Engine & Explainability (Phase 6, 7, 10)
│   │   │   ├── features.py         # 13 railway feature engineering transformations
│   │   │   ├── predictor.py        # XGBoost residual inference & lazy loading
│   │   │   ├── registry.py         # Model catalog & atomic active_model.json pointer
│   │   │   ├── uncertainty.py      # Quantile-based residual interval estimation
│   │   │   └── explain.py          # TreeSHAP factor contribution calculation
│   │   ├── models/                 # SQLAlchemy digital twin domain entities (Phase 2)
│   │   ├── monitoring/             # Health, Data Quality, Drift & MLOps (Phase 10)
│   │   ├── network/                # Railway graph & delay cascade engine (Phase 8)
│   │   │   ├── graph.py            # Bounded spatial-temporal railway network graph
│   │   │   ├── conflict.py         # Shared-section headway conflict detector
│   │   │   ├── propagation.py      # Delay cascade propagation algorithm
│   │   │   └── impact.py           # 0-100 Network Impact scoring & hotspot aggregator
│   │   ├── providers/              # Real railway provider adapters & manager (Phase 4)
│   │   ├── repositories/           # Database access layer (Phase 2, 8, 10)
│   │   ├── schemas/                # Standardized Pydantic schemas (Phase 2, 3, 5-11)
│   │   ├── services/               # Core business services (Phase 3, 5, 6, 7)
│   │   │   ├── baseline_eta_service.py # Deterministic section-aware baseline engine
│   │   │   ├── eta_fusion_service.py   # Baseline + ML Residual fusion orchestrator
│   │   │   └── confidence_service.py   # Multi-factor confidence score engine
│   │   └── streaming/              # Event-driven real-time pipeline (Phase 9)
│   │       ├── consumer.py         # Redis Stream worker consumer group
│   │       ├── pipeline.py         # Continuous prediction orchestrator
│   │       ├── state.py            # Train state updater & dedup
│   │       └── websocket.py        # Multiplexed WebSocket manager
│   ├── docs/                       # Architectural & operational documentation
│   ├── scripts/                    # CLI scripts (seed, retrain, run_demo, benchmark)
│   └── tests/                      # 275+ automated pytest tests
└── src/                            # React 19 + TypeScript + Tailwind CSS Frontend
    ├── lib/                        # api.ts (client contracts) & websocket.ts (real-time hook)
    ├── pages/                      # Operations, Intelligence & System dashboard pages
    └── components/                 # Reusable UI widgets, badges, cards, and navigation
```

---

## 5. Standardized API Synonym Contract (Phase 11)

All endpoints across Phase 1–10 adhere to unified synonym fields preserving 100% backward compatibility:

| Standard Field | Canonical Meaning | Synonyms / Aliases Supported | Target Endpoints |
|:---|:---|:---|:---|
| `scheduled_eta` | Timetable scheduled arrival | `scheduled_arrival` | `/api/v1/eta/*` |
| `baseline_eta` | Deterministic baseline ETA | `baseline_eta` | `/api/v1/eta/*` |
| `ml_residual_minutes`| Clamped ML correction in minutes | `predicted_residual_minutes` | `/api/v1/eta/*` |
| `final_eta` | Fused prediction | `final_eta` | `/api/v1/eta/*` |
| `lower_bound` | Lower uncertainty interval (80%) | `uncertainty.lower_eta` | `/api/v1/eta/*` |
| `upper_bound` | Upper uncertainty interval (80%) | `uncertainty.upper_eta` | `/api/v1/eta/*` |
| `confidence_score` | Calibrated confidence (0–100) | `confidence.score` | `/api/v1/eta/*` |
| `confidence_level` | Categorical confidence level | `confidence.level` (`HIGH`, `MEDIUM`, `LOW`, `FALLBACK`) | `/api/v1/eta/*` |
| `status` / `provider_status` | Honesty data classification | `data_status`, `data_source` | `/api/v1/live/*`, `/api/v1/eta/*` |
| `data_age_seconds` | Elapsed seconds since telemetry retrieval | `data_age_seconds` | `/api/v1/live/*`, `/api/v1/eta/*` |
| `prediction_timestamp`| Generation timestamp of prediction | `generated_at` | `/api/v1/eta/*` |
