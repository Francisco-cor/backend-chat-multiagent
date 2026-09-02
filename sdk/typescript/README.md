# Backend Chat SDK — TypeScript

```bash
npm install backend-chat-sdk
# or local: npm install ../sdk/typescript
```

```ts
import { Client } from "backend-chat-sdk";

const client = new Client({ baseUrl: "http://localhost:8005", token: "jwt_or_sk_..." });
const reply = await client.chat.create({ session_id: "sess1", prompt: "Hello Clara" });
console.log(reply.reply);

// streaming (SSE)
for await (const chunk of client.chat.stream({ session_id: "sess1", prompt: "hi" })) {
  process.stdout.write(chunk);
}
```

Regenerate from OpenAPI: `bash scripts/gen_sdk.sh`
