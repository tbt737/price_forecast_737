/**
 * BYOK chat proxy. Forwards a {provider, model, apiKey, system, messages} request
 * to the chosen LLM provider server-side (avoids browser CORS) and returns the
 * reply. The API key is taken per-request and is NEVER stored or logged. Provider
 * hosts are fixed (no SSRF); inputs are validated and size-capped.
 */

import { NextResponse } from "next/server";
import { createRateLimiter } from "@/shared/lib/rate-limit";
import {
  buildProviderRequest,
  defaultModel,
  extractError,
  extractReply,
  isProvider,
  type ChatMessage,
} from "@/widgets/ai-chat/providers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_MESSAGES = 40;
const MAX_CHARS = 24_000;
const TIMEOUT_MS = 60_000;

// SEC-2: in-memory per-IP rate limit (Node runtime ⇒ module state persists per instance).
// This proxy relays to LLM providers on the owner's Cloud Run bill; cap anonymous abuse.
const limiter = createRateLimiter(15, 60_000); // 15 requests / IP / minute

function clientIp(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  return (fwd ? fwd.split(",")[0] : "").trim() || "unknown";
}

function bad(detail: string, status = 400) {
  return NextResponse.json({ error: detail }, { status });
}

export async function POST(req: Request) {
  if (limiter.isLimited(clientIp(req))) return bad("Quá nhiều yêu cầu — thử lại sau một phút", 429);

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return bad("Body JSON không hợp lệ");
  }

  const provider = body.provider;
  if (!isProvider(provider)) return bad("Provider không hợp lệ");

  const apiKey = typeof body.apiKey === "string" ? body.apiKey.trim() : "";
  if (!apiKey) return bad("Chưa cắm API key");

  const rawMessages = Array.isArray(body.messages) ? body.messages : [];
  if (rawMessages.length === 0) return bad("Thiếu nội dung tin nhắn");
  if (rawMessages.length > MAX_MESSAGES) return bad("Quá nhiều tin nhắn trong một lượt");

  const messages: ChatMessage[] = rawMessages.map((m) => {
    const obj = (m ?? {}) as Record<string, unknown>;
    return {
      role: obj.role === "assistant" ? "assistant" : "user",
      content: typeof obj.content === "string" ? obj.content : String(obj.content ?? ""),
    };
  });
  const chars = messages.reduce((n, m) => n + m.content.length, 0);
  if (chars > MAX_CHARS) return bad("Nội dung quá dài");

  const system = typeof body.system === "string" ? body.system.slice(0, MAX_CHARS) : "";
  const model = typeof body.model === "string" && body.model.trim() ? body.model.trim() : defaultModel(provider);

  try {
    const { url, init } = buildProviderRequest(provider, model, system, messages, apiKey);
    const res = await fetch(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
    const data: unknown = await res.json().catch(() => ({}));
    if (!res.ok) return bad(extractError(data) ?? `Provider trả lỗi ${res.status}`, 502);
    const reply = extractReply(provider, data);
    if (!reply) return bad("Provider không trả về nội dung", 502);
    return NextResponse.json({ reply });
  } catch {
    // Network/timeout/abort — never surface internals.
    return bad("Không gọi được provider (key sai, hết hạn mức, hoặc mạng/timeout)", 502);
  }
}
