# RAILCAST — Real-Time AI-Powered ETA & Railway Network Intelligence Platform

> **A production-grade, event-driven railway intelligence platform combining physics-based deterministic baseline ETA estimation, machine learning residual correction (XGBoost), quantile uncertainty intervals, TreeSHAP explainability, network-level delay cascade prediction, real-time streaming over Redis Streams & WebSockets, and a modern operator frontend.**

---

## 🚆 System Architecture Highlights

```
      Telemetry Ingestion (NTES / RTIS / Simulator)
                           │
                           ▼
               Normalizer & Data Status Tagging
                           │
                           ▼
          Redis Streams (railcast:train-events)
                           │
                           ▼
         Continuous Pipeline & Train State Updater
                           │
                           ▼
         Deterministic Section-Aware Baseline ETA
                           │
                           ▼
             ML Residual ETA Model (XGBoost)
                           │
                           ▼
        Uncertainty (Conformal) + Confidence + SHAP
                           │
                           ▼
      Network Delay Cascade & Shared-Section Conflicts
                           │
                           ▼
       Predictive Alerts & WebSocket Broadcaster
                           │
                           ▼
          React 19 Frontend & Operator Dashboard
```

### Key Capabilities
- **Deterministic Baseline Guarantee:** Section-aware physics and timetable model. If ML fails or degrades, the system falls back safely without downtime (`BASELINE_FALLBACK` mode).
- **Honest Data Attribution:** Every telemetry point explicitly tags status (`LIVE`, `SIMULATED`, `STALE`, `UNAVAILABLE`).
- **Explainable Predictions:** TreeSHAP factor contribution shows operators *why* an ETA changed.
- **Calibrated Uncertainty:** 80% prediction intervals bound likely arrival windows.
- **Network Intelligence:** Temporal graph traversal detects shared-section headway conflicts up to 3 hops ahead.
- **Real-Time Streaming:** Sub-millisecond in-memory routing, Redis Stream backpressure bounding (`MAXLEN ~ 10000`), and auto-reconnecting WebSockets.
- **MLOps & Observability:** Prometheus metrics (`/metrics`), Kubernetes health probes (`/readiness`, `/liveness`), 0–100 Data Quality Score, feature drift (PSI/KS), model quality gate, and atomic rollback.

---

## 📁 Repository Structure

- `backend/` — FastAPI application, ML engine, streaming pipeline, SQLAlchemy digital twin, and MLOps tooling.
  - `app/` — Application source code (api, core, ml, models, monitoring, network, providers, repositories, schemas, services, streaming).
  - `docs/` — Architecture documentation (`architecture.md`), benchmark reports (`benchmark_report.md`), operations, and ML training guides.
  - `scripts/` — CLI scripts (`run_demo.py`, `benchmark_system.py`, `seed.py`, `retrain_eta_model.py`).
  - `tests/` — Automated test suite (275+ tests covering Phases 1–11).
- `src/` — React 19 + TypeScript + Tailwind CSS operator dashboard.
  - `lib/api.ts` — Typed API client with Phase 1–11 contracts and IST timezone formatting.
  - `lib/websocket.ts` — Centralized WebSocket manager and `useWebSocketFeed` React hook.
  - `pages/` — Overview, Live Trains, Stations, Network Intelligence, Simulator, Performance (MLOps), and System Settings.

---

## 🚀 Quickstart

### Prerequisites
- **Python:** 3.12+
- **Node.js:** 20+ & npm
- **PostgreSQL:** 16+
- **Redis:** 7+ (Optional: Platform gracefully degrades to direct DB sync if offline)

### 1. Database Setup & Seed
```bash
cd backend
python -m scripts.seed --reset
```

### 2. Run Backend
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation available at: `http://localhost:8000/docs`

### 3. Run Frontend
```bash
npm install
npm run dev
```
Frontend dashboard available at: `http://localhost:5173`

---

## 🧪 Testing & Verification

### Run End-to-End Demo Scenario
Walks through an end-to-end 6-step train journey (T0 to T5) demonstrating telemetry ingestion, baseline ETA, ML correction, uncertainty bands, network cascade impact, predictive alerts, and WebSocket broadcasting:
```bash
cd backend
python -m scripts.run_demo
```

### Run Full Automated Test Suite (275+ Tests)
```bash
cd backend
pytest -v
```

### Run System Performance Benchmark (100 & 500 Trains)
```bash
cd backend
python -m scripts.benchmark_system
```
Benchmark report generated at: `backend/docs/benchmark_report.md`

### Build Frontend
```bash
npm run build
npm run lint
```

---

## 📜 License
Internal Railway Operations & Intelligence Prototype. All rights reserved.
