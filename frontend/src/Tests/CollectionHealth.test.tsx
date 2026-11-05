import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CollectionHealth } from "../features/settings/CollectionHealth";
import type { CollectionDiagnosis, CollectionDiagnostics, CollectionStatus } from "../types/collection";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("../lib/api-client", () => ({ apiUtils: api }));

beforeEach(() => vi.resetAllMocks());

const metrics = (): CollectionDiagnostics => ({
  mqtt_connected: true, window_seconds: 30,
  rates: { received: 10, accepted: 0.1, invalid: 0, overload_dropped: 0, written: 0.1 },
  last_received_at: new Date().toISOString(), last_database_write_at: null,
  original_queue: 5, original_capacity: 10, sample_slots: 2,
  database_queue: 0, database_capacity: 1000, database_retrying: false,
});
const diagnosis = (title = "Collecting", tone: CollectionDiagnosis["tone"] = "positive"): CollectionDiagnosis => ({
  code: title.toLowerCase().replace(/ /g, "_"), tone, title, explanation: `${title} explained`,
  measurements_current: true, checked_at: new Date().toISOString(),
});
const snapshot = (verdict = diagnosis()): CollectionStatus => ({
  revision: 1,
  collection: { revision: 1, status: "applied", selected_sensors: 1, checked_at: new Date().toISOString(), diagnostics: metrics() },
  ingress: { revision: 1, status: "applied", checked_at: new Date().toISOString(), sources: { broker: { state: "connected" } } },
  diagnosis: verdict,
});

describe("collection diagnostics", () => {
  it("shows the server's verdict with its tone and explanation", async () => {
    api.get.mockResolvedValue(snapshot(diagnosis("Broker disconnected", "danger")));
    render(<CollectionHealth />);
    const status = await screen.findByText("Broker disconnected");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.className).toContain("mn-state--danger");
    expect(screen.getByText("Broker disconnected explained")).toBeTruthy();
  });

  it("expires status even when API responses stop arriving", async () => {
    vi.useFakeTimers();
    try {
      api.get.mockResolvedValueOnce(snapshot()).mockImplementation(() => new Promise(() => {}));
      await act(async () => { render(<CollectionHealth />); });
      expect(screen.getByRole("status").textContent).toBe("Collecting");
      expect(screen.queryByText(/last worker report/)).toBeNull();
      await act(() => vi.advanceTimersByTimeAsync(18000));
      expect(screen.getByRole("status").textContent).toBe("Status not refreshing");
      expect(screen.getByText(/last worker report/)).toBeTruthy();
      expect(api.get).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries failed requests, refreshes diagnostics, and stops polling on unmount", async () => {
    vi.useFakeTimers();
    try {
      api.get.mockRejectedValueOnce(new Error("Network unavailable"));
      const view = render(<CollectionHealth />);
      expect(screen.getByRole("status").textContent).toBe("Loading collection status…");
      await act(async () => {});
      expect(screen.getByRole("alert").textContent).toContain("Network unavailable");
      api.get.mockResolvedValueOnce(snapshot());
      await act(() => vi.advanceTimersByTimeAsync(3000));
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByRole("status").textContent).toBe("Collecting");
      api.get.mockResolvedValueOnce(snapshot(diagnosis("Paused", "neutral")));
      await act(() => vi.advanceTimersByTimeAsync(3000));
      expect(screen.getByRole("status").textContent).toBe("Paused");
      expect(api.get).toHaveBeenCalledWith("/v1/system/health");
      expect(api.get).toHaveBeenCalledTimes(3);
      view.unmount();
      await act(() => vi.advanceTimersByTimeAsync(6000));
      expect(api.get).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows measured queue use and totals since worker start", async () => {
    const value = snapshot();
    value.collection.counters = { overload_dropped: 500, invalid: 20 };
    api.get.mockResolvedValue(value);
    render(<CollectionHealth />);
    expect(await screen.findByText("Collecting")).toBeTruthy();
    expect(screen.getByText("5 / 10 (50%)")).toBeTruthy();
    expect(screen.getByText("None since worker start")).toBeTruthy();
    expect(screen.getByText(/500 observations dropped/)).toBeTruthy();
  });
});
