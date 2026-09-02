# Backend Chat SDK — Python

```bash
pip install ./sdk/python
# or: pip install backend-chat-sdk
```

```python
from backend_chat_sdk import Client

client = Client(base_url="http://localhost:8005", token="jwt_or_sk_...")  # or api_key=...
reply = client.chat.create(session_id="sess1", prompt="Hello Clara", model="gemini-3.1-pro")
print(reply.reply)

# streaming
for chunk in client.chat.stream(session_id="sess1", prompt="hi"):
    print(chunk, end="")

# conversations
convs = client.conversations.list(limit=10)
```

Generated from OpenAPI `/openapi.json` (see `scripts/gen_sdk.sh`). This stub is hand-written for DX; regenerate with `openapi-generator-cli`.
