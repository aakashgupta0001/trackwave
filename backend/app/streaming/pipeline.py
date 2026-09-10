"""Continuous prediction pipeline with debouncing, cache invalidation, and network triggers."""

import logging
import math
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.network.impact import analyze_train_impact
from app.services.eta_fusion_service import get_final_eta
from app.streaming.metrics import streaming_metrics
from app.streaming.publisher import event_publisher
from app.streaming.schemas import (
    NormalizedTrainEvent,
    PredictionUpdatePayload,
    StreamEventType,
)
from app.streaming.state import ActiveTrainState, train_state_updater
from app.streaming.websocket import ws_manager

logger = logging.getLogger(__name__)


def haversine_distance_km(
    lat1: float | None, lng1: float | None, lat2: float | None, lng2: float | None
) -> float:
    """Compute great-circle distance between two points in kilometers."""
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return 0.0
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


class PredictionStreamingPipeline:
    """Orchestrates ingestion, operational state updates, debounced ML predictions,

    network impact recalculations, and real-time WebSocket / Redis Stream broadcasts.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        # train_number -> monotonic timestamp of last prediction calculation
        self._last_prediction_time: dict[str, float] = {}
        # train_number -> monotonic timestamp of last network analysis
        self._last_network_recalc_time: dict[str, float] = {}
        # train_number -> latest known network impact score
        self._last_impact_score: dict[str, int] = {}

    def should_debounce_prediction(self, train_number: str) -> bool:
        """Check if incoming train event should be debounced for ML recalculation."""
        now = time.monotonic()
        last_time = self._last_prediction_time.get(train_number)
        if last_time is None:
            return False
        return (now - last_time) < self.settings.PREDICTION_DEBOUNCE_SECONDS

    def should_trigger_network_recalc(
        self, event: NormalizedTrainEvent, active_state: ActiveTrainState
    ) -> bool:
        """Evaluate whether network-level delay cascade analysis should run."""
        now = time.monotonic()
        last_time = self._last_network_recalc_time.get(event.train_number)

        # Rate limit network recalculation to avoid overloading graph walk
        if last_time is not None and (now - last_time) < self.settings.NETWORK_RECALC_MIN_INTERVAL_SECONDS:
            return False

        # First time seeing train
        if last_time is None:
            return True

        # Significant delay change trigger
        prev_delay = active_state.prev_delay_minutes or 0.0
        curr_delay = active_state.delay_minutes
        if abs(curr_delay - prev_delay) >= self.settings.NETWORK_RECALC_DELAY_CHANGE_MINUTES:
            return True

        # Significant position displacement trigger
        distance_km = haversine_distance_km(
            active_state.prev_lat,
            active_state.prev_lng,
            active_state.current_lat,
            active_state.current_lng,
        )
        if distance_km >= self.settings.NETWORK_RECALC_POSITION_CHANGE_KM:
            return True

        # Station or section transition triggers
        station_or_section_events = {
            StreamEventType.STATION_ARRIVAL,
            StreamEventType.STATION_DEPARTURE,
            StreamEventType.SECTION_ENTRY,
            StreamEventType.SECTION_EXIT,
        }
        if event.event_type in station_or_section_events:
            return True

        return False

    async def process_stream_event(
        self, session: AsyncSession, event: NormalizedTrainEvent
    ) -> list[PredictionUpdatePayload]:
        """Core end-to-end processing method for an incoming stream event.

        1. Safely updates train state and persists TrainEvent (never skipped).
        2. Broadcasts live train state.
        3. Checks debouncing; skips heavy ML if event arrived within debounce window.
        4. Calculates fresh baseline + ML residual ETA with uncertainty & confidence.
        5. Conditionally recalculates network cascade impact.
        6. Publishes prediction update to Redis stream and WebSockets.
        """
        streaming_metrics.record_event_ingested()

        # Step 1: State update & historical event DB persistence (handles out-of-order & dedup)
        is_new_state, active_state, db_event = await train_state_updater.process_event(
            session, event
        )

        if db_event is None and not is_new_state:
            # Duplicate event
            streaming_metrics.record_duplicate()
            return []

        if not is_new_state:
            # Out-of-order event (recorded in DB, but operational state did not advance)
            streaming_metrics.record_out_of_order()
            return []

        assert active_state is not None

        # Step 2: Always broadcast updated live train state to UI/map subscribers
        await ws_manager.broadcast_train_state(active_state)

        # Step 3: Debouncing check for ML ETA recalculation
        if self.should_debounce_prediction(event.train_number):
            logger.debug(
                "Prediction debounced for train %s (<%.1fs since last calculation)",
                event.train_number,
                self.settings.PREDICTION_DEBOUNCE_SECONDS,
            )
            streaming_metrics.record_event_debounced()
            return []

        self._last_prediction_time[event.train_number] = time.monotonic()

        # Step 4: ETA Recalculation (Baseline + ML Residual)
        start_calc = time.perf_counter()
        predictions_emitted: list[PredictionUpdatePayload] = []

        try:
            # use_cache=False ensures fresh prediction on the newly ingested event state.
            # include_explanations=False keeps streaming loop fast (<5s target).
            fused_eta = await get_final_eta(
                session,
                train_number=event.train_number,
                use_cache=False,
                include_explanations=False,
            )
            calc_latency_ms = round((time.perf_counter() - start_calc) * 1000.0, 2)
            streaming_metrics.record_prediction_calculated(calc_latency_ms)

            # Step 5: Network Cascade Recalculation (conditional)
            impact_score = self._last_impact_score.get(event.train_number, 0)
            if self.should_trigger_network_recalc(event, active_state):
                try:
                    impact_resp = await analyze_train_impact(session, event.train_number)
                    impact_score = impact_resp.network_impact_score
                    self._last_impact_score[event.train_number] = impact_score
                    self._last_network_recalc_time[event.train_number] = time.monotonic()
                    streaming_metrics.record_network_recalc()

                    if impact_resp.conflicts:
                        await ws_manager.broadcast_network_alert(
                            {
                                "train_number": event.train_number,
                                "network_impact_score": impact_score,
                                "conflict_count": len(impact_resp.conflicts),
                                "affected_trains": [a.train_number for a in impact_resp.affected_trains],
                            }
                        )
                except Exception as exc:
                    logger.warning("Network impact analysis failed for train %s: %s", event.train_number, exc)

            # Step 6: Formulate and publish prediction update payloads for upcoming stations
            for st in fused_eta.stations:
                payload = PredictionUpdatePayload(
                    train_number=event.train_number,
                    station_code=st.station_code,
                    scheduled_arrival=st.scheduled_arrival,
                    baseline_arrival=st.baseline_eta,
                    final_eta=st.final_eta,
                    delay_minutes=float(st.final_delay_minutes if st.final_delay_minutes is not None else st.delay_minutes or 0.0),
                    uncertainty_lower=st.uncertainty.lower_eta if st.uncertainty else None,
                    uncertainty_upper=st.uncertainty.upper_eta if st.uncertainty else None,
                    confidence_score=st.confidence.score if st.confidence else None,
                    network_impact_score=impact_score,
                    calculation_latency_ms=calc_latency_ms,
                    is_debounced=False,
                )

                # Emit to Redis Stream
                await event_publisher.publish_prediction(payload)

                # Broadcast to WebSockets
                await ws_manager.broadcast_prediction(payload)

                predictions_emitted.append(payload)

        except Exception as exc:
            logger.error("Continuous prediction pipeline error for train %s: %s", event.train_number, exc, exc_info=True)

        return predictions_emitted


# Shared singleton pipeline
streaming_pipeline = PredictionStreamingPipeline()
