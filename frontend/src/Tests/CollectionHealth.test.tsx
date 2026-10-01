import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { collectionDiagnosis } from "../lib/collection-diagnostics";
import { CollectionHealth } from "../pages/settings/CollectionHealth";
import type { CatalogSnapshot, CollectionDiagnostics } from "../types/collection";

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
const snapshot = (): CatalogSnapshot => ({
  revision: 1, can_edit: true, updated_at: null, updated_by: null,
  sensor_activity: {},
  catalog: { schema_version: 1, provider: "ambibox", default_policy: { mode: "off", interval_seconds: 10 }, sources: [] },
  collection: { revision: 1, status: "applied", selected_sensors: 1, checked_at: new Date().toISOString(), diagnostics: metrics() },
  ingress: { revision: 1, status: "applied", checked_at: new Date().toISOString(), sources: { broker: { status: "connected" } } },
});

describe("collection diagnostics", () => {
  it("expires status even when API responses stop arriving", async () => {
    vi.useFakeTimers();
    try {
      api.get.mockResolvedValueOnce(snapshot()).mockImplementation(() => new Promise(() => {}));
      await act(async () => { render(<CollectionHealth />); });
      expect(screen.getByRole("status").textContent).toBe("Collecting");
      await act(() => vi.advanceTimersByTimeAsync(18000));
      expect(screen.getByRole("status").textContent).toBe("Worker not reporting");
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
      const paused = snapshot();
      paused.collection.selected_sensors = 0;
      api.get.mockResolvedValueOnce(paused);
      await act(() => vi.advanceTimersByTimeAsync(3000));
      expect(screen.getByRole("status").textContent).toBe("Paused");
      expect(api.get).toHaveBeenCalledWith("/v1/sources/status");
      expect(api.get).toHaveBeenCalledTimes(3);
      view.unmount();
      await act(() => vi.advanceTimersByTimeAsync(6000));
      expect(api.get).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
  it.each([
    ["Collecting", () => {}],
    ["Paused", (s: CatalogSnapshot) => { s.collection.selected_sensors = 0; }],
    ["Disconnected", (s: CatalogSnapshot) => { s.collection.diagnostics!.mqtt_connected = false; }],
    ["Broker disconnected", (s: CatalogSnapshot) => { s.ingress.sources!.broker!.status = "connecting"; }],
    ["Connected but quiet", (s: CatalogSnapshot) => { s.collection.diagnostics!.rates.received = 0; }],
    ["Invalid payloads", (s: CatalogSnapshot) => { s.collection.diagnostics!.rates.invalid = 1; }],
    ["Overloaded", (s: CatalogSnapshot) => { s.collection.diagnostics!.rates.overload_dropped = 1; }],
    ["Database retrying", (s: CatalogSnapshot) => { s.collection.diagnostics!.database_retrying = true; }],
    ["Worker not reporting", (s: CatalogSnapshot) => { s.collection.checked_at = new Date(Date.now() - 60000).toISOString(); }],
    ["Applying changes", (s: CatalogSnapshot) => { s.collection.revision = 0; }],
  ])("explains %s", (expected, modify) => {
    const value = snapshot();
    modify(value);
    expect(collectionDiagnosis(value)[0]).toBe(expected);
  });

  it.each([
    ["disabled", "Ingress disabled"],
    ["error", "Broker routes failed"],
    ["stale", "Broker controller not reporting"],
  ])("shows the ingress blocker while the collector is prepared: %s", (state, expected) => {
    const value = snapshot();
    value.collection.status = "prepared";
    if (state === "stale") value.ingress.checked_at = new Date(0).toISOString();
    else value.ingress.status = state;
    expect(collectionDiagnosis(value)[0]).toBe(expected);
  });

  it("does not treat old errors as a current overload and shows measured queue use", async () => {
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
