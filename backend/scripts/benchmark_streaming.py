"""Benchmark load test script for RAILCAST continuous prediction streaming pipeline.

Measures:
- Stream event ingestion throughput (events/sec)
- Debounce filter effectiveness
- End-to-end pipeline execution latency percentiles (p50, p95, p99)
- Out-of-order event resilience under high frequency

Run with:
    python -m scripts.benchmark_streaming
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time

from app.core.logging import setup_logging
from app.db.session import AsyncSessionLocal
from app.streaming.metrics import streaming_metrics
from app.streaming.pipeline import streaming_pipeline
from app.streaming.schemas import NormalizedTrainEvent, StreamEventType

setup_logging()
logger = logging.getLogger("railcast.benchmark_streaming")


async def run_benchmark(num_events: int = 50) -> None:
    train_numbers = ["12002", "12951", "12615"]
    base_time = datetime.now(timezone.utc)

    print("\n" + "=" * 80)
    print(f" RAILCAST STREAMING PIPELINE BENCHMARK: {num_events} Events")
    print("=" * 80)

    events: list[NormalizedTrainEvent] = []
    for i in range(num_events):
        train_num = train_numbers[i % len(train_numbers)]
        # Mix of progressive events, rapid debounce candidates, and occasional out-of-order
        is_out_of_order = (i == 15 or i == 35)
        event_time = (
            base_time - timedelta(minutes=10)
            if is_out_of_order
            else base_time + timedelta(seconds=i * 2)  # Some within 5s debounce window
        )

        events.append(
            NormalizedTrainEvent(
                event_type=StreamEventType.GPS_UPDATE if i % 2 == 0 else StreamEventType.SPEED_RESTRICTION,
                train_number=train_num,
                timestamp=event_time,
                delay_minutes=float(i % 15),
                speed_kmh=80.0 + (i % 40),
                current_lat=28.0 - (i * 0.01),
                current_lng=77.5 + (i * 0.01),
                source="benchmark",
            )
        )

    latencies: list[float] = []
    total_start = time.perf_counter()

    async with AsyncSessionLocal() as session:
        for idx, event in enumerate(events):
            t0 = time.perf_counter()
            await streaming_pipeline.process_stream_event(session, event)
            dt = (time.perf_counter() - t0) * 1000.0
            latencies.append(dt)
            if (idx + 1) % 10 == 0:
                print(f"  Processed {idx + 1}/{num_events} events... (last latency: {dt:.2f}ms)")

    total_duration = time.perf_counter() - total_start
    throughput = len(events) / total_duration if total_duration > 0 else 0.0

    sorted_lats = sorted(latencies)
    avg_lat = sum(sorted_lats) / len(sorted_lats) if sorted_lats else 0.0
    p50 = sorted_lats[int(len(sorted_lats) * 0.50)] if sorted_lats else 0.0
    p95 = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0
    p99 = sorted_lats[int(len(sorted_lats) * 0.99)] if sorted_lats else 0.0

    print("\n" + "=" * 80)
    print(" BENCHMARK RESULTS")
    print("=" * 80)
    print(f"  • Total Events Processed   : {len(events)}")
    print(f"  • Total Wall Time Elapsed  : {total_duration:.2f} s")
    print(f"  • Pipeline Throughput      : {throughput:.2f} events/sec")
    print(f"  • Average Latency per Event: {avg_lat:.2f} ms")
    print(f"  • Median Latency (p50)     : {p50:.2f} ms")
    print(f"  • 95th Percentile (p95)    : {p95:.2f} ms")
    print(f"  • 99th Percentile (p99)    : {p99:.2f} ms")

    metrics = streaming_metrics.get_metrics()
    print("\n  Accumulated Pipeline Counters:")
    print(f"  • Ingested Total           : {metrics['events_ingested_total']}")
    print(f"  • Debounced Total          : {metrics['events_debounced_total']}")
    print(f"  • Predictions Calculated   : {metrics['predictions_calculated_total']}")
    print(f"  • Network Recalculations   : {metrics['network_recalcs_total']}")
    print(f"  • Out-of-Order Handled     : {metrics['events_out_of_order_total']}")
    print(f"  • Duplicates Filtered      : {metrics['events_duplicate_total']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
