import { describe, expect, it } from "vitest";
import { buildProviderRequest, extractError, extractReply } from "./providers";

const msgs = [{ role: "user" as const, content: "hi" }];
const headers = (init: RequestInit) => init.headers as Record<string, string>;

describe("ai-chat providers", () => {
  it("claude: x-api-key header + top-level system + messages", () => {
    const { url, init } = buildProviderRequest("claude", "m", "sys", msgs, "K");
    expect(url).toContain("api.anthropic.com");
    expect(headers(init)["x-api-key"]).toBe("K");
    const b = JSON.parse(init.body as string);
    expect(b.system).toBe("sys");
    expect(b.messages).toEqual(msgs);
  });

  it("gemini: key in query, assistant→model, systemInstruction", () => {
    const { url, init } = buildProviderRequest("gemini", "gm", "sys", [{ role: "assistant", content: "a" }], "K");
    expect(url).toContain("generativelanguage.googleapis.com");
    expect(url).toContain("key=K");
    const b = JSON.parse(init.body as string);
    expect(b.contents[0].role).toBe("model");
    expect(b.systemInstruction.parts[0].text).toBe("sys");
  });

  it("deepseek: bearer auth + system prepended as a message", () => {
    const { url, init } = buildProviderRequest("deepseek", "ds", "sys", msgs, "K");
    expect(url).toContain("api.deepseek.com");
    expect(headers(init).authorization).toBe("Bearer K");
    const b = JSON.parse(init.body as string);
    expect(b.messages[0]).toEqual({ role: "system", content: "sys" });
  });

  it("extractReply / extractError per provider shape", () => {
    expect(extractReply("claude", { content: [{ text: "x" }] })).toBe("x");
    expect(extractReply("deepseek", { choices: [{ message: { content: "y" } }] })).toBe("y");
    expect(extractReply("gemini", { candidates: [{ content: { parts: [{ text: "z" }] } }] })).toBe("z");
    expect(extractError({ error: { message: "bad" } })).toBe("bad");
    expect(extractError({ error: "oops" })).toBe("oops");
  });
});
