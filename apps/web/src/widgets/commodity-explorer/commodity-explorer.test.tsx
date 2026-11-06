import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Stats } from "@/shared/api";
import { CommodityExplorer } from "./commodity-explorer";

vi.mock("@/shared/api", () => ({ api: { stats: vi.fn(), listCommodities: vi.fn() } }));
vi.mock("@/widgets/profile-detail", () => ({ ProfileDetail: ({ code }: { code: string }) => <div>Detail {code}</div> }));
vi.mock("@/widgets/commodity-explorer/forecast-compare", () => ({ ForecastCompare: ({ codes }: { codes: string[] }) => <div>Compare {codes.join(",")}</div> }));

const assets = [{ commodity_code: "TEST", commodity_name: "Research asset", commodity_group: "agriculture", base_unit: "kg", default_currency: "USD" }];
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("explorer loading", () => {

  it.each([0, 100])("shows the fact row count %i without inferring ingest status", async (count) => {
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    vi.mocked(api.stats).mockResolvedValue({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: count });
    render(<CommodityExplorer />);
    const label = await screen.findByText("Fact rows");
    expect(label.parentElement).toHaveTextContent(String(count));
    expect(screen.queryByText("chưa ingest")).not.toBeInTheDocument();
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });

  it.each([
    { name: "preserves an available selection", remaining: ["A", "B"], expected: "B" },
    { name: "replaces a removed selection", remaining: ["A"], expected: "A" },
    { name: "clears selection for an empty list", remaining: [] as string[], expected: null },
  ])("$name after refresh", async ({ remaining, expected }) => {
    const choices = ["A", "B"].map((code) => ({ ...assets[0], commodity_code: code, commodity_name: `Asset ${code}` }));
    vi.mocked(api.listCommodities).mockResolvedValueOnce(choices)
      .mockResolvedValueOnce(choices.filter((c) => remaining.includes(c.commodity_code)));
    render(<CommodityExplorer showStats={false} />);
    await screen.findByText("Detail A");
    fireEvent.click(screen.getByRole("button", { name: /B Asset B/ }));
    expect(screen.getByText("Detail B")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Đồng bộ dữ liệu/ }));
    await waitFor(() => expect(api.listCommodities).toHaveBeenCalledTimes(2));
    if (expected) expect(await screen.findByText(`Detail ${expected}`)).toBeInTheDocument();
    else {
      expect(await screen.findByText("Chọn một mặt hàng")).toBeInTheDocument();
      expect(screen.queryByText("Detail B")).not.toBeInTheDocument();
    }
  });

  it("removes unavailable assets from comparison after refresh", async () => {
    const choices = ["A", "B"].map((code) => ({ ...assets[0], commodity_code: code, commodity_name: `Asset ${code}` }));
    vi.mocked(api.listCommodities).mockResolvedValueOnce(choices).mockResolvedValueOnce([choices[0]]);
    render(<CommodityExplorer showStats={false} />);
    await screen.findByText("Detail A");
    fireEvent.click(screen.getByRole("button", { name: /So sánh hàng hóa/ }));
    for (const code of ["A", "B"]) fireEvent.click(screen.getByRole("button", { name: new RegExp(`${code} Asset ${code}`) }));
    expect(screen.getByText("Compare A,B")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Đồng bộ dữ liệu/ }));
    expect(await screen.findByText("Compare A")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bỏ chọn (1)" })).toBeInTheDocument();
  });

  it("reports a failed refresh while keeping existing data, then clears the notice on recovery", async () => {
    vi.mocked(api.stats).mockResolvedValue({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 100 });
    vi.mocked(api.listCommodities).mockResolvedValueOnce(assets)
      .mockRejectedValueOnce(new Error("Fixture unavailable")).mockResolvedValueOnce(assets);
    render(<CommodityExplorer />);
    await screen.findByText("Detail TEST");
    fireEvent.click(screen.getByRole("button", { name: /Đồng bộ dữ liệu/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Đang hiển thị dữ liệu đã tải trước đó");
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: /Đồng bộ dữ liệu/ });
    await waitFor(() => expect(refresh).toBeEnabled());
    fireEvent.click(refresh);
    await waitFor(() => expect(api.listCommodities).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(refresh).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });

  it("finishes manual list refresh before slow optional statistics", async () => {
    let resolveStats!: (stats: Stats) => void;
    const stats: Stats = { commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 100 };
    vi.mocked(api.stats).mockResolvedValueOnce(stats)
      .mockReturnValueOnce(new Promise((resolve) => { resolveStats = resolve; }));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer />);
    await screen.findByText("Fact rows");
    const refresh = screen.getByRole("button", { name: /Đồng bộ dữ liệu/ });
    fireEvent.click(refresh);
    await waitFor(() => expect(api.listCommodities).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(refresh).toBeEnabled());
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
    expect(screen.getByText(/Đang tải thống kê hệ thống/)).toBeInTheDocument();
    await act(async () => resolveStats({ ...stats, fact_rows: 300 }));
    expect(screen.getByText("Fact rows")).toBeInTheDocument();
    expect(screen.queryByText(/Đang tải thống kê hệ thống/)).not.toBeInTheDocument();
  });

  it("recovers from an initial list failure and permits retrying another failure", async () => {
    vi.mocked(api.stats).mockResolvedValue({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 100 });
    vi.mocked(api.listCommodities).mockRejectedValueOnce(new Error("Fixture unavailable"))
      .mockRejectedValueOnce(new Error("Still unavailable")).mockResolvedValueOnce(assets);
    render(<CommodityExplorer />);
    await screen.findByText("Không kết nối được API");
    const retry = screen.getByRole("button", { name: "Thử lại kết nối" });
    expect(screen.getByRole("alert")).toHaveTextContent("Không tải được danh sách mặt hàng");
    fireEvent.click(retry);
    await waitFor(() => expect(api.listCommodities).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Thử lại kết nối" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Thử lại kết nối" }));
    expect(await screen.findByText("Detail TEST")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.listCommodities).toHaveBeenCalledTimes(3);
  });

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
    expect(screen.getByText(/Đang tải thống kê hệ thống/)).toBeInTheDocument();
    expect(screen.getByLabelText("Thống kê hệ thống")).toHaveAttribute("aria-busy", "true");
    await act(async () => resolve({ commodities: 1, profiles: 1, instruments: 1, regions: 1, data_sources: 1, fact_rows: 100 }));
    expect(screen.queryByText(/Đang tải thống kê hệ thống/)).not.toBeInTheDocument();
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });

  it("keeps the asset explorer usable when statistics fail", async () => {
    vi.mocked(api.stats).mockRejectedValue(new Error("Stats unavailable"));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer />);
    expect(await screen.findByText("Detail TEST")).toBeInTheDocument();
    expect(screen.queryByText("Không kết nối được API")).not.toBeInTheDocument();
  });

  it("stops showing loading placeholders after statistics fail", async () => {
    vi.mocked(api.stats).mockRejectedValue(new Error("Stats unavailable"));
    vi.mocked(api.listCommodities).mockResolvedValue(assets);
    render(<CommodityExplorer />);
    await screen.findByText("Detail TEST");
    const counts = screen.getByLabelText("Thống kê hệ thống");
    await waitFor(() => expect(counts.querySelectorAll(".skeleton")).toHaveLength(0));
    expect(counts).toHaveAttribute("aria-busy", "false");
    expect(counts).toHaveTextContent("Thống kê chưa sẵn sàng");
  });

  it("stops superseded statistics loading when the next list refresh fails", async () => {
    vi.mocked(api.stats).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.listCommodities).mockResolvedValueOnce(assets).mockRejectedValueOnce(new Error("Refresh unavailable"));
    render(<CommodityExplorer />);
    await screen.findByText("Detail TEST");
    const counts = screen.getByLabelText("Thống kê hệ thống");
    expect(counts).toHaveAttribute("aria-busy", "true");
    fireEvent.click(screen.getByRole("button", { name: /Đồng bộ dữ liệu/ }));
    await screen.findByRole("alert");
    expect(counts).toHaveAttribute("aria-busy", "false");
    expect(counts.querySelectorAll(".skeleton")).toHaveLength(0);
    expect(screen.getByText("Detail TEST")).toBeInTheDocument();
  });
});
