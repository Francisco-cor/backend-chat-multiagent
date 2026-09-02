"""Resilient SSE Stream Manager — Fase 7.1

Handles:
 - monotonic event IDs per session
 - in-memory ring buffer for Last-Event-ID resume
 - heartbeat handling helpers
 - backpressure via bounded queue size
"""
import asyncio
import time
import logging
from collections import defaultdict, deque
from typing import AsyncGenerator, Deque, Dict, List, Tuple

logger = logging.getLogger(__name__)

# In-memory buffer: session_id -> deque[(event_id, delta)]
_BUFFER_MAX = 100
_buffers: Dict[str, Deque[Tuple[int, str]]] = defaultdict(lambda: deque(maxlen=_BUFFER_MAX))
_counters: Dict[str, int] = defaultdict(int)
_lock = asyncio.Lock()  # protects counters/buffers (light)


def _next_id(session_id: str) -> int:
    _counters[session_id] += 1
    return _counters[session_id]


def _buffer_add(session_id: str, event_id: int, delta: str) -> None:
    _buffers[session_id].append((event_id, delta))


def get_buffered(session_id: str, after_id: int) -> List[Tuple[int, str]]:
    """Return buffered events with id > after_id."""
    buf = _buffers.get(session_id, deque())
    return [(eid, d) for eid, d in buf if eid > after_id]


def reset_session(session_id: str) -> None:
    _buffers.pop(session_id, None)
    _counters.pop(session_id, None)


async def resilient_stream(
    session_id: str,
    inner_gen,
    last_event_id: int | None = 0,
    heartbeat_interval: float = 15.0,
) -> AsyncGenerator[str, None]:
    """
    Wrap an inner async generator of str chunks into resilient SSE frames.

    Frame format:
      id: <mono>\n
      data: {"delta": "...", "id": 123}\n\n

    Heartbeat when idle:
      : heartbeat\n\n

    If last_event_id provided, first replay buffered events where id > last_event_id.
    """
    # Replay buffered if resume requested
    if last_event_id:
        replay = get_buffered(session_id, last_event_id)
        for eid, delta in replay:
            import json

            # keep payload minimal for backward compat (test expects {"delta": "..."})
            payload = json.dumps({"delta": delta})
            yield f"id: {eid}\ndata: {payload}\n\n"

    # Tell client retry interval
    yield "retry: 3000\n\n"

    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    done = asyncio.Event()

    async def producer():
        try:
            async for chunk in inner_gen:
                # backpressure: wait if queue full
                await queue.put(chunk)
        except Exception as e:
            logger.warning(f"Stream producer error: {e}")
            await queue.put(e)  # type: ignore
        finally:
            done.set()
            await queue.put(None)  # sentinel

    prod_task = asyncio.create_task(producer())

    try:
        while True:
            try:
                # wait for next chunk or heartbeat timeout
                chunk = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                # heartbeat comment — keeps connection alive, ignored by EventSource
                yield ": heartbeat\n\n"
                # also optional json heartbeat
                # yield 'data: {"type":"heartbeat"}\n\n'
                continue

            if chunk is None:
                break
            if isinstance(chunk, Exception):
                import json

                yield f"data: {json.dumps({'error': str(chunk)})}\n\n"
                break

            event_id = _next_id(session_id)
            _buffer_add(session_id, event_id, chunk)
            import json

            # Minimal payload for backward compat; id is in SSE header
            payload = json.dumps({"delta": chunk})
            yield f"id: {event_id}\ndata: {payload}\n\n"
            # also legacy plain delta for backward compat? keep inside json above
    finally:
        prod_task.cancel()
        try:
            await prod_task
        except asyncio.CancelledError:
            pass
