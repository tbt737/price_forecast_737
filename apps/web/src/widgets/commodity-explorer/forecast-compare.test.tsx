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

  it("stops old queued work and ignores late fallback prices after a selection change", async () => {
    const prices = deferred<PriceSeries>();
    const old = deferred<Forecast>();
    vi.mocked(api.getForecast).mockImplementation((code) => {
      if (code === "A") return Promise.resolve({ available: false, commodity_code: code, reason: "need >= 252 positive prices, have 100" });
      if (code === "B") return old.promise;
      return Promise.resolve(forecast(code));
    });
    vi.mocked(api.getPrices).mockReturnValue(prices.promise);
    const { rerender } = render(<ForecastCompare codes={["A", "B", "C"]} />);
    await act(async () => {});
    expect(api.getPrices).toHaveBeenCalled();
    rerender(<ForecastCompare codes={["D"]} />);
    expect(await screen.findByText("D")).toBeInTheDocument();
    await act(async () => {
      prices.resolve({ commodity_code: "A", points: [{ date: "2026-01-01", value: 50 }] });
      old.resolve(forecast("B"));
    });
    expect(screen.queryByText("A")).not.toBeInTheDocument();
    expect(screen.queryByText("B")).not.toBeInTheDocument();
    expect(api.getForecast).not.toHaveBeenCalledWith("C");
  });
});
