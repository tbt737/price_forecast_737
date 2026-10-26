import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Forecast } from "@/shared/api";
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

describe("progressive profile loading", () => {
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
