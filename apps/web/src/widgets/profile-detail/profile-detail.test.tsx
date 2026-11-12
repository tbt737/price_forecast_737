import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Forecast, type PriceSeries } from "@/shared/api";
import { ProfileDetail } from "./profile-detail";

vi.mock("@/shared/api", async (original) => ({
  ...await original<typeof import("@/shared/api")>(),
  api: { getCommodity: vi.fn(), getProfile: vi.fn(), getPrices: vi.fn(), getForecast: vi.fn() },
}));
vi.mock("@/shared/ui/echart", () => ({ EChart: () => <div data-testid="chart" /> }));
vi.mock("@/shared/lib/use-chart-theme", () => ({ useChartTheme: () => ({}) }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getCommodity).mockImplementation(async (code) => ({
    commodity_code: code, commodity_name: `Asset ${code}`, commodity_group: "agriculture",
    base_unit: "kg", default_currency: "USD", instruments: [],
  }));
  vi.mocked(api.getProfile).mockResolvedValue({ commodity_code: "TEST", version: 1, profile: {} });
  vi.mocked(api.getPrices).mockResolvedValue({ commodity_code: "TEST", points: [{ date: "2026-01-01", value: 100 }] });
});
afterEach(cleanup);

describe("progressive profile loading", () => {

  it.each(["commodity", "profile"])("can retry failed %s metadata and recover the detail", async (failed) => {
    const method = failed === "commodity" ? api.getCommodity : api.getProfile;
    vi.mocked(method).mockRejectedValueOnce(new Error("Temporary metadata failure"));
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST" });
    render(<ProfileDetail code="TEST" />);
    expect(await screen.findByText(/Lỗi tải TEST: Temporary metadata failure/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử tải lại chi tiết" }));
    expect(await screen.findByText("Asset TEST")).toBeInTheDocument();
    expect(screen.queryByText(/Lỗi tải TEST/)).not.toBeInTheDocument();
    expect(api.getCommodity).toHaveBeenCalledTimes(2);
    expect(api.getProfile).toHaveBeenCalledTimes(2);
  });

  it("ignores late retry metadata after switching to another asset", async () => {
    const old = deferred<Awaited<ReturnType<typeof api.getCommodity>>>();
    vi.mocked(api.getCommodity).mockRejectedValueOnce(new Error("Temporary metadata failure")).mockReturnValueOnce(old.promise);
    vi.mocked(api.getForecast).mockImplementation(async (code) => ({ available: false, commodity_code: code }));
    const { rerender } = render(<ProfileDetail code="A" />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Thử tải lại chi tiết" }));
    expect(api.getCommodity).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: "Thử tải lại chi tiết" })).not.toBeInTheDocument();
    rerender(<ProfileDetail code="B" />);
    expect(await screen.findByText("Asset B")).toBeInTheDocument();
    await act(async () => old.resolve({ commodity_code: "A", commodity_name: "Old retry result", commodity_group: "agriculture", base_unit: "kg", default_currency: "USD", instruments: [] }));
    expect(screen.getByText("Asset B")).toBeInTheDocument();
    expect(screen.queryByText("Old retry result")).not.toBeInTheDocument();
  });

  it.each(["commodity", "profile"])("reports a failed %s without waiting for the other metadata request", async (failed) => {
    const pending = deferred<never>();
    if (failed === "commodity") {
      vi.mocked(api.getCommodity).mockRejectedValue(new Error("Metadata unavailable"));
      vi.mocked(api.getProfile).mockReturnValue(pending.promise);
    } else {
      vi.mocked(api.getProfile).mockRejectedValue(new Error("Metadata unavailable"));
      vi.mocked(api.getCommodity).mockReturnValue(pending.promise);
    }
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST" });
    render(<ProfileDetail code="TEST" />);
    expect(await screen.findByText(/Lỗi tải TEST: Metadata unavailable/)).toBeInTheDocument();
    await act(async () => pending.reject(new Error("Later metadata failure")));
    expect(screen.getByText(/Lỗi tải TEST: Metadata unavailable/)).toBeInTheDocument();
  });

  it.each(["commodity", "profile"])("ignores a stale %s failure after switching assets", async (failed) => {
    const pending = deferred<never>();
    if (failed === "commodity") vi.mocked(api.getCommodity).mockReturnValueOnce(pending.promise);
    else vi.mocked(api.getProfile).mockReturnValueOnce(pending.promise);
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST" });
    const { rerender } = render(<ProfileDetail code="A" />);
    rerender(<ProfileDetail code="B" />);
    await screen.findByText("Asset B");
    await act(async () => pending.reject(new Error("Stale metadata failure")));
    expect(screen.getByText("Asset B")).toBeInTheDocument();
    expect(screen.queryByText(/Stale metadata failure/)).not.toBeInTheDocument();
  });

  it("retries only failed prices, keeping the profile and forecast while loading", async () => {
    const retry = deferred<PriceSeries>();
    vi.mocked(api.getPrices).mockRejectedValueOnce(new Error("Offline")).mockReturnValueOnce(retry.promise);
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST", reason: "Forecast ready" });
    render(<ProfileDetail code="TEST" />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Thử tải lại giá" }));
    expect(screen.getByText("Asset TEST")).toBeInTheDocument();
    expect(screen.getByText("Đang tải giá lịch sử…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử tải lại giá" })).not.toBeInTheDocument();
    await act(async () => retry.resolve({ commodity_code: "TEST", instrument_code: "RECOVERED", points: [{ date: "2026-01-01", value: 100 }] }));
    expect(screen.getByText(/RECOVERED/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.getPrices).toHaveBeenCalledTimes(2);
    expect(api.getCommodity).toHaveBeenCalledTimes(1);
    expect(api.getProfile).toHaveBeenCalledTimes(1);
    expect(api.getForecast).toHaveBeenCalledTimes(1);
  });

  it("ignores a failed price retry after changing assets", async () => {
    const retry = deferred<PriceSeries>();
    vi.mocked(api.getPrices).mockRejectedValueOnce(new Error("Offline")).mockReturnValueOnce(retry.promise)
      .mockResolvedValue({ commodity_code: "B", instrument_code: "NEW_PRICE", points: [{ date: "2026-01-01", value: 200 }] });
    vi.mocked(api.getForecast).mockImplementation(async (code) => ({ available: false, commodity_code: code }));
    const { rerender } = render(<ProfileDetail code="A" />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Thử tải lại giá" }));
    rerender(<ProfileDetail code="B" />);
    await screen.findByText(/NEW_PRICE/);
    await act(async () => retry.reject(new Error("Late failure")));
    expect(screen.getByText("Asset B")).toBeInTheDocument();
    expect(screen.getByText(/NEW_PRICE/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows profile and forecast state before a slow price request, without demo prices", async () => {
    const prices = deferred<PriceSeries>();
    vi.mocked(api.getPrices).mockReturnValue(prices.promise);
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST", reason: "Fixture forecast ready" });
    render(<ProfileDetail code="TEST" />);
    expect(await screen.findByText("Asset TEST")).toBeInTheDocument();
    expect(await screen.findByText(/Fixture forecast ready/)).toBeInTheDocument();
    expect(screen.getByText("Đang tải giá lịch sử…")).toBeInTheDocument();
    expect(screen.queryByText(/DEMO/)).not.toBeInTheDocument();
    await act(async () => prices.resolve({ commodity_code: "TEST", points: [{ date: "2026-01-01", value: 100 }] }));
    expect(screen.queryByText("Đang tải giá lịch sử…")).not.toBeInTheDocument();
    expect(screen.getByText(/Giá 1 phiên/)).toBeInTheDocument();
  });

  it("reports failed prices without hiding the profile or replacing them with demo data", async () => {
    vi.mocked(api.getPrices).mockRejectedValue(new Error("Fixture failure"));
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST" });
    render(<ProfileDetail code="TEST" />);
    expect(await screen.findByText("Asset TEST")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Không tải được giá lịch sử");
    expect(screen.queryByText(/DEMO/)).not.toBeInTheDocument();
  });

  it("ignores old prices after switching to another asset", async () => {
    const oldPrices = deferred<PriceSeries>();
    vi.mocked(api.getPrices).mockImplementation((code) => code === "A" ? oldPrices.promise : Promise.resolve({ commodity_code: code, instrument_code: "NEW_PRICE", points: [{ date: "2026-01-01", value: 200 }] }));
    vi.mocked(api.getForecast).mockImplementation(async (code) => ({ available: false, commodity_code: code }));
    const { rerender } = render(<ProfileDetail code="A" />);
    await screen.findByText("Asset A");
    rerender(<ProfileDetail code="B" />);
    await screen.findByText(/NEW_PRICE/);
    await act(async () => oldPrices.resolve({ commodity_code: "A", instrument_code: "OLD_PRICE", points: [{ date: "2026-01-01", value: 100 }] }));
    expect(screen.getByText("Asset B")).toBeInTheDocument();
    expect(screen.queryByText(/OLD_PRICE/)).not.toBeInTheDocument();
    expect(screen.getByText(/NEW_PRICE/)).toBeInTheDocument();
  });
  it("shows historical data while the forecast is still computing, then reports failure", async () => {
    const task = deferred<Forecast>();
    vi.mocked(api.getForecast).mockReturnValue(task.promise);
    render(<ProfileDetail code="TEST" />);
    expect(await screen.findByText("Asset TEST")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Đang tính dự báo");
    await act(async () => task.reject(new Error("Forecast unavailable")));
    expect(screen.getByText(/Forecast unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Asset TEST")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("ignores a previous asset's late forecast after switching assets", async () => {
    const first = deferred<Forecast>();
    const second = deferred<Forecast>();
    vi.mocked(api.getForecast).mockImplementation((code) => code === "A" ? first.promise : second.promise);
    const { rerender } = render(<ProfileDetail code="A" />);
    await screen.findByText("Asset A");
    rerender(<ProfileDetail code="B" />);
    await screen.findByText("Asset B");
    await act(async () => first.reject(new Error("Stale failure")));
    expect(screen.queryByText(/Stale failure/)).not.toBeInTheDocument();
    await act(async () => second.resolve({ available: false, commodity_code: "B", reason: "Insufficient history" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Insufficient history"));
  });
});
