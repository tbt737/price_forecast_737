"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Commodity } from "@/shared/api";
import { cn } from "@/shared/lib/cn";
import { Card, CardBody, CardHeader } from "@/shared/ui";
import { defaultModel, PROVIDERS, type ChatMessage, type Provider } from "@/widgets/ai-chat/providers";

const LS = {
  provider: "cqp.ai.provider",
  model: (p: Provider) => `cqp.ai.model.${p}`,
  key: (p: Provider) => `cqp.ai.key.${p}`,
};

function load(k: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(k);
  } catch {
    return null;
  }
}
function save(k: string, v: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(k, v);
  } catch {
    /* ignore quota/availability */
  }
}

const BASE_SYSTEM =
  "Bạn là trợ lý phân tích giá hàng hóa (nông sản/kim loại/năng lượng) cho một app dự báo định lượng. " +
  "Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc; nêu kịch bản tăng/giảm và rủi ro chính. " +
  "LUÔN nhắc rằng đây không phải lời khuyên đầu tư.";

async function buildContext(code: string | null, name: string | null): Promise<string> {
  if (!code) return "";
  try {
    const res = await fetch(`/api/commodities/${encodeURIComponent(code)}/forecast`, { cache: "no-store" });
    if (!res.ok) return "";
    const d = (await res.json()) as {
      currency?: string;
      last_price?: number;
      horizons?: Record<string, { model_used?: string; points?: { value?: number }[]; backtest?: { mape_pct?: number; naive_mape_pct?: number } }>;
    };
    if (!d.horizons) return "";
    const parts = Object.entries(d.horizons).map(([h, hz]) => {
      const last = hz.points?.[hz.points.length - 1]?.value;
      const bt = hz.backtest;
      return `${h} phiên: model ${hz.model_used ?? "?"}, dự báo cuối ${last ?? "?"}, backtest MAPE ${bt?.mape_pct ?? "?"}% (naive ${bt?.naive_mape_pct ?? "?"}%)`;
    });
    return (
      `Số liệu MÔ HÌNH ĐỊNH LƯỢNG cho ${name ?? code} (${code}): giá cuối ${d.last_price ?? "?"} ${d.currency ?? ""}. ` +
      parts.join("; ") +
      ". Hãy dựa trên các số này khi phân tích."
    );
  } catch {
    return "";
  }
}

export function AiChat() {
  const [provider, setProvider] = useState<Provider>("gemini");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [withContext, setWithContext] = useState(true);
  const [input, setInput] = useState("");
  const [thread, setThread] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [commodities, setCommodities] = useState<Commodity[]>([]);
  const [ctxCode, setCtxCode] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listCommodities().then(setCommodities).catch(() => {});
  }, []);
  const ctxName = commodities.find((c) => c.commodity_code === ctxCode)?.commodity_name ?? null;

  // hydrate provider + per-provider model/key from localStorage
  useEffect(() => {
    const p = (load(LS.provider) as Provider) || "gemini";
    setProvider(p);
    setModel(load(LS.model(p)) || defaultModel(p));
    setApiKey(load(LS.key(p)) || "");
  }, []);

  const switchProvider = (p: Provider) => {
    setProvider(p);
    save(LS.provider, p);
    setModel(load(LS.model(p)) || defaultModel(p));
    setApiKey(load(LS.key(p)) || "");
  };
  const onModel = (v: string) => {
    setModel(v);
    save(LS.model(provider), v);
  };
  const onKey = (v: string) => {
    setApiKey(v);
    save(LS.key(provider), v);
  };

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [thread, busy]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    if (!apiKey.trim()) {
      setError("Chưa cắm API key cho " + provider + " — nhập key ở ô bên trên.");
      return;
    }
    setError(null);
    const next = [...thread, { role: "user" as const, content: text }];
    setThread(next);
    setInput("");
    setBusy(true);
    try {
      const ctx = withContext && ctxCode ? await buildContext(ctxCode, ctxName) : "";
      const system = ctx ? `${BASE_SYSTEM}\n\n${ctx}` : BASE_SYSTEM;
      const res = await fetch("/ai/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider, model, apiKey, system, messages: next }),
      });
      const data = (await res.json()) as { reply?: string; error?: string };
      if (!res.ok || !data.reply) {
        setError(data.error || "Lỗi không xác định");
      } else {
        setThread((t) => [...t, { role: "assistant", content: data.reply as string }]);
      }
    } catch {
      setError("Không gửi được yêu cầu.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="🤖 Hỏi chuyên gia AI"
        right={
          thread.length > 0 ? (
            <button type="button" onClick={() => setThread([])} className="text-xs font-medium text-info hover:underline">
              Xoá hội thoại
            </button>
          ) : null
        }
      />
      <CardBody>
        {/* config */}
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted">
            Nhà cung cấp
            <select
              value={provider}
              onChange={(e) => switchProvider(e.target.value as Provider)}
              className="rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm text-text outline-none focus:border-brand"
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted">
            Model
            <input
              value={model}
              onChange={(e) => onModel(e.target.value)}
              className="w-40 rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-brand"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
            API key (lưu ở trình duyệt của bạn)
            <input
              type="password"
              value={apiKey}
              onChange={(e) => onKey(e.target.value)}
              placeholder={PROVIDERS.find((p) => p.id === provider)?.keyHint}
              autoComplete="off"
              className="min-w-[160px] rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-brand"
            />
          </label>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <label className="flex items-center gap-1.5">
            Ngữ cảnh:
            <select
              value={ctxCode}
              onChange={(e) => setCtxCode(e.target.value)}
              className="rounded-md border border-border bg-surface-2 px-2 py-1 text-xs text-text outline-none focus:border-brand"
            >
              <option value="">không gắn hàng hóa</option>
              {commodities.map((c) => (
                <option key={c.commodity_code} value={c.commodity_code}>
                  {c.commodity_name}
                </option>
              ))}
            </select>
          </label>
          {ctxCode ? (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={withContext} onChange={(e) => setWithContext(e.target.checked)} />
              kèm số liệu dự báo định lượng
            </label>
          ) : null}
        </div>

        {/* thread */}
        <div ref={threadRef} className="mt-3 max-h-80 space-y-2 overflow-y-auto rounded-lg border border-border bg-surface-2 p-3">
          {thread.length === 0 ? (
            <p className="py-6 text-center text-sm text-subtle">
              Cắm API key, chọn model, rồi hỏi — ví dụ: “Phân tích xu hướng giá {ctxName || "mặt hàng"} 30 ngày tới?”
            </p>
          ) : (
            thread.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                    m.role === "user" ? "bg-brand text-white" : "bg-surface text-text",
                  )}
                >
                  {m.content}
                </div>
              </div>
            ))
          )}
          {busy ? <p className="text-center text-xs text-muted">AI đang trả lời…</p> : null}
        </div>
        {error ? <p className="mt-2 text-xs text-danger" style={{ color: "var(--danger, #dc2626)" }}>⚠️ {error}</p> : null}

        {/* input */}
        <div className="mt-2 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="Nhập câu hỏi… (Enter để gửi)"
            className="flex-1 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-brand"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={busy}
            className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            Gửi
          </button>
        </div>

        <p className="mt-3 border-t border-border pt-3 text-xs text-subtle">
          🔑 Key của bạn lưu trong <b>localStorage trình duyệt</b> và chỉ đi qua server app để chuyển tiếp tới nhà cung cấp —
          <b> không lưu lại</b>. 🤖 Trả lời của AI là ý kiến tham khảo, <b>không phải</b> con số của model định lượng và
          <b> không phải</b> lời khuyên đầu tư.
        </p>
      </CardBody>
    </Card>
  );
}
