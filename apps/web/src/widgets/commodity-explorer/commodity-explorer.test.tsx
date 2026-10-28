import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Stats } from "@/shared/api";
import { CommodityExplorer } from "./commodity-explorer";

vi.mock("@/shared/api", () => ({ api: { stats: vi.fn(), listCommodities: vi.fn() } }));
vi.mock("@/widgets/profile-detail", () => ({ ProfileDetail: ({ code }: { code: string }) => <div>Detail {code}</div> }));
vi.mock("@/widgets/commodity-explorer/forecast-compare", () => ({ ForecastCompare: () => null }));

const assets = [{ commodity_code: "TEST", commodity_name: "Research asset", commodity_group: "agriculture", base_unit: "kg", default_currency: "USD" }];
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("explorer loading", () => {
  it("skips hidden system counts on mount and manual refresh", async () => {
    vi.mocked(api.stats).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer showStats={false} />);
    await screen.findByText("Detail TEST");
    expect(api.stats).not.toHaveBeenCalled();
    const refresh = screen.getByRole("button", { name: /Đồng bộ dữ liệu/ });
    fireEvent.click(refresh);
    await waitFor(() => expect(api.listCommodities).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(refresh).toBeEnabled());
    expect(api.stats).not.toHaveBeenCalled();
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });

  it("loads counts when the stats section becomes visible", async () => {
    vi.mocked(api.stats).mockResolvedValue({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 12345 });
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    const { rerender } = render(<CommodityExplorer showStats={false} />);
    await screen.findByText("Detail TEST");
    expect(api.stats).not.toHaveBeenCalled();
    rerender(<CommodityExplorer showStats />);
    await waitFor(() => expect(api.stats).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Fact rows")).toBeInTheDocument();
  });
  it("renders asset details without waiting for expensive system counts", async () => {
    let resolve!: (stats: Stats) => void;
    vi.mocked(api.stats).mockReturnValue(new Promise((done) => { resolve = done; }));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer />);
    expect(await screen.findByText("Detail TEST")).toBeInTheDocument();
    expect(screen.getByText(/Thống kê chưa sẵn sàng/)).toBeInTheDocument();
    await act(async () => resolve({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 100 }));
    expect(screen.queryByText(/Thống kê chưa sẵn sàng/)).not.toBeInTheDocument();
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });

  it("keeps the asset explorer usable when statistics fail", async () => {
    vi.mocked(api.stats).mockRejectedValue(new Error("Stats unavailable"));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer />);
    expect(await screen.findByText("Detail TEST")).toBeInTheDocument();
    expect(screen.queryByText("Không kết nối được API")).not.toBeInTheDocument();
  });
});
