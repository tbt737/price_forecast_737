"use client";

import { useState } from "react";
import { cn } from "@/shared/lib/cn";
import { Card, CardBody, CardHeader } from "@/shared/ui";
import { castReading, type Line, type MarketLean, type Reading } from "@/widgets/iching/iching";

const TONE_CLASS: Record<MarketLean["tone"], string> = {
  up: "bg-brand-soft text-brand",
  down: "text-white",
  flat: "bg-surface-2 text-muted",
};

function LeanBadge({ lean }: { lean: MarketLean }) {
  return (
    <span
      className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", TONE_CLASS[lean.tone])}
      style={lean.tone === "down" ? { background: "var(--danger, #dc2626)" } : undefined}
    >
      {lean.label}
    </span>
  );
}

/** Six lines drawn top (line 6) → bottom (line 1), the traditional reading order. */
function HexLines({ lines, changing }: { lines: Line[]; changing: number[] }) {
  return (
    <div className="flex flex-col gap-1.5" aria-hidden>
      {[...lines].map((_, i) => lines[lines.length - 1 - i]).map((line, idx) => {
        const realIdx = lines.length - 1 - idx;
        const isChanging = changing.includes(realIdx);
        return (
          <div key={realIdx} className="flex items-center justify-center gap-1.5">
            {line.yang ? (
              <span className="h-2 w-24 rounded-sm bg-text" />
            ) : (
              <>
                <span className="h-2 w-[44px] rounded-sm bg-text" />
                <span className="h-2 w-[44px] rounded-sm bg-text" />
              </>
            )}
            {isChanging ? <span className="ml-1 text-xs text-demo">⟳ động</span> : null}
          </div>
        );
      })}
    </div>
  );
}

export function IchingOracle({ commodityName }: { commodityName?: string | null }) {
  const [reading, setReading] = useState<Reading | null>(null);
  const [casting, setCasting] = useState(false);

  const cast = () => {
    setCasting(true);
    // brief suspense before revealing the quẻ
    window.setTimeout(() => {
      setReading(castReading());
      setCasting(false);
    }, 500);
  };

  const subject = commodityName ? `giá ${commodityName}` : "mặt hàng đang chọn";

  return (
    <Card>
      <CardHeader
        title="🔮 Gieo quẻ Kinh Dịch"
        right={
          <button
            type="button"
            onClick={cast}
            disabled={casting}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {casting ? "Đang gieo…" : reading ? "Gieo lại" : "Gieo quẻ"}
          </button>
        }
      />
      <CardBody>
        {!reading ? (
          <p className="py-6 text-center text-sm text-muted">
            Bấm <b className="text-text">Gieo quẻ</b> để xin một quẻ cho {subject} (tung 6 hào kiểu 3 đồng xu).
          </p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start sm:gap-6">
              <div className="shrink-0">
                <HexLines lines={reading.lines} changing={reading.changingIndices} />
              </div>
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-2xl" aria-hidden>
                    {reading.primary.upper.symbol}
                    {reading.primary.lower.symbol}
                  </span>
                  <span className="text-lg font-bold text-text">Quẻ {reading.primary.name}</span>
                  <LeanBadge lean={reading.primaryLean} />
                </div>
                <p className="text-sm text-muted">
                  <b className="text-text">{reading.primary.upper.nature}</b> trên{" "}
                  <b className="text-text">{reading.primary.lower.nature}</b> ({reading.primary.upper.name}/
                  {reading.primary.lower.name}) · {reading.primary.yangCount} hào dương.
                </p>
                {reading.changed ? (
                  <p className="text-sm text-muted">
                    ⟳ <b className="text-text">{reading.changingIndices.length} hào động</b> → biến sang quẻ{" "}
                    <b className="text-text">{reading.changed.name}</b>{" "}
                    {reading.changedLean ? <LeanBadge lean={reading.changedLean} /> : null} — hàm ý xu thế đang
                    dịch chuyển.
                  </p>
                ) : (
                  <p className="text-sm text-subtle">Không có hào động — quẻ tĩnh, thế cục giữ nguyên.</p>
                )}
              </div>
            </div>
          </div>
        )}
        <p className="mt-4 border-t border-border pt-3 text-xs text-subtle">
          ⚠️ Gieo quẻ chỉ để <b>tham khảo văn hoá / giải trí</b> — KHÔNG phải dự báo của model định lượng, KHÔNG
          phải lời khuyên đầu tư. Quyết định mua/bán xin dựa trên phân tích thật.
        </p>
      </CardBody>
    </Card>
  );
}
