"use client";

import { useEffect, useState } from "react";
import { api, type Commodity } from "@/shared/api";
import { defaultModel, PROVIDERS, type Provider } from "@/widgets/ai-chat/providers";
import { LS, loadLS, saveLS } from "@/widgets/ai-chat/storage";
import { castReading, type Reading } from "@/widgets/iching/iching";
import { cycleSummary, hanhOf, yearCanChi } from "@/widgets/iching/ngu-hanh";

const SYSTEM =
  "Bạn là một CHUYÊN GIA KINH DỊCH và NGŨ HÀNH uyên thâm, luận giải để dự đoán xu hướng giá hàng hóa. " +
  "Hãy luận theo 3 tầng, mỗi tầng một đề mục ngắn: (1) TƯỢNG QUẺ Kinh Dịch (quẻ chính, hào động, biến quẻ) nói gì về thế cục; " +
  "(2) NGŨ HÀNH của hàng hóa đối chiếu Can Chi của năm — tương sinh thì vượng, tương khắc thì suy; " +
  "(3) CHU KỲ theo tháng — chỉ ra giai đoạn thuận/nghịch. " +
  "Cuối cùng nêu NHẬN ĐỊNH xu hướng (tăng/giảm/đi ngang) kèm khoảng thời gian. " +
  "Văn phong thầy Dịch, súc tích, tiếng Việt. " +
  "KẾT THÚC luôn nhắc: đây là luận giải văn hoá/giải trí, KHÔNG phải dự báo định lượng và KHÔNG phải lời khuyên đầu tư.";

function buildPrompt(reading: Reading, code: string, name: string, question: string): string {
  const year = new Date().getFullYear();
  const cc = yearCanChi(year);
  const h = hanhOf(code);
  const r = reading;
  const que =
    `Quẻ chính: ${r.primary.name} — ${r.primary.upper.nature} trên ${r.primary.lower.nature} ` +
    `(${r.primary.yangCount} hào dương), ${r.primaryLean.label}.` +
    (r.changed
      ? ` Có ${r.changingIndices.length} hào động → biến sang quẻ ${r.changed.name} (${r.changedLean?.label}).`
      : " Quẻ tĩnh, không hào động.");
  const nguHanh = h
    ? `${name} thuộc hành ${h.hanh} (${h.reason}). Năm ${year} là ${cc.label}: Can ${cc.can} hành ${cc.canHanh}, ` +
      `Chi ${cc.chi} hành ${cc.chiHanh} (${cc.conGiap}). Chu kỳ ngũ hành theo tháng âm cho hành ${h.hanh} — ` +
      `tháng THUẬN: ${cycleSummary(h.hanh).favorable}; tháng NGHỊCH: ${cycleSummary(h.hanh).unfavorable}.`
    : `Chưa gắn hàng hóa cụ thể. Năm ${year} là ${cc.label}.`;
  const q = question.trim() || `Xin thầy luận xu hướng giá ${name || "mặt hàng này"} thời gian tới.`;
  return `Câu hỏi: ${q}\n\n[KINH DỊCH] ${que}\n\n[NGŨ HÀNH] ${nguHanh}`;
}

export function IchingExpert() {
  const [commodities, setCommodities] = useState<Commodity[]>([]);
  const [code, setCode] = useState("");
  const [question, setQuestion] = useState("");
  const [provider, setProvider] = useState<Provider>("gemini");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reading, setReading] = useState<Reading | null>(null);
  const [aiText, setAiText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listCommodities().then(setCommodities).catch(() => {});
    const p = (loadLS(LS.provider) as Provider) || "gemini";
    setProvider(p);
    setModel(loadLS(LS.model(p)) || defaultModel(p));
    setApiKey(loadLS(LS.key(p)) || "");
  }, []);

  const switchProvider = (p: Provider) => {
    setProvider(p);
    saveLS(LS.provider, p);
    setModel(loadLS(LS.model(p)) || defaultModel(p));
    setApiKey(loadLS(LS.key(p)) || "");
  };

  const name = commodities.find((c) => c.commodity_code === code)?.commodity_name ?? code;
  const h = hanhOf(code);
  const cc = yearCanChi(new Date().getFullYear());

  const run = async () => {
    if (busy) return;
    setError(null);
    setAiText(null);
    const r = castReading();
    setReading(r);
    if (!apiKey.trim()) {
      setError("Cắm API key để AI luận giải (quẻ + ngũ hành bên dưới đã gieo sẵn). Lấy key free: Gemini / Groq / OpenRouter.");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/ai/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          apiKey,
          system: SYSTEM,
          messages: [{ role: "user", content: buildPrompt(r, code, name, question) }],
        }),
      });
      const data = (await res.json()) as { reply?: string; error?: string };
      if (!res.ok || !data.reply) setError(data.error || "Lỗi không xác định");
      else setAiText(data.reply);
    } catch {
      setError("Không gửi được yêu cầu.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-xl border border-border bg-surface p-4">
      {/* commodity + question */}
      <div className="space-y-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Hàng hóa (để quy ngũ hành)
          <select
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm text-text outline-none focus:border-brand"
          >
            <option value="">— chọn hàng hóa (tùy chọn) —</option>
            {commodities.map((c) => (
              <option key={c.commodity_code} value={c.commodity_code}>
                {c.commodity_name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          Câu hỏi cho thầy Dịch
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            placeholder={`VD: Giá ${name || "cà phê"} 3 tháng tới lên hay xuống? Có nên trữ hàng?`}
            className="resize-y rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text outline-none focus:border-brand"
          />
        </label>
      </div>

      {/* AI config */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          AI
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
            onChange={(e) => {
              setModel(e.target.value);
              saveLS(LS.model(provider), e.target.value);
            }}
            className="w-36 rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-brand"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
          API key (lưu ở trình duyệt)
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              saveLS(LS.key(provider), e.target.value);
            }}
            placeholder={PROVIDERS.find((p) => p.id === provider)?.keyHint}
            autoComplete="off"
            className="min-w-[140px] rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-brand"
          />
        </label>
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy}
          className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {busy ? "Đang luận…" : "🔮 Gieo quẻ & luận giải"}
        </button>
      </div>

      {error ? (
        <p className="text-xs" style={{ color: "var(--danger, #dc2626)" }}>
          ⚠️ {error}
        </p>
      ) : null}

      {/* deterministic cast + ngũ hành */}
      {reading ? (
        <div className="rounded-lg border border-border bg-surface-2 p-3 text-sm">
          <p>
            <b className="text-text">Quẻ {reading.primary.name}</b> — {reading.primary.upper.nature} trên{" "}
            {reading.primary.lower.nature} · {reading.primaryLean.label}
            {reading.changed ? (
              <>
                {" "}
                ⟳ {reading.changingIndices.length} hào động → biến quẻ <b className="text-text">{reading.changed.name}</b>
              </>
            ) : (
              " · quẻ tĩnh"
            )}
          </p>
          <p className="mt-1 text-muted">
            Năm <b className="text-text">{cc.label}</b>
            {h ? (
              <>
                {" · "}
                {name} thuộc hành <b className="text-text">{h.hanh}</b> — thuận:{" "}
                <span className="text-brand">{cycleSummary(h.hanh).favorable}</span>; nghịch:{" "}
                <span style={{ color: "var(--danger, #dc2626)" }}>{cycleSummary(h.hanh).unfavorable}</span>
              </>
            ) : null}
          </p>
        </div>
      ) : null}

      {/* AI luận */}
      {aiText ? (
        <div className="whitespace-pre-wrap rounded-lg border border-brand/40 bg-brand-soft p-3 text-sm text-text">
          {aiText}
        </div>
      ) : null}

      <p className="border-t border-border pt-3 text-xs text-subtle">
        ⚠️ Luận giải Kinh Dịch / Ngũ hành chỉ để <b>tham khảo văn hoá / giải trí</b> — KHÔNG phải dự báo của model định
        lượng và KHÔNG phải lời khuyên đầu tư. Quy hành hàng hóa là gợi ý, có thể tranh luận.
      </p>
    </div>
  );
}
