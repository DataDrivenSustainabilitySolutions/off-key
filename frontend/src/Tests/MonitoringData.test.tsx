import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ApiRequestOptions } from "../lib/api-client";
import Monitoring from "../pages/Monitoring";
import { useMonitoringData } from "../pages/monitoring/useMonitoringData";

const { get, errorToast } = vi.hoisted(() => ({
  get: vi.fn<(url: string, options?: ApiRequestOptions) => Promise<unknown>>(),
  errorToast: vi.fn(),
}));

vi.mock("../lib/api-client", () => ({ apiUtils: { get } }));
vi.mock("react-hot-toast", () => ({ default: { error: errorToast } }));
vi.mock("../components/NavigationBar", () => ({ NavigationBar: () => null }));
vi.mock("../pages/monitoring/StaticMonitoringSetup", () => ({
  StaticMonitoringSetup: ({ sensorTypes }: { sensorTypes: string[] }) =>
    <div data-testid="sensors">{sensorTypes.join(",")}</div>,
}));
vi.mock("../pages/monitoring/MonitoringDataPanels", () => ({
  MonitoringDataPanels: () => null,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  get.mockImplementation(async (url) => url.includes("models") ? {} : []);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("isolates charger state and ignores an old response after navigation", async () => {
  const oldSensors = deferred<string[]>();
  let oldSignal: AbortSignal | undefined;
  get.mockImplementation(async (url, options) => {
    if (url.includes("models")) return {};
    if (url.endsWith("/type")) {
      if (url.includes("charger-A")) {
        oldSignal = options?.signal;
        return oldSensors.promise;
      }
      return ["sensor-B"];
    }
    return [];
  });
  const router = createMemoryRouter([
    { path: "/monitoring/:chargerId", element: <Monitoring /> },
  ], { initialEntries: ["/monitoring/charger-A"] });
  render(<RouterProvider router={router} />);
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(() => router.navigate("/monitoring/charger-B"));
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(screen.getByTestId("sensors").textContent).toBe("sensor-B");
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => oldSensors.resolve(["sensor-A"]));
  expect(screen.getByTestId("sensors").textContent).toBe("sensor-B");
});

it("does not overlap polls and gives manual refresh precedence over an old poll", async () => {
  const oldServices = deferred<unknown[]>();
  const freshServices = deferred<unknown[]>();
  const signals: AbortSignal[] = [];
  get.mockImplementation(async (url, options) => {
    if (url.includes("models")) return {};
    if (url.includes("active_only")) {
      if (options?.signal) signals.push(options.signal);
      return signals.length === 1 ? oldServices.promise : freshServices.promise;
    }
    return [];
  });
  const { result } = renderHook(() => useMonitoringData("charger-A"));
  await act(() => vi.advanceTimersByTimeAsync(90_000));
  expect(signals).toHaveLength(1);
  let refresh: Promise<void>;
  act(() => { refresh = result.current.services.reload(); });
  expect(signals[0]?.aborted).toBe(true);
  await act(async () => {
    freshServices.resolve([]); // Deleted service is absent in the fresh response.
    await refresh;
  });
  await act(async () => oldServices.resolve([{ id: "deleted-service" }]));
  expect(result.current.services.data).toEqual([]);
  expect(result.current.services.loading).toBe(false);
  await act(() => vi.advanceTimersByTimeAsync(29_999));
  expect(signals).toHaveLength(2);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(signals).toHaveLength(3);
});

it("aborts requests and suppresses stale errors after unmount", async () => {
  const pending = deferred<unknown[]>();
  const signals: AbortSignal[] = [];
  get.mockImplementation(async (_url, options) => {
    if (options?.signal) signals.push(options.signal);
    return pending.promise;
  });
  const { unmount } = renderHook(() => useMonitoringData("charger-A"));
  await act(() => vi.advanceTimersByTimeAsync(1));
  unmount();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  await act(async () => pending.reject(new Error("late failure")));
  expect(errorToast).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(90_000));
  expect(get).toHaveBeenCalledTimes(4);
});
