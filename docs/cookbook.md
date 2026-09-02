# Cookbook — Multi-Agent Backend

Quick recipes (<5 min) for integration. See `/docs` (Swagger) and `sdk/python`.

## 1. Python SDK (sync)

```bash
pip install ./sdk/python
```

```python
from backend_chat_sdk import Client

client = Client(base_url="http://localhost:8005", token="eyJ...")  # or api_key="sk_..."
# or: client.login("user@example.com","Str0ng!Pass123")

# Direct chat
r = client.chat.create(session_id="sess1", prompt="Hello Clara", model="gemini-3.1-pro")
print(r["reply"], r["usage"])

# Streaming SSE
for delta in client.chat.stream(session_id="sess1", prompt="Tell me a joke"):
    print(delta, end="")

# Orchestrate (Researcher + Analyst)
r = client.chat.orchestrate(session_id="sess1", prompt="Investiga FastAPI y analiza", strategy="auto")
print(r["trace"])

# Conversations
convs = client.conversations.list(limit=10)
print(convs["items"][0])
msgs = client.conversations.get_messages(conversation_id=1)
```

## 2. TypeScript SDK

```ts
import { Client } from "./sdk/typescript/src/client";
const c = new Client({ baseUrl: "http://localhost:8005", token: process.env.TOKEN });
const r = await c.chat.create({ session_id: "s1", prompt: "hi" });
for await (const d of c.chat.stream({ session_id: "s1", prompt: "hi" })) process.stdout.write(d);
```

## 3. cURL

```bash
# login
curl -X POST http://localhost:8005/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=Str0ng!Pass123"
# -> {"access_token":"...","refresh_token":"..."}

TOKEN="..."

# chat
curl -X POST http://localhost:8005/api/v1/chat/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"session_id":"sess1","prompt":"Hello","model":"gemini-3.1-pro"}'

# stream (SSE)
curl -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"session_id":"sess1","prompt":"hi","model":"gemini-3.1-pro"}' \
  http://localhost:8005/api/v1/chat/stream

# with Last-Event-ID resume
curl -N -H "Authorization: Bearer $TOKEN" -H "Last-Event-ID: 42" ...

# API key
curl -X POST http://localhost:8005/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"cli","scopes":["chat:write"]}'

# use API key
curl -X POST http://localhost:8005/api/v1/chat/ \
  -H "X-API-Key: sk_..." -H "Content-Type: application/json" \
  -d '{"session_id":"sess1","prompt":"hi via key"}'

# WS
# wscat -c "ws://localhost:8005/ws/chat?token=$TOKEN"
# > {"prompt":"hi","session_id":"sess1","model":"gemini-3.1-pro"}
```

## 4. Error Handling (RFC 7807)

All errors return `application/problem+json`:

```json
{
  "type": "https://api.example.com/errors/validation",
  "title": "Validation Error",
  "status": 422,
  "detail": "body.prompt: Field required",
  "instance": "/api/v1/chat/",
  "code": "VALIDATION_ERROR",
  "errors": [{"loc":["body","prompt"],"msg":"Field required","type":"missing"}],
  "request_id": "550e8400-..."
}
```

- `401` Unauthorized (missing/bad JWT or `sk_...`)
- `403` Missing scope (`chat:write`)
- `422` Validation / bad base64
- `423` Account locked (lockout)
- `429` Rate-limit (`Retry-After`, `X-RateLimit-Remaining`) or Quota (`X-Quota-Remaining`, `X-Quota-Limit`)
- `500` Internal (logged with `request_id`)

Check `X-Quota-Remaining` after each chat to warn at soft-limit (80%).

## 5. Pagination & Conversations

```bash
# list
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8005/api/v1/conversations?limit=20&cursor=0"
# -> {"items":[...],"next_cursor":20,"has_more":true}

# messages
curl -H "Authorization: Bearer $TOKEN" http://localhost:8005/api/v1/conversations/1/messages?limit=50

# patch title / delete
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"title":"New"}' http://localhost:8005/api/v1/conversations/1
curl -X DELETE -H "Authorization: Bearer $TOKEN" http://localhost:8005/api/v1/conversations/1
```

## 6. RAG

```bash
curl -X POST http://localhost:8005/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" -F "file=@paper.pdf" -F "title=Paper"
# retrieve is auto-injected via Researcher agent; also:
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8005/api/v1/documents?limit=10"
```

## 7. Rate-limit & Quota (Redis)

When `REDIS_URL` set, slowapi uses `redis://...` storage (distributed). Per-principal sliding window (`redis_sliding_window`) 5/min for chat.

Check headers:
 - `X-RateLimit-Remaining` (redis)
 - `X-Quota-Remaining` / `X-Quota-Limit` / `X-Quota-Warning: soft-limit`
 - `Retry-After` on 429

2 replicas share limit (verify with `ab -n 100 -c 10`).

## 8. Troubleshooting

- `SECRET_KEY must be at least 32 chars` → set in `.env` (`openssl rand -hex 32`)
- `Model 'x' not allowed` → see `GET /` or `ALLOWED_MODELS_LIST`
- `Payload Too Large` 413 → `MAX_UPLOAD_SIZE_MB` (default 10)
- `Database unavailable` 503 on `/health/ready` → check `docker compose logs db` / `pg_isready`
- Streaming stuck → ensure `X-Accel-Buffering: no` and client handles `retry: 3000` + `Last-Event-ID`
