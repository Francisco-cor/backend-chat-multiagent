// Minimal TS SDK — fetch-based, no external deps

export type ChatRequest = {
  session_id: string;
  prompt: string;
  model?: string;
  use_search?: boolean;
  image_base64?: string;
  image_mime_type?: string;
};

export type ChatResponse = {
  session_id: string;
  reply: string;
  model_used: string;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_usd: number };
};

export type ClientOptions = {
  baseUrl?: string;
  token?: string;
  apiKey?: string;
  headers?: Record<string, string>;
};

export class Client {
  baseUrl: string;
  token?: string;
  headers: Record<string, string>;

  constructor(opts: ClientOptions = {}) {
    this.baseUrl = (opts.baseUrl || "http://localhost:8005").replace(/\/$/, "");
    this.token = opts.token || opts.apiKey;
    this.headers = opts.headers || {};
  }

  private authHeaders(): Record<string, string> {
    const h: Record<string, string> = { ...this.headers };
    if (this.token) {
      if (this.token.startsWith("sk_")) {
        h["Authorization"] = `Bearer ${this.token}`;
        h["X-API-Key"] = this.token;
      } else {
        h["Authorization"] = `Bearer ${this.token}`;
      }
    }
    return h;
  }

  private url(path: string) {
    return `${this.baseUrl}${path}`;
  }

  chat = {
    create: async (req: ChatRequest): Promise<ChatResponse> => {
      const res = await fetch(this.url("/api/v1/chat/"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...this.authHeaders() },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`chat.create failed: ${res.status} ${await res.text()}`);
      return (await res.json()) as ChatResponse;
    },

    // SSE streaming — yields delta strings
    stream: async function* (req: ChatRequest): AsyncGenerator<string> {
      const res = await fetch((this as unknown as Client).url("/api/v1/chat/stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(this as unknown as Client).authHeaders() },
        body: JSON.stringify(req),
      });
      if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          for (const line of part.split("\n")) {
            if (line.startsWith("data:")) {
              const data = line.slice(5).trim();
              if (data === "[DONE]") return;
              try {
                const obj = JSON.parse(data) as any;
                if (obj.delta) yield obj.delta as string;
              } catch {}
            }
          }
        }
      }
    }.bind(this),

    orchestrate: async (req: ChatRequest & { strategy?: string }): Promise<ChatResponse & { trace: any[] }> => {
      const res = await fetch(this.url("/api/v1/chat/orchestrate"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...this.authHeaders() },
        body: JSON.stringify(req),
      });
      if (!res.ok) throw new Error(`orchestrate failed: ${res.status} ${await res.text()}`);
      return (await res.json()) as any;
    },
  };

  conversations = {
    list: async (params: { limit?: number; cursor?: number } = {}) => {
      const qs = new URLSearchParams(params as any).toString();
      const res = await fetch(this.url(`/api/v1/conversations?${qs}`), { headers: this.authHeaders() });
      if (!res.ok) throw new Error(`conversations.list failed`);
      return res.json();
    },
  };

  async health() {
    const res = await fetch(this.url("/health"));
    return res.json();
  }

  async login(email: string, password: string) {
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(this.url("/api/v1/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    if (!res.ok) throw new Error(`login failed: ${res.status}`);
    const data = (await res.json()) as any;
    this.token = data.access_token;
    return data;
  }
}
