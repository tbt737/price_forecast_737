import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Forecast, type PriceSeries } from "@/shared/api";
import { ForecastCompare } from "./forecast-compare";

vi.mock("@/shared/api", () => ({ api: { getForecast: vi.fn(), getPrices: vi.fn() } }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const forecast = (code: string): Forecast => ({ available: true, commodity_code: code, last_price: 100 });
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("progressive forecast comparison", () => {

  it("starts queued forecasts before optional prices while keeping at most two requests active", async () => {
    const forecasts = [deferred<Forecast>(), deferred<Forecast>(), deferred<Forecast>()];
    const prices = [deferred<PriceSeries>(), deferred<PriceSeries>()];
    const calls: string[] = [];
    let active = 0;
    let peak = 0;
    function track<T>(label: string, promise: Promise<T>): Promise<T> {
      calls.push(label);
      active += 1;
      peak = Math.max(peak, active);
      return promise.finally(() => { active -= 1; });
    }
    vi.mocked(api.getForecast).mockImplementation((code) => track(`forecast:${code}`, forecasts[["A", "B", "C"].indexOf(code)].promise));
    vi.mocked(api.getPrices).mockImplementation((code) => track(`prices:${code}`, prices[["A", "B"].indexOf(code)].promise));
    render(<ForecastCompare codes={["A", "B", "C"]} />);
    expect(calls).toEqual(["forecast:A", "forecast:B"]);
    await act(async () => forecasts[0].resolve({ available: false, commodity_code: "A", reason: "need >= 252 positive prices, have 100" }));
    expect(screen.getByText(/100\/252 phiên/)).toBeInTheDocument();
    expect(calls).toEqual(["forecast:A", "forecast:B", "forecast:C"]);
    await act(async () => forecasts[1].resolve({ available: false, commodity_code: "B", reason: "need >= 252 positive prices, have 101" }));
    expect(calls).toEqual(["forecast:A", "forecast:B", "forecast:C", "prices:A"]);
    await act(async () => forecasts[2].resolve(forecast("C")));
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(calls.at(-1)).toBe("prices:B");
    expect(peak).toBe(2);
    await act(async () => {
      prices[0].resolve({ commodity_code: "A", points: [{ date: "2026-01-01", value: 50 }] });
      prices[1].reject(new Error("Unavailable"));
    });
    expect(screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent)).toEqual(["A", "B", "C"]);
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText("chưa có dữ liệu")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(active).toBe(0);
  });

  it.each(["success", "failure"])("shows the history result before fallback price %s", async (outcome) => {
    const prices = deferred<PriceSeries>();
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST", reason: "need >= 252 positive prices, have 100" });
    vi.mocked(api.getPrices).mockReturnValue(prices.promise);
    render(<ForecastCompare codes={["TEST"]} />);
    expect(await screen.findByText(/100\/252 phiên/)).toBeInTheDocument();
    expect(screen.getByText("Đang tải giá…")).toBeInTheDocument();
    await act(async () => {
      if (outcome === "success") prices.resolve({ commodity_code: "TEST", currency: "USD", points: [{ date: "2026-01-01", value: 50 }] });
      else prices.reject(new Error("Price unavailable"));
    });
    expect(screen.getByText(/100\/252 phiên/)).toBeInTheDocument();
    expect(screen.queryByText("Đang tải giá…")).not.toBeInTheDocument();
    if (outcome === "success") expect(screen.getByText("50")).toBeInTheDocument();
    else expect(screen.getByText("chưa có dữ liệu")).toBeInTheDocument();
    expect(api.getForecast).toHaveBeenCalledTimes(1);
    expect(api.getPrices).toHaveBeenCalledTimes(1);
  });

  it("reports zero available history without claiming the price source is missing", async () => {
    vi.mocked(api.getForecast).mockResolvedValue({ available: false, commodity_code: "TEST", reason: "need >= 252 positive prices, have 0" });
    render(<ForecastCompare codes={["TEST"]} />);
    expect(await screen.findByText(/0\/252 phiên/)).toBeInTheDocument();
    expect(screen.getByText(/Chưa đủ lịch sử để dự báo/)).toBeInTheDocument();
    expect(screen.queryByText("Chưa có nguồn dữ liệu giá")).not.toBeInTheDocument();
    expect(api.getPrices).not.toHaveBeenCalled();
  });

  it("marks a forecast anchored on a stale price and leaves a current one unmarked", async () => {
    vi.mocked(api.getForecast).mockImplementation(async (code) => code === "OLD"
      ? { ...forecast(code), last_date: "2025-06-30", data_age_days: 499, data_stale: true }
      : { ...forecast(code), last_date: "2026-11-10", data_age_days: 1, data_stale: false });
    render(<ForecastCompare codes={["OLD", "NEW"]} />);
    expect(await screen.findByText(/dữ liệu cũ · 2025-06-30 \(499 ngày\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/dữ liệu cũ ·/)).toHaveLength(1);
  });

  it("limits work to two, displays a fast result before a slow one, and keeps selection order", async () => {
    const tasks = [deferred<Forecast>(), deferred<Forecast>(), deferred<Forecast>()];
    vi.mocked(api.getForecast).mockImplementation((code) => tasks[["A", "B", "C"].indexOf(code)].promise);
    render(<ForecastCompare codes={["A", "B", "C"]} />);
    expect(api.getForecast).toHaveBeenCalledTimes(2);
    await act(async () => tasks[1].resolve(forecast("B")));
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("A")).not.toBeInTheDocument();
    expect(api.getForecast).toHaveBeenCalledTimes(3);
    await act(async () => tasks[0].resolve(forecast("A")));
    expect(screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent)).toEqual(["A", "B"]);
    await act(async () => tasks[2].resolve(forecast("C")));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reports failures while preserving successful results", async () => {
    vi.mocked(api.getForecast).mockImplementation(async (code) => {
      if (code === "A") throw new Error("Unavailable");
      return forecast(code);
    });
    render(<ForecastCompare codes={["A", "B"]} />);
    expect(await screen.findByText("B")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Không tải được 1/2");
  });

  it("stops queued forecasts after a selection change", async () => {
    const old = deferred<Forecast>();
    vi.mocked(api.getForecast).mockImplementation((code) => code === "D" ? Promise.resolve(forecast(code)) : old.promise);
    const { rerender } = render(<ForecastCompare codes={["A", "B", "C"]} />);
    expect(api.getForecast).toHaveBeenCalledTimes(2);
    rerender(<ForecastCompare codes={["D"]} />);
    expect(await screen.findByText("D")).toBeInTheDocument();
    await act(async () => old.resolve(forecast("A")));
    expect(api.getForecast).not.toHaveBeenCalledWith("C");
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });

  it("stops queued prices and ignores late prices after a selection change", async () => {
    const prices = deferred<PriceSeries>();
    vi.mocked(api.getForecast).mockImplementation(async (code) => code === "D" ? forecast(code) : { available: false, commodity_code: code, reason: "need >= 252 positive prices, have 100" });
    vi.mocked(api.getPrices).mockReturnValue(prices.promise);
    const { rerender } = render(<ForecastCompare codes={["A", "B", "C"]} />);
    await act(async () => {});
    expect(api.getPrices).toHaveBeenCalledTimes(2);
    rerender(<ForecastCompare codes={["D"]} />);
    expect(await screen.findByText("D")).toBeInTheDocument();
    await act(async () => prices.resolve({ commodity_code: "A", points: [{ date: "2026-01-01", value: 50 }] }));
    expect(screen.queryByText("A")).not.toBeInTheDocument();
    expect(screen.queryByText("B")).not.toBeInTheDocument();
    expect(screen.queryByText("C")).not.toBeInTheDocument();
    expect(api.getPrices).not.toHaveBeenCalledWith("C", 400);
  });
});
