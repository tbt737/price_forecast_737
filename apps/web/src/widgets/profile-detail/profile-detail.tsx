"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type CommodityDetail,
  type Forecast,
  type PriceSeries,
  type ProfileDetail as Profile,
} from "@/shared/api";
import { demoSeries } from "@/shared/lib/demo";
import { titleCase } from "@/shared/lib/format";
import { sectorMeta } from "@/shared/lib/sectors";
import { Badge, CompositionChart, PriceChart, SectorChip, Skeleton, Tabs, type TabItem } from "@/shared/ui";
import { RenderValue } from "@/widgets/profile-detail/render-value";

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function forecastErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "Dịch vụ dự báo tạm thời không khả dụng (503)";
    if (err.status === 401) return "Thiếu cấu hình khóa nội bộ cho dự báo (401)";
    return `Lỗi dự báo HTTP ${err.status}`;
  }
  return err instanceof Error ? err.message : "Không tải được dự báo";
}

function buildTabs(commodity: CommodityDetail, profile: Record<string, unknown>): TabItem[] {
  const regionKeys = Object.keys(profile).filter((k) => k.endsWith("_regions"));
  const driverKeys = Object.keys(profile).filter((k) => k.endsWith("_drivers"));
  const shown = new Set([
    "commodity_code",
    "commodity_name",
    "commodity_group",
    "base_unit",
    "default_currency",
    "notes",
    "instruments",
    "models",
    "data_sources",
    ...regionKeys,
    ...driverKeys,
  ]);
  const restKeys = Object.keys(profile)
    .filter((k) => !shown.has(k) && profile[k] != null && !(Array.isArray(profile[k]) && profile[k].length === 0))
    .sort();

  const tabs: TabItem[] = [];

  tabs.push({
    id: "instruments",
    label: "Instruments",
    count: commodity.instruments.length,
    content: <RenderValue value={commodity.instruments} />,
  });

  if (asArray(profile.models).length) {
    tabs.push({
      id: "models",
      label: "Models",
      count: asArray(profile.models).length,
      content: <RenderValue value={profile.models} />,
    });
  }

  if (regionKeys.length) {
    tabs.push({
      id: "regions",
      label: "Regions",
      count: regionKeys.reduce((s, k) => s + asArray(profile[k]).length, 0),
      content: (
        <div className="space-y-4">
          {regionKeys.map((k) => (
            <section key={k}>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-brand-text">
                {titleCase(k)}
              </h4>
              <RenderValue value={profile[k]} />
            </section>
          ))}
        </div>
      ),
    });
  }

  if (asArray(profile.data_sources).length) {
    tabs.push({
      id: "sources",
      label: "Data Sources",
      count: asArray(profile.data_sources).length,
      content: <RenderValue value={profile.data_sources} />,
    });
  }

  if (driverKeys.length) {
    tabs.push({
      id: "drivers",
      label: "Drivers",
      content: (
        <div className="space-y-4">
          {driverKeys.map((k) => (
            <section key={k}>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-brand-text">
                {titleCase(k)}
              </h4>
              <RenderValue value={profile[k]} />
            </section>
          ))}
        </div>
      ),
    });
  }

  if (restKeys.length) {
    tabs.push({
      id: "more",
      label: "More",
      content: (
        <div className="space-y-4">
          {restKeys.map((k) => (
            <section key={k}>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-brand-text">
                {titleCase(k)}
              </h4>
              <RenderValue value={profile[k]} />
            </section>
          ))}
        </div>
      ),
    });
  }

  return tabs;
}

interface Data {
  commodity: CommodityDetail;
  profile: Profile;
  prices: PriceSeries;
  forecast: Forecast | null;
  forecastError: string | null;
}
type State = { s: "loading" } | { s: "error"; m: string } | { s: "ready"; d: Data };

export function ProfileDetail({ code }: { code: string }) {
  const [state, setState] = useState<State>({ s: "loading" });

  useEffect(() => {
    let active = true;
    setState({ s: "loading" });
    (async () => {
      // Forecast is compute-heavy and SEC-2 gated — never let it fail the whole page.
      const [commodityR, profileR, pricesR, forecastR] = await Promise.allSettled([
        api.getCommodity(code),
        api.getProfile(code),
        api.getPrices(code, 730),
        api.getForecast(code),
      ]);
      if (!active) return;

      if (commodityR.status === "rejected" || profileR.status === "rejected") {
        const err =
          commodityR.status === "rejected"
            ? commodityR.reason
            : profileR.status === "rejected"
              ? profileR.reason
              : "unknown";
        setState({ s: "error", m: err instanceof Error ? err.message : "unknown" });
        return;
      }

      const emptyPrices: PriceSeries = {
        commodity_code: commodityR.value.commodity_code,
        points: [],
      };
      setState({
        s: "ready",
        d: {
          commodity: commodityR.value,
          profile: profileR.value,
          prices: pricesR.status === "fulfilled" ? pricesR.value : emptyPrices,
          forecast: forecastR.status === "fulfilled" ? forecastR.value : null,
          forecastError: forecastR.status === "rejected" ? forecastErrorMessage(forecastR.reason) : null,
        },
      });
    })();
    return () => {
      active = false;
    };
  }, [code]);

  if (state.s === "loading") {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (state.s === "error") {
    return <p className="text-sm text-neg">Lỗi tải {code}: {state.m}</p>;
  }

  const { commodity, profile: prof, prices, forecast, forecastError } = state.d;
  const p = prof.profile;
  const sector = sectorMeta(commodity.commodity_group);
  const hasRealPrices = prices.points.length > 0;
  const priceValues = hasRealPrices ? prices.points.map((pt) => pt.value) : demoSeries(commodity.commodity_code);
  const priceLabels = hasRealPrices ? prices.points.map((pt) => pt.date) : undefined;
  const fc30 = forecast?.available ? forecast.horizons?.["30"] : undefined;
  const overlay =
    hasRealPrices && fc30
      ? {
          dates: fc30.points.map((pt) => pt.date),
          value: fc30.points.map((pt) => pt.value),
          lower: fc30.points.map((pt) => pt.lower),
          upper: fc30.points.map((pt) => pt.upper),
        }
      : undefined;
  const counts = [
    { label: "Instr", value: commodity.instruments.length },
    {
      label: "Regions",
      value: Object.keys(p)
        .filter((k) => k.endsWith("_regions"))
        .reduce((s, k) => s + asArray(p[k]).length, 0),
    },
    { label: "Models", value: asArray(p.models).length },
    { label: "Sources", value: asArray(p.data_sources).length },
  ];
  const notes = typeof p.notes === "string" ? p.notes : null;

  return (
    <div className="animate-fade-in space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-2xl" aria-hidden>
            {sector.icon}
          </span>
          <h2 className="text-xl font-bold">{commodity.commodity_name}</h2>
          <span className="font-mono text-sm text-info">{commodity.commodity_code}</span>
          <SectorChip group={commodity.commodity_group} />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <span>Đơn vị: <b className="text-text">{commodity.base_unit}</b></span>
          <span>Tiền tệ: <b className="text-text">{commodity.default_currency}</b></span>
          <span>Profile <b className="text-text">v{prof.version}</b></span>
          <span>Source: <b className="text-text">{prof.source_path ?? "—"}</b></span>
        </div>
      </div>

      {forecastError ? (
        <p className="rounded-r-card border-l-2 border-neg bg-surface-2 px-3 py-2 text-sm text-muted">
          {forecastError}. Giá và hồ sơ vẫn hiển thị bình thường.
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-card border border-border bg-surface-2 p-3">
          <div className="mb-1 flex items-center justify-between text-xs text-muted">
            <span>
              {hasRealPrices
                ? `Giá ${prices.points.length} phiên · ${prices.instrument_code} (${prices.currency})`
                : "Giá 32 phiên"}
            </span>
            {hasRealPrices ? (
              <Badge tone="info">dữ liệu thật</Badge>
            ) : (
              <Badge tone="demo">DEMO · chưa ingest</Badge>
            )}
          </div>
          <PriceChart
            data={priceValues}
            labels={priceLabels}
            tone={hasRealPrices ? "real" : "demo"}
            forecast={overlay}
          />
          {overlay && fc30 ? (
            <p className="mt-1 text-[11px] leading-snug text-subtle">
              <span style={{ color: "var(--brand)" }}>┄┄</span> Dự báo 30 phiên (
              {fc30.model_used === "ridge_ar"
                ? "Ridge AR"
                : fc30.model_used === "gbm"
                  ? "XGBoost"
                  : fc30.model_used === "gbm_cyc"
                    ? "XGBoost + chu kỳ"
                    : "naive"}
              ) · backtest MAPE{" "}
              <b className="text-text">{fc30.backtest.mape_pct}%</b> (naive {fc30.backtest.naive_mape_pct}%
              {fc30.backtest.beats_naive
                ? " — thắng naive ✓"
                : " — chưa vượt naive, dùng đường naive"}
              )
            </p>
          ) : null}
        </div>
        <div className="rounded-card border border-border bg-surface-2 p-3">
          <div className="mb-1 flex items-center justify-between text-xs text-muted">
            <span>Cấu trúc profile</span>
            <Badge tone="brand">dữ liệu thật</Badge>
          </div>
          <CompositionChart items={counts} />
        </div>
      </div>

      {notes ? (
        <p className="rounded-r-card border-l-2 border-brand bg-brand-soft px-3 py-2 text-sm leading-relaxed">
          {notes}
        </p>
      ) : null}

      <Tabs items={buildTabs(commodity, p)} />
    </div>
  );
}
