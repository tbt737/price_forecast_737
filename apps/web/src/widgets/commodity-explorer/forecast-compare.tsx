"use client";

import { useEffect, useState } from "react";
import { api, type Forecast } from "@/shared/api";
import { cn } from "@/shared/lib/cn";
import { EmptyState, Skeleton } from "@/shared/ui";

const MODEL_LABEL: Record<string, string> = {
  ridge_ar: "Ridge AR",
  gbm: "XGBoost",
  gbm_cyc: "XGBoost+chu kỳ",
  naive: "naive",
};

function horizonChange(fc: Forecast, h: "30" | "90"): number | null {
  const ho = fc.horizons?.[h];
  const last = fc.last_price;
  const end = ho?.points?.[ho.points.length - 1]?.value;
  if (!ho || last == null || end == null || last === 0) return null;
  return ((end - last) / last) * 100;
}

function Trend({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-subtle">—</span>;
  const up = pct >= 0;
  return (
    <span className={cn("font-mono font-semibold", up ? "text-pos" : "text-neg")}>
      {up ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function HorizonCell({ fc, h }: { fc: Forecast; h: "30" | "90" }) {
  const ho = fc.horizons?.[h];
  if (!ho) return <td className="px-3 py-2 text-subtle">—</td>;
  const beats = ho.backtest.beats_naive;
  return (
    <td className="px-3 py-2">
      <div className="flex items-center gap-2">
        <Trend pct={horizonChange(fc, h)} />
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-medium",
            beats ? "bg-pos-soft text-pos" : "bg-surface-2 text-subtle",
          )}
          title={`backtest MAPE ${ho.backtest.mape_pct ?? "—"}% vs naive ${ho.backtest.naive_mape_pct ?? "—"}%`}
        >
          {MODEL_LABEL[ho.model_used ?? "naive"] ?? ho.model_used}
          {beats ? " ✓" : ""}
        </span>
      </div>
    </td>
  );
}

export function ForecastCompare({ codes }: { codes: string[] }) {
  const key = codes.join(",");
  const [rows, setRows] = useState<Forecast[] | null>(null);
  const [done, setDone] = useState(0);

  useEffect(() => {
    if (codes.length === 0) {
      setRows([]);
      return;
    }
    let active = true;
    setRows(null);
    setDone(0);
    (async () => {
      const out: Forecast[] = [];
      for (const c of codes) {
        const fc = await api.getForecast(c).catch(() => null);
        if (!active) return;
        if (fc) out.push(fc);
        setDone((n) => n + 1);
      }
      if (active) setRows(out);
    })();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (codes.length === 0) {
    return (
      <EmptyState
        title="Chọn hàng hóa để so sánh"
        hint="Tích vào các ô bên trái (2 hàng trở lên) để so sánh dự báo & backtest."
      />
    );
  }
  if (rows === null) {
    return (
      <div className="space-y-2">
        <p className="text-xs text-muted">
          Đang tính dự báo… {done}/{codes.length} (lần đầu mỗi hàng mất vài giây, sau đó được cache).
        </p>
        <Skeleton className="h-40" />
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-3 py-2">Hàng hóa</th>
            <th className="px-3 py-2">Giá cuối</th>
            <th className="px-3 py-2">Dự báo 30 phiên</th>
            <th className="px-3 py-2">Dự báo 90 phiên</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((fc) => (
            <tr key={fc.commodity_code} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-2">
                <span className="font-mono text-xs font-semibold">{fc.commodity_code}</span>
              </td>
              <td className="px-3 py-2 font-mono text-xs">
                {fc.available && fc.last_price != null ? (
                  <>
                    {fc.last_price.toLocaleString()} <span className="text-subtle">{fc.currency}</span>
                  </>
                ) : (
                  <span className="text-subtle">chưa có dữ liệu</span>
                )}
              </td>
              {fc.available ? (
                <>
                  <HorizonCell fc={fc} h="30" />
                  <HorizonCell fc={fc} h="90" />
                </>
              ) : (
                <td className="px-3 py-2 text-subtle" colSpan={2}>
                  {fc.reason ?? "không khả dụng"}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 px-3 text-[11px] leading-snug text-subtle">
        ▲/▼ = hướng dự báo điểm cuối so với giá hiện tại · nhãn = model thắng backtest (✓ = vượt naive). Dự báo dùng
        dữ liệu thật, không phải lời khuyên đầu tư.
      </p>
    </div>
  );
}
