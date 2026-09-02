"""Queue — Fase 11.6 arq/celery stub with Redis fallback.

Provides:
 - enqueue(task_name, payload) -> job_id
 - get_job(job_id)
 - worker settings for `arq` if installed, otherwise asyncio in-memory worker for tests.

Tasks are defined in app.worker.tasks.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Try arq
try:
    from arq import create_pool as arq_create_pool
    from arq.connections import RedisSettings
    ARQ_AVAILABLE = True
except ImportError:
    ARQ_AVAILABLE = False

_inmem_jobs: Dict[str, Dict[str, Any]] = {}
_inmem_queue: asyncio.Queue = asyncio.Queue()


async def enqueue(task_name: str, payload: Dict[str, Any], queue_name: str = "default") -> str:
    """Enqueue task; returns job_id. Tries arq+Redis, falls back to in-memory."""
    job_id = str(uuid.uuid4())
    # Try arq redis
    if ARQ_AVAILABLE:
        try:
            from app.core.config import settings
            if settings.REDIS_URL:
                import redis.asyncio as redis  # type: ignore
                # arq pool
                redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
                pool = await arq_create_pool(redis_settings)
                job = await pool.enqueue_job(task_name, payload)
                await pool.close()
                # arq returns job with job_id
                if job:
                    return job.job_id
        except Exception as e:
            logger.warning(f"arq enqueue failed, fallback mem: {e}")

    # in-memory fallback
    _inmem_jobs[job_id] = {"task": task_name, "payload": payload, "status": "queued", "queue": queue_name}
    await _inmem_queue.put((job_id, task_name, payload))
    logger.info(f"Enqueued in-mem {task_name} -> {job_id}")
    return job_id


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return _inmem_jobs.get(job_id)


async def update_job(job_id: str, status: str, result: Any = None, error: str | None = None):
    if job_id in _inmem_jobs:
        _inmem_jobs[job_id].update({"status": status, "result": result, "error": error})


# Worker run loop for in-memory (used in tests / without arq)
async def run_inmem_worker(stop_event: asyncio.Event | None = None):
    """Simple in-mem worker that processes tasks via app.worker.tasks dispatch."""
    from app.worker.tasks import dispatch

    logger.info("In-mem worker started")
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            job_id, task_name, payload = await asyncio.wait_for(_inmem_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            if stop_event and stop_event.is_set():
                break
            continue
        try:
            _inmem_jobs[job_id]["status"] = "running"
            result = await dispatch(task_name, payload)
            await update_job(job_id, "success", result=result)
            logger.info(f"Job {job_id} {task_name} success")
        except Exception as e:
            logger.exception(f"Job {job_id} {task_name} failed: {e}")
            await update_job(job_id, "failed", error=str(e))
        finally:
            _inmem_queue.task_done()


# arq worker settings (if using arq CLI: `arq app.worker.queue.WorkerSettings`)
try:
    from app.worker.tasks import ingest_document_task, eval_task, webhook_task

    class WorkerSettings:
        functions = [ingest_document_task, eval_task, webhook_task]
        queue_name = "default"
        max_jobs = 10
        job_timeout = 300

        # redis via settings
        try:
            from app.core.config import settings
            redis_settings = RedisSettings.from_dsn(settings.REDIS_URL) if settings.REDIS_URL else RedisSettings()
        except Exception:
            redis_settings = RedisSettings()

except Exception:
    class WorkerSettings:  # type: ignore
        pass
