"""Simulation script for Phase 9 continuous real-time streaming and prediction updates.

Replays realistic movement and delay events for a train across its route, demonstrating:
1. Event ingestion into Redis Streams and DB
2. Continuous baseline + ML ETA prediction recalculation
3. Uncertainty interval progression as train moves closer
4. Debounce filtering on rapid GPS ticks
5. Network cascade analysis trigger when delay jumps

Run with:
    python -m scripts.simulate_streaming
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import sys
import time

from app.core.logging import setup_logging
from app.db.session import AsyncSessionLocal
from app.streaming.metrics import streaming_metrics
from app.streaming.pipeline import streaming_pipeline
from app.streaming.publisher import event_publisher
from app.streaming.schemas import NormalizedTrainEvent, StreamEventType

setup_logging()
logger = logging.getLogger("railcast.simulate_streaming")


async def run_simulation() -> None:
    train_number = "12002"  # New Delhi - Bhopal Shatabdi Express
    base_time = datetime.now(timezone.utc)

    # Step-by-step movement scenario
    scenario_events = [
        # 1. Train departs New Delhi on time
        {
            "event_type": StreamEventType.STATION_DEPARTURE,
            "current_station_code": "NDLS",
            "next_station_code": "MTJ",
            "delay_minutes": 0.0,
            "speed_kmh": 20.0,
            "current_lat": 28.6432,
            "current_lng": 77.2196,
            "delay_offset_seconds": 0,
            "description": "Departed NDLS on time",
        },
        # 2. GPS tick cruising on NDLS-MTJ
        {
            "event_type": StreamEventType.GPS_UPDATE,
            "current_station_code": None,
            "next_station_code": "MTJ",
            "delay_minutes": 0.0,
            "speed_kmh": 125.0,
            "current_lat": 28.1000,
            "current_lng": 77.4500,
            "delay_offset_seconds": 6,  # > 5s -> will trigger prediction
            "description": "Cruising at 125 km/h towards MTJ",
        },
        # 3. Rapid GPS tick (within 2 seconds -> should be debounced)
        {
            "event_type": StreamEventType.GPS_UPDATE,
            "current_station_code": None,
            "next_station_code": "MTJ",
            "delay_minutes": 0.0,
            "speed_kmh": 124.0,
            "current_lat": 28.0800,
            "current_lng": 77.4600,
            "delay_offset_seconds": 2,  # < 5s -> DEBOUNCED
            "description": "Rapid GPS tick (expecting debounce)",
        },
        # 4. Signal slowdown approaching MTJ
        {
            "event_type": StreamEventType.SPEED_RESTRICTION,
            "current_station_code": None,
            "next_station_code": "MTJ",
            "delay_minutes": 8.0,
            "speed_kmh": 40.0,
            "current_lat": 27.6000,
            "current_lng": 77.6200,
            "delay_offset_seconds": 6,
            "description": "Signal clearance restriction; delay increased to +8m",
        },
        # 5. Station Arrival at MTJ
        {
            "event_type": StreamEventType.STATION_ARRIVAL,
            "current_station_code": "MTJ",
            "next_station_code": "AGC",
            "delay_minutes": 9.0,
            "speed_kmh": 0.0,
            "current_lat": 27.4924,
            "current_lng": 77.6737,
            "delay_offset_seconds": 6,
            "description": "Arrived at Mathura Junction (+9m delay)",
        },
        # 6. Sudden major delay jump on MTJ-AGC section (Triggers Network Cascade)
        {
            "event_type": StreamEventType.SECTION_ENTRY,
            "current_station_code": "MTJ",
            "next_station_code": "AGC",
            "delay_minutes": 26.0,  # Jump +17 min -> Network Recalc Triggered!
            "speed_kmh": 15.0,
            "current_lat": 27.3500,
            "current_lng": 77.8000,
            "delay_offset_seconds": 32,  # > 30s -> network trigger allowed
            "description": "Section congestion on MTJ-AGC; delay jumps to +26m (Network Trigger!)",
        },
        # 7. Speed recovery on approach to Agra Cantt
        {
            "event_type": StreamEventType.GPS_UPDATE,
            "current_station_code": None,
            "next_station_code": "AGC",
            "delay_minutes": 22.0,
            "speed_kmh": 110.0,
            "current_lat": 27.2000,
            "current_lng": 77.9800,
            "delay_offset_seconds": 6,
            "description": "Signal cleared, speed recovered to 110 km/h; delay recovered to +22m",
        },
    ]

    print("\n" + "=" * 80)
    print(f" RAILCAST REAL-TIME STREAMING SIMULATION: Train {train_number}")
    print("=" * 80)

    sim_time = base_time

    async with AsyncSessionLocal() as session:
        for idx, step in enumerate(scenario_events, 1):
            sim_time += timedelta(seconds=step["delay_offset_seconds"])

            event = NormalizedTrainEvent(
                event_type=step["event_type"],
                train_number=train_number,
                timestamp=sim_time,
                current_station_code=step["current_station_code"],
                next_station_code=step["next_station_code"],
                delay_minutes=step["delay_minutes"],
                speed_kmh=step["speed_kmh"],
                current_lat=step["current_lat"],
                current_lng=step["current_lng"],
                source="simulator",
                raw_data={"scenario_step": idx, "desc": step["description"]},
            )

            # Publish to Redis stream
            msg_id = await event_publisher.publish_event(event)

            # Process through continuous prediction pipeline
            start_tick = time.perf_counter()
            predictions = await streaming_pipeline.process_stream_event(session, event)
            tick_latency = (time.perf_counter() - start_tick) * 1000.0

            print(f"\n[Step {idx}/{len(scenario_events)}] {step['description']}")
            print(f"  • Event: {event.event_type.value} | Delay: {event.delay_minutes}m | Speed: {event.speed_kmh} km/h")
            print(f"  • Stream Msg ID: {msg_id or 'offline'} | Pipeline Latency: {tick_latency:.1f} ms")

            if predictions:
                next_pred = predictions[0]
                unc = ""
                if next_pred.uncertainty_lower and next_pred.uncertainty_upper:
                    lower_fmt = next_pred.uncertainty_lower.strftime("%H:%M")
                    upper_fmt = next_pred.uncertainty_upper.strftime("%H:%M")
                    unc = f" [Range: {lower_fmt} - {upper_fmt}]"

                final_fmt = next_pred.final_eta.strftime("%H:%M") if next_pred.final_eta else "N/A"
                print(f"  -> PREDICTION RECALCULATED for {next_pred.station_code}:")
                print(f"     ETA: {final_fmt}{unc} | Delay: {next_pred.delay_minutes:.1f}m | Confidence: {next_pred.confidence_score}/100")
                if next_pred.network_impact_score:
                    print(f"     * Network Impact Score: {next_pred.network_impact_score}/100")
            else:
                print("  -> Prediction recalculation skipped (Debounced or Out-of-Order)")

            # Sleep slightly between steps
            await asyncio.sleep(0.2)

    print("\n" + "=" * 80)
    print(" SIMULATION SUMMARY & PIPELINE METRICS")
    print("=" * 80)
    metrics = streaming_metrics.get_metrics()
    for k, v in metrics.items():
        if k == "latency_ms":
            print(f"  • Latency percentiles: avg={v['avg']}ms, p50={v['p50']}ms, p95={v['p95']}ms, p99={v['p99']}ms")
        else:
            print(f"  • {k}: {v}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_simulation())
