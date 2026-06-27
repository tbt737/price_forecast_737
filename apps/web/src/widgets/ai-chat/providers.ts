/**
 * Multi-provider chat adapters (BYOK — bring your own key). Most providers speak
 * the OpenAI /chat/completions shape (only the base URL differs); Claude and
 * Gemini have their own. Pure (no Next/DOM imports) so it is unit-tested and
 * shared by the server route handler.
 */

export type Provider =
  | "gemini"
  | "groq"
  | "openrouter"
  | "openai"
  | "claude"
  | "grok"
  | "deepseek";

type Kind = "gemini" | "claude" | "openai";

export interface ProviderInfo {
  id: Provider;
  label: string;
  kind: Kind;
  baseUrl?: string; // OpenAI-compatible endpoint (kind === "openai")
  defaultModel: string;
  keyHint: string;
  free?: boolean; // has a usable free tier
}

export const PROVIDERS: ProviderInfo[] = [
  { id: "gemini", label: "Gemini (Google) · free", kind: "gemini", defaultModel: "gemini-2.0-flash", keyHint: "AIza…", free: true },
  {
    id: "groq",
    label: "Groq · free (Llama/Mixtral)",
    kind: "openai",
    baseUrl: "https://api.groq.com/openai/v1/chat/completions",
    defaultModel: "llama-3.3-70b-versatile",
    keyHint: "gsk_…",
    free: true,
  },
  {
    id: "openrouter",
    label: "OpenRouter · model free",
    kind: "openai",
    baseUrl: "https://openrouter.ai/api/v1/chat/completions",
    defaultModel: "meta-llama/llama-3.3-70b-instruct:free",
    keyHint: "sk-or-…",
    free: true,
  },
  {
    id: "openai",
    label: "OpenAI (GPT)",
    kind: "openai",
    baseUrl: "https://api.openai.com/v1/chat/completions",
    defaultModel: "gpt-4o-mini",
    keyHint: "sk-…",
  },
  { id: "claude", label: "Claude (Anthropic)", kind: "claude", defaultModel: "claude-3-5-sonnet-latest", keyHint: "sk-ant-…" },
  {
    id: "grok",
    label: "Grok (xAI)",
    kind: "openai",
    baseUrl: "https://api.x.ai/v1/chat/completions",
    defaultModel: "grok-2-latest",
    keyHint: "xai-…",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    kind: "openai",
    baseUrl: "https://api.deepseek.com/chat/completions",
    defaultModel: "deepseek-chat",
    keyHint: "sk-…",
  },
];

const BY_ID = new Map(PROVIDERS.map((p) => [p.id, p]));

export function defaultModel(provider: Provider): string {
  return BY_ID.get(provider)?.defaultModel ?? "";
}

export function isProvider(value: unknown): value is Provider {
  return typeof value === "string" && BY_ID.has(value as Provider);
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
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
  const info = BY_ID.get(provider);
  if (!info) throw new Error(`Unknown provider: ${provider}`);

  if (info.kind === "claude") {
    return {
      url: "https://api.anthropic.com/v1/messages",
      init: {
        method: "POST",
        headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify({ model, max_tokens: MAX_TOKENS, ...(system ? { system } : {}), messages }),
      },
    };
  }

  if (info.kind === "gemini") {
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

  // OpenAI-compatible (OpenAI, Grok, Groq, OpenRouter, DeepSeek)
  const msgs = system ? [{ role: "system", content: system }, ...messages] : messages;
  return {
    url: info.baseUrl as string,
    init: {
      method: "POST",
      headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
      body: JSON.stringify({ model, messages: msgs, max_tokens: MAX_TOKENS }),
    },
  };
}

interface ClaudeResp {
  content?: { text?: string }[];
}
interface OpenAIResp {
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
  const kind = BY_ID.get(provider)?.kind;
  if (kind === "claude") return (data as ClaudeResp).content?.[0]?.text ?? null;
  if (kind === "gemini") return (data as GeminiResp).candidates?.[0]?.content?.parts?.[0]?.text ?? null;
  return (data as OpenAIResp).choices?.[0]?.message?.content ?? null;
}

export function extractError(data: unknown): string | null {
  const err = (data as ErrResp)?.error;
  if (typeof err === "string") return err;
  return err?.message ?? (data as ErrResp)?.message ?? null;
}
