import asyncio
import logging
from app.worker.queue import run_inmem_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Worker __main__ starting in-mem loop (Ctrl+C to stop)")
    stop = asyncio.Event()
    try:
        await run_inmem_worker(stop)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker stopped")

if __name__ == "__main__":
    asyncio.run(main())
