"""Standalone entrypoint for running the continuous prediction worker."""

import asyncio
import logging
import signal
import sys

from app.streaming.consumer import StreamingConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("railcast.streaming.worker")


async def main() -> None:
    consumer = StreamingConsumer()

    loop = asyncio.get_running_loop()

    def handle_signal() -> None:
        logger.info("Shutdown signal received; stopping consumer...")
        consumer.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Signal handlers not implemented on Windows event loops
            pass

    logger.info("Starting RAILCAST Continuous Prediction Worker...")
    try:
        await consumer.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        consumer.stop()
        logger.info("Worker interrupted by user.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
