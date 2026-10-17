import { act, cleanup, fireEvent, render as renderUI, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorerSidebar } from "@/features/explorer/ExplorerSidebar";
import { ExplorerList, type ExplorerRow, type ListPosition } from "@/features/explorer/ExplorerList";
import { buildNavigationIndex, navigationRows } from "@/features/explorer/navigationIndex";
import { createEmptySystem } from "@/features/catalogue/systemDocument";
import type { SystemDocument } from "@/features/catalogue/systemTypes";
import { apiClient } from "@/lib/api-client";
import { SystemLiveTelemetry } from "@/features/catalogue/systemLiveTelemetry";
import type { LiveBatch } from "@/features/catalogue/systemLiveTypes";
import type { SystemRuntime } from "@/features/catalogue/systemTypes";

const viewportHeight = 360;
const rowHeight = 72;
const initialScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const initialWindowObserver = Object.getOwnPropertyDescriptor(window, "ResizeObserver");

function render(element: ReactNode, path = "/") {
  return renderUI(element, { wrapper: ({ children }) => <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter> });
}

beforeEach(() => {
  // Exercise the real TanStack virtualizer. jsdom provides no element geometry,
  // so supply only the browser measurements and scrolling behaviour it observes.
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll") ? viewportHeight : this.tagName === "LI" ? rowHeight : 24;
  });
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(264);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll") ? viewportHeight : 24;
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("ex-list-scroll")
      ? Number.parseFloat(this.querySelector<HTMLElement>(".ex-list")?.style.height ?? "0")
      : 24;
  });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: function (this: HTMLElement, options: ScrollToOptions) {
      const next = options.top ?? 0;
      if (this.scrollTop === next) return;
      this.scrollTop = next;
      this.dispatchEvent(new Event("scroll"));
    },
  });
  class ViewportObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(window, "ResizeObserver", { configurable: true, value: ViewportObserver });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (initialScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", initialScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  if (initialWindowObserver) Object.defineProperty(window, "ResizeObserver", initialWindowObserver);
  else Reflect.deleteProperty(window, "ResizeObserver");
});

function system(readings = 3): SystemDocument {
  return {
    ...createEmptySystem("Test catalogue"),
    connections: [{ id: "broker", label: "North laboratory", protocol: "mqtt", host: "private.example.invalid", port: 1883, transport: "tcp", tls: false }],
    streams: Array.from({ length: readings }, (_, position) => ({
      id: `value-${position}`, label: `Value ${position}`, connection_id: "broker", topic: `site/room/value${position}`,
      value_type: "number", category: "Environment",
    })),
    groups: [{ id: "catalogue-watch", label: "Building A", member_ids: ["broker"] }],
  };
}

function sidebarOptions(document = system()) {
  const index = buildNavigationIndex(document);
  return {
    index, scopeKey: index.rootKey, rows: navigationRows(index, index.rootKey), title: "Test catalogue",
    catalogueGroups: document.groups, query: "", selectedKey: null,
    positions: new Map<string, ListPosition>(), loading: false,
    onQuery: vi.fn(), onScope: vi.fn(), onOpen: vi.fn(), onBack: vi.fn(), onInspect: vi.fn(),
    onSettings: vi.fn(), onCatalogue: vi.fn(), onDismiss: vi.fn(),
  };
}

function listOptions(document = system()) {
  const index = buildNavigationIndex(document);
  const broker = index.nodes.get(index.objectKeys.get("broker")![0]!)!;
  const branch = navigationRows(index, broker.key)[0]!.node;
  return {
    rows: navigationRows(index, branch.key), viewKey: branch.key,
    positions: new Map<string, ListPosition>(), selectedKey: null,
    onOpen: vi.fn(), onBack: vi.fn(),
  };
}

describe("explorer sidebar and catalogue list", () => {
  it("observes fresh preview traffic and clears the circle when its listener leaves", async () => {
    const document = system();
    let batch: LiveBatch = { mode: "live", revision: 1, sequence: 0, reset: true,
      connections: [{ connection_id: "broker", state: "connected", message: null, received_messages: 1, fresh_count: 0, retained_count: 1, fresh_received_at: null, rate_hz: 0 }],
      streams: [{ stream_id: "value-0", value: 20, received_at: new Date().toISOString(), is_retained: true, received_count: 1, fresh_count: 0, retained_count: 1,
        decode_errors: 0, fresh_received_at: null, rate_hz: 0, sequence: 0 }], samples: [],
      limits: { max_samples: 8192, history_seconds: 7200, sample_interval_seconds: 1, lease_seconds: 45 } };
    const lease = () => Promise.resolve({ lease_id: "preview", expires_in_seconds: 45, telemetry: batch });
    const telemetry = new SystemLiveTelemetry({ create: lease, renew: lease, read: async () => batch, release: async () => {} });
    telemetry.configure(document, 1, "test-member", true);
    telemetry.setScope(["value-0"]);
    await telemetry.start();
    const options = listOptions(document);
    const view = render(<ExplorerList {...options} activity={{ telemetry, liveStreamIds: ["value-0"] }} />);
    try {
      const row = await screen.findByRole("button", { name: "value0, preview" });
      expect(row.querySelector("svg")!.getAttribute("fill")).toBe("none");
      expect(row.querySelector(".ex-reading-activity")?.getAttribute("title")).toBe("Listening, waiting for fresh data");
      batch = { ...batch, sequence: 1, reset: false, streams: [{ ...batch.streams[0]!, value: 21, is_retained: false, fresh_count: 1,
        fresh_received_at: new Date().toISOString(), sequence: 1 }] };
      act(() => telemetry.accept(batch, true));
      expect(row.querySelector("svg")!.getAttribute("fill")).toBe("currentColor");
      view.rerender(<ExplorerList {...options} activity={{ telemetry, liveStreamIds: ["value-1"] }} />);
      expect(row.querySelector("svg")!.getAttribute("fill")).toBe("none");
      view.rerender(<ExplorerList {...options} activity={{ telemetry, liveStreamIds: ["value-0"] }} />);
      expect(row.querySelector("svg")!.getAttribute("fill")).toBe("currentColor");
      act(() => telemetry.stop());
      expect(row.querySelector("svg")!.getAttribute("fill")).toBe("none");
      expect(row.querySelector(".ex-reading-activity")?.getAttribute("title")).toBe("Not listening");
    } finally {
      view.unmount();
      telemetry.stop();
    }
  });

  it("updates same-size circles from fresh traffic to waiting and off without changing selection", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const options = listOptions();
    const runtime: SystemRuntime = { mode: "collection", message: "", collection_revision: 1, collection: { status: "applied" },
      ingress: { revision: 1, status: "applied", sources: { broker: { state: "connected" } }, readings: { "value-0": { fresh_received_at: new Date().toISOString() } } },
      bindings: { "value-0": { entity_id: "room", connection_id: "broker", telemetry_key: "value", accepted_topic: "telemetry/room/value", policy: { mode: "sample", interval_seconds: 3600 } } } };
    const source = { telemetry: new SystemLiveTelemetry(), runtime, liveStreamIds: [] };
    const view = render(<ExplorerList {...options} selectedKey={options.rows[0]!.node.key} activity={source} />);
    const row = await screen.findByRole("button", { name: "value0, preview" });
    const circle = row.querySelector("svg")!;
    expect(circle.getAttribute("width")).toBe("16");
    expect(circle.getAttribute("fill")).toBe("currentColor");
    expect(document.getElementById(row.getAttribute("aria-describedby")!)?.textContent).toBe("Receiving data (last 30 seconds)");
    act(() => vi.advanceTimersByTime(30_000));
    expect(circle.getAttribute("fill")).toBe("none");
    expect(row.getAttribute("aria-current")).toBe("true");
    expect(document.getElementById(row.getAttribute("aria-describedby")!)?.textContent).toBe("Listening, waiting for fresh data");
    source.runtime = { ...runtime, ingress: { ...runtime.ingress, readings: { "value-0": { fresh_received_at: new Date().toISOString() } } } };
    view.rerender(<ExplorerList {...options} selectedKey={options.rows[0]!.node.key} activity={source} />);
    expect(circle.getAttribute("fill")).toBe("currentColor");
    source.runtime = { ...runtime, ingress: { ...runtime.ingress, sources: {} } };
    view.rerender(<ExplorerList {...options} selectedKey={options.rows[0]!.node.key} activity={source} />);
    expect(circle.getAttribute("fill")).toBe("none");
    expect(document.getElementById(row.getAttribute("aria-describedby")!)?.textContent).toBe("Not listening");
    view.unmount();
    vi.useRealTimers();
  });

  it("keeps the sidebar for MQTT navigation and catalogue settings", () => {
    render(<ExplorerSidebar {...sidebarOptions()} />);
    expect(screen.getByText("MQTT catalogue")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Workspaces" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Monitoring" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Sources" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Reporting" })).toBeNull();
    expect(screen.getByRole("button", { name: "Catalogue settings" })).toBeTruthy();
  });

  it("counts brokers independently of the unassigned entity branch", () => {
    const document = system();
    document.devices.push({ id: "loose", label: "Unassigned sensor", kind: "sensor" });
    const options = sidebarOptions(document);
    render(<ExplorerSidebar {...options} />);
    expect(screen.getByText("1 broker · unassigned entities")).toBeTruthy();
    expect(screen.queryByText("2 brokers")).toBeNull();
  });

  it("moves from search into the rendered virtual window after scrolling past the first row", () => {
    const document = system(4000);
    const list = listOptions(document);
    render(<ExplorerSidebar {...sidebarOptions(document)} rows={list.rows} scopeKey={list.viewKey} />);
    const viewport = screen.getByRole("list").parentElement!;
    fireEvent.scroll(viewport, { target: { scrollTop: 2000 * rowHeight } });
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    const input = screen.getByRole("searchbox", { name: "Search catalogue" });
    act(() => input.focus());
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(window.document.activeElement?.getAttribute("data-row")).not.toBeNull();
    expect(window.document.activeElement).not.toBe(input);
  });

  it("renders a bounded viewport for 4,000 topics and reaches late items without mounting the entire list", () => {
    const options = listOptions(system(4000));
    render(<ExplorerList {...options} />);
    const list = screen.getByRole("list", { name: "Catalogue items" });
    expect(within(list).getAllByRole("button").length).toBeLessThanOrEqual(12);
    expect(screen.getByRole("button", { name: "value0, preview" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "value2000, preview" })).toBeNull();
    const scroll = list.parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 2000 * rowHeight } });
    expect(screen.getByRole("button", { name: "value2000, preview" })).toBeTruthy();
    expect(within(list).getAllByRole("button").length).toBeLessThanOrEqual(18);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(options.positions.get(options.viewKey)?.offset).toBe(2000 * rowHeight);
    fireEvent.click(screen.getByRole("button", { name: "value2000, preview" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(options.rows[2000]!.node);
  });

  it("supports keyboard movement across the virtualized window, opening, and returning to a parent", async () => {
    const options = listOptions(system(4000));
    render(<ExplorerList {...options} />);
    const first = screen.getByRole("button", { name: "value0, preview" });
    act(() => first.focus());
    fireEvent.keyDown(first, { key: "ArrowDown" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value1, preview" })));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(options.onOpen).toHaveBeenLastCalledWith(options.rows[3999]!.node);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(options.onBack).toHaveBeenCalledOnce();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value0, preview" })));
  });

  it("restores each branch's scroll position when entering and returning", async () => {
    const options = listOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const scroll = screen.getByRole("list").parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 100 * rowHeight } });
    expect(screen.getByRole("button", { name: "value100, preview" })).toBeTruthy();
    view.rerender(<ExplorerList {...options} viewKey="other-branch" />);
    await waitFor(() => expect(scroll.scrollTop).toBe(0));
    view.rerender(<ExplorerList {...options} />);
    await waitFor(() => expect(scroll.scrollTop).toBe(100 * rowHeight));
    expect(screen.getByRole("button", { name: "value100, preview" })).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value100, preview" })));
  });

  it("restores the focused topic as well as its viewport after entering another branch", async () => {
    const options = listOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const scroll = screen.getByRole("list").parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 2000 * rowHeight } });
    const previous = screen.getByRole("button", { name: "value2000, preview" });
    act(() => previous.focus());
    expect(options.positions.get(options.viewKey)?.focused).toBe(options.rows[2000]!.node.key);
    const elsewhere = [{ ...options.rows[0]!, label: "Other branch", node: { ...options.rows[0]!.node, key: "other-topic" } }];
    view.rerender(<ExplorerList {...options} rows={elsewhere} viewKey="other-branch" />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Other branch, preview" })));
    view.rerender(<ExplorerList {...options} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value2000, preview" })));
    expect(scroll.scrollTop).toBe(2000 * rowHeight);
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it.each([0, 1])("keeps explicit toolbar focus during deferred branch restoration after %i frames", (elapsedFrames) => {
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrame = 0;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((callback) => {
      frames.set(++nextFrame, callback);
      return nextFrame;
    });
    vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation((handle) => { frames.delete(handle); });
    const advanceFrame = () => act(() => {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach((callback) => callback(performance.now()));
    });
    const options = listOptions();
    const content = (viewKey: string) => <><button>Back to catalogue</button><ExplorerList {...options} viewKey={viewKey} /></>;
    const view = render(content(options.viewKey));
    act(() => screen.getByRole("button", { name: "value0, preview" }).focus());

    view.rerender(content("catalogue:north"));
    for (let frame = 0; frame < elapsedFrames; frame++) advanceFrame();
    const toolbar = screen.getByRole("button", { name: "Back to catalogue" });
    act(() => toolbar.focus());
    advanceFrame();
    advanceFrame();

    expect(document.activeElement).toBe(toolbar);
  });

  it("reveals a late search result in its canonical branch instead of restoring an unrelated saved viewport", async () => {
    const options = listOptions(system(4000));
    const late = options.rows[3999]!;
    options.positions.set(options.viewKey, { offset: 100 * rowHeight, focused: options.rows[100]!.node.key });
    const view = render(<ExplorerList {...options} viewKey="search:value3999" rows={[late]} />);
    const result = screen.getByRole("button", { name: "value3999, preview" });
    fireEvent.click(result);
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(late.node);
    view.rerender(<ExplorerList {...options} selectedKey={late.node.key} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    const selected = screen.getByRole("button", { name: "value3999, preview" });
    const scroll = screen.getByRole("list").parentElement!;
    const rowStart = 3999 * rowHeight;
    expect(selected.getAttribute("aria-current")).toBe("true");
    expect(rowStart).toBeGreaterThanOrEqual(scroll.scrollTop);
    expect(rowStart + rowHeight).toBeLessThanOrEqual(scroll.scrollTop + viewportHeight);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it("waits for deferred search rows before revealing the selected topic in its canonical scope", async () => {
    const options = sidebarOptions(system(4000));
    const broker = options.index.nodes.get(options.index.objectKeys.get("broker")![0]!)!;
    const branch = navigationRows(options.index, broker.key)[0]!.node;
    const canonicalRows = navigationRows(options.index, branch.key);
    const late = canonicalRows[3999]!;
    const searchRows = [late];
    options.positions.set(branch.key, { offset: 100 * rowHeight, focused: canonicalRows[100]!.node.key });
    const view = render(<ExplorerSidebar {...options} query="value3999" resultsQuery="value3999" rows={searchRows} />);
    fireEvent.click(screen.getByRole("button", { name: "value3999, preview" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(late.node);

    // The input clears immediately, while useDeferredValue still supplies the
    // previous search result. Its view identity must remain a search identity.
    view.rerender(<ExplorerSidebar {...options} query="" resultsQuery="value3999" rows={searchRows}
      scopeKey={branch.key} title={branch.label} selectedKey={late.node.key} />);
    expect((screen.getByRole("searchbox", { name: "Search catalogue" }) as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("list").classList.contains("is-search")).toBe(true);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });

    view.rerender(<ExplorerSidebar {...options} query="" resultsQuery="" rows={canonicalRows}
      scopeKey={branch.key} title={branch.label} selectedKey={late.node.key} />);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "value3999, preview" })));
    const scroll = screen.getByRole("list").parentElement!;
    expect(screen.getByRole("list").classList.contains("is-search")).toBe(false);
    expect(3999 * rowHeight).toBeGreaterThanOrEqual(scroll.scrollTop);
    expect(4000 * rowHeight).toBeLessThanOrEqual(scroll.scrollTop + viewportHeight);
    expect(screen.queryByRole("button", { name: "value0, preview" })).toBeNull();
    expect(within(screen.getByRole("list")).getAllByRole("button").length).toBeLessThanOrEqual(18);
  });

  it("keeps complete long names in relative-path rows and accessible titles", () => {
    const options = listOptions();
    const label = `prefix-visible-${"long-relative-path-".repeat(25)}tail`;
    const rows: ExplorerRow[] = [{ ...options.rows[0]!, label }];
    render(<ExplorerList {...options} rows={rows} selectedKey={rows[0]!.node.key} />);
    const button = screen.getByRole("button", { name: `${label}, preview` });
    expect(button.getAttribute("title")).toBe(label);
    expect(button.querySelector(".ex-row-label")?.textContent).toBe(label);
    expect(button.querySelector(".ex-row-label")?.textContent?.startsWith("prefix-visible-")).toBe(true);
    expect(button.getAttribute("aria-current")).toBe("true");
    expect(screen.queryByText("private.example.invalid")).toBeNull();
  });

  it("opens branches, exposes actual ancestors, and leaves workspace navigation explicit", () => {
    const options = sidebarOptions();
    const root = render(<ExplorerSidebar {...options} />);
    expect(screen.queryByRole("button", { name: "Test catalogue" })).toBeNull();
    expect(screen.getByText("1 broker")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Back to catalogue" }).getAttribute("title")).toBe("Back to catalogue");
    const broker = options.index.nodes.get(options.index.objectKeys.get("broker")![0]!)!;
    fireEvent.click(screen.getByRole("button", { name: "North laboratory, open" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(broker);
    const branch = navigationRows(options.index, broker.key)[0]!.node;
    root.rerender(<ExplorerSidebar {...options} scopeKey={branch.key} title={branch.label} rows={navigationRows(options.index, branch.key)} />);
    fireEvent.click(screen.getByRole("button", { name: "Back one level" }));
    expect(options.onBack).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: branch.label }));
    expect(screen.getByText("Current path")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "North laboratory" }));
    expect(options.onScope).toHaveBeenLastCalledWith(broker.key);
    fireEvent.click(screen.getByRole("button", { name: "Back to catalogue" }));
    expect(options.onCatalogue).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Catalogue settings" }));
    expect(options.onSettings).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Hide catalogue" }));
    expect(options.onDismiss).toHaveBeenCalledOnce();
  });

  it("focuses search with the desktop shortcut and clears a query without closing the explorer", () => {
    const options = sidebarOptions();
    render(<ExplorerSidebar {...options} query="temperature" />);
    const search = screen.getByRole("searchbox", { name: "Search catalogue" }) as HTMLInputElement;
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(document.activeElement).toBe(search);
    expect(search.selectionStart).toBe(0);
    expect(search.selectionEnd).toBe("temperature".length);
    fireEvent.change(search, { target: { value: "power" } });
    expect(options.onQuery).toHaveBeenLastCalledWith("power");
    fireEvent.keyDown(search, { key: "Escape" });
    expect(options.onQuery).toHaveBeenLastCalledWith("");
    expect(options.onDismiss).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close search" }));
    expect(options.onBack).toHaveBeenCalledOnce();
  });

  it("enters search results with ArrowDown and retains input focus while the query changes", () => {
    const options = sidebarOptions();
    const node = options.index.nodes.get(options.index.objectKeys.get("value-0")![0]!)!;
    const rows = [{ node, label: "Air temperature", detail: "North laboratory · site/room" }];
    const view = render(<ExplorerSidebar {...options} query="air" rows={rows} />);
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    act(() => search.focus());
    view.rerender(<ExplorerSidebar {...options} query="temperature" rows={rows} />);
    expect(document.activeElement).toBe(search);
    fireEvent.keyDown(search, { key: "ArrowDown" });
    const result = screen.getByRole("button", { name: "Air temperature, preview" });
    expect(document.activeElement).toBe(result);
    fireEvent.keyDown(result, { key: "ArrowRight" });
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(node);
    view.rerender(<ExplorerSidebar {...options} query="missing" rows={[]} />);
    act(() => search.focus());
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(document.activeElement).toBe(search);
    expect(options.onScope).not.toHaveBeenCalled();
  });

  it("keeps collections navigable without exposing personal grouping", () => {
    const document = system();
    const original = structuredClone(document);
    const options = sidebarOptions(document);
    const save = vi.spyOn(apiClient, "put");
    const view = render(<ExplorerSidebar {...options} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse collections" }));
    expect(screen.queryByText("Personal groups")).toBeNull();
    expect(screen.queryByRole("button", { name: "Manage personal groups" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Building A/ }));
    expect(options.onScope).toHaveBeenLastCalledWith("catalogue:catalogue-watch");
    expect(options.onOpen).not.toHaveBeenCalled();
    expect(document).toEqual(original);
    expect(save).not.toHaveBeenCalled();
    view.rerender(<ExplorerSidebar {...options} catalogueGroups={[]} />);
    expect(screen.queryByRole("button", { name: "Browse collections" })).toBeNull();
  });

  it("keeps loading and empty navigation states accessible", () => {
    const options = sidebarOptions();
    const view = render(<ExplorerSidebar {...options} loading />);
    expect(screen.getByRole("status").textContent).toBe("Loading catalogue…");
    expect(screen.queryByRole("list")).toBeNull();
    view.rerender(<ExplorerSidebar {...options} rows={[]} />);
    expect(screen.getByText("No items here.")).toBeTruthy();
  });
});
