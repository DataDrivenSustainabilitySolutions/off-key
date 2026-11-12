import { act, fireEvent, render as renderUI, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CatalogueBrowser } from "@/features/workspace/CatalogueBrowser";
import { ExplorerList, type ListPosition } from "@/features/workspace/ExplorerList";
import { catalogueRoots, catalogueSearchRows, catalogueTreeRows } from "@/features/workspace/catalogue-tree";
import { buildNavigationIndex, type NavigationIndex } from "@/domain/system/navigationIndex";
import { createEmptySystem } from "@/domain/system/systemDocument";
import type { SystemDocument, SystemRuntime } from "@/types/system";
import { SystemLiveTelemetry } from "@/domain/system/systemLiveTelemetry";
import type { LiveBatch } from "@/types/system-live";
import { mqttConnection } from "./support/fixtures/system";

const viewportHeight = 320;
const rowHeight = 32;
const initialScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
const initialWindowObserver = Object.getOwnPropertyDescriptor(window, "ResizeObserver");

function render(element: ReactNode) {
  return renderUI(element, { wrapper: ({ children }) => <MemoryRouter>{children}</MemoryRouter> });
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
  class ViewportObserver { observe() {} unobserve() {} disconnect() {} }
  Object.defineProperty(window, "ResizeObserver", { configurable: true, value: ViewportObserver });
});

afterEach(() => {
  if (initialScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", initialScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
  if (initialWindowObserver) Object.defineProperty(window, "ResizeObserver", initialWindowObserver);
  else Reflect.deleteProperty(window, "ResizeObserver");
});

/** A broker with a device, readings owned by the broker itself, and `readings` values under one topic branch. */
function system(readings = 3): SystemDocument {
  return {
    ...createEmptySystem("Test catalogue"),
    brokers: [mqttConnection({ id: "broker", label: "North laboratory", host: "private.example.invalid" })],
    devices: [{ id: "meter", label: "Main meter", kind: "meter", broker_id: "broker" }],
    readings: [
      { id: "power", label: "Active power", broker_id: "broker", device_id: "meter", topic: "site/meter/power", value_type: "number", category: "Energy", unit: "kW" },
      { id: "inactive", label: "Spare input", broker_id: "broker", topic: "site/spare", value_type: "number", category: "Energy" },
      ...Array.from({ length: readings }, (_, position) => ({
        id: `value-${position}`, label: `Value ${position}`, broker_id: "broker", topic: `site/room/value${position}`,
        value_type: "number" as const, category: "Environment", unit: "°C",
      })),
    ],
    groups: [{ id: "watch", label: "Building A", member_ids: ["meter", "value-0"], color: "#4f7cac" }],
  };
}

const streamsOf = (document: SystemDocument) => new Map(document.readings.map(stream => [stream.id, stream]));
const keyOf = (index: NavigationIndex, id: string) => index.objectKeys.get(id)![0]!;
/** A topic level the broker owns directly, outside any device. */
const topicKey = (index: NavigationIndex, topic: string) =>
  [...index.nodes.values()].find(node => node.kind === "topic" && node.topic === topic && !node.deviceId)!.key;

/** Rows of the tree with the broker and its `site/room` branch open. */
function treeOptions(document = system()) {
  const index = buildNavigationIndex(document);
  const expanded = new Set([keyOf(index, "broker"), topicKey(index, "site"), topicKey(index, "site/room")]);
  const rows = catalogueTreeRows(index, catalogueRoots(index), expanded, streamsOf(document));
  return { index, expanded, rows, viewKey: "tree", positions: new Map<string, ListPosition>(), selectedKey: null as string | null,
    onOpen: vi.fn(), onToggle: vi.fn() };
}
const readingRows = (options: ReturnType<typeof treeOptions>) => options.rows.filter(row => row.node.objectId?.startsWith("value-"));

function browserProps(document = system()): ComponentProps<typeof CatalogueBrowser> {
  const options = treeOptions(document);
  return { rows: options.rows, viewKey: "tree", query: "", selectedKey: null, positions: options.positions, loading: false,
    onQuery: vi.fn(), onOpen: vi.fn(), onToggle: vi.fn(), onCollapseAll: vi.fn() };
}

describe("catalogue tree model", () => {
  it("shows brokers, devices, MQTT topic levels and readings, opening only expanded branches", () => {
    const document = system();
    const index = buildNavigationIndex(document);
    const streams = streamsOf(document);
    const roots = catalogueRoots(index);
    expect(catalogueTreeRows(index, roots, new Set(), streams).map(row => row.label)).toEqual(["North laboratory"]);
    const broker = keyOf(index, "broker");
    const meter = keyOf(index, "meter");
    const rows = catalogueTreeRows(index, roots, new Set([broker, meter, topicKey(index, "site")]), streams);
    expect(rows.map(row => [row.label, row.depth, row.expandable, row.expanded])).toEqual([
      ["North laboratory", 0, true, true],
      ["Main meter", 1, true, true],
      // A topic chain without branches ends in its reading, which shows its display name.
      ["Active power", 2, false, false],
      ["site", 1, true, true],
      ["room", 2, true, false],
      // A broker-owned reading needs no device level; it shows its display name.
      ["Spare input", 2, false, false],
    ]);
  });

  it("names readings by display name with their unit, keeping the topic address in the full name", () => {
    const options = treeOptions();
    const reading = readingRows(options)[0]!;
    expect(reading).toMatchObject({ label: "Value 0", detail: "°C", depth: 3 });
    expect(reading.path).toBe("Value 0 — North laboratory / site/room/value0");
  });

  it("narrows the roots to a collection's members", () => {
    const document = system();
    const index = buildNavigationIndex(document);
    const rows = catalogueTreeRows(index, catalogueRoots(index, document.groups[0]), new Set(), streamsOf(document));
    expect(rows.map(row => [row.label, row.color])).toEqual([["Main meter", "#4f7cac"], ["Value 0", "#4f7cac"]]);
  });

  it("finds readings by name, unit and full MQTT path and says where each sits", () => {
    const document = system();
    const index = buildNavigationIndex(document);
    const [byPath] = catalogueSearchRows(index, "site/room/value2", streamsOf(document));
    expect(byPath).toMatchObject({ label: "Value 2", detail: "site/room/value2 · North laboratory", depth: 0, expandable: false });
    const [byName] = catalogueSearchRows(index, "active power", streamsOf(document));
    expect(byName).toMatchObject({ label: "Active power", detail: "site/meter/power · Main meter" });
    expect(catalogueSearchRows(index, "spare", streamsOf(document)).map(row => row.label)).toContain("Spare input");
  });
});

describe("catalogue list", () => {
  it("observes fresh preview traffic and clears the activity badge when its listener leaves", async () => {
    const document = system();
    let batch: LiveBatch = { mode: "live", revision: 1, sequence: 0, reset: true,
      brokers: [{ broker_id: "broker", state: "connected", message: null, received_messages: 1, fresh_count: 0, retained_count: 1, fresh_received_at: null, rate_hz: 0 }],
      readings: [{ reading_id: "value-0", value: 20, received_at: new Date().toISOString(), is_retained: true, received_count: 1, fresh_count: 0, retained_count: 1,
        decode_errors: 0, fresh_received_at: null, rate_hz: 0, sequence: 0 }], samples: [],
      limits: { max_samples: 8192, history_seconds: 7200, sample_interval_seconds: 1, lease_seconds: 45 } };
    const lease = () => Promise.resolve({ view_id: "preview", expires_in_seconds: 45, measurements: batch });
    const telemetry = new SystemLiveTelemetry({ create: lease, renew: lease, read: async () => batch, release: async () => {} });
    telemetry.configure(document, 1, "test-member", true);
    telemetry.setScope(["value-0"]);
    await telemetry.start();
    const options = treeOptions(document);
    const view = render(<ExplorerList {...options} activity={{ telemetry, liveStreamIds: ["value-0"] }} />);
    try {
      const row = await screen.findByRole("button", { name: "Value 0, preview" });
      expect(row.querySelector(".source-activity-dot")!.classList.contains("is-receiving")).toBe(false);
      expect(row.querySelector(".ex-row-icon")?.getAttribute("title")).toBe("Listening, waiting for fresh data");
      batch = { ...batch, sequence: 1, reset: false, readings: [{ ...batch.readings[0]!, value: 21, is_retained: false, fresh_count: 1,
        fresh_received_at: new Date().toISOString(), sequence: 1 }] };
      act(() => telemetry.accept(batch, true));
      expect(row.querySelector(".source-activity-dot")!.classList.contains("is-receiving")).toBe(true);
      view.rerender(<ExplorerList {...options} activity={{ telemetry, liveStreamIds: ["value-1"] }} />);
      expect(row.querySelector(".source-activity-dot")!.classList.contains("is-receiving")).toBe(false);
      act(() => telemetry.stop());
      expect(row.querySelector(".ex-row-icon")?.getAttribute("title")).toBe("Not listening");
    } finally {
      view.unmount();
      telemetry.stop();
    }
  });

  it("keeps inactive readings in the tree and marks the selected source without changing it", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const options = treeOptions();
    const runtime: SystemRuntime = { mode: "collection", message: "", collection_revision: 1, collection: { status: "applied" },
      ingress: { revision: 1, status: "applied", sources: { broker: { state: "connected" } }, readings: { "value-0": { fresh_received_at: new Date().toISOString() } } },
      bindings: { "value-0": { broker_id: "broker", policy: { mode: "sample", interval_seconds: 3600 } } } };
    const selected = readingRows(options)[0]!.node.key;
    render(<ExplorerList {...options} selectedKey={selected} activity={{ telemetry: new SystemLiveTelemetry(), runtime, liveStreamIds: [] }} />);
    const row = await screen.findByRole("button", { name: "Value 0, preview" });
    expect(row.querySelector(".source-activity-dot")!.classList.contains("is-receiving")).toBe(true);
    expect(row.getAttribute("aria-current")).toBe("true");
    act(() => vi.advanceTimersByTime(120_000));
    expect(row.querySelector(".source-activity-dot")!.classList.contains("is-receiving")).toBe(false);
    expect(screen.getByRole("button", { name: "Value 1, preview" })).toBeTruthy();
    expect(options.onOpen).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("renders a bounded viewport for 4,000 readings and reaches late items without mounting the entire list", () => {
    const options = treeOptions(system(4000));
    render(<ExplorerList {...options} />);
    const list = screen.getByRole("list", { name: "Catalogue items" });
    expect(within(list).getAllByRole("listitem").length).toBeLessThanOrEqual(24);
    expect(screen.queryByRole("button", { name: "Value 2000, preview" })).toBeNull();
    const late = options.rows.findIndex(row => row.label === "Value 2000");
    fireEvent.scroll(list.parentElement!, { target: { scrollTop: late * rowHeight } });
    expect(screen.getByRole("button", { name: "Value 2000, preview" })).toBeTruthy();
    expect(within(list).getAllByRole("listitem").length).toBeLessThanOrEqual(30);
    expect(options.positions.get("tree")?.offset).toBe(late * rowHeight);
    fireEvent.click(screen.getByRole("button", { name: "Value 2000, preview" }));
    expect(options.onOpen).toHaveBeenCalledExactlyOnceWith(options.rows[late]!.node);
  });

  it("moves like a file tree: arrows move, right opens or enters, left closes or returns to the parent", async () => {
    const options = treeOptions();
    render(<ExplorerList {...options} />);
    const broker = screen.getByRole("button", { name: "North laboratory, open" });
    expect(broker.tabIndex).toBe(0);
    act(() => broker.focus());
    fireEvent.keyDown(broker, { key: "ArrowRight" });
    const first = options.rows[1]!;
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toBe(`${first.label}, open`));
    expect(document.activeElement!.closest("li")?.getAttribute("aria-level")).toBe("2");
    // The meter is closed: right opens it and leaves focus in place.
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(options.onToggle).toHaveBeenLastCalledWith(first);
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toBe("Spare input, preview"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toBe("site, open"));
    // An open branch closes on left.
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(options.onToggle).toHaveBeenLastCalledWith(options.rows.find(row => row.label === "site"));
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    await waitFor(() => expect(document.activeElement).toBe(broker));
    expect(options.onOpen).not.toHaveBeenCalled();
  });

  it("opens and closes branches from their disclosure without choosing them", () => {
    const options = treeOptions();
    render(<ExplorerList {...options} />);
    const disclosure = screen.getByRole("button", { name: "Expand Main meter" });
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
    expect(disclosure.tabIndex).toBe(-1);
    fireEvent.click(disclosure);
    expect(options.onToggle).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Collapse North laboratory" }).getAttribute("aria-expanded")).toBe("true");
    expect(options.onOpen).not.toHaveBeenCalled();
  });

  it("restores the tree's scroll position when a search is cleared", async () => {
    const options = treeOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const scroll = screen.getByRole("list").parentElement!;
    fireEvent.scroll(scroll, { target: { scrollTop: 100 * rowHeight } });
    const results = options.rows.slice(5, 6).map(row => ({ ...row, depth: 0, expandable: false, expanded: false }));
    view.rerender(<ExplorerList {...options} rows={results} viewKey="search:value" />);
    expect(screen.getByRole("list", { name: "Search results" })).toBeTruthy();
    await waitFor(() => expect(scroll.scrollTop).toBe(0));
    view.rerender(<ExplorerList {...options} />);
    await waitFor(() => expect(scroll.scrollTop).toBe(100 * rowHeight));
  });

  it("reveals a source chosen elsewhere once its branch is in the tree", async () => {
    const options = treeOptions(system(4000));
    const view = render(<ExplorerList {...options} />);
    const late = options.rows.findIndex(row => row.label === "Value 3999");
    view.rerender(<ExplorerList {...options} selectedKey={options.rows[late]!.node.key} />);
    const scroll = screen.getByRole("list").parentElement!;
    await waitFor(() => expect(screen.getByRole("button", { name: "Value 3999, preview" }).getAttribute("aria-current")).toBe("true"));
    expect(late * rowHeight).toBeGreaterThanOrEqual(scroll.scrollTop);
    expect((late + 1) * rowHeight).toBeLessThanOrEqual(scroll.scrollTop + viewportHeight);
  });

  it("truncates long names visually but keeps them complete for assistive technology and hover", () => {
    const options = treeOptions();
    const label = `prefix-visible-${"long-relative-path-".repeat(25)}tail`;
    const rows = [{ ...readingRows(options)[0]!, label, path: `${label} — North laboratory / site/room/value0` }];
    render(<ExplorerList {...options} rows={rows} />);
    const button = screen.getByRole("button", { name: `${label}, preview` });
    expect(button.getAttribute("title")).toBe(`${label} — North laboratory / site/room/value0`);
    expect(button.querySelector(".ex-row-label")?.textContent).toBe(label);
    expect(screen.queryByText("private.example.invalid")).toBeNull();
  });
});

describe("catalogue browser", () => {
  it("enters results with ArrowDown and clears the search with Escape without leaving the field", () => {
    const props = browserProps();
    const view = render(<CatalogueBrowser {...props} query="value" />);
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    act(() => search.focus());
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(document.activeElement?.getAttribute("data-row")).toBe("0");
    view.rerender(<CatalogueBrowser {...props} query="value" />);
    act(() => search.focus());
    fireEvent.keyDown(search, { key: "Escape" });
    expect(props.onQuery).toHaveBeenLastCalledWith("");
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("counts results, offers the recently active filter and collapses every branch", () => {
    const props = browserProps();
    const onOnlineOnlyChange = vi.fn();
    render(<CatalogueBrowser {...props} query="value" rows={props.rows.slice(0, 3)} onlineOnly onOnlineOnlyChange={onOnlineOnlyChange} />);
    expect(screen.getByRole("status").textContent).toBe("3 matches");
    const filter = screen.getByRole("button", { name: "Recently active" });
    expect(filter.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(filter);
    expect(onOnlineOnlyChange).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(props.onCollapseAll).toHaveBeenCalledOnce();
  });

  it("names an applied collection and clears it without choosing a source", () => {
    const props = browserProps();
    const onClear = vi.fn();
    render(<CatalogueBrowser {...props} collection={{ label: "Building A", onClear }} />);
    expect(screen.getByText("In Building A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show every source" }));
    expect(onClear).toHaveBeenCalledOnce();
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("keeps loading, failure and empty states inside the catalogue category", () => {
    const props = browserProps();
    const view = render(<CatalogueBrowser {...props} loading />);
    expect(screen.getByRole("status").textContent).toBe("Loading catalogue…");
    expect(screen.queryByRole("list")).toBeNull();
    view.rerender(<CatalogueBrowser {...props} error="The catalogue could not be loaded." />);
    expect(screen.getByRole("alert").textContent).toBe("The catalogue could not be loaded.");
    const open = vi.fn();
    view.rerender(<CatalogueBrowser {...props} rows={[]} emptyMessage="No sources yet." emptyAction={{ label: "Open catalogue settings", onClick: open }} />);
    expect(screen.getByText("No sources yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open catalogue settings" }));
    expect(open).toHaveBeenCalledOnce();
  });
});
