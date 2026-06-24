"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type Commodity, type Stats } from "@/shared/api";
import { cn } from "@/shared/lib/cn";
import { sectorMeta } from "@/shared/lib/sectors";
import { Card, CardBody, CardHeader, EmptyState, SectorChip, Skeleton, Stat } from "@/shared/ui";
import { ProfileDetail } from "@/widgets/profile-detail";

interface Loaded {
  stats: Stats;
  commodities: Commodity[];
}
type State = { s: "loading" } | { s: "error"; m: string } | { s: "ready"; d: Loaded };

export function CommodityExplorer() {
  const [state, setState] = useState<State>({ s: "loading" });
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [stats, commodities] = await Promise.all([api.stats(), api.listCommodities()]);
        if (!active) return;
        setState({ s: "ready", d: { stats, commodities } });
        setSelected(commodities[0]?.commodity_code ?? null);
      } catch (e) {
        if (active) setState({ s: "error", m: e instanceof Error ? e.message : "unknown" });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const all = state.s === "ready" ? state.d.commodities : [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (c) =>
        c.commodity_code.toLowerCase().includes(q) ||
        c.commodity_name.toLowerCase().includes(q) ||
        c.commodity_group.toLowerCase().includes(q),
    );
  }, [state, query]);

  if (state.s === "loading") {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-[60vh]" />
      </div>
    );
  }
  if (state.s === "error") {
    return (
      <Card>
        <CardHeader title="Không kết nối được API" />
        <CardBody className="text-sm text-muted">
          {state.m}. Khởi động backend (FastAPI cổng 8000).
        </CardBody>
      </Card>
    );
  }

  const { stats } = state.d;

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Commodities" value={stats.commodities} accent="var(--brand)" />
        <Stat label="Instruments" value={stats.instruments} accent="var(--info)" />
        <Stat label="Regions" value={stats.regions} accent="var(--sector-agriculture)" />
        <Stat label="Data sources" value={stats.data_sources} accent="var(--sector-metal)" />
        <Stat label="Fact rows" value={stats.fact_rows} hint="chưa ingest" accent="var(--demo)" />
      </section>

      <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
        <Card className="self-start">
          <CardHeader
            title={`Commodities · ${filtered.length}`}
            right={
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Tìm…"
                aria-label="Tìm commodity"
                className="w-28 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs outline-none placeholder:text-subtle focus:w-36 focus:border-brand"
              />
            }
          />
          <div className="max-h-[68vh] overflow-y-auto">
            {filtered.map((c) => {
              const on = c.commodity_code === selected;
              const s = sectorMeta(c.commodity_group);
              return (
                <button
                  key={c.commodity_code}
                  onClick={() => setSelected(c.commodity_code)}
                  className={cn(
                    "flex w-full items-center gap-2 border-b border-border/60 px-4 py-2.5 text-left transition-colors last:border-0 hover:bg-surface-2",
                    on && "bg-brand-soft",
                  )}
                  style={on ? { boxShadow: "inset 3px 0 0 var(--brand)" } : undefined}
                >
                  <span aria-hidden>{s.icon}</span>
                  <span className="font-mono text-sm font-semibold">{c.commodity_code}</span>
                  <span className="truncate text-xs text-muted">{c.commodity_name}</span>
                  <span className="ml-auto shrink-0">
                    <SectorChip group={c.commodity_group} withIcon={false} />
                  </span>
                </button>
              );
            })}
            {filtered.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-subtle">Không có kết quả cho “{query}”.</p>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Chi tiết profile"
            right={
              selected ? (
                <Link href={`/commodities/${selected}`} className="text-xs font-medium text-info hover:underline">
                  Mở trang riêng ↗
                </Link>
              ) : null
            }
          />
          <CardBody>
            {selected ? (
              <ProfileDetail code={selected} />
            ) : (
              <EmptyState title="Chọn một commodity" hint="Bấm vào một hàng ở danh sách bên trái để xem hồ sơ chi tiết." />
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
