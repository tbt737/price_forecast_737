"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, type Commodity, type Stats } from "@/shared/api";
import { cn } from "@/shared/lib/cn";
import { filterByGroup, type GroupScope } from "@/shared/lib/filter-group";
import { sectorMeta } from "@/shared/lib/sectors";
import { Card, CardBody, CardHeader, EmptyState, SectorChip, Skeleton, Stat } from "@/shared/ui";
import { ForecastCompare } from "@/widgets/commodity-explorer/forecast-compare";
import { ProfileDetail } from "@/widgets/profile-detail";

interface Loaded {
  stats: Stats;
  commodities: Commodity[];
}
type State = { s: "loading" } | { s: "error"; m: string } | { s: "ready"; d: Loaded };

interface ExplorerProps extends GroupScope {
  /** Hide the platform-wide stat row (it counts every asset class). */
  showStats?: boolean;
  /** Header label of the list card (e.g. "Cổ phiếu" on the stocks page). */
  listLabel?: string;
}

export function CommodityExplorer({ group, excludeGroup, showStats = true, listLabel = "Commodities" }: ExplorerProps = {}) {
  const [state, setState] = useState<State>({ s: "loading" });
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [compareMode, setCompareMode] = useState(false);
  const [compareSet, setCompareSet] = useState<Set<string>>(new Set());
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState<string | null>(null);

  const detailRef = useRef<HTMLDivElement>(null);

  const toggleCompare = (code: string) =>
    setCompareSet((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  // On phones the detail sits below the (stacked) list — scroll it into view on pick.
  const selectCommodity = (code: string) => {
    setSelected(code);
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  };

  // Pull the latest stats + commodities from the API (which reads the database
  // live, cache:"no-store"). Used on mount and by the manual "Đồng bộ" button —
  // a manual sync keeps the current view (no skeleton) and only toggles a spinner.
  const loadData = useCallback(async (opts?: { manual?: boolean }) => {
    if (opts?.manual) setSyncing(true);
    try {
      const [stats, commodities] = await Promise.all([api.stats(), api.listCommodities()]);
      setState({ s: "ready", d: { stats, commodities } });
      const scoped = filterByGroup(commodities, { group, excludeGroup });
      setSelected((prev) => prev ?? scoped[0]?.commodity_code ?? null);
      setLastSync(new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }));
    } catch (e) {
      // On a manual re-sync, keep the data already on screen rather than blanking it.
      setState((prev) => (prev.s === "ready" ? prev : { s: "error", m: e instanceof Error ? e.message : "unknown" }));
    } finally {
      if (opts?.manual) setSyncing(false);
    }
  }, [group, excludeGroup]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filtered = useMemo(() => {
    const all = filterByGroup(state.s === "ready" ? state.d.commodities : [], { group, excludeGroup });
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (c) =>
        c.commodity_code.toLowerCase().includes(q) ||
        c.commodity_name.toLowerCase().includes(q) ||
        c.commodity_group.toLowerCase().includes(q),
    );
  }, [state, query, group, excludeGroup]);

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
      {showStats ? (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Commodities" value={stats.commodities} accent="var(--brand)" />
          <Stat label="Instruments" value={stats.instruments} accent="var(--info)" />
          <Stat label="Regions" value={stats.regions} accent="var(--sector-agriculture)" />
          <Stat label="Data sources" value={stats.data_sources} accent="var(--sector-metal)" />
          <Stat label="Fact rows" value={stats.fact_rows} hint="chưa ingest" accent="var(--demo)" />
        </section>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
          <button
            type="button"
            onClick={() => setCompareMode(false)}
            aria-pressed={!compareMode}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              !compareMode ? "bg-brand text-white shadow-sm" : "text-muted hover:text-text",
            )}
          >
            📋 Khám phá
          </button>
          <button
            type="button"
            onClick={() => setCompareMode(true)}
            aria-pressed={compareMode}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              compareMode ? "bg-brand text-white shadow-sm" : "text-muted hover:text-text",
            )}
          >
            ⚖ So sánh hàng hóa
          </button>
        </div>
        {compareMode ? (
          <span className="text-xs text-muted">
            Tích chọn ít nhất 2 mặt hàng để so sánh dự báo · đang chọn{" "}
            <b className="text-text">{compareSet.size}</b>
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          {lastSync ? (
            <span className="hidden text-xs text-subtle sm:inline">Đồng bộ lúc {lastSync}</span>
          ) : null}
          <button
            type="button"
            onClick={() => void loadData({ manual: true })}
            disabled={syncing}
            title="Kéo lại dữ liệu mới nhất từ database"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm font-medium text-text transition-colors hover:border-brand disabled:opacity-60"
          >
            <span className={cn("text-base leading-none", syncing && "animate-spin")} aria-hidden>
              🔄
            </span>
            {syncing ? "Đang đồng bộ…" : "Đồng bộ dữ liệu"}
          </button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
        <Card className="self-start">
          <CardHeader
            title={compareMode ? `So sánh · ${compareSet.size} chọn` : `${listLabel} · ${filtered.length}`}
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
          <div className="max-h-[48vh] overflow-y-auto lg:max-h-[68vh]">
            {filtered.map((c) => {
              const on = compareMode ? compareSet.has(c.commodity_code) : c.commodity_code === selected;
              const s = sectorMeta(c.commodity_group);
              return (
                <button
                  key={c.commodity_code}
                  onClick={() =>
                    compareMode ? toggleCompare(c.commodity_code) : selectCommodity(c.commodity_code)
                  }
                  className={cn(
                    "flex w-full items-center gap-2 border-b border-border/60 px-4 py-2.5 text-left transition-colors last:border-0 hover:bg-surface-2",
                    on && "bg-brand-soft",
                  )}
                  style={on ? { boxShadow: "inset 3px 0 0 var(--brand)" } : undefined}
                >
                  {compareMode ? (
                    <input
                      type="checkbox"
                      checked={on}
                      readOnly
                      tabIndex={-1}
                      aria-hidden
                      className="h-3.5 w-3.5 shrink-0 accent-brand"
                    />
                  ) : null}
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

        <div ref={detailRef} className="scroll-mt-16">
          <Card>
          <CardHeader
            title={compareMode ? "So sánh dự báo" : "Chi tiết profile"}
            right={
              compareMode ? (
                compareSet.size > 0 ? (
                  <button
                    type="button"
                    onClick={() => setCompareSet(new Set())}
                    className="text-xs font-medium text-info hover:underline"
                  >
                    Bỏ chọn ({compareSet.size})
                  </button>
                ) : null
              ) : selected ? (
                <Link href={`/commodities/${selected}`} className="text-xs font-medium text-info hover:underline">
                  Mở trang riêng ↗
                </Link>
              ) : null
            }
          />
          <CardBody>
            {compareMode ? (
              <ForecastCompare codes={[...compareSet]} />
            ) : selected ? (
              <ProfileDetail code={selected} />
            ) : (
              <EmptyState title="Chọn một mặt hàng" hint="Bấm vào một mặt hàng trong danh sách để xem hồ sơ chi tiết." />
            )}
          </CardBody>
          </Card>
        </div>
      </div>

    </div>
  );
}
