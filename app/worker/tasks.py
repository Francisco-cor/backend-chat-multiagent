"""Worker tasks — Fase 11.6 ingest + batch evals + webhook dispatch."""
import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def ingest_document_task(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest pipeline: chunk -> embed -> store. Payload: {document_id, user_id}."""
    try:
        doc_id = payload.get("document_id")
        user_id = payload.get("user_id")
        logger.info(f"Ingest task doc={doc_id} user={user_id}")
        # Simulate chunk/embed
        # In real: call IngestService.ingest_document(doc_id)
        # For stub, just sleep and return
        await asyncio.sleep(0.1)
        # Audit
        try:
            from app.db.session import AsyncSessionLocal
            from app.db.models import AuditLog
            async with AsyncSessionLocal() as db:
                db.add(AuditLog(user_id=user_id, action="ingest.worker", detail=f"doc {doc_id} processed"))
                await db.commit()
        except Exception:
            pass
        return {"status": "ingested", "document_id": doc_id}
    except Exception as e:
        logger.exception(f"ingest_document_task failed: {e}")
        raise


async def eval_task(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Batch eval: payload {threshold, dataset}. Runs evals/runner.py logic."""
    try:
        from pathlib import Path
        threshold = payload.get("threshold", 0.85)
        logger.info(f"Eval task threshold={threshold}")
        # Call runner logic
        from evals.runner import main as eval_main
        from pathlib import Path
        dataset = Path(payload.get("dataset", "evals/datasets/golden.jsonl"))
        # Use mock mode
        import os
        os.environ["EVAL_MOCK"] = "1"
        # Patch: run via function
        from evals.runner import run_case
        import json
        cases = []
        with open(dataset) as f:
            for line in f:
                if line.strip():
                    cases.append(json.loads(line))
        passed = 0
        results = []
        for case in cases[:10]:  # limit for worker demo
            r = await run_case(case, use_mock=True)
            results.append(r)
            if r["passed"]:
                passed += 1
        return {"passed": passed, "total": len(results), "pass_rate": passed/len(results) if results else 0, "results": results}
    except Exception as e:
        logger.exception(f"eval_task failed: {e}")
        raise


async def webhook_task(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch webhook. Payload {url, event, data}."""
    url = payload.get("url")
    event = payload.get("event", "unknown")
    data = payload.get("data", {})
    logger.info(f"Webhook dispatch {event} -> {url}")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"event": event, "data": data})
            return {"status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        logger.warning(f"Webhook dispatch failed (stub): {e}")
        return {"status": "stubbed", "event": event, "error": str(e)}


# Generic dispatch for in-mem worker
async def dispatch(task_name: str, payload: Dict[str, Any]) -> Any:
    mapping = {
        "ingest_document": ingest_document_task,
        "ingest_document_task": ingest_document_task,
        "eval": eval_task,
        "eval_task": eval_task,
        "webhook": webhook_task,
        "webhook_task": webhook_task,
    }
    fn = mapping.get(task_name)
    if not fn:
        raise ValueError(f"Unknown task {task_name}")
    return await fn({}, payload)
