import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { POST } from "../../../app/ai/chat/route";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

function chatReq(ip: string): Request {
  return new Request("http://localhost/ai/chat", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": ip },
    body: JSON.stringify({ provider: "not-a-real-provider" }), // fails validation IF it gets past the limiter
  });
}

function chatReqSpoofedXff(cfIp: string, spoofedXff: string): Request {
  return new Request("http://localhost/ai/chat", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "cf-connecting-ip": cfIp,
      "x-forwarded-for": spoofedXff,
    },
    body: JSON.stringify({ provider: "not-a-real-provider" }),
  });
}

describe("/ai/chat rate limiting (behavioral)", () => {
  it("returns 429 once one IP exceeds the per-minute limit; body carries no stack trace", async () => {
    let last: Response | undefined;
    for (let i = 0; i < 20; i++) last = await POST(chatReq("9.9.9.9"));
    expect(last?.status).toBe(429);
    const body = (await last!.json()) as Record<string, unknown>;
    expect(String(body.error)).toContain("Quá nhiều");
    expect(JSON.stringify(body)).not.toMatch(/stack|\bat \b|\.ts:\d/i); // no internals leaked
  });

  it("does not rate-limit a different IP", async () => {
    const res = await POST(chatReq("8.8.8.8"));
    expect(res.status).not.toBe(429); // 400 validation, never 429
  });

  it("keys on cf-connecting-ip, not a client-spoofable x-forwarded-for", async () => {
    // Same real client (same cf-connecting-ip) rotating a fresh x-forwarded-for on
    // every request must still hit the cap — proves the limiter can't be bypassed by
    // spoofing the header the client controls.
    let last: Response | undefined;
    for (let i = 0; i < 20; i++) {
      last = await POST(chatReqSpoofedXff("7.7.7.7", `1.2.3.${i}`));
    }
    expect(last?.status).toBe(429);
  });

  it("does not rate-limit a different real client behind the same spoofed x-forwarded-for", async () => {
    const res = await POST(chatReqSpoofedXff("6.6.6.6", "1.2.3.4"));
    expect(res.status).not.toBe(429); // different cf-connecting-ip ⇒ different bucket
  });
});

describe("middleware internal-key contract (source)", () => {
  const src = readFileSync(path.join(WEB_ROOT, "middleware.ts"), "utf8");

  it("always strips any inbound x-internal-key (anti-spoof)", () => {
    expect(src).toMatch(/\.delete\(\s*["']x-internal-key["']\s*\)/);
  });

  it("reads the key only from the server env, never a NEXT_PUBLIC_* var", () => {
    expect(src).toMatch(/process\.env\.INTERNAL_API_KEY/);
    // no NEXT_PUBLIC_* env ACCESS (a mention in a comment is fine, an env read is not)
    expect(src).not.toMatch(/process\.env\.NEXT_PUBLIC/);
    expect(src).not.toMatch(/NEXT_PUBLIC_INTERNAL/);
  });
});
