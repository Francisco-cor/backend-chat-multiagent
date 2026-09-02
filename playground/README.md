# Playground — Clara Chat

Static HTML playground that consumes `POST /api/v1/chat/stream` (SSE resilient) and `GET /api/v1/conversations`.

```bash
# serve via python http.server (CORS already allows *)
npx serve playground
# or open directly: file://.../playground/index.html  (ensure API at http://localhost:8005 and CORS)
# via FastAPI static mount (if enabled):
# http://localhost:8005/playground/
```

Features:
 - JWT or `sk_...` API key in header (`Authorization: Bearer` + `X-API-Key`)
 - Model picker, `use_search` toggle
 - SSE streaming with `Last-Event-ID` resume (heartbeat 15s) — see `app/services/stream_manager.py`
 - Conversations list (cursor) + messages
 - Login demo (register + login inline)
 - Orchestrate test (`POST /chat/orchestrate`)

Backend must be running (`docker compose up` or `uvicorn app.main:app --port 8005`).
