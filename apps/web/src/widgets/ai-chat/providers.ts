/**
 * Multi-provider chat adapters (BYOK — bring your own key). Normalises a simple
 * {role, content} thread + system prompt into each provider's request shape and
 * pulls the reply/error back out. Pure (no Next/DOM imports) so it is unit-tested
 * and shared by the server route handler.
 */

export type Provider = "claude" | "gemini" | "deepseek";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ProviderInfo {
  id: Provider;
  label: string;
  defaultModel: string;
  keyHint: string;
}

export const PROVIDERS: ProviderInfo[] = [
  { id: "gemini", label: "Gemini (Google)", defaultModel: "gemini-2.0-flash", keyHint: "AIza…" },
  { id: "claude", label: "Claude (Anthropic)", defaultModel: "claude-3-5-sonnet-latest", keyHint: "sk-ant-…" },
  { id: "deepseek", label: "DeepSeek", defaultModel: "deepseek-chat", keyHint: "sk-…" },
];

export function defaultModel(provider: Provider): string {
  return PROVIDERS.find((p) => p.id === provider)?.defaultModel ?? "";
}

export function isProvider(value: unknown): value is Provider {
  return value === "claude" || value === "gemini" || value === "deepseek";
}

export interface ProviderRequest {
  url: string;
  init: RequestInit;
}

const MAX_TOKENS = 1024;

/** Build the provider-specific HTTP request for a normalised thread. */
export function buildProviderRequest(
  provider: Provider,
  model: string,
  system: string,
  messages: ChatMessage[],
  apiKey: string,
): ProviderRequest {
  if (provider === "claude") {
    return {
      url: "https://api.anthropic.com/v1/messages",
      init: {
        method: "POST",
        headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify({ model, max_tokens: MAX_TOKENS, ...(system ? { system } : {}), messages }),
      },
    };
  }
  if (provider === "deepseek") {
    const msgs = system ? [{ role: "system", content: system }, ...messages] : messages;
    return {
      url: "https://api.deepseek.com/chat/completions",
      init: {
        method: "POST",
        headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
        body: JSON.stringify({ model, messages: msgs, max_tokens: MAX_TOKENS }),
      },
    };
  }
  // gemini — roles are user/model; key goes in the query string
  const contents = messages.map((m) => ({
    role: m.role === "assistant" ? "model" : "user",
    parts: [{ text: m.content }],
  }));
  return {
    url:
      `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}` +
      `:generateContent?key=${encodeURIComponent(apiKey)}`,
    init: {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}), contents }),
    },
  };
}

interface ClaudeResp {
  content?: { text?: string }[];
}
interface DeepseekResp {
  choices?: { message?: { content?: string } }[];
}
interface GeminiResp {
  candidates?: { content?: { parts?: { text?: string }[] } }[];
}
interface ErrResp {
  error?: string | { message?: string };
  message?: string;
}

export function extractReply(provider: Provider, data: unknown): string | null {
  if (provider === "claude") return (data as ClaudeResp).content?.[0]?.text ?? null;
  if (provider === "deepseek") return (data as DeepseekResp).choices?.[0]?.message?.content ?? null;
  return (data as GeminiResp).candidates?.[0]?.content?.parts?.[0]?.text ?? null;
}

export function extractError(data: unknown): string | null {
  const err = (data as ErrResp)?.error;
  if (typeof err === "string") return err;
  return err?.message ?? (data as ErrResp)?.message ?? null;
}
