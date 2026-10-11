import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Entities from "@/pages/Entities";
import { apiUtils } from "@/lib/api-client";
import { createEmptySystem } from "@/features/spatial/systemDocument";
import type { SystemDocument, SystemSnapshot } from "@/features/spatial/systemTypes";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ isAuthenticated: true, userId: 7 }) }));
vi.mock("@/components/NavigationBar", () => ({ NavigationBar: () => null }));
vi.mock("@/lib/api-client", async (original) => {
  const actual = await original<typeof import("@/lib/api-client")>();
  return { ...actual, apiUtils: { ...actual.apiUtils, get: vi.fn() } };
});

const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const originalObserver = Object.getOwnPropertyDescriptor(window, "ResizeObserver");
const rowHeight = 76;
const viewportHeight = 360;

function catalogue(): SystemDocument {
  const document = createEmptySystem("Test catalogue");
  return {
    ...document,
    connections: [
      { id: "north", label: "North laboratory", protocol: "mqtt", host: "north.example.test", port: 1883, transport: "tcp", tls: false },
      { id: "south", label: "South warehouse", protocol: "mqtt", host: "south.example.test", port: 1883, transport: "tcp", tls: false },
    ],
    devices: [
      { id: "entity:warehouse/gateway", label: "Gateway 2", kind: "gateway", connection_id: "north" },
      { id: "air-10", label: "Air quality 10", kind: "air monitor", connection_id: "south" },
      { id: "air-2", label: "Air quality 2", kind: "air monitor" },
    ],
    streams: [
      { id: "temperature", label: "Temperature", connection_id: "north", device_id: "entity:warehouse/gateway", topic: "environment/metrics", payload_pointer: "/temperature", value_type: "number", category: "Environment" },
      { id: "humidity", label: "Humidity", connection_id: "north", device_id: "entity:warehouse/gateway", topic: "environment/metrics", payload_pointer: "/humidity", value_type: "number", category: "Environment" },
      { id: "remote-temperature", label: "Remote temperature", connection_id: "south", device_id: "entity:warehouse/gateway", topic: "environment/metrics", value_type: "number", category: "Environment" },
      { id: "online", label: "Online", connection_id: "south", device_id: "entity:warehouse/gateway", topic: "environment/state", value_type: "boolean", category: "State" },
      { id: "global", label: "Unassigned reading", connection_id: "south", topic: "global/reading", value_type: "number", category: "Environment" },
    ],
  };
}

function snapshot(document = catalogue()): SystemSnapshot {
  return {
    document, revision: 9, can_edit: false, storage_origin: "saved",
    runtime: { mode: "configured_only", message: "Saved", legacy_collection_revision: 0 },
  };
}

function mount() {
  return render(<MemoryRouter initialEntries={["/entities"]}><Entities /></MemoryRouter>);
}

beforeEach(() => {
  vi.mocked(apiUtils.get).mockReset();
  vi.mocked(apiUtils.get).mockResolvedValue(snapshot());
  // Keep the real virtualizer; supply the measurements absent from jsdom.
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("directory-list") ? viewportHeight : this.tagName === "LI" ? rowHeight : 24;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(900);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("directory-list") ? viewportHeight : 24;
  });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: function (this: HTMLElement, options: ScrollToOptions) {
      if (this.scrollTop === (options.top ?? 0)) return;
      this.scrollTop = options.top ?? 0;
      this.dispatchEvent(new Event("scroll"));
    },
  });
  class ViewportObserver { observe() {} unobserve() {} disconnect() {} }
  Object.defineProperty(window, "ResizeObserver", { configurable: true, value: ViewportObserver });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  if (originalObserver) Object.defineProperty(window, "ResizeObserver", originalObserver);
  else Reflect.deleteProperty(window, "ResizeObserver");
});

describe("generic entity directory", () => {
  it("loads the saved system, deduplicates broker-qualified topics, and links by stable identity", async () => {
    mount();
    const link = await screen.findByRole("link", { name: "Open Gateway 2" });
    expect(apiUtils.get).toHaveBeenCalledExactlyOnceWith("/v1/system", expect.objectContaining({ redirectOnUnauthorized: false }));
    const row = within(link);
    expect(row.getByText("4 readings")).toBeTruthy();
    expect(row.getByText("3 topics")).toBeTruthy();
    expect(row.getByText("North laboratory, South warehouse")).toBeTruthy();
    const location = new URL(link.getAttribute("href")!, "https://example.test");
    expect(location.pathname).toBe("/");
    expect(location.searchParams.get("entity")).toBe("entity:warehouse/gateway");
    expect(screen.getByRole("status").textContent).toBe("3 entities");
    expect(screen.getAllByRole("link").map((item) => item.getAttribute("aria-label")))
      .toEqual(["Open Air quality 2", "Open Air quality 10", "Open Gateway 2"]);
    const unassigned = within(screen.getByRole("link", { name: "Open Air quality 2" }));
    expect(unassigned.getByText("Unassigned")).toBeTruthy();
    expect(unassigned.getByText("0 readings")).toBeTruthy();
  });

  it("searches names, kinds, broker labels and IDs with all terms and case-insensitive matching", async () => {
    mount();
    await screen.findByRole("link", { name: "Open Gateway 2" });
    const search = screen.getByRole("searchbox", { name: "Search entities" });
    fireEvent.change(search, { target: { value: "  NORTH GaTeWaY  " } });
    await waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(1));
    expect(screen.getByRole("link", { name: "Open Gateway 2" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("1 entity");
    fireEvent.change(search, { target: { value: "entity:warehouse/gateway" } });
    await waitFor(() => expect(screen.getByRole("link", { name: "Open Gateway 2" })).toBeTruthy());
    fireEvent.change(search, { target: { value: "air monitor south" } });
    expect(await screen.findByRole("link", { name: "Open Air quality 10" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open Air quality 2" })).toBeNull();
    fireEvent.change(search, { target: { value: "north air" } });
    expect(await screen.findByText("No matching entities")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("0 entities");
    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(3));
  });

  it("shows a retryable load error and recovers from the API without inventing entities", async () => {
    vi.mocked(apiUtils.get).mockRejectedValueOnce(new Error("Catalogue unavailable"));
    mount();
    expect((await screen.findByRole("alert")).textContent).toContain("Catalogue unavailable");
    expect(screen.queryByRole("link", { name: "Open Gateway 2" })).toBeNull();
    expect(screen.queryByText("No entities")).toBeNull();
    expect(screen.queryByText("0 entities")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Open Gateway 2" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(apiUtils.get).toHaveBeenCalledTimes(2);
  });

  it("keeps a full 2,048-entity catalogue virtualized and resets the viewport on search", async () => {
    const document = createEmptySystem("Large catalogue");
    document.devices = Array.from({ length: 2048 }, (_, index) => ({ id: `entity-${index}`, label: `Entity ${index}`, kind: "device" }));
    vi.mocked(apiUtils.get).mockResolvedValue(snapshot(document));
    mount();
    const list = await screen.findByRole("list", { name: "Entities" });
    expect(within(list).getAllByRole("link").length).toBeLessThanOrEqual(12);
    expect(screen.queryByRole("link", { name: "Open Entity 2000" })).toBeNull();
    const viewport = list.parentElement!;
    fireEvent.scroll(viewport, { target: { scrollTop: 2000 * rowHeight } });
    expect(screen.getByRole("link", { name: "Open Entity 2000" })).toBeTruthy();
    expect(within(list).getAllByRole("link").length).toBeLessThanOrEqual(20);
    expect(screen.queryByRole("link", { name: "Open Entity 0" })).toBeNull();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search entities" }), { target: { value: "Entity 2047" } });
    expect(await screen.findByRole("link", { name: "Open Entity 2047" })).toBeTruthy();
    expect(viewport.scrollTop).toBe(0);
    expect(screen.getByRole("status").textContent).toBe("1 entity");
  });
});
