"use client";

import { useEffect, useState } from "react";
import { api, type Commodity, type Health, type Ready } from "@/shared/api";
import { Badge, Card, CardBody, CardHeader, Stat } from "@/shared/ui";

interface Overview {
  health: Health;
  ready: Ready;
  commodities: Commodity[];
  profiles: number;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: Overview };

export default function HomePage() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [health, ready, commodities, profiles] = await Promise.all([
          api.health(),
          api.ready(),
          api.listCommodities(),
          api.listProfiles(),
        ]);
        if (active) {
          setState({ status: "ready", data: { health, ready, commodities, profiles: profiles.length } });
        }
      } catch (e) {
        if (active) setState({ status: "error", message: e instanceof Error ? e.message : "unknown" });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (state.status === "loading") {
    return <p className="text-sm text-muted">Đang kết nối API…</p>;
  }

  if (state.status === "error") {
    return (
      <Card>
        <CardHeader>Không kết nối được API</CardHeader>
        <CardBody className="text-sm text-muted">
          {state.message}
          <p className="mt-2">
            Khởi động backend (FastAPI cổng 8000) và đặt <code>API_PROXY_TARGET</code> nếu cần.
          </p>
        </CardBody>
      </Card>
    );
  }

  const { health, ready, commodities, profiles } = state.data;
  const dbUp = ready.database === "up";

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-center gap-3">
        <Badge tone="brand">API v{health.version}</Badge>
        <Badge tone={dbUp ? "brand" : "demo"}>DB: {ready.database}</Badge>
        <Badge tone="info">status: {health.status}</Badge>
      </section>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Commodities" value={commodities.length} />
        <Stat label="Profiles" value={profiles} />
        <Stat label="Groups" value={new Set(commodities.map((c) => c.commodity_group)).size} />
      </section>

      <Card>
        <CardHeader>Commodities</CardHeader>
        <CardBody className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {commodities.map((c) => (
            <div
              key={c.commodity_code}
              className="flex items-baseline gap-2 rounded border border-border bg-surface-2 px-3 py-2"
            >
              <span className="font-mono text-sm font-semibold">{c.commodity_code}</span>
              <span className="text-xs text-muted">{c.commodity_name}</span>
              <span className="ml-auto text-[10px] text-subtle">{c.commodity_group}</span>
            </div>
          ))}
        </CardBody>
      </Card>

      <p className="text-xs text-subtle">
        P0 scaffold — chỉ nền (Next.js + TS + Tailwind + tokens/theme + API client). Bảng/biểu đồ/chi
        tiết sẽ thêm ở các phase sau.
      </p>
    </div>
  );
}
